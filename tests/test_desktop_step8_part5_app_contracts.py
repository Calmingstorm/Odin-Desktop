"""Actual desktop settings boundaries behind inherited app-facing obligations."""
from __future__ import annotations

import pytest

from src.desktop.management import MethodError
from src.desktop.paths import ProfilePaths
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService
from src.tools.defs.agents import SPAWN_NEUTRAL_REASONING_OPTIONS


class TemporaryKeyring:
    def get_password(self, *_args):
        return None


@pytest.fixture
def settings(tmp_path):
    paths = ProfilePaths.from_xdg(home=tmp_path, environ={})
    paths.create_private()
    paths.config_file.write_text("# untouched profile\n{}\n")
    return SettingsService(paths, ProfileSecretStore(paths, backend=TemporaryKeyring()))


def test_desktop_schema_neutral_vocabulary_is_engine_authority(settings):
    fields = {row["path"]: row for row in settings.schema()["fields"]}
    assert fields["openai_compatible.reasoning_effort"]["enum"] == SPAWN_NEUTRAL_REASONING_OPTIONS
    assert fields["openai_codex.reasoning_effort"]["enum"] == SPAWN_NEUTRAL_REASONING_OPTIONS


@pytest.mark.asyncio
async def test_generic_settings_rejects_every_host_owned_field_atomically(settings):
    before = settings.config.model_dump()
    source = settings.paths.config_file.read_bytes()
    changes = [
        {"path": "tools.hosts", "value": {"new-host": {"address": "192.0.2.10"}}},
        {"path": "tools.default_host", "value": "new-host"},
        {"path": "tools.allow_host_tofu", "value": True},
    ]
    for submitted in [[change] for change in changes] + [changes]:
        with pytest.raises(MethodError) as caught:
            await settings.handle(
                "settings.set", {"expected_revision": settings.revision, "changes": submitted}
            )
        assert caught.value.code == "bad_request"
        assert "changed through hosts.settings" in str(caught.value)
        assert settings.config.model_dump() == before
        assert settings.paths.config_file.read_bytes() == source
