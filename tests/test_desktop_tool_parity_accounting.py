"""Offline, exact-only admission rejects hidden weakening and wrong corpus."""
import shutil
from pathlib import Path

from scripts.maintenance import phase2_suites as checker

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "tests/characterization/test_tool_parity.py"
HASH = "41aa806975873b2dd35cb0bc8f0c4763350f9a509c2f3c85b63f267be3f0a6c2"
SELECTOR = "tests/test_tool_parity.py"


def test_reviewed_parity_admission_is_exact_and_rejects_drift(tmp_path):
    files = [SOURCE, SELECTOR, "tests/desktop_adapters/tool_parity.py",
             "tests/test_desktop_tool_parity_adaptation.py"]
    for name in files:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    assert checker._full_adapter(tmp_path, SELECTOR, SOURCE, HASH, [])
    assert not checker._full_adapter(tmp_path, SELECTOR, SOURCE, "0" * 64, [])
    assert not checker._full_adapter(tmp_path, SELECTOR, "tests/test_other.py", HASH, [])
    assert not checker._full_adapter(tmp_path, SELECTOR, SOURCE, HASH, [{"case": "retired"}])
    for name in files:
        target = tmp_path / name
        original = target.read_bytes()
        target.write_bytes(original + b"\n# unreviewed alteration\n")
        assert not checker._full_adapter(tmp_path, SELECTOR, SOURCE, HASH, [])
        target.write_bytes(original)
