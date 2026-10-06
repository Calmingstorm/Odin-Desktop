"""Merged audit authority remains profile-bound and off the event loop."""
import asyncio
import threading
from types import SimpleNamespace

import pytest

from src.audit.logger import AuditLogger
from src.desktop.hosts import HostsService
from src.desktop.management import MethodError
from src.desktop.records import RecordsService
from src.desktop.secrets import SecretStoreError
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
async def test_locked_signing_authority_does_not_fall_back_to_unsigned(tmp_path):
    def locked():
        raise SecretStoreError("isolated locked backend")

    settings = SimpleNamespace(
        config=SimpleNamespace(audit=SimpleNamespace(hmac_key="")),
        audit_signing_key=locked,
    )
    reader = RecordsService(SimpleNamespace(data_dir=tmp_path), settings=settings)
    with pytest.raises(MethodError, match="Records read is unavailable"):
        await reader.handle("audit.verify", {})
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
