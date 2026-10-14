"""Phase 5: the Mac app's Resources signed before the seal, the disk image notarized, and
the signed build's workflow. Pure logic over recorded commands, on any system;
macos-release.yml signs for real."""

from __future__ import annotations

import json
import os
import plistlib
import re
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

PACKAGING = Path(__file__).resolve().parents[1]
ROOT = PACKAGING.parents[1]
sys.path.insert(0, str(PACKAGING / "python"))
import macos_notary  # noqa: E402
import macos_sign  # noqa: E402

MACHO = struct.pack("<I", 0xFEEDFACF) + b"\0" * 28
IDENTITY = "Developer ID Application: Fixture Person (TEAM123456)"


class Recorder:
    """Records each command; answers codesign's display and notarytool by program and flags."""

    def __init__(
        self,
        *,
        team="TEAM123456",
        flags="0x10000(runtime)",
        timestamp=True,
        entitlements=None,
        notary="Accepted",
    ):
        self.calls = []
        self.team, self.flags, self.timestamp = team, flags, timestamp
        self.entitlements = entitlements or {}
        self.notary = notary

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[:3] == ["/usr/bin/codesign", "-d", "--verbose=4"]:
            facts = f"TeamIdentifier={self.team}\nflags={self.flags}\n"
            facts += "Timestamp=Oct 13, 2026\n" if self.timestamp else ""
            return SimpleNamespace(returncode=0, stdout="", stderr=facts)
        if argv[:3] == ["/usr/bin/codesign", "-d", "--entitlements"]:
            keys = self.entitlements.get(Path(argv[-1]).name, [])
            body = plistlib.dumps({key: True for key in keys}) if keys else b""
            return SimpleNamespace(returncode=0, stdout=body, stderr=b"")
        if argv[:2] == ["/usr/bin/xcrun", "notarytool"]:
            reply = {"id": "a4c08b5a-3a30-4cfb-b2d8-dd30114e27ac", "status": self.notary}
            return SimpleNamespace(
                returncode=0 if self.notary == "Accepted" else 1,
                stdout=json.dumps(reply),
                stderr="",
            )
        return SimpleNamespace(
            returncode=0, stdout="accepted\n", stderr="source=Notarized Developer ID"
        )


class SigningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.resources = Path(self.temp.name) / "Odin.app/Contents/Resources"
        for relative in [
            *macos_sign.ROLES,
            "runtime/odin-guardian",
            "runtime/python/lib/python3.12/lib-dynload/_ssl.cpython-312-darwin.so",
        ]:
            (self.resources / relative).parent.mkdir(parents=True, exist_ok=True)
            (self.resources / relative).write_bytes(MACHO)
        (self.resources / "runtime/python/lib/python3.12/os.py").write_text("# not Mach-O\n")
        os.symlink("python3.12", self.resources / "runtime/python/bin/python3")

    def tearDown(self):
        self.temp.cleanup()

    def test_every_macho_is_planned_deepest_first_with_its_roles_entitlements(self):
        steps = macos_sign.plan(self.resources)
        names = [path.relative_to(self.resources).as_posix() for path, _ in steps]
        self.assertEqual(len(names), 5)  # not the source file, not the link to the interpreter
        depths = [len(Path(name).parts) for name in names]
        self.assertEqual(depths, sorted(depths, reverse=True))
        given = {name: entitlements for name, (_, entitlements) in zip(names, steps)}
        self.assertEqual(given["runtime/python/bin/python3.12"], macos_sign.PYTHON)
        self.assertEqual(
            given["runtime/python/lib/python3.12/site-packages/playwright/driver/node"],
            macos_sign.JIT,
        )
        self.assertIsNone(given["runtime/odin-guardian"])

    def test_a_role_whose_file_is_missing_refuses(self):
        (
            self.resources / "runtime/python/lib/python3.12/site-packages/playwright/driver/node"
        ).unlink()
        with self.assertRaisesRegex(macos_sign.SigningError, "playwright/driver/node"):
            macos_sign.plan(self.resources)

    def test_each_file_is_signed_hardened_and_timestamped_then_every_one_verified(self):
        run = Recorder()
        keychain = Path("/tmp/signing.keychain-db")
        self.assertEqual(macos_sign.sign(self.resources, IDENTITY, keychain, run=run), 5)
        signs, verifies = run.calls[:5], run.calls[5:]
        for argv in signs:
            self.assertEqual(
                argv[:9],
                [
                    "/usr/bin/codesign",
                    "--force",
                    "--options",
                    "runtime",
                    "--timestamp",
                    "--sign",
                    IDENTITY,
                    "--keychain",
                    str(keychain),
                ],
            )
            entitled = "--entitlements" in argv
            self.assertEqual(
                entitled,
                Path(argv[-1]).name in {"python3.12", "chrome-headless-shell", "node"},
                argv,
            )
        self.assertEqual(
            [argv[:3] for argv in verifies], [["/usr/bin/codesign", "--verify", "--strict"]] * 5
        )

    def test_the_signed_resources_are_checked_for_team_runtime_timestamp_and_entitlements(self):
        roles = {
            "python3.12": ["com.apple.security.cs.disable-library-validation"],
            "chrome-headless-shell": ["com.apple.security.cs.allow-jit"],
            "node": ["com.apple.security.cs.allow-jit"],
        }
        self.assertEqual(
            macos_sign.verify_signed(
                self.resources, "TEAM123456", run=Recorder(entitlements=roles)
            ),
            5,
        )
        gaps = {
            "another team": Recorder(team="OTHER00000", entitlements=roles),
            "no hardened runtime": Recorder(flags="0x0(none)", entitlements=roles),
            "no timestamp": Recorder(timestamp=False, entitlements=roles),
            "get-task-allow": Recorder(
                entitlements={**roles, "odin-guardian": ["com.apple.security.get-task-allow"]}
            ),
            "a lost entitlement": Recorder(entitlements={**roles, "node": []}),
        }
        for gap, run in gaps.items():
            with self.subTest(gap), self.assertRaises(macos_sign.SigningError):
                macos_sign.verify_signed(self.resources, "TEAM123456", run=run)


class NotaryTests(unittest.TestCase):
    def test_a_verdict_is_what_apple_said(self):
        accepted = macos_notary.verdict(
            json.dumps({"id": "a4c08b5a-3a30-4cfb-b2d8-dd30114e27ac", "status": "Accepted"}), "", 0
        )
        self.assertEqual((accepted["status"], accepted["detail"]), ("Accepted", ""))
        lost = macos_notary.verdict(
            "not json", "Submission ID: a4c08b5a-3a30-4cfb-b2d8-dd30114e27ac", 1
        )
        self.assertEqual(
            (lost["status"], lost["id"]), (None, "a4c08b5a-3a30-4cfb-b2d8-dd30114e27ac")
        )
        self.assertIn("Submission ID", lost["detail"])

    def test_the_image_is_signed_notarized_stapled_and_assessed_in_order(self):
        run = Recorder()
        dmg = Path("/tmp/odin.dmg")
        evidence = macos_notary.seal(dmg, IDENTITY, Path("/tmp/key.p8"), "KEY", "ISSUER", run=run)
        self.assertEqual(
            [argv[:3] for argv in run.calls],
            [
                ["/usr/bin/codesign", "--force", "--timestamp"],
                ["/usr/bin/xcrun", "notarytool", "submit"],
                ["/usr/bin/xcrun", "stapler", "staple"],
                ["/usr/bin/xcrun", "stapler", "validate"],
                ["/usr/sbin/spctl", "--assess", "--type"],
            ],
        )
        self.assertEqual(evidence["notarization"]["status"], "Accepted")
        self.assertIn("Notarized Developer ID", evidence["assessment"])

    def test_an_image_apple_didnt_accept_is_never_stapled(self):
        for status in ("Invalid", "In Progress"):
            run = Recorder(notary=status)
            with self.subTest(status), self.assertRaisesRegex(macos_notary.NotaryError, status):
                macos_notary.seal(
                    Path("/tmp/odin.dmg"), IDENTITY, Path("/tmp/key.p8"), "KEY", "ISSUER", run=run
                )
            self.assertFalse(any(argv[:2] == ["/usr/bin/xcrun", "stapler"] for argv in run.calls))


class SignedBuildTests(unittest.TestCase):
    def test_osx_sign_leaves_every_sealed_resource_alone_and_signs_the_rest(self):
        config = yaml.safe_load(
            (PACKAGING.parent / "electron-builder.macos.signed.yml").read_text()
        )
        self.assertEqual(config["extends"], "electron-builder.macos.yml")
        ignore = [re.compile(pattern) for pattern in config["mac"]["signIgnore"]]
        app = "/build/mac-arm64/Odin.app/Contents"
        for path in (
            "Resources/runtime/python/bin/python3.12",
            "Resources/ownership.py",
            "Resources/runtime/browser/chromium/chrome-headless-shell-mac-arm64/libEGL.dylib",
        ):
            self.assertTrue(any(pattern.search(f"{app}/{path}") for pattern in ignore), path)
        for path in (
            "MacOS/Odin",
            "Frameworks/Electron Framework.framework/Electron Framework",
            "Frameworks/Odin Helper (Renderer).app/Contents/MacOS/Odin Helper (Renderer)",
        ):
            self.assertFalse(any(pattern.search(f"{app}/{path}") for pattern in ignore), path)
        self.assertIs(config["mac"]["notarize"], True)
        for key in ("entitlements", "entitlementsInherit"):
            self.assertEqual(config["mac"][key], "packaging/macos/entitlements.jit.plist")

    def test_the_entitlements_are_the_two_exceptions_and_nothing_else(self):
        jit = plistlib.loads((PACKAGING / "macos/entitlements.jit.plist").read_bytes())
        python = plistlib.loads((PACKAGING / "macos/entitlements.python.plist").read_bytes())
        self.assertEqual(jit, {"com.apple.security.cs.allow-jit": True})
        self.assertEqual(python, {"com.apple.security.cs.disable-library-validation": True})

    def test_the_signed_workflow_runs_only_by_hand_in_its_environment_and_cleans_up(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/macos-release.yml").read_text())
        # Never pull requests or pushes: by hand, or called from a scratch branch.
        self.assertEqual(set(workflow[True]), {"workflow_dispatch", "workflow_call"})
        (job,) = workflow["jobs"].values()
        self.assertEqual(job["environment"], "macos-signing")
        self.assertIn("github.actor == 'Calmingstorm'", job["if"])
        steps = job["steps"]
        runs = [step.get("run", "") for step in steps]
        self.assertTrue(any("build-macos.mjs --signed" in run for run in runs))
        self.assertTrue(any("verify-macos-signatures.py" in run for run in runs))
        self.assertTrue(any("tests/macos/test_packaged_app.py" in run for run in runs))
        self.assertFalse(any("${{" in run for run in runs))
        last = steps[-1]
        self.assertEqual(last["if"], "always()")
        self.assertIn("security delete-keychain", last["run"])
        secrets = {step["name"] for step in steps if "secrets." in json.dumps(step)}
        self.assertEqual(
            secrets,
            {
                "A disposable signing keychain, and the notary key",
                "Build, sign and notarize the app and the disk image",
            },
        )


if __name__ == "__main__":
    unittest.main()
