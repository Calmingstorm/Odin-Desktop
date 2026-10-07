"""Real entry/core with one harmless startup read withheld, isolated E2E only."""
import os
import time
from pathlib import Path

from src import __main__ as entry
from src.desktop.core import CoreService
from src.desktop.settings import SettingsService

gate = Path(os.environ["ODIN_DESKTOP_STARTUP_GATE"])
root = Path(os.environ["ODIN_REAL_CORE_ROOT"])
assert os.getuid() != 0 and gate.is_relative_to(root)
assert os.readlink("/proc/self/ns/pid") != os.environ["ODIN_REAL_CORE_OUTER_PID_NS"]
original_init = CoreService.__init__
original_hydrate = SettingsService.hydrate_secrets
waited = False


class EmptyKeyring:
    def get_password(self, service, name):
        return None


def initialize(self, *args, **kwargs):
    original_init(self, *args, secret_backend=EmptyKeyring(), **kwargs)


def hydrate(self):
    global waited
    if not waited:
        waited = True
        gate.with_suffix(".entered").write_text("startup read entered")
        deadline = time.monotonic() + 30
        while not gate.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
    return original_hydrate(self)


CoreService.__init__ = initialize
SettingsService.hydrate_secrets = hydrate
entry.main()
