"""Hosted tests must measure a trusted fixture, never weaken executable trust."""
import os
import stat
from pathlib import Path


def test_workflow_uses_owned_interpreter_copy():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/phase1-engine.yml").read_text()
    assert "python -m venv --copies .venv" in workflow
    executable = Path(f"/proc/{os.getpid()}/exe")
    measured = executable.stat()
    assert stat.S_ISREG(measured.st_mode)
    assert not measured.st_mode & 0o022
