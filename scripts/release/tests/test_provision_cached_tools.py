"""Cached runtime selection validates existing binaries and never installs runtimes."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "provision_cached_tools.py"


def _runtime(path, version):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{version}'\n")
    path.chmod(0o755)
    return path


def _python_cache(root, version="3.12.4", actual=None):
    directory = root / "Python" / version
    directory.mkdir(parents=True)
    (directory / "x64.complete").touch()
    executable = _runtime(directory / "x64/bin/python", actual or version)
    _runtime(directory / "x64/bin/python3", actual or version)
    return executable


def _run(cache, tmp_path, *, require_node=False, path=""):
    output = tmp_path / "output"
    ghpath = tmp_path / "path"
    env = {
        "PATH": path,
        "GITHUB_OUTPUT": str(output),
        "GITHUB_PATH": str(ghpath),
    }
    if cache is not None:
        env["RUNNER_TOOL_CACHE"] = str(cache)
    args = [sys.executable, str(SCRIPT)] + (["--require-node"] if require_node else [])
    return subprocess.run(args, env=env, capture_output=True, text=True), output, ghpath


class ProvisionCachedToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cache = self.root / "cache"

    def tearDown(self):
        self.temp.cleanup()

    def run_helper(self, *, require_node=False, path="", cache=None):
        return _run(cache or self.cache, self.root, require_node=require_node, path=path)

    def test_cached_python_and_cached_node_are_selected_and_version_checked(self):
        py = _python_cache(self.cache)
        node_dir = self.cache / "node" / "22.23.3"
        node_dir.mkdir(parents=True)
        (node_dir / "x64.complete").touch()
        node = _runtime(node_dir / "x64/bin/node", "v22.23.3")

        result, output, paths = self.run_helper(require_node=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output.read_text().splitlines(), [f"python={py}", f"node={node}"])
        self.assertEqual(paths.read_text().splitlines(), [str(py.parent), str(node.parent)])

    def test_cached_python_chooses_highest_verified_patch(self):
        _python_cache(self.cache, "3.12.8")
        selected = _python_cache(self.cache, "3.12.11")
        result, output, _ = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output.read_text().splitlines(), [f"python={selected}"])

    def test_python_failure_branches_never_download(self):
        for case in ("missing", "wrong_version", "marker_missing", "binary_missing",
                     "python3_missing", "python3_mismatch"):
            with self.subTest(case=case):
                cache = self.root / f"{case}-cache"
                if case == "wrong_version":
                    _python_cache(cache, actual="3.11.9")
                elif case == "marker_missing":
                    binary = _python_cache(cache)
                    (binary.parents[2] / "x64.complete").unlink()
                elif case == "binary_missing":
                    _python_cache(cache).unlink()
                elif case == "python3_missing":
                    _python_cache(cache).with_name("python3").unlink()
                elif case == "python3_mismatch":
                    executable = _python_cache(cache).with_name("python3")
                    executable.write_text("#!/bin/sh\nprintf '%s\\n' '3.11.9'\n")
                result, output, paths = self.run_helper(cache=cache)
                self.assertEqual(result.returncode, 1)
                self.assertIn("Provision Python 3.12", result.stderr)
                self.assertIn("download", result.stderr)
                self.assertFalse(output.exists())
                self.assertFalse(paths.exists())

    def test_wrong_system_node_version_fails_without_download(self):
        for node_version in ("v20.18.0", "not-node", "v22.bad"):
            with self.subTest(node_version=node_version):
                cache = self.root / f"cache-{node_version}"
                _python_cache(cache)
                system_bin = self.root / f"system-{node_version}"
                _runtime(system_bin / "node", node_version)
                result, output, paths = self.run_helper(
                    require_node=True, path=str(system_bin), cache=cache
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn("Node.js 22", result.stderr)
                self.assertIn("will not download", result.stderr)
                self.assertFalse(output.exists())
                self.assertFalse(paths.exists())

    def test_node22_system_fallback_does_not_require_toolcache_node(self):
        py = _python_cache(self.cache)
        system_bin = self.root / "system"
        node = _runtime(system_bin / "node", "v22.1.0")
        result, output, _ = self.run_helper(require_node=True, path=str(system_bin))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output.read_text().splitlines(), [f"python={py}", f"node={node}"])

    def test_python_only_jobs_do_not_require_node(self):
        py = _python_cache(self.cache)
        result, output, paths = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output.read_text().splitlines(), [f"python={py}"])
        self.assertEqual(paths.read_text().splitlines(), [str(py.parent)])

    def test_missing_tool_cache_fails_instead_of_scanning_current_directory(self):
        result, output, paths = _run(None, self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("RUNNER_TOOL_CACHE is unset", result.stderr)
        self.assertFalse(output.exists())
        self.assertFalse(paths.exists())

    def test_wrong_or_incomplete_cached_node_never_masks_valid_system_node(self):
        py = _python_cache(self.cache)
        node_dir = self.cache / "node" / "22.23.3"
        node_dir.mkdir(parents=True)
        (node_dir / "x64.complete").touch()
        _runtime(node_dir / "x64/bin/node", "v22.22.0")
        incomplete = self.cache / "node" / "22.99.0"
        _runtime(incomplete / "x64/bin/node", "v22.99.0")
        system_bin = self.root / "system"
        node = _runtime(system_bin / "node", "v22.1.0")
        result, output, _ = self.run_helper(require_node=True, path=str(system_bin))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output.read_text().splitlines(), [f"python={py}", f"node={node}"])
