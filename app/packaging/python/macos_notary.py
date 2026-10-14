"""The signed Mac build's disk image: signed, notarized, stapled, assessed (phase 5).

electron-builder notarizes and staples the app inside; the .dmg around it is signed here, submitted
with notarytool under a bounded wait, stapled, and assessed. A verdict is what Apple says: an exit
status or a submission ID alone is never one (phase 1's rule).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ACCEPTED = "Accepted"
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")


class NotaryError(RuntimeError):
    pass


def verdict(text: str, errors: str, code: int) -> dict:
    """Apple's answer in notarytool's JSON output: its status and submission ID, if given."""
    try:
        reply = json.loads(text) if text.strip() else None
    except json.JSONDecodeError:
        reply = None
    reply = reply if isinstance(reply, dict) else {}
    status = reply.get("status") if isinstance(reply.get("status"), str) else None
    submission = reply.get("id") if isinstance(reply.get("id"), str) else None
    if submission is None:
        found = _UUID.search(f"{text}\n{errors}")
        submission = found.group(0) if found else None
    return {"status": status, "id": submission, "exit": code,
            "detail": "" if code == 0 and status else (errors or text)[-300:]}


def notarize(path: Path, key: Path, key_id: str, issuer: str, *, wait: str = "60m",
             run=subprocess.run) -> dict:
    """Submit and wait; returns Apple's verdict, raising unless it is Accepted."""
    result = run(["/usr/bin/xcrun", "notarytool", "submit", str(path), "--key", str(key),
                  "--key-id", key_id, "--issuer", issuer, "--wait", "--timeout", wait,
                  "--output-format", "json"], capture_output=True, text=True)
    answer = verdict(result.stdout, result.stderr, result.returncode)
    if answer["status"] != ACCEPTED:
        raise NotaryError(f"notarization of {path.name}: {answer}")
    return answer


def seal(dmg: Path, identity: str, key: Path, key_id: str, issuer: str, *,
         keychain: Path | None = None, run=subprocess.run) -> dict:
    """Sign, notarize, staple and assess the disk image; returns the evidence."""
    run(["/usr/bin/codesign", "--force", "--timestamp", "--sign", identity,
         *(["--keychain", str(keychain)] if keychain else []), str(dmg)], check=True)
    answer = notarize(dmg, key, key_id, issuer, run=run)
    run(["/usr/bin/xcrun", "stapler", "staple", str(dmg)], check=True)
    run(["/usr/bin/xcrun", "stapler", "validate", str(dmg)], check=True)
    assessed = run(["/usr/sbin/spctl", "--assess", "--type", "open", "--context",
                    "context:primary-signature", "-vv", str(dmg)],
                   capture_output=True, text=True, check=True)
    return {"notarization": answer, "assessment": (assessed.stderr or assessed.stdout).strip()}


def seal_app(app: Path, key: Path, key_id: str, issuer: str, *, run=subprocess.run) -> dict:
    """Have Apple notarize the signed app, then staple its ticket into the app; returns the
    evidence. The zip ditto makes keeps the signature intact and goes once submitted."""
    folder = Path(tempfile.mkdtemp(prefix="odin-notary-"))
    try:
        archive = folder / f"{app.stem}.zip"
        run(["/usr/bin/ditto", "-c", "-k", "--keepParent", str(app), str(archive)], check=True)
        answer = notarize(archive, key, key_id, issuer, run=run)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    run(["/usr/bin/xcrun", "stapler", "staple", str(app)], check=True)
    run(["/usr/bin/xcrun", "stapler", "validate", str(app)], check=True)
    return {"notarization": answer}
