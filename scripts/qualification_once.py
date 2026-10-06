"""Assign overlapping selected node IDs to their first qualification group.

Only the qualification runner loads this plugin with a fresh, invocation-local
state file. Reviewed selectors and -k exclusions run normally before exact-ID
ownership filtering. A failed execution is never retried by a later group.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption("--qualification-once-state", required=True)


@pytest.hookimpl(wrapper=True)
def pytest_collection_modifyitems(config, items):
    result = yield
    target = Path(config.getoption("--qualification-once-state"))
    state = json.loads(target.read_text())
    seen = set(state["seen"])
    selected, duplicates, retained, deselected = [], [], [], []
    for item in items:
        if item.nodeid in seen:
            duplicates.append(item.nodeid)
            deselected.append(item)
        else:
            selected.append(item.nodeid)
            retained.append(item)
            seen.add(item.nodeid)
    items[:] = retained
    if deselected:
        config.hook.pytest_deselected(items=deselected)
    state["seen"] = sorted(seen)
    state["groups"].append({"selected": selected, "duplicates": duplicates})
    with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as file:
        json.dump(state, file)
        file.write("\n")
    os.replace(file.name, target)
    return result


def pytest_sessionfinish(session, exitstatus):
    # A reviewed group wholly owned by earlier groups still gets its JUnit
    # receipt, without treating deliberate duplicate deselection as "no tests".
    # Truly empty/excluded groups and collection errors keep their failure.
    if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED:
        state = json.loads(Path(session.config.getoption("--qualification-once-state")).read_text())
        if state["groups"] and state["groups"][-1]["duplicates"]:
            session.exitstatus = pytest.ExitCode.OK
