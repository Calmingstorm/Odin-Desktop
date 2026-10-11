"""Only the named pip payload may differ in Linux, including a real old tree.

Set ODIN_LINUX_PIP_BASELINE to an existing, packaged pre-exception runtime root
(containing python/). The acceptance row copies it, never edits the original.
Other rows are portable and use the real pinned wheel, not mocked pip bytes.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

MODULE = Path(__file__).resolve().parents[1] / "python/runtime.py"
IMPORT = importlib.util.spec_from_file_location("linux_pip_runtime", MODULE)
runtime = importlib.util.module_from_spec(IMPORT)
IMPORT.loader.exec_module(runtime)


def inventory(root):
    """Exact paths, object kind, mode, bytes/link target, including empty dirs."""
    rows = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            rows[name] = ("link", stat.S_IMODE(info.st_mode), os.readlink(path))
        elif path.is_dir():
            rows[name] = ("dir", stat.S_IMODE(info.st_mode))
        else:
            rows[name] = ("file", stat.S_IMODE(info.st_mode), runtime.sha256(path))
    return rows


def assert_only_named_change(case, before, after, version):
    """Not a broad prefix exemption: exact pip roots and two derived records."""
    site = runtime.SITE.as_posix()
    roots = (site + "/pip", site + f"/pip-{version}.dist-info")
    records = {"python/runtime-metadata.json", "python/dependency-licenses.json"}
    changed = {name for name in before.keys() | after.keys()
               if before.get(name) != after.get(name)}
    unexpected = {name for name in changed
                  if name not in records and not any(
                      name == root or name.startswith(root + "/") for root in roots)}
    case.assertFalse(unexpected, f"Non-pip Linux output changed: {sorted(unexpected)}")
    case.assertTrue(changed, "No actual copied-tree change was measured")
    return changed


class LinuxPipException(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads(runtime.LOCK_PATH.read_text())
        cls.pin = cls.spec["pip"]
        cls.temporary = tempfile.TemporaryDirectory(prefix="linux-pip-exception-")
        cls.cache = Path(cls.temporary.name)
        # Download only the exact lock, always hash/size-check. No environment
        # installs, resolver, newest-release lookup or upstream pip invocation.
        cls.wheel = runtime._download(cls.pin, cls.cache / "artifacts")
        if cls.wheel.stat().st_size != cls.pin["size"]:
            raise AssertionError("Downloaded pinned pip size mismatch")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_both_platform_locks_pin_the_exact_uv_lock_wheel(self):
        self.assertEqual(runtime._locked_pip(self.spec), self.pin)
        windows = json.loads((runtime.LOCK_PATH.parent /
                              "runtime-lock.win_amd64.json").read_text())
        self.assertEqual(windows["pip"], {k: v for k, v in self.pin.items()
                                        if k != "named_change"})

    def test_each_lock_drift_and_missing_provenance_is_rejected(self):
        for key, value in [("version", "0"), ("url", "https://invalid/pip.whl"),
                           ("sha256", "0" * 64), ("size", 1), ("license", ""),
                           ("provenance", ""), ("named_change", "")]:
            changed = copy.deepcopy(self.spec)
            changed["pip"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                runtime._locked_pip(changed)

    def test_bootstrap_and_target_shadow_are_replaced_by_exact_wheel(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            site = root / runtime.SITE
            (site / "pip").mkdir(parents=True)
            (site / "pip/stale-bootstrap.py").write_bytes(b"upstream bootstrap")
            for version in ("24.0", "26.2.1"):
                (site / f"pip-{version}.dist-info").mkdir()
                (site / f"pip-{version}.dist-info/INSTALLER").write_bytes(b"stale")
            (root / "python/bin").mkdir()
            (root / "python/bin/python3.12").write_bytes(b"interpreter sentinel")
            record = runtime._stage_pip(root, self.cache, self.spec)
            runtime._clean_runtime(root)
            self.assertFalse((site / "pip/stale-bootstrap.py").exists())
            self.assertFalse((site / "pip-24.0.dist-info").exists())
            self.assertFalse((site / "pip-26.2.1.dist-info/INSTALLER").exists())
            with zipfile.ZipFile(self.wheel) as wheel:
                expected = {"python/lib/python3.12/site-packages/" + n:
                            hashlib.sha256(wheel.read(n)).hexdigest()
                            for n in wheel.namelist() if not n.endswith("/")}
            self.assertEqual({r["path"]: r["sha256"] for r in record["payload"]}, expected)
            runtime._verify_staged_pip(root, {"pip": record}, self.spec)
            self.assertTrue(record["license_files"])
            (site / "pip/extra.py").write_bytes(b"unexpected")
            with self.assertRaises(ValueError):
                runtime._verify_staged_pip(root, {"pip": record}, self.spec)

    def test_old_cache_refused_before_engine_refresh_or_any_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "python").mkdir()
            (root / "python/runtime-metadata.json").write_text(json.dumps({
                "python": self.spec["python"], "uv_lock_sha256": runtime.sha256(runtime.REPO / "uv.lock")
            }))
            before = inventory(root)
            with patch.object(runtime, "refresh_engine") as refresh:
                with self.assertRaisesRegex(ValueError, "stage a new bundle root"):
                    runtime.stage_runtime(root, self.cache)
                refresh.assert_not_called()
            self.assertEqual(before, inventory(root))

    def test_corrupt_cached_wheel_refused_without_bootstrap_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "runtime"
            cache = Path(temporary) / "cache"
            (root / runtime.SITE / "pip").mkdir(parents=True)
            (root / runtime.SITE / "pip/__init__.py").write_bytes(b"old")
            (cache / "artifacts").mkdir(parents=True)
            (cache / "artifacts" / self.pin["sha256"]).write_bytes(b"corrupt")
            before = inventory(root)
            with self.assertRaisesRegex(ValueError, "Corrupt cached artifact"):
                runtime._stage_pip(root, cache, self.spec)
            self.assertEqual(before, inventory(root))

    def test_comparison_rejects_non_pip_and_unrelated_dist_info_changes(self):
        before = {"python/bin/python3.12": ("file", 493, "hash")}
        for path in ("python/bin/python3.12", runtime.SITE.as_posix() + "/pip-unlocked.dist-info/METADATA",
                     runtime.SITE.as_posix() + "/pip_shadow/__init__.py",
                     "python/engine-source.json", "python/other.json"):
            with self.subTest(path=path), self.assertRaises(AssertionError):
                assert_only_named_change(self, before, {**before, path: ("file", 493, "different")},
                                         self.pin["version"])

    @unittest.skipUnless(os.environ.get("ODIN_LINUX_PIP_BASELINE"),
                         "requires an actual existing packaged Linux runtime")
    def test_actual_copied_existing_tree_only_pip_and_derived_records_change(self):
        original = Path(os.environ["ODIN_LINUX_PIP_BASELINE"]).resolve()
        self.assertTrue((original / "python/bin/python3.12").is_file())
        source = inventory(original)
        self.assertFalse(any(n == runtime.SITE.as_posix() + "/pip" for n in source),
                         "Acceptance baseline must predate the named pip exception")
        with tempfile.TemporaryDirectory(prefix="linux-pip-copied-tree-") as temporary:
            root = Path(temporary) / "runtime"
            shutil.copytree(original, root, symlinks=True)
            before = inventory(root)
            self.assertEqual(before, source, "Copy did not preserve original tree")
            metadata_path = root / "python/runtime-metadata.json"
            metadata_before = json.loads(metadata_path.read_text())
            record = runtime._stage_pip(root, self.cache, self.spec)
            runtime._clean_runtime(root)
            # Same derived metadata fields used by the production stage; no
            # unrelated record/key can be excused by the allowlist.
            metadata_after = {**metadata_before, "pip": record,
                              "python_license_files": runtime._license_files(root)}
            metadata_path.write_text(json.dumps(metadata_after, indent=2) + "\n")
            stripped = {k: v for k, v in metadata_after.items() if k not in {"pip", "python_license_files"}}
            self.assertEqual(stripped, {k: v for k, v in metadata_before.items()
                                       if k not in {"pip", "python_license_files"}})
            after = inventory(root)
            changed = assert_only_named_change(self, before, after, self.pin["version"])
            self.assertNotIn("python/dependency-licenses.json", changed)
            old_licenses = metadata_before["python_license_files"]
            self.assertEqual([row for row in metadata_after["python_license_files"]
                              if not row["path"].startswith(runtime.SITE.as_posix() + "/pip")],
                             old_licenses)
            runtime._verify_staged_pip(root, {"pip": record}, self.spec)
            output = subprocess.check_output([str(root / "python/bin/python3.12"), "-I", "-B", "-c",
                    "import pip,importlib.metadata as m;print(pip.__version__);print(m.version('pip'))"],
                    cwd=temporary, env={"PATH": "/usr/bin:/bin", "HOME": temporary,
                                        "PYTHONPATH": "/nonexistent/host-site"}, text=True)
            self.assertEqual(output.splitlines(), [self.pin["version"], self.pin["version"]])
            self.assertEqual(source, inventory(original), "Original baseline was modified")
            print(f"actual copied Linux tree: {len(before)} original objects; "
                  f"{len(changed)} pip/derived-record-only changes")


if __name__ == "__main__":
    unittest.main()
