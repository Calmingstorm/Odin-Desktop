"""A saved personality preset selected before a restart is the identity from the first prompt.

Temporary profile, a fake compatible provider, no network.
"""

import pytest

from src.config.schema import Config, PersonalityPreset
from src.desktop.authority import OwnerAuthority
from src.desktop.commands import JournalStore
from src.desktop.conversations import ConversationStore
from src.desktop.delivery import DurableDelivery, PublicationEventJournal
from src.desktop.paths import ProfilePaths
from src.desktop.services import build_engine_services
from src.desktop.transcript import TranscriptStore
from src.llm.system_prompt import register_user_presets
from src.permissions.manager import PermissionManager
from tests.test_desktop_engine_services import Provider


@pytest.fixture
def restarted_profile(tmp_path):
    """A fresh process: the saved-preset registry starts empty, as it does after a restart."""
    register_user_presets({})
    paths = ProfilePaths.from_xdg("test", home=tmp_path, environ={})
    authority = OwnerAuthority(paths)
    permissions = PermissionManager(authority)
    owner = authority.authenticate_local(peer_uid=authority.owner_uid)
    token = permissions.set_request_owner(owner)
    store = JournalStore(paths.data_dir / "transport.sqlite3", "test")
    events = PublicationEventJournal(store)
    transcript = TranscriptStore(store, events, ConversationStore(store, events))
    delivery = DurableDelivery(store, events, transcript_commit=transcript.commit)
    engines = []

    def start(cfg):
        engine = build_engine_services(cfg, paths, permissions, delivery=delivery,
                                       compatible_client=Provider([]))
        engines.append(engine)
        return engine

    yield paths, start
    for engine in engines:
        engine.deps.turn_store.close()
    store.close()
    permissions.reset_request_owner(token)
    authority.release_runtime()
    register_user_presets({})


def config(paths, preset, presets):
    cfg = Config()
    cfg.openai_codex.enabled = False
    cfg.llm_provider.model = "compat:test"
    cfg.openai_compatible.enabled = True
    cfg.context.directory = str(paths.data_dir / "context")
    cfg.learning.enabled = False
    cfg.browser.enabled = False
    cfg.personality.user_presets = presets
    cfg.personality.preset = preset
    return cfg


def test_a_saved_preset_is_the_identity_from_the_first_prompt_after_a_restart(restarted_profile):
    paths, start = restarted_profile
    identity = "You are Clippy, the paperclip assistant."
    clippy = PersonalityPreset(name="Clippy", identity=identity, voice="Cheerful, a little nosy.")
    engine = start(config(paths, "clippy", {"clippy": clippy}))
    prompt = engine.deps.prompt_builder.default_prompt
    assert "Clippy" in prompt
    assert identity in prompt
    assert "Cheerful, a little nosy." in prompt
    assert "All-Father" not in prompt
    # Every later prompt resolves it too, not only the cached default.
    assert identity in engine.deps.prompt_builder.build_full_prompt()


def test_built_in_and_custom_personalities_are_unchanged(restarted_profile):
    paths, start = restarted_profile
    assert "All-Father" in start(config(paths, "odin", {})).deps.prompt_builder.default_prompt
    custom = config(paths, "custom", {})
    custom.personality.custom_name = "Hal"
    custom.personality.custom_identity = "You are Hal, a calm ship computer."
    assert "You are Hal, a calm ship computer." in start(custom).deps.prompt_builder.default_prompt
