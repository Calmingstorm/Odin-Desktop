"""Phase 5: the Mac app's Resources signed before the seal, the disk image notarized, and
the signed build's workflow. Pure logic over recorded commands, on any system;
macos-release.yml signs for real."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import plistlib
import re
import struct
import subprocess
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


def _script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


resolver = _script("resolve_signing_source", PACKAGING / "resolve-signing-source.py")
candidate = _script("check_signed_candidate", PACKAGING / "check-signed-candidate.py")

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
        notary_exit=None,
        notary_id=True,
    ):
        self.calls = []
        self.team, self.flags, self.timestamp = team, flags, timestamp
        self.entitlements = entitlements or {}
        self.notary, self.notary_exit, self.notary_id = notary, notary_exit, notary_id

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[:3] == ["/usr/bin/codesign", "-d", "--verbose=4"]:
            facts = f"TeamIdentifier={self.team}\nflags={self.flags}\n"
            facts += "Timestamp=Oct 13, 2026\n" if self.timestamp else ""
            return SimpleNamespace(returncode=0, stdout="", stderr=facts)
        if argv[:3] == ["/usr/bin/codesign", "-d", "--entitlements"]:
            granted = self.entitlements.get(Path(argv[-1]).name, {})
            if isinstance(granted, list):
                granted = {key: True for key in granted}
            body = plistlib.dumps(granted) if granted else b""
            return SimpleNamespace(returncode=0, stdout=body, stderr=b"")
        if argv[:2] == ["/usr/bin/xcrun", "notarytool"]:
            reply = {"status": self.notary}
            if self.notary_id:
                reply["id"] = "a4c08b5a-3a30-4cfb-b2d8-dd30114e27ac"
            code = self.notary_exit
            if code is None:
                code = 0 if self.notary == "Accepted" else 1
            return SimpleNamespace(returncode=code, stdout=json.dumps(reply), stderr="")
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
            "an exception set to false": Recorder(entitlements={**roles, "python3.12": {
                "com.apple.security.cs.disable-library-validation": False}}),
            "an exception of the wrong type": Recorder(entitlements={**roles, "node": {
                "com.apple.security.cs.allow-jit": 1}}),
            "an extra exception": Recorder(entitlements={**roles, "chrome-headless-shell": {
                "com.apple.security.cs.allow-jit": True,
                "com.apple.security.cs.allow-unsigned-executable-memory": True}}),
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


class StrictVerdictTests(unittest.TestCase):
    def test_accepted_with_a_failed_command_or_no_submission_fails_closed(self):
        for run in (Recorder(notary_exit=1), Recorder(notary_id=False)):
            with self.subTest(exit=run.notary_exit, id=run.notary_id):
                with self.assertRaises(macos_notary.NotaryError):
                    macos_notary.notarize(
                        Path("/tmp/odin.zip"), Path("/tmp/key.p8"), "KEY", "ISSUER", run=run
                    )


class CandidateTests(unittest.TestCase):
    """The retained job's check of the kept artifact."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.kept = Path(self.temp.name)
        image = b"signed disk image"
        (self.kept / "odin.dmg").write_bytes(image)
        digest = hashlib.sha256(image).hexdigest()
        app = {"status": "Accepted", "exit": 0, "id": "a0a2d2e1-6ece-432f-96ef-12b63fe429c9"}
        dmg = {"status": "Accepted", "exit": 0, "id": "f1838453-ab46-44af-aee0-8d5e04484d33"}
        self.receipt = {
            "disk_image": "odin.dmg",
            "sha256": digest,
            "revision": "a" * 40,
            "app_notarization": {"notarization": app},
            "disk_image_notarization": {"notarization": dmg},
        }
        # Each check as a passed acceptance records it (tests/macos/test_packaged_app.py).
        evidence = {
            "engine under the guardian": {"guardian": [41], "engine": [40, 41, 42]},
            "a command, with the Mac's PATH": ["/opt/homebrew/bin", "/opt/homebrew/sbin",
                                               "/usr/bin", "/bin"],
            "a background job stopped from Work": {"resource_release": "best_effort",
                                                   "scope": "session_best_effort",
                                                   "state": "settled"},
            "the bundled browser read a page": {"browser": [43, 44]},
            "the app exited": 0,
            "what the session changed in the app": {"changed": {}, "changed_count": 0,
                                                    "added": [], "removed": []},
            "the start check passed, and nothing wrote into the app": "c" * 64,
        }
        self.report = {
            "disk_image_sha256": digest,
            "revision": "a" * 40,
            "checks": {name: evidence.get(name, True) for name in candidate.CHECKS},
        }
        self.write()

    def tearDown(self):
        self.temp.cleanup()

    def write(self):
        (self.kept / "receipt.json").write_text(json.dumps(self.receipt))
        (self.kept / "acceptance.json").write_text(json.dumps(self.report))

    def test_a_whole_candidate_passes(self):
        self.assertIn("odin.dmg", candidate.check(self.kept, "a" * 40))

    def test_the_checks_are_the_acceptances_own(self):
        acceptance = (ROOT / "tests/macos/test_packaged_app.py").read_text()
        recorded = set(re.findall(r'checks\["([^"]+)"\] = ', acceptance))
        self.assertEqual(recorded, set(candidate.CHECKS))

    def test_every_gap_is_refused(self):
        def notary(record, **change):
            return lambda: self.receipt[record]["notarization"].update(change)

        app_id = "a0a2d2e1-6ece-432f-96ef-12b63fe429c9"
        gaps = {
            "an extra file": lambda: (self.kept / "extra.txt").write_text("x"),
            "another image": lambda: (self.kept / "odin.dmg").write_bytes(b"changed"),
            "another revision": lambda: self.receipt.update(revision="b" * 40),
            "not accepted": notary("app_notarization", status="Invalid"),
            "a failed command": notary("disk_image_notarization", exit=1),
            "no submission": notary("app_notarization", id=None),
            "a malformed submission": notary("app_notarization", id="not-a-uuid"),
            "one submission twice": notary("disk_image_notarization", id=app_id),
            "another image's report": lambda: self.report.update(disk_image_sha256="0" * 64),
            "a short report": lambda: self.report.update(checks={"one": True}),
            "an exit that is a boolean": notary("app_notarization", exit=False),
            "an exit that is a float": notary("disk_image_notarization", exit=0.0),
            "a check missing": lambda: self.report["checks"].pop("a failing command"),
            "a check added": lambda: self.report["checks"].update({"another check": True}),
            "a check recorded as failed": lambda: self.report["checks"].update(
                {"a failing command": False}),
            "the app's exit status": lambda: self.report["checks"].update({"the app exited": 1}),
            "an exit status that is a boolean":
                lambda: self.report["checks"].update({"the app exited": False}),
            "a change in the app": lambda: self.report["checks"].update(
                {"what the session changed in the app": {"added": ["x.pyc"]}}),
            "no evidence": lambda: self.report["checks"].update(
                {"engine under the guardian": {}}),
            # Containers that aren't empty, but don't hold what the acceptance records.
            "no guardian or engine processes": lambda: self.report["checks"].update(
                {"engine under the guardian": {"guardian": [], "engine": []}}),
            "no browser processes": lambda: self.report["checks"].update(
                {"the bundled browser read a page": {"browser": []}}),
            "no PATH": lambda: self.report["checks"].update(
                {"a command, with the Mac's PATH": {"not-path": False}}),
            "a failed stop": lambda: self.report["checks"].update(
                {"a background job stopped from Work": {"resource_release": "failed",
                                                        "state": "failed"}}),
            "a partial change record": lambda: self.report["checks"].update(
                {"what the session changed in the app": {"changed_count": 0}}),
            "a change count that is a boolean": lambda: self.report["checks"].update(
                {"what the session changed in the app": {"changed": {}, "changed_count": False,
                                                        "added": [], "removed": []}}),
            "no manifest digest": lambda: self.report["checks"].update(
                {"the start check passed, and nothing wrote into the app": True}),
        }
        for gap, change in gaps.items():
            with self.subTest(gap):
                self.tearDown()
                self.setUp()
                change()
                self.write()
                with self.assertRaises(candidate.CandidateError):
                    candidate.check(self.kept, "a" * 40)


class AppNotaryTests(unittest.TestCase):
    def test_the_app_is_zipped_notarized_then_stapled_and_its_zip_removed(self):
        run = Recorder()
        app = Path("/build/mac-arm64/Odin.app")
        evidence = macos_notary.seal_app(app, Path("/tmp/key.p8"), "KEY", "ISSUER", run=run)
        self.assertEqual([argv[:3] for argv in run.calls], [
            ["/usr/bin/ditto", "-c", "-k"], ["/usr/bin/xcrun", "notarytool", "submit"],
            ["/usr/bin/xcrun", "stapler", "staple"], ["/usr/bin/xcrun", "stapler", "validate"]])
        archive = Path(run.calls[0][-1])
        self.assertEqual(run.calls[1][3], str(archive))
        self.assertFalse(archive.parent.exists())  # the zip went once submitted
        self.assertEqual(evidence["notarization"]["status"], "Accepted")
        self.assertEqual(evidence["notarization"]["id"], "a4c08b5a-3a30-4cfb-b2d8-dd30114e27ac")

    def test_an_app_apple_didnt_accept_is_never_stapled(self):
        run = Recorder(notary="Invalid")
        with self.assertRaisesRegex(macos_notary.NotaryError, "Invalid"):
            macos_notary.seal_app(Path("/build/Odin.app"), Path("/tmp/key.p8"), "KEY", "ISSUER",
                                  run=run)
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
        # The app's notarization is after-sign-macos.cjs's, which keeps Apple's record.
        self.assertIs(config["mac"]["notarize"], False)
        self.assertEqual(config["afterSign"], "packaging/after-sign-macos.cjs")
        for key in ("entitlements", "entitlementsInherit"):
            self.assertEqual(config["mac"][key], "packaging/macos/entitlements.jit.plist")

    def test_the_entitlements_are_the_two_exceptions_and_nothing_else(self):
        jit = plistlib.loads((PACKAGING / "macos/entitlements.jit.plist").read_bytes())
        python = plistlib.loads((PACKAGING / "macos/entitlements.python.plist").read_bytes())
        self.assertEqual(jit, {"com.apple.security.cs.allow-jit": True})
        self.assertEqual(python, {"com.apple.security.cs.disable-library-validation": True})

    def test_the_signed_workflow_settles_its_source_before_any_secret(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/macos-release.yml").read_text())
        # Never pull requests, pushes or other workflows: by hand only.
        self.assertEqual(set(workflow[True]), {"workflow_dispatch"})
        jobs = workflow["jobs"]
        target, signed, retained = jobs["target"], jobs["signed"], jobs["retained"]
        self.assertIn("github.actor == 'Calmingstorm'", target["if"])
        for job in (target, retained):  # no secrets and no signing environment
            self.assertNotIn("environment", job)
            self.assertNotIn("secrets.", json.dumps(job))
        self.assertIn("resolve-signing-source.py", json.dumps(target["steps"]))
        self.assertEqual(signed["needs"], "target")
        self.assertEqual(signed["environment"], "macos-signing")
        self.assertEqual(signed["steps"][0]["with"]["ref"], "${{ needs.target.outputs.sha }}")
        runs = [step.get("run", "") for job in (target, signed, retained) for step in job["steps"]]
        self.assertFalse(any("${{" in run for run in runs))
        steps = signed["steps"]
        signed_runs = [step.get("run", "") for step in steps]
        for needed in ("build-macos.mjs --signed", "verify-macos-signatures.py",
                       "tests/macos/test_packaged_app.py", "ODIN_PACKAGING_RELEASE=1"):
            self.assertTrue(any(needed in run for run in signed_runs), needed)
        secrets = {step["name"] for step in steps if "secrets." in json.dumps(step)}
        self.assertEqual(secrets, {"A disposable signing keychain, and the notary key",
                                   "Build, sign and notarize the app and the disk image"})
        (kept,) = [step for step in steps if "upload-artifact" in step.get("uses", "")]
        self.assertEqual(kept["with"]["path"], "signed-candidate/")  # a plain folder, not hidden
        last = steps[-1]
        self.assertEqual(last["if"], "always()")
        self.assertIn("security delete-keychain", last["run"])
        self.assertIn("search-list.txt", last["run"])
        self.assertEqual(retained["needs"], ["target", "signed"])
        self.assertIn("download-artifact", json.dumps(retained["steps"]))
        self.assertEqual(retained["steps"][0]["with"]["ref"], "${{ needs.target.outputs.sha }}")
        self.assertIn("check-signed-candidate.py", retained["steps"][-1]["run"])


class SourceTests(unittest.TestCase):
    """The signed build's source: a release tag on master with its version, and nothing else."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.git("init", "-q", "-b", "master")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Fixture")
        self.master = self.commit("1.2.3")
        self.git("tag", "v1.2.3")
        self.git("tag", "v9.9.9")  # a tag whose app version isn't its own
        self.git("checkout", "-q", "-b", "side")
        self.side = self.commit("1.2.4")
        self.git("tag", "v1.2.4")  # not on master's history
        self.git("update-ref", "refs/remotes/origin/master", self.master)
        self.git("update-ref", "refs/remotes/origin/macos/port", self.side)

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        result = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True,
                                check=True)
        return result.stdout.strip()

    def commit(self, version):
        (self.repo / "app").mkdir(exist_ok=True)
        (self.repo / "app/package.json").write_text(json.dumps({"version": version}))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", version)
        return self.git("rev-parse", "HEAD")

    def test_a_release_tag_on_master_with_its_version(self):
        self.assertEqual(resolver.resolve("v1.2.3", cwd=self.repo), (self.master, "release"))

    def test_everything_else_is_refused(self):
        # The port's branch too, by name or by its head: its candidates ended with the port.
        for ref in ("v1.2.4", "v9.9.9", "v0.0.1", self.master, "side", "master", "macos/port",
                    self.side, "macos/probe", "1.2.3", "v1.2.3-rc1"):
            with self.subTest(ref), self.assertRaises(resolver.SourceRefusedError):
                resolver.resolve(ref, cwd=self.repo)

if __name__ == "__main__":
    unittest.main()
