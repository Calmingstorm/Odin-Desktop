#!/usr/bin/env python3
"""Generate self-contained dpkg hooks before builder runs."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def generate(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    source = (HERE / 'deb_transaction.py').read_text()
    version = json.loads((HERE.parent / 'package.json').read_text())['version']
    source = source.replace('BUILD_VERSION = None', f'BUILD_VERSION = {version!r}')
    for hook in ('preinst', 'postinst', 'prerm', 'postrm'):
        text = ('#!/bin/sh\nset -eu\nexec /usr/bin/python3 -I -B - "' + hook
                + '" "$@" <<\'ODIN_PACKAGE_CONTROL\'\n' + source + '\nODIN_PACKAGE_CONTROL\n')
        path = output / hook
        path.write_text(text)
        path.chmod(0o755)


if __name__ == '__main__':
    generate(HERE.parents[1] / '.packaging-stage' / 'deb-control')
