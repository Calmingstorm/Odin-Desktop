#!/usr/bin/env python3
"""The pinned signing tools for a signed Windows release build, and nothing else.

Microsoft's SignTool and its Artifact Signing library come from signing-lock.win_amd64.json, each
package hash-checked before a byte is used, into a fresh folder outside the source tree. The
library's settings (metadata.json) name the Artifact Signing endpoint, account and certificate
profile from ODIN_SIGNING_ENDPOINT, ODIN_SIGNING_ACCOUNT and ODIN_SIGNING_PROFILE, and leave only
the Azure CLI's sign-in to it: the release job signs in with GitHub's identity token, never a
stored secret. The paths packaging/sign-windows.cjs reads are printed as KEY=value lines for
GITHUB_ENV. Never bundled into the app: windows-release.yml runs this, and only for its build.
"""
from __future__ import annotations

import json
import os
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'python'))
from runtime import _download  # noqa: E402

LOCK = HERE / 'signing-lock.win_amd64.json'
# DefaultAzureCredential's other sources stay off: no secret in the environment, no managed
# identity or developer sign-in on the builder, only the Azure CLI's (GitHub's identity token).
EXCLUDED_CREDENTIALS = [
    'EnvironmentCredential', 'WorkloadIdentityCredential', 'ManagedIdentityCredential',
    'SharedTokenCacheCredential', 'VisualStudioCredential', 'VisualStudioCodeCredential',
    'AzurePowerShellCredential', 'AzureDeveloperCliCredential', 'InteractiveBrowserCredential',
]
SETTINGS = {
    'endpoint': ('ODIN_SIGNING_ENDPOINT', re.compile(r'https://[a-z0-9]+\.codesigning\.azure\.net/?')),
    'account': ('ODIN_SIGNING_ACCOUNT', re.compile(r'[A-Za-z][A-Za-z0-9-]{1,22}[A-Za-z0-9]')),
    'profile': ('ODIN_SIGNING_PROFILE', re.compile(r'[A-Za-z][A-Za-z0-9-]{3,98}[A-Za-z0-9]')),
}


def settings_from(env) -> dict:
    """The account settings, each present and well formed, or a refusal naming the variable."""
    found = {}
    for key, (name, pattern) in SETTINGS.items():
        value = env.get(name, '')
        if not pattern.fullmatch(value):
            raise ValueError(f'{name} is missing or malformed: {value!r}')
        found[key] = value
    return found


def extract(archive: Path, folder: str, out: Path) -> list[str]:
    """The files under ``folder`` in a NuGet package (a zip), written below ``out``."""
    prefix = folder.rstrip('/') + '/'
    written = []
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            if member.is_dir() or not member.filename.startswith(prefix):
                continue
            relative = PurePosixPath(member.filename[len(prefix):])
            if not relative.parts or relative.is_absolute() or '..' in relative.parts:
                raise ValueError(f'Unsafe package entry: {member.filename}')
            target = out.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(package.read(member))
            written.append(relative.as_posix())
    return written


def provision(out: Path, cache: Path, settings: dict, *, lock: dict | None = None,
              download=_download) -> dict[str, str]:
    """Each pinned package checked and unpacked into a fresh ``out``, then the library's
    settings."""
    lock = lock if lock is not None else json.loads(LOCK.read_text(encoding='utf-8'))
    out.mkdir(parents=True)  # a fresh folder: never tools left from another run
    paths = {}
    for key in ('signtool', 'dlib'):
        spec = lock['packages'][key]
        archive = download(spec, cache)
        if archive.stat().st_size != spec['size']:
            raise ValueError(f"{spec['package']} {spec['version']} is not the pinned size")
        files = extract(archive, spec['folder'], out / key)
        if spec['file'] not in files:
            raise ValueError(f"{spec['package']} {spec['version']} has no "
                             f"{spec['folder']}/{spec['file']}")
        paths[key] = out / key / spec['file']
    metadata = out / 'metadata.json'
    metadata.write_text(json.dumps({
        'Endpoint': settings['endpoint'],
        'CodeSigningAccountName': settings['account'],
        'CertificateProfileName': settings['profile'],
        'ExcludeCredentials': EXCLUDED_CREDENTIALS,
    }, indent=2) + '\n', encoding='utf-8')
    return {'ODIN_SIGNTOOL': str(paths['signtool']), 'ODIN_SIGNING_DLIB': str(paths['dlib']),
            'ODIN_SIGNING_METADATA': str(metadata)}


def main(argv=None, env=os.environ) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print('usage: provision-signing.py OUT', file=sys.stderr)
        return 2
    try:
        cache = Path(env.get('ODIN_PACKAGING_CACHE')
                     or Path.home() / '.cache/odin-desktop-packaging')
        found = provision(Path(argv[0]), cache / 'signing-tools', settings_from(env))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        print(f'Signing tools refused: {error}', file=sys.stderr)
        return 1
    for name, value in found.items():
        print(f'{name}={value}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
