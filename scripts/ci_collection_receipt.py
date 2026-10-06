"""Opt-in collect-only receipt of final selected pytest node IDs, not a model."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pytest_addoption(parser):
    parser.addoption("--ci-collection-receipt",
                     default=str(ROOT / ".test-state/ci-collected-nodeids.json"))


def pytest_collection_finish(session):
    if session.config.getoption("collectonly"):
        target = Path(session.config.getoption("--ci-collection-receipt"))
        target.write_text(json.dumps([item.nodeid for item in session.items], indent=2) + "\n")
