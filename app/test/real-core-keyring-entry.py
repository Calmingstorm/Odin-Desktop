"""Only substitute unavailable OS secret storage; execute the actual shipped CLI."""
import os
import runpy
from pathlib import Path

root = Path(os.environ["ODIN_REAL_CORE_ROOT"]).resolve()
assert os.getuid() != 0 and Path(os.environ["HOME"]).resolve() == root
assert os.readlink("/proc/self/ns/pid") != os.environ["ODIN_REAL_CORE_OUTER_PID_NS"]
from src.desktop.management import ManagementService


class MemoryKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, namespace, name):
        return self.values.get((namespace, name))

    def set_password(self, namespace, name, value):
        self.values[(namespace, name)] = value

    def delete_password(self, namespace, name):
        self.values.pop((namespace, name), None)


original = ManagementService.compose.__func__
backend = MemoryKeyring()
ManagementService.compose = classmethod(
    lambda cls, core, **kw: original(cls, core, secret_backend=backend)
)
runpy.run_module("src", run_name="__main__")
