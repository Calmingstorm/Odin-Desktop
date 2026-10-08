#!/usr/bin/env python3
"""One-shot guest probes. No sandbox switch, replacement browser or retry."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import time


def processes(match):
    rows = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmd = (entry / 'cmdline').read_bytes().replace(b'\0', b' ').decode()
            if match not in cmd or entry.stat().st_uid != os.getuid():
                continue
            if ' --no-sandbox ' in cmd or ' --disable-setuid-sandbox ' in cmd:
                raise AssertionError('Sandbox-disabling argument: ' + cmd)
            if '--type=renderer' not in cmd:
                continue
            status = (entry / 'status').read_text()
            assert 'Seccomp:\t2' in status and 'NoNewPrivs:\t1' in status, status
            rows.append({'pid': int(entry.name), 'cmdline': cmd, 'status': status,
                         'apparmor': (entry / 'attr/current').read_text(),
                         'user_namespace': os.readlink(entry / 'ns/user')})
        except FileNotFoundError:
            continue
    return rows


async def browser(output):
    runtime = Path('/opt/odin-desktop/resources/runtime')
    os.environ['ODIN_DESKTOP_BUNDLE_ROOT'] = str(runtime)
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(runtime / 'browser')
    from src.tools.browser import BrowserManager
    manager = BrowserManager()
    await manager._ensure_connected()
    try:
        context, page = await manager._create_page()
        await page.goto('data:text/html,<title>Ubuntu restricted userns</title><h1>Real installed browser</h1>')
        assert await page.title() == 'Ubuntu restricted userns'
        png = await page.screenshot()
        (output / 'browser.png').write_bytes(png)
        rows = processes('chrome-headless-shell')
        assert rows, 'No sandboxed bundled browser renderer'
        return {'passed': True, 'title': await page.title(), 'version': manager._browser.version,
                'png_sha256': hashlib.sha256(png).hexdigest(), 'renderers': rows}
    finally:
        await manager._browser.close()
        await manager._playwright.stop()


def gui(output, command):
    with (output / 'launch.log').open('w') as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        rows, mount_rows, dialogs = [], [], []
        deadline = time.monotonic() + 75
        while child.poll() is None and time.monotonic() < deadline:
            rows.extend(processes('odin-desktop.bin'))
            mount_rows.extend(line for line in Path('/proc/self/mountinfo').read_text().splitlines()
                              if '.mount_' in line and 'fuse' in line)
            for entry in Path('/proc').iterdir():
                try:
                    if entry.name.isdigit() and entry.stat().st_uid == os.getuid():
                        cmd = (entry / 'cmdline').read_bytes().replace(b'\0', b' ').decode()
                        if cmd.startswith('/usr/bin/zenity '):
                            dialogs.append(cmd)
                except (FileNotFoundError, PermissionError):
                    pass
            time.sleep(.15)
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
            raise AssertionError('One-shot GUI deadline exceeded; no retry')
    text = (output / 'launch.log').read_text()
    appimage = command[0].endswith('.AppImage')
    # Preserve sandbox witnesses even when the subsequent GUI checkpoint fails.
    # Earlier lane7 run lacked this file; do not reconstruct missing evidence.
    observations = {'command': command, 'exit': child.returncode,
                    'renderers': rows, 'fuse_mounts': sorted(set(mount_rows)),
                    'dialog_commands': sorted(set(dialogs))}
    (output / 'observations.json').write_text(json.dumps(observations, indent=2) + '\n')
    if appimage:
        assert child.returncode > 0 and child.returncode < 128, text
        assert '.deb' in text and 'sandbox' in text.lower(), text
        assert not rows, 'AppImage launched Electron instead of refusing safely'
        assert mount_rows, 'No actual FUSE AppImage mount observed'
        assert dialogs, 'No graphical plain-error dialog observed'
    else:
        assert child.returncode == 0 and 'smoke: ok link=ready' in text, text
        assert rows, 'No Electron renderer sandbox evidence'
        assert (output / 'electron.png').is_file(), 'No rendered app screenshot'
    return {'passed': True, **observations, 'case': 'appimage' if appimage else 'deb'}


if __name__ == '__main__':
    assert os.getuid() == pwd.getpwnam('odq').pw_uid != 0
    assert Path('/proc/sys/kernel/apparmor_restrict_unprivileged_userns').read_text().strip() == '1'
    assert Path('/sys/module/apparmor/parameters/enabled').read_text().strip() == 'Y'
    output = Path(sys.argv[2])
    output.mkdir(exist_ok=False)
    try:
        result = asyncio.run(browser(output)) if sys.argv[1] == 'browser' else gui(output, sys.argv[3:])
    except Exception as exc:
        (output / 'proof.json').write_text(json.dumps({'passed': False, 'error': str(exc)}, indent=2))
        raise
    (output / 'proof.json').write_text(json.dumps(result, indent=2) + '\n')
