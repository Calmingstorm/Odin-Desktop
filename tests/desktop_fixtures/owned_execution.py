"""Harmless, bounded descendant effect, only inside the private PID runner."""
import json
import os
import signal
import sys
import time
from pathlib import Path


def identity():
    pid = os.getpid()
    raw = Path(f"/proc/{pid}/stat").read_text()
    return {"pid": pid, "ppid": os.getppid(), "sid": os.getsid(0),
            "pgid": os.getpgrp(), "startTicks": raw[raw.rfind(")") + 2:].split()[19],
            "namespace": os.readlink("/proc/self/ns/pid")}


def main():
    root = Path(sys.argv[1])
    if os.getuid() == 0 or not os.environ.get("ODIN_REAL_CORE_OUTER_PID_NS"):
        raise RuntimeError("Owned execution requires unprivileged PID isolation")
    if os.readlink("/proc/self/ns/pid") == os.environ["ODIN_REAL_CORE_OUTER_PID_NS"]:
        raise RuntimeError("Refusing host PID namespace")
    if not root.is_relative_to(Path(os.environ["HOME"])):
        raise RuntimeError("Owned effects must remain under throwaway HOME")
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if os.fork() == 0:
        os.setsid()
        if os.fork() != 0:
            os._exit(0)
        role = "escaped"
    else:
        role = "leader"
    (root / f"{role}.json").write_text(json.dumps(identity()))
    deadline = time.monotonic() + 40
    with (root / f"{role}.effects").open("a", buffering=1) as effects:
        while time.monotonic() < deadline:
            effects.write("effect\n")
            time.sleep(0.025)


if __name__ == "__main__":
    main()
