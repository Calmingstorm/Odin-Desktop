"""Read-only local X11 monitor discovery in a bounded, disposable worker."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# -I excludes ambient import paths, as with the retained attached workers.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.computer.runtime.x11_capture import X11MonitorCapture  # noqa: E402


def main():
    capture = X11MonitorCapture(sys.argv[1], enabled=True)
    try:
        topology = capture.topology()
        names = [capture._connection._display.get_atom_name(monitor.identity[0])
                 for monitor in topology.monitors]
        print(json.dumps(names))
    finally:
        capture.close()


if __name__ == "__main__":
    main()
