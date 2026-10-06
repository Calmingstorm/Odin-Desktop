"""Merged audit authority remains profile-bound and off the event loop."""
import asyncio
import threading
from types import SimpleNamespace

import pytest

from src.audit.logger import AuditLogger
from src.desktop.hosts import HostsService
from src.desktop.management import MethodError
from src.desktop.paths import ProfilePaths
from src.desktop.records import RecordsService
from src.desktop.secrets import ProfileSecretStore, SecretStoreError
from src.desktop.settings import SettingsService
from tests.desktop_adapters.step8_runtime_guard import temporary_guard_graph


@pytest.mark.asyncio
@pytest.mark.parametrize("method,params", [
    ("audit.query", {}), ("audit.verify", {}), ("logs.search", {"level": "all"}),
])
async def test_signed_record_reads_resolve_authority_in_settled_worker(tmp_path, method, params):
    path = tmp_path / "audit.jsonl"
    key = "isolated-round3-signing-key"
    writer = AuditLogger(str(path), hmac_key=key)
    await writer.log_event(event_type="fixture", action="saved", detail="fixture")
    before = path.read_bytes()
    loop_thread = threading.get_ident()
    calls = []

    def resolve():
        assert threading.get_ident() != loop_thread
        assert threading.current_thread().daemon
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        calls.append(True)
        return key

    settings = SimpleNamespace(
        config=SimpleNamespace(audit=SimpleNamespace(hmac_key=""),
                               tools=SimpleNamespace(audit_log_path=str(path))),
        audit_signing_key=resolve,
    )
    reader = RecordsService(SimpleNamespace(data_dir=tmp_path), settings=settings)
    answer = await reader.handle(method, params)
    if method == "audit.verify":
        assert answer["valid"] is True
        assert answer["verified"] == 1
    assert calls == [True]
    assert reader._audit_reader._signer is not None
    assert path.read_bytes() == before


@pytest.mark.asyncio
async def test_locked_signing_authority_keeps_history_readable_unverified(tmp_path):
    path = tmp_path / "audit.jsonl"
    writer = AuditLogger(str(path), hmac_key="isolated-original-key")
    await writer.log_event(event_type="fixture", action="retained", detail="retained record")
    before = path.read_bytes()

    def locked():
        raise SecretStoreError("isolated locked backend")

    settings = SimpleNamespace(
        config=SimpleNamespace(audit=SimpleNamespace(hmac_key="isolated-stale-config-key"),
                               tools=SimpleNamespace(audit_log_path=str(path))),
        audit_signing_key=locked,
    )
    reader = RecordsService(SimpleNamespace(data_dir=tmp_path), settings=settings)
    assert (await reader.handle("audit.query", {}))[0]["tool_name"] == "retained"
    result = await reader.handle("audit.verify", {})
    assert result["valid"] is False
    assert result["verified"] == 0
    assert result["availability"] == "not_enabled"
    assert result["segments"] == []
    assert reader.audit._signer is None
    assert path.read_bytes() == before


class _IsolatedAuditKeyring:
    """Only this injected backend accesses a disposable credential file."""

    def __init__(self, path, state="available"):
        self.path, self.state = path, state
        self.calls = []

    def get_password(self, namespace, name):
        self.calls.append((namespace, name, threading.get_ident()))
        assert name == "audit.hmac_key"
        if self.state == "unavailable":
            raise RuntimeError("disposable backend is unavailable")
        if self.state == "missing":
            return None
        return self.path.read_text()


def _settings_with_audit_keyring(tmp_path, key, state):
    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    paths.create_private()
    paths.config_file.write_text("{}\n")
    key_file = tmp_path / "disposable-signing-key"
    if state != "missing":
        key_file.write_text(key)
        if state == "unreadable":
            key_file.chmod(0)
    backend = _IsolatedAuditKeyring(key_file, state)
    secrets = ProfileSecretStore(paths, backend=backend)
    return paths, SettingsService(paths, secrets), backend


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["unavailable", "missing", "unreadable"])
@pytest.mark.parametrize("signed", [False, True])
async def test_real_profile_missing_authority_reads_signed_and_unsigned_history(
    tmp_path, state, signed,
):
    key = "isolated-round5-authority"
    paths, settings, backend = _settings_with_audit_keyring(tmp_path, key, state)
    writer = AuditLogger(str(paths.data_dir / "audit.jsonl"), hmac_key=key if signed else "")
    await writer.log_event(event_type="fixture", action="retained", detail="readable history")
    before = writer.path.read_bytes()
    chain = writer._signer.prev_hmac if signed else None
    if state != "missing":
        # Even previously hydrated authority is not usable while its store is
        # inaccessible. Missing authority follows the existing config fallback.
        settings.config.audit.hmac_key = key
        with pytest.raises(SecretStoreError):
            settings.audit_signing_key()
    else:
        assert settings.audit_signing_key() == ""
        assert not backend.path.exists()

    reader = RecordsService(paths, settings=settings)
    loop_thread = threading.get_ident()
    backend.calls.clear()
    queried = await reader.handle("audit.query", {"q": "readable history", "tool": "retained"})
    assert len(queried) == 1
    assert queried[0]["tool_name"] == "retained"
    logs = await reader.handle("logs.search", {"level": "all", "q": "readable history"})
    assert logs == {"entries": queried, "count": 1}
    verified = await reader.handle("audit.verify", {})
    assert verified["valid"] is False
    assert verified["verified"] == 0
    assert verified["availability"] == "not_enabled"
    assert verified["segments"] == []
    assert "Signing not enabled" in verified["error"]
    assert len(backend.calls) == 3
    assert all(thread != loop_thread for _, _, thread in backend.calls)
    assert all(namespace == settings.secrets.namespace for namespace, _, _ in backend.calls)
    # The synchronous property follows the same no-authority contract.
    assert reader.audit._signer is None
    assert writer.path.read_bytes() == before
    assert (writer._signer.prev_hmac if signed else None) == chain
    assert paths.config_file.read_text() == "{}\n"
    assert not writer.path.with_name(writer.path.name + ".repair-required").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("synchronous_loss", [False, True])
async def test_authority_loss_recovery_restart_and_tamper_keep_fresh_binding(
    tmp_path, synchronous_loss,
):
    key = "isolated-round5-restart-authority"
    paths, settings, backend = _settings_with_audit_keyring(tmp_path, key, "available")
    path = paths.data_dir / "audit.jsonl"
    # The retained unsigned prefix must not count as verified even when a key
    # becomes available later, across fresh SettingsService/reader instances.
    unsigned = AuditLogger(str(path))
    await unsigned.log_event(event_type="fixture", action="unsigned", detail="unsigned prefix")
    writer = AuditLogger(str(path), hmac_key=settings.audit_signing_key())
    await writer.log_event(event_type="fixture", action="signed", detail="signed history")
    original_chain = writer._signer.prev_hmac
    before = path.read_bytes()
    restarted = SettingsService(paths, settings.secrets)
    assert restarted.config.audit.hmac_key == ""
    reader = RecordsService(paths, settings=restarted)
    verified = await reader.handle("audit.verify", {})
    assert verified["valid"] is True
    assert verified["total"] == 2
    assert verified["verified"] == 1
    assert verified["unsigned_prefix"] == 1
    original_reader = reader._audit_reader

    backend.state = "unavailable"
    if synchronous_loss:
        assert reader.audit._signer is None
    lost = await reader.handle("audit.verify", {})
    assert lost["valid"] is False
    assert lost["verified"] == 0
    assert lost["availability"] == "not_enabled"
    assert reader._audit_reader is not original_reader
    assert reader._audit_reader._signer is None
    assert len(await reader.handle("audit.query", {})) == 2
    assert (await reader.handle("logs.search", {}))["count"] == 2

    backend.state = "available"
    recovered = await reader.handle("audit.verify", {})
    assert recovered == verified
    assert reader._audit_reader._signer is not None
    assert path.read_bytes() == before
    # The reader neither resumes the writer chain nor repairs altered history.
    tampered = path.read_text().replace("signed history", "altered history", 1)
    path.write_text(tampered)
    broken = await reader.handle("audit.verify", {})
    assert broken["valid"] is False
    assert broken["first_bad"] is not None
    assert broken["segments"][0]["status"] == "broken"
    assert path.read_text() == tampered
    assert writer._signer.prev_hmac == original_chain


@pytest.mark.asyncio
async def test_available_profile_key_does_not_verify_wholly_unsigned_records(tmp_path):
    paths, settings, _ = _settings_with_audit_keyring(
        tmp_path, "isolated-round5-unused-authority", "available",
    )
    writer = AuditLogger(str(paths.data_dir / "audit.jsonl"))
    await writer.log_event(event_type="fixture", action="unsigned", detail="unsigned history")
    before = writer.path.read_bytes()
    reader = RecordsService(paths, settings=settings)
    assert (await reader.handle("audit.query", {}))[0]["tool_name"] == "unsigned"
    verified = await reader.handle("audit.verify", {})
    assert verified["verified"] == 0
    assert verified["unsigned_prefix"] == verified["total"] == 1
    assert verified["segments"][0]["status"] == "unsigned"
    assert writer.path.read_bytes() == before


@pytest.mark.asyncio
async def test_unexpected_signing_resolver_error_still_refuses_records(tmp_path):
    def broken():
        raise ValueError("unexpected manager failure")

    settings = SimpleNamespace(
        config=SimpleNamespace(audit=SimpleNamespace(hmac_key="")),
        audit_signing_key=broken,
    )
    reader = RecordsService(SimpleNamespace(data_dir=tmp_path), settings=settings)
    with pytest.raises(MethodError, match="Records read is unavailable"):
        await reader.handle("audit.query", {})
    with pytest.raises(ValueError, match="unexpected manager failure"):
        _ = reader.audit
    assert reader._audit_reader is None


def test_host_audit_resolves_restart_signing_authority_offloop(tmp_path):
    with temporary_guard_graph(tmp_path, False) as (core, runner):
        key = "isolated-round3-host-signing-key"
        calls = []

        def resolve():
            assert threading.current_thread().daemon
            with pytest.raises(RuntimeError):
                asyncio.get_running_loop()
            calls.append(True)
            return key

        settings = core.management.settings
        settings.audit_signing_key = resolve
        service = HostsService(settings)
        runner.run(service._audit("save", "fixture"))
        assert calls == [True]
        assert service.audit is not None
        assert service.audit._signer is not None
        result = runner.run(service.audit.verify_integrity())
        assert result["valid"] is True
        assert result["verified"] == 1


@pytest.mark.asyncio
async def test_pending_audit_key_read_keeps_loop_responsive_and_settles_cancellation(tmp_path):
    entered, release = threading.Event(), threading.Event()

    def blocked():
        entered.set()
        assert release.wait(5)
        return "isolated-key"

    settings = SimpleNamespace(
        config=SimpleNamespace(audit=SimpleNamespace(hmac_key="")),
        audit_signing_key=blocked,
    )
    reader = RecordsService(SimpleNamespace(data_dir=tmp_path), settings=settings)
    task = asyncio.create_task(reader.handle("audit.verify", {}))
    try:
        for _ in range(500):
            if entered.is_set():
                break
            await asyncio.sleep(.001)
        assert entered.is_set()
        task.cancel()
        await asyncio.sleep(.02)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert reader._audit_reader is None
