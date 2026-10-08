"""Consume the review-point A inventory as data; never infer dispositions.

These contracts intentionally fail on new schema fields and runtime methods.
No core, request engine, browser, display or native secret backend is started.
"""

import ast
import copy
import csv
import importlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from src.config.apply_registry import is_secret, schema_facts
from src.desktop.core import CAPABILITIES
from src.desktop.settings import _handler

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs/design"
VISIBLE = {"primary", "more-options", "advanced"}
DISPOSITIONS = VISIBLE | {"internal-or-legacy", "unsupported-on-desktop"}


def core_rows():
    with (DATA / "ui-v1-core-inventory.tsv").open() as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def owners():
    return json.loads((DATA / "ui-v1-write-owners.json").read_text())


def composed_services():
    """Resolve exactly the services passed to cls(core, services=[...]).

    Reading the AST of executable source is not a wording test: it verifies the
    real composition contract without provisioning a profile or starting owners.
    """
    tree = ast.parse((ROOT / "src/desktop/management.py").read_text())
    compose = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef) and node.name == "compose")
    imports = {alias.asname or alias.name: (node.module, alias.name)
               for node in ast.walk(compose) if isinstance(node, ast.ImportFrom)
               for alias in node.names}
    # Some constructors are module-level imports.
    imports.update({alias.asname or alias.name: (node.module, alias.name)
                    for node in tree.body if isinstance(node, ast.ImportFrom)
                    for alias in node.names})
    constructors = {}
    for node in ast.walk(compose):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id in imports):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constructors[target.id] = imports[node.value.func.id]
    constructors["settings"] = ("settings", "SettingsService")
    composition = next(node for node in ast.walk(compose)
                       if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                       and node.func.id == "cls"
                       and any(k.arg == "services" for k in node.keywords))
    names = next(k.value for k in composition.keywords if k.arg == "services")
    result = {}
    for name in names.elts:
        module, cls = constructors[name.id]
        result[name.id] = getattr(importlib.import_module(f"src.desktop.{module}"), cls)
    return result


def supported_methods():
    return set(CAPABILITIES) | set().union(
        *(cls.METHODS for cls in composed_services().values()))


def validate_core(rows, facts=None, write_owners=None, methods=None):
    facts = schema_facts() if facts is None else facts
    write_owners = owners() if write_owners is None else write_owners
    methods = supported_methods() if methods is None else methods
    paths = [row["path"] for row in rows]
    assert len(paths) == len(set(paths)), "duplicate editor ownership"
    assert set(paths) == set(facts), (
        f"unclassified fields: {sorted(set(facts) - set(paths))}; "
        f"invalid paths: {sorted(set(paths) - set(facts))}")
    assert {r["path"] for r in rows if r["disposition"] == "advanced"} == set(
        write_owners["advanced_allowlist"]), "Advanced is an explicit allowlist"
    presentation = write_owners["advanced_presentation"]
    assert presentation["category_headings"], "Advanced needs category headings"
    assert len(presentation["category_headings"]) == len(set(presentation["category_headings"]))
    if len(write_owners["advanced_allowlist"]) > 30:
        assert presentation["search_required"] is True, "Advanced over 30 needs search"
    for row in rows:
        path = row["path"]
        assert row["disposition"] in DISPOSITIONS
        assert row["reason"].strip() and "\n" not in row["reason"]
        if row["disposition"] not in VISIBLE:
            assert row["editor"] == "none" and row["credential_route"] == "none"
            continue
        assert not row["reason"].startswith("No "), "visible fields need a user reason"
        editor = row["editor"]
        assert editor in write_owners["editors"], "missing write owner"
        method = write_owners["editors"][editor]
        assert method in methods, "unsupported write method"
        assert method == _handler(path), "wrong Desktop write owner"
        route = row["credential_route"]
        if path.startswith("mcp.servers") and path in {
            "mcp.servers", "mcp.servers.env", "mcp.servers.headers", "mcp.servers.url"
        }:
            assert route == "mcp.save", "MCP credentials require the section transaction"
        elif path in {"outbound_webhooks.targets", "outbound_webhooks.targets.url",
                      "outbound_webhooks.targets.secret"}:
            assert route == "webhooks.outbound.save", (
                "outbound credentials require the section transaction")
        elif path == "webhook.triggers":
            assert route == "per-entry-secrets", "incoming credentials require separate leaves"
        elif is_secret(path):
            assert route == "secrets.set|secrets.clear", "secret route missing"
        else:
            assert route == "none", "public field cannot be a generic secret editor"
        for secret_method in route.split("|"):
            if secret_method not in {"none", "per-entry-secrets"}:
                assert secret_method in methods
        # Container and child members are one structured workflow, not two editors.
        for prefix, parent_facts in facts.items():
            if parent_facts.get("is_container") and path.startswith(prefix + "."):
                parent = next(r for r in rows if r["path"] == prefix)
                assert parent["editor"] == editor, "duplicate container ownership"
    for methods_used in write_owners["special_transactions"].values():
        if isinstance(methods_used, str):
            methods_used = [methods_used]
        assert set(methods_used) <= methods, "unsupported specialized method"


def test_every_recursive_registry_field_has_one_explicit_disposition():
    validate_core(core_rows())


def test_review_a_disposition_counts_and_advanced_groups():
    rows = core_rows()
    assert len(rows) == 290
    assert Counter(row["disposition"] for row in rows) == {
        "primary": 76, "more-options": 42, "advanced": 61,
        "internal-or-legacy": 81, "unsupported-on-desktop": 30,
    }
    assert len({r["editor"] for r in rows if r["disposition"] == "advanced"}) == 29


def test_more_options_is_the_explicit_user_policy_selection_not_numeric_leftovers():
    expected = {
        "openai_codex.auxiliary.enabled", "openai_codex.auxiliary.model",
        "ollama.num_ctx", "openai_compatible.reasoning_content_feedback_policy",
        "openai_compatible.openrouter.order", "openai_compatible.openrouter.allow_fallbacks",
        "openai_compatible.openrouter.quantizations", "openai_compatible.openrouter.sort",
        "openai_compatible.openrouter.data_collection",
        "openai_compatible.openrouter.reasoning_effort",
        "openai_compatible.openrouter.model_pins", "sessions.adaptive_compaction",
        "sessions.archive_max_bytes", "sessions.archive_max_files",
        "tools.governor.block_critical", "tools.governor.block_exfil",
        "tools.governor.owner_can_override", "tools.allow_host_tofu",
        "tools.command_timeout_seconds", "tools.tool_timeouts", "tools.skill_allowed_urls",
        "tools.streaming.enabled", "tools.streaming.tools", "learning.loop_reflection_enabled",
        "observability.trajectory_user_content", "email.tls_verify",
        "email.allowed_attachment_dirs",
        "browser.cdp_url", "browser.allow_private_targets", "image.openai.enabled",
        "image.openai.outer_model", "image.openai.image_model",
        "mcp.max_published_tools_per_server", "mcp.max_published_tools_global",
        "mcp.servers.cwd", "mcp.servers.tool_allowlist", "mcp.servers.timeout_seconds",
        "agents.thinking_mode", "agents.model_selection_hints",
        "outbound_webhooks.targets.scrub_secrets", "outbound_webhooks.targets.verify_ssl",
        "turn_state.auto_resume",
    }
    rows = [r for r in core_rows() if r["disposition"] == "more-options"]
    assert {r["path"] for r in rows} == expected
    # Page ownership follows the explicit editor IDs, not the core schema groups.
    assert Counter(r["editor"].split(".")[0] for r in rows) == {
        "models": 17, "tools": 8, "skills": 1, "mcp": 5, "hosts": 4, "work": 4, "data": 3,
    }
    groups = {page: {r["editor"] for r in rows if r["editor"].startswith(page + ".")}
              for page in ("models", "tools", "skills", "mcp", "hosts", "work", "data")}
    assert {page: len(editors) for page, editors in groups.items()} == {
        "models": 8, "tools": 6, "skills": 1, "mcp": 2, "hosts": 2, "work": 3, "data": 2,
    }
    # The documented models exception is seven OpenRouter choices plus ten
    # other explicit policy/model choices, not a claim of eight scalar fields.
    assert sum(r["editor"] == "models.openrouter-routing" for r in rows) == 7


def test_pure_trace_diagnostics_have_no_visible_editor():
    rows = core_rows()
    diagnostic = {r["path"] for r in rows if r["path"].startswith("observability.context_trace.")}
    diagnostic |= {
        "observability.prompt_budget_accounting", "observability.max_user_content_chars",
        "observability.max_tool_result_chars", "observability.loop_trace",
    }
    for row in rows:
        if row["path"] in diagnostic:
            assert row["disposition"] == "internal-or-legacy"
            assert row["editor"] == "none"


@pytest.mark.parametrize("mutation,message", [
    ("search", "over 30 needs search"), ("headings", "needs category headings"),
])
def test_advanced_growth_requires_search_and_category_headings(mutation, message):
    write_owners = copy.deepcopy(owners())
    if mutation == "search":
        write_owners["advanced_presentation"]["search_required"] = False
    else:
        write_owners["advanced_presentation"]["category_headings"] = []
    with pytest.raises(AssertionError, match=message):
        validate_core(core_rows(), write_owners=write_owners)


def test_new_core_field_must_be_classified():
    facts = dict(schema_facts(), **{"future.setting": {}})
    with pytest.raises(AssertionError, match="unclassified fields.*future.setting"):
        validate_core(core_rows(), facts=facts)


@pytest.mark.parametrize("mutation,message", [
    ("duplicate", "duplicate editor ownership"),
    ("fabricated", "invalid paths"),
    ("wrong-owner", "wrong Desktop write owner"),
    ("unsupported", "unsupported write method"),
    ("secret", "secret route missing"),
    ("mcp", "MCP credentials"),
    ("outbound", "outbound credentials"),
    ("incoming", "incoming credentials"),
    ("advanced", "explicit allowlist"),
])
def test_inventory_rejects_drift_and_unsafe_routes(mutation, message):
    rows = core_rows()
    write_owners = copy.deepcopy(owners())
    by_path = {r["path"]: r for r in rows}
    if mutation == "duplicate":
        rows.append(dict(rows[0], editor="other-owner"))
    elif mutation == "fabricated":
        rows.append(dict(rows[0], path="invented.field"))
    elif mutation == "wrong-owner":
        write_owners["editors"]["general.timezone"] = "providers.codex.set"
    elif mutation == "unsupported":
        write_owners["editors"]["general.timezone"] = "runtime.restart"
    elif mutation == "secret":
        by_path["email.smtp.password"]["credential_route"] = "none"
    elif mutation == "mcp":
        by_path["mcp.servers.env"]["credential_route"] = "secrets.set"
    elif mutation == "outbound":
        by_path["outbound_webhooks.targets.secret"]["credential_route"] = "secrets.set"
    elif mutation == "incoming":
        by_path["webhook.triggers"]["credential_route"] = "settings.set"
    else:
        by_path["timezone"]["disposition"] = "advanced"
    with pytest.raises(AssertionError, match=message):
        validate_core(rows, write_owners=write_owners)


def test_unsupported_native_fields_match_actual_desktop_write_boundary():
    rows = core_rows()
    unsupported = {r["path"] for r in rows if r["disposition"] == "unsupported-on-desktop"}
    assert unsupported == {p for p in schema_facts()
                           if p.startswith("computer.") and p != "computer.enabled"} | {
                               "outbound_webhooks.enabled", "outbound_webhooks.scrub_secrets",
                               "outbound_webhooks.rate_limit_seconds"}


def test_schema_container_and_members_are_not_fabricated_entry_paths():
    facts = schema_facts()
    for path in ("tools.hosts", "mcp.servers", "personality.user_presets",
                 "webhook.triggers", "outbound_webhooks.targets",
                 "openai_compatible.model_profiles"):
        assert facts[path]["is_container"]
        assert any(p.startswith(path + ".") for p in facts)
    assert "agents.auto_model_allowlist" in facts
    assert "agents.auto_model_allowlist.model" not in facts


def test_container_members_cannot_acquire_a_second_editor():
    rows = core_rows()
    write_owners = copy.deepcopy(owners())
    write_owners["editors"]["second-mcp-editor"] = "mcp.save"
    next(r for r in rows if r["path"] == "mcp.servers.command")["editor"] = "second-mcp-editor"
    with pytest.raises(AssertionError, match="duplicate container ownership"):
        validate_core(rows, write_owners=write_owners)


async def test_outbound_global_fields_have_no_actual_desktop_write_contract(tmp_path):
    # The routing table alone suggests these globals are supported. Exercise the
    # actual owner: save edits target rows only, leaving all three globals intact.
    from src.desktop.integrations import IntegrationsService
    from tests.test_desktop_integrations import Settings

    settings = Settings(tmp_path)
    service = IntegrationsService(settings)
    before = settings.config.outbound_webhooks.model_dump()
    await service.handle("webhooks.outbound.save", {
        "name": "fixture", "url": "https://example.invalid/hook",
        "changes": [{"path": "outbound_webhooks.rate_limit_seconds", "value": 99}],
    })
    for key in ("enabled", "scrub_secrets", "rate_limit_seconds"):
        assert getattr(settings.config.outbound_webhooks, key) == before[key]
    assert settings.calls and all(path == ("outbound_webhooks", "targets")
                                  for changes in settings.calls for path, _ in changes)


@pytest.mark.parametrize("path", [p for p in schema_facts()
                                  if p.startswith("computer.") and p != "computer.enabled"])
async def test_every_native_unsupported_field_is_rejected_by_real_desktop_owner(tmp_path, path):
    from src.desktop.management import MethodError
    from src.desktop.paths import ProfilePaths
    from src.desktop.secrets import ProfileSecretStore
    from src.desktop.settings import SettingsService
    from tests.test_desktop_settings import MemoryKeyring

    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    paths.create_private()
    paths.config_file.write_text("{}\n")
    service = SettingsService(paths, ProfileSecretStore(paths, backend=MemoryKeyring()))
    value = service.config.model_dump()["computer"][path.split(".", 1)[1]]
    with pytest.raises(MethodError, match="derived from the session"):
        await service.handle("settings.set", {"expected_revision": service.revision,
                                              "changes": [{"path": path, "value": value}]})
    assert paths.config_file.read_text() == "{}\n"


def management_data():
    return json.loads((DATA / "ui-v1-management-inventory.json").read_text())


def validate_management(actions, methods=None):
    methods = supported_methods() if methods is None else methods
    ids = [row["id"] for row in actions]
    assert len(ids) == len(set(ids)), "duplicate action ownership"
    assert set(ids) == methods, (
        f"missing actions: {sorted(methods - set(ids))}; "
        f"unsupported methods: {sorted(set(ids) - methods)}")
    services = composed_services()
    for row in actions:
        assert row["method"] == row["id"]
        assert row["reason"].strip() and "\n" not in row["reason"]
        assert row["domain"] and row["source"]
        assert isinstance(row["read"], bool)
        module, name = row["owner"].rsplit(".", 1)
        owner = getattr(importlib.import_module(module), name)
        method = row["method"]
        if method not in set(CAPABILITIES):
            assert owner in services.values(), "not a composed management owner"
            assert method in owner.METHODS, "wrong method owner"
            assert row["read"] == (method in owner.READ_METHODS), "wrong read classification"
        elif method in {"status.get", "turn_state.list"}:
            assert name == {"status.get": "CoreService",
                            "turn_state.list": "TurnStateService"}[method]
        elif method in set().union(*(cls.METHODS for cls in services.values())):
            assert method in owner.METHODS, "wrong method owner"


def test_inventory_covers_actual_composed_methods_and_direct_core_dispatch():
    validate_management(management_data()["management_actions"])


@pytest.mark.parametrize("mutation,message", [
    ("new", "missing actions"), ("unsupported", "unsupported methods"),
    ("duplicate", "duplicate action ownership"), ("owner", "wrong method owner"),
])
def test_management_inventory_rejects_unreviewed_methods_and_duplicate_owners(mutation, message):
    actions = copy.deepcopy(management_data()["management_actions"])
    methods = supported_methods()
    if mutation == "new":
        methods.add("future.operation")
    elif mutation == "unsupported":
        actions.append(dict(actions[0], id="runtime.restart", method="runtime.restart"))
    elif mutation == "duplicate":
        actions.append(dict(actions[0]))
    else:
        row = next(r for r in actions if r["id"] == "mcp.save")
        row["owner"] = "src.desktop.hosts.HostsService"
    with pytest.raises(AssertionError, match=message):
        validate_management(actions, methods=methods)


def test_app_forwarding_only_advertises_supported_core_methods():
    data = management_data()
    supported = {row["id"] for row in data["management_actions"]}
    for action in data["app_actions"]:
        assert set(action.get("core_methods", [])) <= supported, action["id"]


def test_direct_ipc_broker_routes_match_inventory():
    # Extract each actual IPC handle call and its literal broker/command route.
    # Indirect attachment/artifact ownership is reviewed separately in the data.
    source = (ROOT / "app/src/main/ipc.ts").read_text()
    handlers = re.split(r"handle\(IPC\.(\w+),", source)[1:]
    routes = {}
    for name, body in zip(handlers[::2], handlers[1::2], strict=True):
        if name == "settingsSet":
            body = body.split("// Each settings-shaped method", 1)[0]
        matches = re.findall(r"(?:broker\.request|command)\('([^']+)'", body)
        if matches:
            routes[name] = sorted(set(matches))
    by_name = {r["id"]: r for r in management_data()["app_actions"]}
    assert routes, "actual direct broker route extraction must be nonempty"
    for name, methods in routes.items():
        assert by_name[name]["core_methods"] == methods, name


def bridge_contract():
    """Extract the named preload API and its two declarative dispatch tables."""
    shared = (ROOT / "app/src/shared/api.ts").read_text()
    preload = (ROOT / "app/src/preload/index.ts").read_text()
    management = shared.split("export const MANAGEMENT:", 1)[1].split("\n}", 1)[0]
    shaped = shared.split("export const SETTINGS_SHAPED =", 1)[1].split("} as const", 1)[0]
    table = {name: core for name, core in re.findall(
        r"^  (\w+): \{ channel: '[^']+', core: '([^']+)'", management, re.M)}
    shaped_table = {call: core for core, call in re.findall(
        r"'([^']+)': \{ call: '([^']+)'", shaped)}
    api = preload.split("const api: OdinApi = {", 1)[1].split("\n}", 1)[0]
    direct = set(re.findall(r"^  (\w+):", api, re.M))
    assert table and shaped_table and direct, "bridge parser must not accept an empty extraction"
    return table, shaped_table, direct


def validate_app(actions):
    table, shaped, direct = bridge_contract()
    by_id = {row["id"]: row for row in actions}
    assert len(by_id) == len(actions), "duplicate app action"
    expected = set(table) | set(shaped) | direct
    assert set(by_id) == expected, (
        f"unclassified app capabilities: {sorted(expected - set(by_id))}; "
        f"unsupported app methods: {sorted(set(by_id) - expected)}")
    for row in actions:
        assert row["app_method"] == row["id"]
        assert row["reason"].strip() and "\n" not in row["reason"]
        assert row["owner"] and row["source"] and row["domain"]
        assert isinstance(row["read"], bool)
    for name, core in (table | shaped).items():
        assert by_id[name]["core_methods"] == [core], "wrong bridge core route"


def test_every_preload_action_is_explicitly_classified_and_correctly_routed():
    validate_app(management_data()["app_actions"])


def test_app_local_bridge_actions_are_explicit_and_never_fabricated_core_methods():
    actions = {row["id"]: row for row in management_data()["app_actions"]}
    expected = {"getDesktopInfo": True, "openSettingsFolder": False, "exitOdin": False,
                "getSetupReminderHidden": True, "setSetupReminderHidden": False}
    for name, read in expected.items():
        assert actions[name]["read"] is read
        assert actions[name]["core_methods"] == []
    # The exhaustive preload-vs-inventory equality above must reject a newly
    # introduced bridge method until it has an explicit, reviewed disposition.
    actions["futureLocalAction"] = {
        "id": "futureLocalAction", "app_method": "futureLocalAction",
        "domain": "general", "reason": "Unreviewed action.",
        "owner": "app.src.main.ipc.registerIpc", "read": False,
        "source": "app/src/preload/index.ts:api", "core_methods": [],
    }
    with pytest.raises(AssertionError, match="unclassified app capabilities"):
        validate_app(list(actions.values()))


@pytest.mark.parametrize("mutation,message", [
    ("missing", "unclassified app capabilities"),
    ("unsupported", "unsupported app methods"),
    ("duplicate", "duplicate app action"),
    ("route", "wrong bridge core route"),
])
def test_app_inventory_rejects_new_missing_or_fabricated_actions(mutation, message):
    actions = copy.deepcopy(management_data()["app_actions"])
    if mutation == "missing":
        actions.pop()
    elif mutation == "unsupported":
        actions.append(dict(actions[0], id="restartApp", app_method="restartApp"))
    elif mutation == "duplicate":
        actions.append(dict(actions[0]))
    else:
        table, shaped, _ = bridge_contract()
        routes = table | shaped
        row = next(r for r in actions if r["id"] in routes)
        row["core_methods"] = ["runtime.restart"]
    with pytest.raises(AssertionError, match=message):
        validate_app(actions)


def test_app_preferences_match_real_persisted_fields_and_implemented_slices():
    # Compiler AST extraction is a contract test of executable persistence, not
    # an assertion on docs/comments. Never evaluate the Electron entry point.
    extraction = r"""
const ts = require('typescript'); const fs = require('node:fs');
function source(path) { return ts.createSourceFile(path, fs.readFileSync(path, 'utf8'),
  ts.ScriptTarget.Latest, true, ts.ScriptKind.TS); }
const index = source('src/main/index.ts');
const persisted = index.statements.find(n => ts.isInterfaceDeclaration(n)
  && n.name.text === 'PersistedState');
const result = persisted.members.map(n => n.name.getText(index));
const notifications = source('src/main/notifications.ts');
let defaults;
function find(n) {
  if (ts.isVariableDeclaration(n)
    && n.name.getText(notifications) === 'DEFAULT_NOTIFICATION_SETTINGS') defaults = n.initializer;
  ts.forEachChild(n, find);
}
find(notifications);
function walk(n, prefix) {
  for (const p of n.properties) {
    const name = prefix + p.name.getText(notifications);
    if (ts.isObjectLiteralExpression(p.initializer)) walk(p.initializer, name + '.');
    else result.push(name);
  }
}
walk(defaults, 'notifications.');
console.log(JSON.stringify(result));
"""
    result = subprocess.run(["node", "-e", extraction], cwd=ROOT / "app",
                            check=True, capture_output=True, text=True, timeout=20)
    actual = set(json.loads(result.stdout)) - {"notifications"}
    prefs = management_data()["app_preferences"]
    ids = [p["id"] for p in prefs]
    assert len(ids) == len(set(ids)), "duplicate app preference"
    persisted = {p["id"] for p in prefs if p["status"] == "persisted"}
    assert persisted == actual | {"autostart", "drafts[conversation_id]"}
    planned = {p["id"] for p in prefs if p["status"] == "planned"}
    assert planned == set()
    assert not (planned & actual)
    by_id = {p["id"]: p for p in prefs}
    assert by_id["setupReminderHidden"]["app_method"] == "setSetupReminderHidden"
    assert by_id["windowState"]["user_editable"] is False
    assert "app_method" not in by_id["windowState"], "native geometry has no renderer route"
    assert not ({"setupReminderDismissed", "window.normalBounds", "window.maximized"} & set(ids))
    available = {r["id"] for r in management_data()["app_actions"]}
    for pref in prefs:
        assert pref["reason"] and pref["owner"] and pref["source"] and pref["storage"]
        if pref["status"] == "planned":
            assert pref["identifier_status"] == "proposed-not-current"
            assert "app_method" not in pref
        if "app_method" in pref:
            assert pref["app_method"] in available


def test_inventory_preserves_native_conditional_publication_not_just_static_methods():
    from src.desktop.computer_binding import ComputerBindingService

    rows = {r["id"]: r for r in management_data()["management_actions"]}
    for method in ComputerBindingService.METHODS - ComputerBindingService.READ_METHODS:
        assert rows[method]["conditional_capability"] == "computer-management-started"
    # Call the real publication method without constructing or starting native owners.
    service = object.__new__(ComputerBindingService)
    service._started = False
    service._closed = False
    assert service.management_methods == ComputerBindingService.READ_METHODS
    service._started = True
    assert service.management_methods == ComputerBindingService.METHODS
    service._closed = True
    assert service.management_methods == ComputerBindingService.READ_METHODS


def test_app_credentials_keep_dedicated_write_only_routes():
    actions = {r["id"]: r for r in management_data()["app_actions"]}
    expected = {
        "secretsSet": "secrets.set", "secretsClear": "secrets.clear",
        "secretsUnlock": "secrets.unlock", "mcpSave": "mcp.save",
    }
    for name, method in expected.items():
        assert actions[name]["core_methods"] == [method]
        assert actions[name]["read"] is False


def test_action_evidence_references_existing_executable_source_not_new_prose():
    data = management_data()
    for action in data["management_actions"] + data["app_actions"]:
        evidence = action["source"].split(";", 1)[0].split(":", 1)[0]
        assert not Path(evidence).is_absolute()
        assert evidence.endswith((".py", ".ts"))
        assert (ROOT / evidence).is_file(), action["id"]


def test_core_methods_without_preload_are_explicitly_retained_not_fabricated():
    data = management_data()
    methods = {r["id"] for r in data["management_actions"]}
    forwarded = set().union(*(set(r.get("core_methods", [])) for r in data["app_actions"]))
    # Outbound workflows now have reviewed named bridges. Email remains a
    # composed capability, not an invented app call.
    for method in {"webhooks.outbound.list", "webhooks.outbound.save",
                   "webhooks.outbound.delete", "webhooks.outbound.test"}:
        assert method in methods
        assert method in forwarded
    assert "integrations.email.get" in methods
    assert "integrations.email.get" not in forwarded
