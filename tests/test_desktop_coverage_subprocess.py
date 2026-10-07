"""A child interpreter contributes actual engine execution to coverage reports."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_child_python_coverage_is_not_only_parent_imports(tmp_path):
    from coverage import Coverage

    root = Path(__file__).parents[1]
    config = tmp_path / "coverage.ini"
    config.write_text(
        f"[run]\nsource = {root / 'src/desktop'}\npatch = subprocess\n"
        f"data_file = {tmp_path / '.coverage'}\n")
    # A harmless child performs only the pure protocol encoder. The parent
    # never imports that module under the measured Coverage object.
    cov = Coverage(config_file=str(config))
    cov.start()
    result = subprocess.run(
        [sys.executable, "-c",
         "from src.desktop.protocol import encode_frame; "
         "assert encode_frame({'fixture': 1})[4:] == b'{\\\"fixture\\\":1}'"],
        cwd=root, capture_output=True, text=True, timeout=10,
    )
    cov.stop()
    cov.save()
    assert result.returncode == 0, result.stderr
    cov.combine(strict=True)
    cov.save()
    data = cov.get_data()
    path = str(root / "src/desktop/protocol.py")
    assert data.lines(path), "Child engine lines absent from measurement"
