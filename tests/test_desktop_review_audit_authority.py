"""Keyring-backed audit reads and writes agree before incidental schema reads."""
import pytest

from src.audit.logger import AuditLogger
from src.desktop.hosts import HostsService
from src.desktop.management import MethodError
from src.desktop.records import RecordsService
from src.desktop.secrets import ProfileSecretStore, SecretStoreError
from src.desktop.settings import SettingsService
from tests.desktop_adapters.step8_runtime_guard import (
    TemporaryKeyring,
    temporary_guard_graph,
)


def test_composed_restart_verifies_keyring_signed_history_before_schema(tmp_path):
    key = "temporary-profile-audit-signing-key"
    with temporary_guard_graph(tmp_path, False) as (core, runner):
        manager = core.management
        settings = manager.settings
        settings.secrets.set("audit.hmac_key", key)
        assert settings.config.audit.hmac_key == ""
        assert not settings._keyring_checked
        paths, backend = core.paths, settings.secrets._backend
        reader = manager.methods["audit.verify"]
        runner.run(manager.hosts._audit("save", "fixture"))
        writer = manager.hosts.audit
        assert writer._signer is not None
        answer = runner.run(manager.invoke("audit.verify", {}))
        assert answer["ok"]
        assert answer["result"]["valid"] is True
        assert answer["result"]["verified"] == 1
        assert reader.audit._signer is not None
        assert not settings._keyring_checked
        before = writer.path.read_bytes()
        restarted_settings = SettingsService(
            paths, ProfileSecretStore(paths, backend=backend),
        )
        assert restarted_settings.config.audit.hmac_key == ""
        restarted_reader = RecordsService(paths, settings=restarted_settings)
        verified = runner.run(restarted_reader.handle("audit.verify", {}))
        assert verified["valid"] is True
        assert verified["verified"] == 1
        assert not restarted_settings._keyring_checked
        assert writer.path.read_bytes() == before
        assert key not in paths.config_file.read_text()


def test_reader_keyring_failure_is_unavailable_not_unsigned(tmp_path):
    with temporary_guard_graph(tmp_path, False) as (core, runner):
        key = "temporary-profile-audit-signing-key"
        path = core.paths.data_dir / "audit.jsonl"
        writer = AuditLogger(str(path), hmac_key=key)
        runner.run(writer.log_event(event_type="fixture", action="saved", detail="fixture"))
        before = path.read_bytes()

        class Locked(TemporaryKeyring):
            def get_password(self, *args):
                raise RuntimeError("temporary locked vault")

        settings = SettingsService(
            core.paths, ProfileSecretStore(core.paths, backend=Locked()),
        )
        with pytest.raises(SecretStoreError):
            settings.audit_signing_key()
        reader = RecordsService(core.paths, settings=settings)
        with pytest.raises(MethodError, match="Records read is unavailable"):
            runner.run(reader.handle("audit.verify", {}))
        assert path.read_bytes() == before
        service = HostsService(settings)
        runner.run(service._audit("save", "fixture"))
        assert service.audit is None
        assert path.read_bytes() == before
