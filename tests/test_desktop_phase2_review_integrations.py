"""PR34 review C: complete audit/integration/webhook suites; partial log search."""
import ast
import json
from copy import deepcopy

import pytest

from scripts.maintenance.fixture_corpus import corpus, dump
from src.config.schema import Config, OutboundWebhookTarget
from src.desktop.integrations import IntegrationsService
from src.desktop.management import MethodError
from src.desktop.paths import ProfilePaths
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService
from tests.desktop_adapters import step8_review_integrations as adapter

adapter.load(globals())


@pytest.mark.parametrize("suite", adapter.CORPUS_SELECTIONS)
def test_exact_frozen_corpus_and_reversible_seals(suite):
    original, adapted = adapter.adapted_tree(suite)
    assert corpus(original) == corpus(adapted)
    record = json.loads(adapter.RECORD.read_text())
    restored = deepcopy(adapted)
    rules = list(record["ledger_by_path"]["tests/" + suite + ".py"])
    rules.extend(
        (r["symbol"], r["line"], r["key"])
        for r in record["setup_hunks"] if r["path"] == "tests/" + suite + ".py"
    )
    for symbol, line, key in reversed(rules):
        before = [n for s, n in adapter.nodes(original)
                  if s == symbol and getattr(n, "lineno", None) == line
                  and adapter.hashlib.sha256(dump(n).encode()).hexdigest()
                  == record["sealed_imports"][key][0]]
        after = [n for s, n in adapter.nodes(restored)
                 if s == symbol and getattr(n, "lineno", None) == line
                 and adapter.hashlib.sha256(dump(n).encode()).hexdigest()
                 == record["sealed_imports"][key][1]]
        assert len(before) == len(after) == 1
        old, replacement = after[0], deepcopy(before[0])
        class Undo(ast.NodeTransformer):
            def generic_visit(self, node):
                return replacement if node is old else super().generic_visit(node)
        restored = Undo().visit(restored)
    assert dump(restored) == dump(original)


async def test_owner_saved_rejected_url_survives_mutation_rejection_and_restart(
    tmp_path, monkeypatch,
):
    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    paths.create_private()
    desired_url = "https://owner-saved.example.test/hook"
    paths.config_file.write_text(
        "# owner note\noutbound_webhooks:\n  enabled: true\n  targets:\n"
        f"    - id: bad # rejected row\n      name: rejected\n      url: {desired_url}\n"
        "      events: [all] # saved events\n"
        "    - id: good\n      name: valid\n      url: https://good.example.test/hook\n")
    config = Config()
    config.outbound_webhooks.enabled = True
    config.outbound_webhooks.targets = [
        OutboundWebhookTarget(id="bad", name="rejected", url="http://169.254.169.254/"),
        OutboundWebhookTarget(id="good", name="valid", url="https://good.example.test/hook"),
    ]
    backend = adapter.Backend()
    vault = ProfileSecretStore(paths, backend=backend)
    settings = SettingsService(paths, vault, config=config)
    service = IntegrationsService(settings)
    status = await service.handle("webhooks.outbound.list", {})
    assert {row["id"] for row in status["webhooks"]} == {"good"}
    await service.handle("webhooks.outbound.save", {
        "id": "good", "name": "renamed", "secret": "temporary-key",
    })
    import yaml
    assert "temporary-key" not in paths.config_file.read_text()
    # Rejected owner adoption must roll back to the saved desired document,
    saved = yaml.safe_load(paths.config_file.read_text())["outbound_webhooks"]["targets"]
    assert saved[0]["url"] == desired_url
    for comment in ("# owner note", "# rejected row", "# saved events"):
        assert comment in paths.config_file.read_text()
    # never resurrect the metadata URL from startup.
    monkeypatch.setattr(service, "_apply_targets", lambda *args: False)
    with pytest.raises(MethodError, match="could not save"):
        await service.handle("webhooks.outbound.save", {"id": "good", "name": "not adopted"})
    saved = yaml.safe_load(paths.config_file.read_text())["outbound_webhooks"]["targets"]
    assert saved[0]["url"] == desired_url
    restarted = IntegrationsService(SettingsService(paths, vault))
    status = await restarted.handle("webhooks.outbound.list", {})
    # The saved URL is now valid on a fresh boot, so it can be adopted there.
    assert {row["id"] for row in status["webhooks"]} == {"bad", "good"}
    assert next(row for row in status["webhooks"] if row["id"] == "bad")["url"] == desired_url
    good = next(row for row in status["webhooks"] if row["id"] == "good")
    assert good["name"] == "renamed"
    assert good["has_secret"] is True
    await restarted.handle("webhooks.outbound.save", {"id": "good", "enabled": False})
    saved = yaml.safe_load(paths.config_file.read_text())["outbound_webhooks"]["targets"]
    assert saved[0]["url"] == desired_url
    assert "temporary-key" not in paths.config_file.read_text()
    for comment in ("# owner note", "# rejected row", "# saved events"):
        assert comment in paths.config_file.read_text()
    await service.dispatcher.close()
    await restarted.dispatcher.close()


@pytest.mark.parametrize("malformed", [
    "null", "{}", "[7]", "[{id: bad, url: {bad: type}}]",
    "[{id: good, url: 'https://good.example.test/hook', secret: 'disk-key'}]",
    "[{id: good, url: 'https://user:pass@good.example.test/hook'}]",
])
async def test_invalid_saved_targets_fail_closed_before_keyring_or_runtime_change(
    tmp_path, malformed,
):
    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    paths.create_private()
    config = Config()
    config.outbound_webhooks.targets = [OutboundWebhookTarget(
        id="good", name="valid", url="https://good.example.test/hook")]
    paths.config_file.write_text("{}")
    backend = adapter.Backend()
    vault = ProfileSecretStore(paths, backend=backend)
    settings = SettingsService(paths, vault, config=config)
    service = IntegrationsService(settings)
    before = await service.handle("webhooks.outbound.list", {})
    desired = f"outbound_webhooks:\n  targets: {malformed}\n"
    paths.config_file.write_text(desired)
    with pytest.raises(MethodError, match="could not read"):
        await service.handle("webhooks.outbound.save", {"id": "good", "secret": "must-not-write"})
    assert paths.config_file.read_text() == desired
    assert backend.values == {}
    assert await service.handle("webhooks.outbound.list", {}) == before
    await service.dispatcher.close()


def test_partial_log_search_not_whole_restoration():
    record = json.loads(adapter.RECORD.read_text())
    row = next(row for row in record["entries"] if row["path"] == "tests/test_log_search.py")
    assert row["status"] == "deferred"
    assert "restoration" not in row
    assert row["blocked_on"] == "awaiting the step 5 completion PR"
    assert row["partial_adaptation"]["inherited_cases"] == 35
    assert row["partial_adaptation"]["deferred_cases"] == 6
    _, tree = adapter.adapted_tree("test_log_search")
    samples = [n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert "ls /tmp/broken" in samples
    assert not any(value.startswith("rm ") for value in samples)


async def test_integrity_status_is_projection_of_real_domain_valid_false(tmp_path):
    from src.audit.logger import AuditLogger
    from src.desktop.management import ManagementService
    from src.desktop.records import RecordsService
    path = tmp_path / "audit.jsonl"
    logger = AuditLogger(path=str(path), hmac_key="temporary-signing-key")
    await logger.log_execution(user_id="owner", user_name="owner", channel_id="local",
        tool_name="read_file", tool_input={}, approved=True,
        result_summary="ok", execution_time_ms=1)
    manager = ManagementService(None, services=[RecordsService(None, audit=logger)],
                                identity_key=b"x" * 32)
    valid = await manager.invoke("audit.verify", {})
    good = adapter.DesktopResponse(valid, "audit.verify")
    assert valid["ok"] and valid["result"]["valid"] is True
    assert good.status == 200
    entry = json.loads(path.read_text())
    entry["tool_name"] = "tampered"
    path.write_text(json.dumps(entry) + "\n")
    invalid = await manager.invoke("audit.verify", {})
    bad = adapter.DesktopResponse(invalid, "audit.verify")
    assert invalid["ok"] and invalid["result"]["valid"] is False
    assert bad.status == 409
    assert await bad.json() == invalid["result"]
    assert invalid["result"]["first_bad_file"] == "audit.jsonl"
    assert any(segment["reason"] == "hmac_mismatch"
               for segment in invalid["result"]["segments"])


async def test_validation_and_absent_wiring_project_real_desktop_refusals(tmp_path):
    from src.desktop.management import ManagementService
    paths = ProfilePaths.from_xdg(environ={}, home=tmp_path)
    paths.create_private()
    paths.config_file.write_text("{}")
    service = IntegrationsService(SettingsService(paths, ProfileSecretStore(
        paths, backend=adapter.Backend())))
    manager = ManagementService(None, services=[service], identity_key=b"x" * 32)
    invalid = await manager.invoke("webhooks.outbound.save", {"name": []})
    response = adapter.DesktopResponse(invalid, "webhooks.outbound.save")
    assert not invalid["ok"]
    assert invalid["error"]["code"] == "bad_request"
    assert response.status == 400
    assert await response.json() == {"error": invalid["error"]["message"]}
    assert service.dispatcher.list_webhooks() == []
    unavailable = await ManagementService(None, services=[], identity_key=b"x" * 32).invoke(
        "webhooks.outbound.list", {})
    response = adapter.DesktopResponse(unavailable, "webhooks.outbound.list")
    assert not unavailable["ok"]
    assert unavailable["error"]["code"] == "capability_unavailable"
    assert response.status == 503
    assert await response.json() == {"error": "outbound webhooks not available"}
    # Unexpected business verdicts must never become the expected success/error.
    with pytest.raises(KeyError):
        adapter.DesktopResponse({"ok": False, "error": {
            "code": "internal", "message": "unknown", "disposition": "outcome_unknown",
        }}, "webhooks.outbound.save")
    await service.dispatcher.close()
