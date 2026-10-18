"""Real entry/core that answers slowly once its gate appears, isolated E2E only.

The gate's text says how: "reads N" pauses the next N status.get answers for 2 s each (each
shorter than Exit's bound, together longer; the core answers a connection's requests in
order, so an Exit sent meanwhile waits behind them); "shutdown S" blocks the event loop for
S seconds when the next runtime.shutdown arrives, before it is accepted, as a stalled core on a
loaded machine does.
"""
import asyncio
import os
import time
from pathlib import Path

from src import __main__ as entry
from src.desktop.core import CoreService

gate = Path(os.environ["ODIN_DESKTOP_SLOW_READ_GATE"])
root = Path(os.environ["ODIN_REAL_CORE_ROOT"])
assert os.getuid() != 0 and gate.is_relative_to(root)
assert os.readlink("/proc/self/ns/pid") != os.environ["ODIN_REAL_CORE_OUTER_PID_NS"]
PAUSE_SECONDS = 2
original_init = CoreService.__init__
original_dispatch = CoreService.dispatch
slow_reads = 0


class EmptyKeyring:
    def get_password(self, service, name):
        return None


def initialize(self, *args, **kwargs):
    original_init(self, *args, secret_backend=EmptyKeyring(), **kwargs)


async def dispatch(self, connection, request):
    global slow_reads
    method = request.get("method")
    if method in ("status.get", "runtime.shutdown") and gate.exists():
        kind, _, amount = gate.read_text().partition(" ")
        if (kind, method) in (("reads", "status.get"), ("shutdown", "runtime.shutdown")):
            gate.unlink()
            gate.with_suffix(".entered").write_text(kind)
            if kind == "reads":
                slow_reads = int(amount)
            else:
                time.sleep(float(amount))
    if method == "status.get" and slow_reads > 0:
        slow_reads -= 1
        await asyncio.sleep(PAUSE_SECONDS)
    return await original_dispatch(self, connection, request)


CoreService.__init__ = initialize
CoreService.dispatch = dispatch
entry.main()
