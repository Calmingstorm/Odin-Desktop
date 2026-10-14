"""Native macOS tests: collected only on macOS, run by the macOS engine job.

Tests that write to a keychain run only when the job has made a disposable default keychain
(ODIN_MACOS_DISPOSABLE_KEYCHAIN=1). They never run against a person's own login keychain.
"""
from __future__ import annotations

import sys

collect_ignore_glob = [] if sys.platform == "darwin" else ["test_*.py"]
