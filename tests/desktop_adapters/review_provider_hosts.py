"""Frozen whole hosts corpus on authenticated, disposable desktop domain owners.

No HTTP or SSH transport is started. Only verdict carriers and obsolete setup
are projected; enrollment, publication, leases and diagnostics are real owners.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, nodes, register_module
from src.desktop import hosts as domain
from src.desktop.management import ManagementService, MethodError
from src.desktop.provisioning import fresh_config
from src.desktop.settings import SettingsService

PATH = "tests/test_hosts_api.py"
SOURCE_PATH = PATH
SOURCE_SHA256 = "5d430317b977293f50151292dec46c455b93088a4dde0d99a811c9bd32796173"
SUITES = {
    "test_hosts_api": "5d430317b977293f50151292dec46c455b93088a4dde0d99a811c9bd32796173",
}
CORPUS_SELECTIONS = {"test_hosts_api": None}
CORPUS_EXCLUSIONS = {}


async def _persist_ok(changes):
    return None, False


class ApiSeams:
    """Forward only the frozen suite's existing external-edge monkeypatch seams."""

    config_persistence = SimpleNamespace(persist_config_paths_locked=_persist_ok)
    HostEnrollmentManager = domain.HostEnrollmentManager
    _drain_host_mutation = staticmethod(domain._drain_mutation)

    @property
    def public_key_info(self):
        return domain.public_key_info

    @public_key_info.setter
    def public_key_info(self, value):
        domain.public_key_info = value

    @property
    def scan_host_references(self):
        return self._scan

    @scan_host_references.setter
    def scan_host_references(self, value):
        self._scan = value
        if value is _original_scan:
            domain.scan_host_references = value
        else:
            domain.scan_host_references = lambda config, alias, **kwargs: value(config, alias)


_original_scan = domain.scan_host_references
api = ApiSeams()
api._scan = _original_scan


class Bot:
    @property
    def config(self):
        return self.settings.config


def make_bot(
    tmp_path,
    *,
    hosts=None,
    auth=False,
    with_registry=True,
    host_factory,
    audit_factory,
    process_factory,
):
    bot = Bot()
    bot.tmp_path = tmp_path
    bot.denied = auth
    configured = hosts if hosts is not None else {"alpha": host_factory()}
    # Authority is created only on client entry, under the nonroot fixture.
    bot.configured = configured
    bot.registry_present = with_registry
    bot.audit = audit_factory()
    bot.prompt_builder = SimpleNamespace(cached_hosts={"old": "value"})
    bot.tool_executor = SimpleNamespace(_process_registry=process_factory())
    # The inherited suite inspects/patches registry before entering a client.
    from src.desktop.paths import ProfilePaths

    paths = ProfilePaths.from_xdg(
        environ={
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
        home=tmp_path,
    )
    from src.desktop.authority import OwnerAuthority

    bot.authority = OwnerAuthority(paths)
    config = fresh_config(paths)
    config.tools.hosts = configured
    config.tools.default_host = "alpha" if "alpha" in configured else ""
    config.tools.ssh_key_path = "/fake/desired-key"
    config.tools.ssh_known_hosts_path = "/fake/desired-known-hosts"
    from src.config.persistence import _dump_atomic
    from src.desktop.paths import private_directory

    private_directory(paths.config_dir)
    private_directory(paths.data_dir)
    from src.permissions.persistence import write_private_atomic

    if not write_private_atomic(paths.config_file, "{}\n"):
        raise RuntimeError("temporary config publication failed")
    _dump_atomic(config.model_dump(mode="json"), paths.config_file, 0o600)
    from src.desktop.secrets import ProfileSecretStore
    from tests.test_desktop_settings import MemoryKeyring

    bot.settings = SettingsService(
        paths, ProfileSecretStore(paths, backend=MemoryKeyring()), config=config
    )
    bot.host_registry = (
        domain.HostRegistry(
            configured,
            key_path="/fake/effective-key",
            legacy_known_hosts_path="/fake/effective-known-hosts",
            default_host="alpha",
            trust_dir=tmp_path / "trust",
        )
        if with_registry
        else None
    )
    bot.service = domain.HostsService(
        bot.settings,
        registry=bot.host_registry,
        executor=bot.tool_executor,
        audit=bot.audit,
        prompt_builder=bot.prompt_builder,
    )
    if not with_registry:
        bot.service.registry = None
    original_save = bot.settings.save_changes

    async def save(changes, **kwargs):
        error, _ = await api.config_persistence.persist_config_paths_locked(changes)
        if error is not None:
            raise MethodError("internal_error", "Configuration not saved")
        return original_save(changes, **kwargs)

    bot.settings.save_changes = save
    return bot


class Response:
    """Strict projection of actual domain verdicts, never inferred from request."""

    def __init__(self, frame, method):
        self.frame = frame
        if frame["ok"]:
            self.body = frame["result"]
            if method == "hosts.test" and not self.body["tested"]:
                self.status = 424
            else:
                self.status = 201 if method in {"hosts.prepare", "hosts.commit"} else 200
        else:
            error = frame["error"]
            self.status = {
                "bad_request": 400,
                "forbidden": 403,
                "not_found": 404,
                "conflict": 409,
                "internal_error": 500,
                "unavailable": 503,
            }[error["code"]]
            self.body = {"error": error["message"]}
            if "details" in error:
                self.body.update(error["details"])

    async def json(self):
        return self.body


def route(verb, path, payload):
    parts = path.strip("/").split("/")
    if parts[:2] != ["api", "hosts"]:
        raise ValueError("unmapped frozen path")
    tail = parts[2:]
    if not tail and verb == "get":
        return "hosts.list", payload
    fixed = {
        ("post", "settings"): "hosts.settings",
        ("get", "public-key"): "hosts.public_key",
        ("post", "candidates"): "hosts.prepare",
    }
    if len(tail) == 1 and (verb, tail[0]) in fixed:
        return fixed[verb, tail[0]], payload
    if len(tail) == 3 and tail[0] == "candidates" and verb == "post":
        return {"test": "hosts.test", "commit": "hosts.commit"}[tail[2]], {
            **payload,
            "token": tail[1],
        }
    if len(tail) == 1 and verb == "delete":
        return "hosts.delete", {**payload, "alias": tail[0]}
    if len(tail) == 2:
        method = {
            ("post", "enabled"): "hosts.set_enabled",
            ("post", "force-revoke"): "hosts.force_revoke",
            ("post", "import-legacy"): "hosts.import_legacy",
            ("get", "references"): "hosts.references",
        }[verb, tail[1]]
        return method, {**payload, "alias": tail[0]}
    raise ValueError("unmapped frozen request")


class CommandClient:
    def __init__(self, bot):
        self.bot = bot

    async def __aenter__(self):
        # Multiple client contexts reuse a bot/profile; workspace is disposable.
        (self.bot.tmp_path / "workspace").mkdir(mode=0o700, exist_ok=True)
        self.owner_context = owner_profile(self.bot.tmp_path)
        self.owner = self.owner_context.__enter__()
        self.core = SimpleNamespace()
        self.management = ManagementService(
            self.core, services=[self.bot.service], identity_key=b"h" * 32
        )
        return self

    async def __aexit__(self, *exc):
        self.owner_context.__exit__(*exc)

    async def request(self, verb, path, *, json=None, data=None, headers=None):
        from src.desktop.commands import response_error

        # Admission is real profile authority, not old bearer/tier policy.
        context = (
            None
            if self.bot.denied
            else self.owner.authority.authenticate_local(peer_uid=__import__("os").geteuid())
        )
        token = self.owner.manager.set_request_owner(context)
        try:
            if not self.owner.manager.is_owner(self.owner.authority.owner_id):
                return Response(response_error("forbidden", "profile owner required"), "")
            payload = {} if json is None else json
            method, params = route(verb, path, payload)
            # Missing-domain refusal precedes malformed input as inherited.
            if self.bot.service.registry is not None and data is not None:
                try:
                    params = __import__("json").loads(data)
                except ValueError:
                    return Response(response_error("bad_request", "invalid JSON"), method)
            return Response(await self.management.invoke(method, params), method)
        finally:
            self.owner.manager.reset_request_owner(token)

    async def get(self, path, **kwargs):
        return await self.request("get", path, **kwargs)

    async def post(self, path, **kwargs):
        return await self.request("post", path, **kwargs)

    async def delete(self, path, **kwargs):
        return await self.request("delete", path, **kwargs)


@contextmanager
def owner_profile(tmp_path):
    import os

    from src.desktop.authority import OwnerAuthority
    from src.desktop.paths import ProfilePaths
    from src.permissions.manager import PermissionManager

    if os.geteuid() == 0:
        raise RuntimeError("isolated nonroot runner required")
    paths = ProfilePaths.from_xdg(
        environ={
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
        home=tmp_path,
    )
    authority = OwnerAuthority(paths)
    manager = PermissionManager(authority)
    context = authority.authenticate_local(peer_uid=os.geteuid())
    token = manager.set_request_owner(context)
    try:
        assert manager.is_owner(authority.owner_id)
        yield SimpleNamespace(paths=paths, authority=authority, manager=manager)
    finally:
        manager.reset_request_owner(token)
        authority.release_runtime()


def source_tree():
    source = frozen_source(PATH)
    assert hashlib.sha256(source).hexdigest() == SOURCE_SHA256
    return ast.parse(source)


# Frozen exact seals live in a unique fragment, not a mutable suite map.
def hunk_records():
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2] / "maintenance/step8-part2-review-provider-hosts.json"
    )
    return json.loads(path.read_text())["setup_hunks"]


def adapted_tree():
    tree = source_tree()
    original = copy.deepcopy(tree)
    for rule in hunk_records():
        found = [
            n
            for symbol, n in nodes(tree)
            if symbol == rule["symbol"]
            and getattr(n, "lineno", None) == rule["line"]
            and type(n).__name__ == rule["kind"]
            and hashlib.sha256(dump(n).encode()).hexdigest() == rule["before_sha256"]
        ]
        assert len(found) == 1, rule
        target = found[0]
        replacement = ast.parse(rule["after_source"]).body[0]
        assert hashlib.sha256(dump(replacement).encode()).hexdigest() == rule["after_sha256"]

        class Exact(ast.NodeTransformer):
            def visit(self, node):
                return (
                    ast.copy_location(copy.deepcopy(replacement), node)
                    if node is target
                    else super().visit(node)
                )

        tree = Exact().visit(tree)
    assert corpus(original) == corpus(tree)
    # Independent reverse replacement locates exact after ASTs by symbol/line.
    reverse = copy.deepcopy(tree)
    for rule in reversed(hunk_records()):
        found = [
            n
            for symbol, n in nodes(reverse)
            if symbol == rule["symbol"]
            and getattr(n, "lineno", None) == rule["line"]
            and hashlib.sha256(dump(n).encode()).hexdigest() == rule["after_sha256"]
        ]
        assert len(found) == 1
        target = found[0]
        restored = ast.parse(rule["before_source"]).body[0]
        assert hashlib.sha256(dump(restored).encode()).hexdigest() == rule["before_sha256"]

        class Reverse(ast.NodeTransformer):
            def visit(self, node):
                return (
                    ast.copy_location(copy.deepcopy(restored), node)
                    if node is target
                    else super().visit(node)
                )

        reverse = Reverse().visit(reverse)
    assert dump(reverse) == dump(original)
    return ast.fix_missing_locations(tree)


def load(namespace):
    module = ModuleType("desktop_review_provider_hosts_frozen")
    module.__dict__.update(make_bot=make_bot, CommandClient=CommandClient)
    exec(compile(adapted_tree(), PATH, "exec"), module.__dict__)
    register_module(namespace, module)
    for name, value in vars(module).items():
        if name.startswith("__"):
            continue
        if getattr(value, "__module__", None) == module.__name__:
            value.__module__ = namespace["__name__"]
        namespace[name] = value
