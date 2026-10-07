#!/usr/bin/env python3
"""Guest-only nonsecret environment facts. No workstation capture or input."""
import json
import os
import pwd
import socket
import subprocess
import sys
from pathlib import Path


def command(*args):
    return subprocess.check_output(args, text=True, timeout=30).strip()


def main():
    vm = sys.argv[1]
    if (socket.gethostname() != vm or vm not in ('odq-cinnamon', 'odq-gnome', 'odq-kde')
            or command('systemd-detect-virt') not in ('kvm', 'qemu')
            or os.getuid() != pwd.getpwnam('odq').pw_uid
            or Path('/etc/odin-desktop-qualification').read_text().strip()
            != 'odin-desktop-qualification-v1'):
        raise RuntimeError('Marked odq VM/session user required')
    packages = command('dpkg-query', '-W', '-f=${Package}\t${Version}\n')
    records = dict(line.split('\t', 1) for line in packages.splitlines())
    names = {'odq-cinnamon': ('cinnamon', 'muffin'),
             'odq-gnome': ('gnome-shell', 'mutter-common'),
             'odq-kde': ('plasma-workspace', 'kwin-wayland')}
    desktop, compositor = names[vm]
    manifest = json.loads(Path('/opt/Odin/resources/bundle-manifest.json').read_text())
    python = command('/opt/Odin/resources/runtime/python/bin/python3', '-I', '-B', '--version')
    driver = []
    for path in Path('/sys/class/drm').glob('card*/device/driver'):
        driver.append(path.resolve().name)
    info = {
        'distro': Path('/etc/os-release').read_text(), 'kernel': command('uname', '-r'),
        'desktop': {desktop: records.get(desktop, 'not installed')},
        'compositor': {compositor: records.get(compositor, 'not installed')},
        'session': os.environ.get('XDG_SESSION_TYPE', ''),
        'portal': ({name: version for name, version in records.items()
                    if name.startswith('xdg-desktop-portal')}
                   or {'implementation': 'absent (dpkg inventory)', 'qualified': False}),
        'gpu': command('lspci', '-nn'), 'driver': driver or ['No DRM device driver reported'],
        'electron': 'pending measured Electron probe',
        'chromium': 'pending measured Chromium probe',
        'python': python,
        'helpers': [{'path': item['path'], 'sha256': item['sha256']}
                    for item in manifest['files'] if 'helpers/bin/' in item['path']],
        'session_environment': {name: os.environ.get(name, '') for name in (
            'XDG_CURRENT_DESKTOP', 'XDG_SESSION_TYPE', 'WAYLAND_DISPLAY', 'DISPLAY')},
        'graphics_packages': {name: version for name, version in records.items()
                              if any(key in name for key in
                                     ('mesa', 'virgl', 'libdrm', 'xserver-xorg'))},
        'package_source_sha': manifest['source']['commit'],
        'gnome_extensions': command('gsettings', 'get', 'org.gnome.shell', 'enabled-extensions')
        if vm == 'odq-gnome' else 'not GNOME',
    }
    print(json.dumps(info, indent=2))


if __name__ == '__main__':
    main()
