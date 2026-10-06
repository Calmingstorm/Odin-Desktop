#!/usr/bin/env python3
"""Build the reviewed, reusable P3.3 native-guest source bundle.

The bundle is intentionally source-only. The qualified guest checkout must also
provide app/out, app/node_modules (Electron and Playwright), and an explicit
ODIN_DESKTOP_ENGINE_PYTHON runtime; these are provisioned separately and must
match the checkout. Never substitute an old hand-maintained archive.
"""

from __future__ import annotations

import argparse
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GUEST_SOURCES = (
    "scripts/qualification/lab/guest/common.sh",
    "scripts/qualification/lab/guest/cinnamon.sh",
    "scripts/qualification/lab/guest/gnome.sh",
    "scripts/qualification/lab/guest/hyprland.sh",
    "scripts/qualification/lab/guest/kde.sh",
    "scripts/qualification/lab/guest/native-p33-probe.py",
    "scripts/qualification/lab/guest/native-session.py",
    "scripts/qualification/lab/guest/smoke.py",
    "app/scripts/native-p33-guest.mjs",
    "app/scripts/native-p33-display.mjs",
    "tests/desktop_fixtures/notification_core.py",
    "tests/desktop_fixtures/private_notification_server.py",
    "app/fixture-core/fixture_core.py",
)


def archive_sources(root: Path, output: Path) -> tuple[str, ...]:
    """Create a source tar of every reviewed source helper/dependency."""
    root = root.resolve(strict=True)
    if output.exists() or output.is_symlink():
        raise ValueError("Refusing to replace an existing archive")
    members: list[tuple[str, Path]] = []
    for relative in GUEST_SOURCES:
        path = root / relative
        current = root
        for component in Path(relative).parts:
            current = current / component
            if current.is_symlink():
                raise ValueError(f"Unsafe or missing guest archive source: {relative}")
        if not path.is_file() or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError(f"Unsafe or missing guest archive source: {relative}")
        members.append((relative, path))

    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(output, "w:gz", format=tarfile.PAX_FORMAT) as bundle:
            for name, path in members:
                info = bundle.gettarinfo(str(path), arcname=name)
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                info.mtime = 0
                with path.open("rb") as source:
                    bundle.addfile(info, source)
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return tuple(name for name, _ in members)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    names = archive_sources(args.root, args.output)
    print(f"Created {args.output} with {len(names)} reviewed guest source files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
