"""Whole frozen quota suite: real keyring/provider/composed-owner setup only."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from contextvars import ContextVar
from pathlib import Path
from types import ModuleType, SimpleNamespace

from scripts.maintenance.fixture_corpus import corpus, dump, frozen_source, nodes, register_module
from src.config.schema import Config
from src.desktop.authority import OwnerAuthority
from src.desktop.codex_accounts import CodexAccountsService, KeyringCodexAuthPool, KeyringCodexVault
from src.desktop.core import CoreService
from src.desktop.management import ManagementService
from src.desktop.paths import ProfilePaths
from src.desktop.providers import ProviderOwner
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService
from src.permissions.manager import PermissionManager

SOURCE_PATH = "tests/test_codex_quota_check.py"
SOURCE_SHA256 = "f478b1afe910589314a8ea4ffaae91f73edfe09a27debc4455a8252efe0cf462"
TREE_SHA256 = "43d02810109cf433f71b522945d60b4e251571d48875c67c228012a3be8cc754"
ADAPTED_TREE_SHA256 = "0f99bc0e40773334d2bee69c5b3a8a8095fc66c1f45b449b5cdb8b4a07cd2143"
CORPUS_SHA256 = "ae7381d9f07c8c09773df983b7c2c36c06b0f56e4bca268215f6e339cdfd9a79"
INHERITED_COUNTS = {"assertions": 45, "cases": 10, "classes": 4}
SUITES = {"test_codex_quota_check": SOURCE_SHA256}
CORPUS_SELECTIONS = {"test_codex_quota_check": None}
CORPUS_EXCLUSIONS = {}
FIRST = "test_disable_enable_check_uses_only_current_serving_pool"
HUNKS = (
    ("<module>", 11, "857505ba2c53a9770dfa4a0d044b914d0b78e72b7a5382c51d910ff526962ea6",
     "from tests.desktop_adapters.review_provider_quota import desktop_gateway as LLMGateway"),
    ("<module>", 13, "f52c2901492903e8a434a083c9abe3dc017f897d436b8476fc1908e40e5af734",
     "from src.llm.codex_auth import CodexAuth\n"
     "from tests.desktop_adapters.review_provider_quota import keyring_boot_pool as CodexAuthPool"),
    (FIRST, 92, "986bebc418fffc02b0806cce70f696cf8b8993037902b8ec1b0a201991bbddf0",
     "config = desktop_config(path)"),
    (FIRST, 116, "3afe5b9d442d71f2af400383f1b7321f041768848cf8784e54bb05f785f6b145",
     "gateway.reload_codex"),
    (FIRST, 120, "3afe5b9d442d71f2af400383f1b7321f041768848cf8784e54bb05f785f6b145",
     "gateway.reload_codex"),
    ("test_bot_wiring_check_lookup_tracks_current_gateway_and_live_config", 157,
     "646db53e419b41e77462bf1e80f5989b31e3cde479d1006f1c3722aa5c46c1b1",
     "from tests.desktop_adapters.review_provider_quota import make_bot"),
    ("test_missing_identity_and_http_exception_are_display_safe", 322,
     "f01f5fae4a95c61b1439953b0675d16587956e972adc94ca29ea35e4c31a2629",
     "reset_identity_patch(monkeypatch)"),
)
_resources = ContextVar("review_quota_resources", default=None)
HUNK_AFTER_SHA256 = (
    "77987a85df7c3e997fc738d3af9cb8b6c1b7723a4524f9d01e9a18a0c861ac48",
    "fbc0e445433f1c2b2f88119c2253637ec89d63c7c9e4cd7637bdc372010c372a",
    "06182b515db200bb1e583bf3f753d66fb94e313b4747da15b075a82257dd2148",
    "56c4879793baf437225d8788dcfdc04a731e345cf8024f8faeeead44b19d4997",
    "56c4879793baf437225d8788dcfdc04a731e345cf8024f8faeeead44b19d4997",
    "143f4390e716d7de2f2e680f83ab933cb13621df52635693c49821397dd1793d",
    "a6f0f5bc745d832f2319242427333d7919701a09956de4d4c471e251d49b7c1c",
)


class TemporaryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, namespace, name):
        return self.values.get((namespace, name))

    def set_password(self, namespace, name, value):
        self.values[namespace, name] = value

    def delete_password(self, namespace, name):
        self.values.pop((namespace, name), None)


def _own(resource):
    active = _resources.get()
    assert active is not None, "quota adapter needs temporary resource fixture"
    active.append(resource)
    return resource


def keyring_boot_pool(path):
    paths = ProfilePaths.from_xdg(home=Path(path).parent / "quota-profile", environ={})
    paths.create_private()
    secrets = ProfileSecretStore(paths, backend=TemporaryKeyring())
    vault = KeyringCodexVault(secrets)
    vault.write(json.loads(Path(path).read_text()))
    return KeyringCodexAuthPool(vault)


def desktop_config(path):
    config = Config()
    cfg = config.openai_codex
    cfg.enabled = False
    cfg.credentials_path = str(path)  # Retained field, never used by Desktop owner.
    cfg.model, cfg.reasoning_effort = "gpt-6-luna", "none"
    cfg.request_timeout_seconds, cfg.stream_stall_timeout_seconds = 60, 30
    cfg.retry.max_retries, cfg.retry.base_delay, cfg.retry.max_delay = 1, 1, 2
    cfg.connection_pool.max_connections, cfg.connection_pool.keepalive_timeout = 2, 30
    cfg.auxiliary.enabled = False
    return config


def reset_identity_patch(monkeypatch):
    from src.llm import account_key

    isolated_path = account_key.DEFAULT_KEY_PATH
    monkeypatch.undo()
    # undo also rolls back conftest's isolation fixture. Retain its real key
    # filesystem, not a stubbed account-key result or the runtime default.
    monkeypatch.setattr(account_key, "DEFAULT_KEY_PATH", isolated_path)


def desktop_gateway(*, get_config, codex_client, **unused):
    config = get_config()
    paths = codex_client.auth.vault.secrets.paths
    paths.config_file.write_text("{}\n")
    settings = SettingsService(paths, codex_client.auth.vault.secrets, config=config)
    accounts = _own(CodexAccountsService(settings, vault=codex_client.auth.vault))
    owner = _own(ProviderOwner(settings, accounts))
    owner.codex_client = codex_client
    owner._review_quota_original_records = accounts.vault.read()
    return owner


def make_bot():
    paths = ProfilePaths.from_xdg(home=Path.cwd() / "composed-quota", environ={})
    paths.create_private()
    core = CoreService(paths, paths.config_dir / "unused.sock", paths.config_dir / "unused.token")
    core.authority = OwnerAuthority(paths, app_bootstrap=True)
    core.permissions = PermissionManager(core.authority)
    manager = _own(ManagementService.compose(core, secret_backend=TemporaryKeyring()))
    # These aliases project real composition owners. The checker itself is not
    # constructed here: absent production wiring raises rather than fabricates.
    return SimpleNamespace(config=manager.settings.config, llm_gateway=manager.providers,
                           codex_quota_check=manager.codex_quota_check)


def source_tree():
    source = frozen_source(SOURCE_PATH)
    assert hashlib.sha256(source).hexdigest() == SOURCE_SHA256
    return ast.parse(source)


def verify_adaptation(original, adapted):
    """Seal the entire module, not only asserts or test function names."""
    assert hashlib.sha256(dump(original).encode()).hexdigest() == TREE_SHA256
    assert hashlib.sha256(json.dumps(
        corpus(original), sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest() == CORPUS_SHA256
    assert {key: len(value) for key, value in corpus(original).items()} == INHERITED_COUNTS
    expected = _transform(original)
    assert corpus(original) == corpus(adapted)
    assert dump(expected) == dump(adapted)
    assert hashlib.sha256(dump(adapted).encode()).hexdigest() == ADAPTED_TREE_SHA256
    return True


def adapted_tree():
    original = source_tree()
    tree = _transform(original)
    verify_adaptation(original, tree)
    return tree


def reverse_adaptation(tree):
    original = source_tree()
    verify_adaptation(original, tree)
    return copy.deepcopy(original)


def _transform(original):
    tree = copy.deepcopy(original)
    for (symbol, line, before_hash, replacement), after_hash in zip(
        HUNKS, HUNK_AFTER_SHA256, strict=True,
    ):
        targets = [node for owner, node in nodes(tree) if owner == symbol
                   and getattr(node, "lineno", None) == line
                   and hashlib.sha256(dump(node).encode()).hexdigest() == before_hash]
        assert len(targets) == 1, (symbol, line)
        target = targets[0]
        value = (ast.parse(replacement, mode="eval").body if isinstance(target, ast.Attribute)
                 else ast.parse(replacement).body)
        representation = (dump(value) if isinstance(value, ast.AST)
                          else json.dumps([dump(item) for item in value]))
        assert hashlib.sha256(representation.encode()).hexdigest() == after_hash

        class Replace(ast.NodeTransformer):
            def visit(self, node):
                if node is target:
                    if isinstance(value, list):
                        return [ast.copy_location(copy.deepcopy(item), node) for item in value]
                    return ast.copy_location(copy.deepcopy(value), node)
                return super().visit(node)

        tree = Replace().visit(tree)
    return ast.fix_missing_locations(tree)


def load(namespace):
    """Export the complete suite, all helpers, all ten cases, no exclusions."""
    module = ModuleType("desktop_review_provider_quota_frozen")
    module.desktop_config = desktop_config
    module.reset_identity_patch = reset_identity_patch
    exec(compile(adapted_tree(), SOURCE_PATH, "exec"), module.__dict__)
    register_module(namespace, module)
    exported = {}
    for name, value in vars(module).items():
        if name.startswith("__"):
            continue
        if getattr(value, "__module__", None) == module.__name__:
            value.__module__ = namespace["__name__"]
        assert name not in namespace or namespace[name] is value, name
        namespace[name] = value
        exported[name] = value
    return exported
