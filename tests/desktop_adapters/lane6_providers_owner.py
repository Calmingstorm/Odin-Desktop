"""Disposable real profile provider owner, with synthetic external transports."""
from __future__ import annotations

import tempfile
from pathlib import Path

from src.desktop.codex_accounts import CodexAccountsService
from src.desktop.paths import ProfilePaths
from src.desktop.providers import ProviderOwner
from src.desktop.secrets import ProfileSecretStore
from src.desktop.settings import SettingsService
from tests.desktop_adapters.step5_llm_bridge import MemoryKeyring


def gateway(*, get_config, settings_config=None, **dependencies):
    root = tempfile.TemporaryDirectory(prefix="lane6_providers_")
    paths = ProfilePaths.from_xdg(home=Path(root.name), environ={})
    paths.create_private()
    paths.config_file.write_text("{}\n")
    settings = SettingsService(paths, ProfileSecretStore(paths, backend=MemoryKeyring()))
    if settings_config is not None:
        settings.config = settings_config
        key = settings_config.openai_compatible.api_key
        if key:
            settings.secrets.set("openai_compatible.api_key", key)
    owner = ProviderOwner(settings, CodexAccountsService(settings),
                          get_config=get_config, **dependencies)
    owner._lane6_providers_directory = root
    # A test-injected graph is already serving; generation reads the explicitly
    # supplied live policy once, just as the canonical engine injection seam.
    owner._effective_config = None
    return owner
