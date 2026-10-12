"""The Windows release candidate's checks around its hosted build (windows-release.yml).

``validate`` runs before anything is built: the tag is a release tag, the product version is
the tag's, and the checkout is exactly that tag's commit with no local changes. ``receipt`` runs
after the installer acceptance passed: it copies the installer and the acceptance report into
the candidate folder and writes ``windows-candidate-receipt.json``, naming the bytes, the source
and the run. A signed build (``--publisher``) records the signer the acceptance checked on the
installer, the installed Odin.exe and its uninstaller; an unsigned one says it's unsigned. Nothing
here uploads or publishes; publication stays the manual verified-candidate operation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TAG = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
THUMBPRINT = re.compile(r"[0-9A-F]{40}")
RECEIPT = "windows-candidate-receipt.json"
REPORT = "windows-installer-acceptance.json"


class CandidateError(ValueError):
    pass


def git(*args: str, root: Path = ROOT) -> str:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          check=False)
    if done.returncode:
        raise CandidateError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def product_version(root: Path = ROOT) -> str:
    return json.loads((root / "app" / "package.json").read_text(encoding="utf-8"))["version"]


def installer_name(version: str) -> str:
    # electron-builder.windows.yml's artifactName for this version.
    return f"odin-desktop-{version}-candidate-x64-setup.exe"


def validate(tag: str, *, root: Path = ROOT, run=git) -> str:
    """The version the tag names, once the checkout is proven to be that tag, unchanged."""
    if not TAG.fullmatch(tag):
        raise CandidateError(f"not a release tag: {tag!r}")
    version = tag[1:]
    current = product_version(root)
    if current != version:
        raise CandidateError(f"the product version is {current}, not the tag's {version}")
    head = run("rev-parse", "HEAD", root=root)
    tagged = run("rev-parse", f"refs/tags/{tag}^{{commit}}", root=root)
    if head != tagged:
        raise CandidateError(f"the checkout is {head}, not {tag}'s commit {tagged}")
    if run("status", "--porcelain", "--untracked-files=no", root=root):
        raise CandidateError("the checkout has local changes")
    return version


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def receipt(tag: str, candidates: Path, report: Path, out: Path, *, publisher: str = "",
            root: Path = ROOT, run=git, env=os.environ) -> dict:
    """Copy the accepted installer and its report into ``out``; write and return the receipt."""
    version = validate(tag, root=root, run=run)
    installer = candidates / installer_name(version)
    if not installer.is_file():
        raise CandidateError(f"no installer for {version} at {installer}")
    accepted = json.loads(report.read_text(encoding="utf-8-sig"))
    checks = accepted.get("checks") or []
    # Only a whole orchestrated run counts: every row's ok a real true, and its own count of
    # failures zero.
    failed = [check for check in checks
              if not (isinstance(check, dict) and check.get("ok") is True)]
    if accepted.get("mode") != "orchestrate" or accepted.get("failed") != 0 or not checks or failed:
        raise CandidateError(
            f"the installer acceptance didn't pass: {len(failed)} of {len(checks)} checks failed "
            f"(mode {accepted.get('mode')!r}, failed {accepted.get('failed')!r})")
    tested = accepted.get("installer_sha256")
    if tested != _sha256(installer):
        raise CandidateError(
            f"the acceptance tested other bytes ({tested!r}) than {installer.name}")
    # The signer comes from the acceptance, which checked it on every signed file; the receipt
    # only records a signature it was told to expect, and never calls a signed build unsigned.
    signature = accepted.get("signature")
    if publisher:
        if not (isinstance(signature, dict) and signature.get("publisher") == publisher
                and THUMBPRINT.fullmatch(str(signature.get("thumbprint", "")))):
            raise CandidateError(
                f"the acceptance didn't check a signature by {publisher}: {signature!r}")
    elif signature is not None:
        raise CandidateError(f"the acceptance checked a signature ({signature!r}), but no "
                             "publisher was named for the receipt")
    out.mkdir(parents=True)  # a fresh folder: a candidate is never assembled over another
    shutil.copy2(installer, out / installer.name)
    shutil.copy2(report, out / REPORT)
    record = {
        "version": version,
        "tag": tag,
        "source_sha": run("rev-parse", "HEAD", root=root),
        "workflow_sha": env.get("RELEASE_WORKFLOW_SHA", ""),
        "run_id": env.get("RELEASE_RUN_ID", ""),
        "run_attempt": env.get("RELEASE_ATTEMPT", ""),
        "signed": bool(publisher),
        "artifacts": [{"name": installer.name, "size": (out / installer.name).stat().st_size,
                       "sha256": _sha256(out / installer.name)}],
        "acceptance": {"report": REPORT, "checks": len(checks), "failed": 0,
                       "sha256": _sha256(out / REPORT)},
    }
    if publisher:
        record["signature"] = {"publisher": publisher, "thumbprint": signature["thumbprint"]}
    (out / RECEIPT).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("validate").add_argument("--tag", required=True)
    receipting = actions.add_parser("receipt")
    receipting.add_argument("--tag", required=True)
    receipting.add_argument("--candidates", type=Path, required=True)
    receipting.add_argument("--report", type=Path, required=True)
    receipting.add_argument("--out", type=Path, required=True)
    receipting.add_argument("--publisher", default="",
                            help="the signer the acceptance checked (a signed build)")
    args = parser.parse_args(argv)
    try:
        if args.action == "validate":
            print(validate(args.tag))
        else:
            print(json.dumps(receipt(args.tag, args.candidates, args.report, args.out,
                                     publisher=args.publisher), sort_keys=True))
    except (CandidateError, OSError, ValueError) as error:
        print(f"Windows candidate refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
