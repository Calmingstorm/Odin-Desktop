#!/usr/bin/env python3
"""Guest root orchestrator, all candidate execution under isolated guest odq."""
import importlib.util
import json
from pathlib import Path
import pwd
import subprocess
import sys

assert subprocess.check_output(['systemd-detect-virt'], text=True).strip() in ('kvm', 'qemu')
spec = importlib.util.spec_from_file_location('session', '/var/tmp/lane7-session.py')
session = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session)
info = session.session_info()
assert info['Type'] == 'wayland'
environment = session.session_environment(pwd.getpwnam('odq').pw_uid, 'wayland')
case = sys.argv[1]
base = Path('/home/odq/lane7-proof')
base.mkdir(mode=0o700, exist_ok=True)
subprocess.run(['chown', 'odq:odq', str(base)], check=True)
environment.update({'XDG_CONFIG_HOME': str(base / 'config'), 'XDG_DATA_HOME': str(base / 'data'),
                    'XDG_CACHE_HOME': str(base / 'cache')})
out = base / case
if case == 'deb':
    environment['ODIN_SMOKE_OUT'] = str(out / 'electron.png')
    arguments = ['gui', str(out), '/opt/Odin/odin-desktop', '--smoke-test']
elif case == 'appimage':
    arguments = ['gui', str(out), '/home/odq/lane7.AppImage', '--smoke-test']
elif case == 'browser':
    arguments = ['browser', str(out)]
else:
    raise ValueError(case)
print(json.dumps({'case': case, 'session': info, 'uid': pwd.getpwnam('odq').pw_uid,
                  'environment': environment}), flush=True)
result = subprocess.run(['runuser', '-u', 'odq', '--', 'env', '-i',
                         *(f'{key}={value}' for key, value in environment.items()),
                         '/opt/Odin/resources/runtime/python/bin/python3', '-I', '-B',
                         '/var/tmp/lane7-probe.py', *arguments])
raise SystemExit(result.returncode)
