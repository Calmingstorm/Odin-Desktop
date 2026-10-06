"""PR34 LLM review: real private provider graph, never a restored HTTP server.

The inherited LLM admin suite is mixed: connection-pool controls and OpenRouter
admin are missing. Its whole frozen corpus remains blocked. These helpers allow
independent tests of already-present private model/provider behavior without
pretending the incomplete suite has been restored.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, nodes
from src.config.schema import Config
from src.desktop.codex_accounts import CodexAccountsService
from src.desktop.management import MethodError
from src.desktop.model_settings import ModelSettingsService
from src.desktop.providers import ProviderOwner
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService
from tests.desktop_adapters.process_cases import temporary_owner

SOURCE_PATH = "tests/test_web_api_llm_admin.py"
SOURCE_SHA256 = "f3fc8276fc85ab39e3234dff0f902e1d800d8f64ec6d0c58c2d5aa01d26980d1"
CORPUS_SHA256 = "28d3ade7c9f403b97e857707120660433169b8941045e00b33031f9af2a07bf3"
SETUP_HUNKS = ()
RESTORATION_STATUS = "deferred"
BLOCKER = "awaiting the step 5 completion PR"
MISSING_BEHAVIOR = {
    "TestConnectionPools": "No private connection-pool stats or close controls",
    "TestKimiAdmin.test_openrouter_select_persists_route_profile_and_per_model_pin": (
        "No private OpenRouter catalog selection or endpoint admin"),
    "TestKimiAdmin.test_openrouter_catalogue_projects_profiles_endpoints_and_measured_cache": (
        "No private OpenRouter catalog/profile/endpoint measured cache projection"),
    "TestKimiAdmin.test_openrouter_select_rejects_model_absent_from_catalogue": (
        "No private OpenRouter catalog selection validation"),
    "TestKimiAdmin.test_openrouter_routes_reject_non_openrouter_and_bad_selection": (
        "No private OpenRouter catalog selection verdict surface"),
}


class IncompleteDesktopSuiteError(RuntimeError):
    pass


def source_tree():
    source = frozen_source(SOURCE_PATH)
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("LLM admin frozen whole-source hash changed")
    tree = ast.parse(source, filename=SOURCE_PATH)
    seal = hashlib.sha256(json.dumps(corpus(tree), sort_keys=True).encode()).hexdigest()
    if seal != CORPUS_SHA256:
        raise ValueError("LLM admin whole inherited assertion/case seal changed")
    return tree


def verify_adaptation(original, candidate):
    """Zero approved hunks: full tree identity, not merely matching assertions."""
    if dump(original) != dump(candidate) or corpus(original) != corpus(candidate):
        raise ValueError("Blocked suite has no admitted setup or assertion rewrites")
    return True


def adapted_tree():
    original = source_tree()
    candidate = copy.deepcopy(original)
    verify_adaptation(original, candidate)
    return candidate


def inventory():
    """Static whole-suite inventory without importing obsolete HTTP test setup."""
    tree = source_tree()
    cases = []
    for symbol, node in nodes(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        count = 1
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "parametrize"
            ):
                values = decorator.args[1]
                if not isinstance(values, (ast.List, ast.Tuple)):
                    raise ValueError("Uncounted inherited parametrization")
                count *= len(values.elts)
        cases.append({"symbol": symbol, "line": node.lineno, "cases": count})
    inherited = corpus(tree)
    return {
        "functions": len(cases),
        "cases": sum(row["cases"] for row in cases),
        "assertions": len(inherited["assertions"]),
        "classes": len(inherited["classes"]),
        "case_inventory": cases,
    }


def load(namespace):
    """Never subset, skip or manufacture absent inherited feature outcomes."""
    adapted_tree()
    raise IncompleteDesktopSuiteError(f"{BLOCKER}: connection pools and OpenRouter admin")


class TemporaryKeyring:
    """Only the keyring backend seam; secrets retain real profile namespacing."""

    def __init__(self):
        self.values = {}

    def get_password(self, namespace, name):
        return self.values.get((namespace, name))

    def set_password(self, namespace, name, value):
        self.values[namespace, name] = value

    def delete_password(self, namespace, name):
        self.values.pop((namespace, name), None)


@asynccontextmanager
async def provider_graph(tmp_path, *, config=None):
    """Real canonical authenticated owner, profile storage and provider engine.

    Only keyring I/O is in memory. Concrete clients, validators, disk persistence,
    provider locks, graph qualification, publication and rollback are not replaced.
    Callers must fake network at concrete transport boundaries when needed.
    """
    with temporary_owner(tmp_path) as state:
        state.paths.create_private()
        state.paths.config_file.write_text("{}\n", encoding="utf-8")
        keyring = TemporaryKeyring()
        secrets = ProfileSecretStore(state.paths, backend=keyring)
        config = config or Config()
        config.openai_codex.auxiliary.enabled = False
        settings = SettingsService(state.paths, secrets, config=config)
        accounts = CodexAccountsService(settings)
        owner = ProviderOwner(settings, accounts)
        settings.owners.update(dict.fromkeys(owner.METHODS, owner))
        models = ModelSettingsService(settings, provider=owner)
        graph = SimpleNamespace(
            state=state,
            paths=state.paths,
            authority=state.authority,
            permissions=state.manager,
            settings=settings,
            accounts=accounts,
            owner=owner,
            models=models,
            keyring=keyring,
        )
        try:
            yield graph
        finally:
            await owner.close()


class CommandResponse:
    """Approved status carrier projection from an actual private method verdict.

    Unknown codes fail closed: they cannot be made into an expected HTTP status.
    This class does not manufacture any domain payload or execute web handlers.
    """

    STATUS = {
        "bad_request": 400,
        "stale_binding": 409,
        "conflict": 409,
        "not_found": 404,
        "unavailable": 503,
        "capability_unavailable": 503,
        "internal_error": 500,
        "internal": 500,
        "storage_unavailable": 500,
    }

    def __init__(self, result=None, *, error=None):
        self.verdict = error
        if error is None:
            self.status, self.body = 200, result
        else:
            if not isinstance(error, MethodError):
                raise TypeError("only a real private MethodError may be projected")
            self.status = self.STATUS[error.code]
            self.body = {"error": str(error)}

    async def json(self):
        return self.body


async def command(graph, method, params):
    """Execute the actual owner method and preserve its refusal classification."""
    service = graph.models if method in graph.models.METHODS else graph.settings
    try:
        return CommandResponse(await service.handle(method, params))
    except MethodError as error:
        return CommandResponse(error=error)


async def save(graph, method, *changes, expected_revision=None):
    return await command(
        graph,
        method,
        {
            "expected_revision": graph.settings.revision
            if expected_revision is None
            else expected_revision,
            "changes": [{"path": path, "value": value} for path, value in changes],
        },
    )
