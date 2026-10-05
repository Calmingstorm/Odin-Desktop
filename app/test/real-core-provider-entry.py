"""Test-only config injection, retaining the repository's actual CLI/lifecycle.

The steps 2-4 CLI has no provider settings loader. Its existing CoreService
config_provider seam is used, never a fabricated runner/client/tool result.
"""
import json
import os
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY))


def main():
    root = Path(os.environ["ODIN_REAL_CORE_ROOT"]).resolve()
    outer = os.environ["ODIN_REAL_CORE_OUTER_PID_NS"]
    assert os.getuid() != 0 and os.readlink("/proc/self/ns/pid") != outer
    assert Path(os.environ["HOME"]).resolve().is_relative_to(root)
    # Electron smoke has its own isolated Xvfb. Core is headless regardless;
    # remove display handles only after establishing namespace ownership.
    os.environ.pop("DISPLAY", None)
    os.environ.pop("WAYLAND_DISPLAY", None)
    config_path = Path(os.environ["ODIN_REAL_CORE_PROVIDER_CONFIG"]).resolve()
    assert config_path.is_relative_to(root)
    patch = json.loads(config_path.read_text())
    from urllib.parse import urlparse
    parsed = urlparse(patch["openai_compatible"]["base_url"])
    assert parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
    assert patch["openai_compatible"]["api_key"] == "canned-local-test-only"

    from src.config import Config
    from src.desktop import core
    original = core.CoreService

    def config_provider(paths):
        values = core.profile_config(paths).model_dump(mode="json")
        for key, value in patch.items():
            values[key] = {**values[key], **value} if isinstance(value, dict) else value
        workspace = Path(values["tools"]["local_working_dir"])
        assert workspace.resolve().is_relative_to(root)
        workspace.mkdir(parents=True, mode=0o700, exist_ok=True)
        try:
            return Config.model_validate(values)
        except Exception as error:
            # Fixture has only a disposable test credential. Validation locations
            # and messages are useful; never echo the complete config/input.
            details = error.errors(include_input=False) if hasattr(error, "errors") else type(error).__name__
            print(f"Canned fixture config validation failed: {details}", file=sys.stderr)
            raise

    class ProviderCore(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, config_provider=config_provider)

    core.CoreService = ProviderCore
    from src.__main__ import main as real_main
    real_main()


if __name__ == "__main__":
    main()
