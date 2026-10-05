"""Mounted individually inside a namespace. Imports no checkout code."""
import asyncio
import json
import math
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import sys
import time
import uuid

def d14(resources):
    runtime = Path(resources) / 'runtime'
    os.environ['ODIN_DESKTOP_BUNDLE_ROOT'] = str(runtime)
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(runtime / 'browser')
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    from src.tools.browser import BrowserManager
    from src.search.embedder import LocalEmbedder
    import fitz
    from importlib.resources import files

    async def features():
        manager = BrowserManager()
        await manager._ensure_connected()
        try:
            context, page = await manager._create_page()
            await page.goto('data:text/html,<title>D14 candidate offline</title><h1>Packaged</h1>')
            assert await page.title() == 'D14 candidate offline'
            png = await page.screenshot()
            assert png[:8] == b'\x89PNG\r\n\x1a\n'
            renderers = []
            for entry in Path('/proc').iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    cmd = (entry / 'cmdline').read_bytes().replace(b'\0', b' ')
                    if b'chrome-headless-shell' not in cmd:
                        continue
                    assert b' --no-sandbox ' not in cmd and b' --disable-setuid-sandbox ' not in cmd
                    if b' --type=renderer ' in cmd:
                        status = (entry / 'status').read_text()
                        assert 'Seccomp:\t2' in status and 'NoNewPrivs:\t1' in status
                        renderers.append(int(entry.name))
                except FileNotFoundError:
                    continue
            assert renderers, 'No sandboxed Chromium renderer observed'
            browser = {'title': await page.title(), 'png_bytes': len(png),
                       'version': manager._browser.version, 'sandboxed_renderers': renderers}
            await context.close()
        finally:
            await manager._browser.close()
            await manager._playwright.stop()
        embedder = LocalEmbedder()
        vector = await embedder.embed('A committed database transaction is durable.')
        assert vector is not None, embedder.unavailable_reason
        assert len(vector) == 384 and all(math.isfinite(x) for x in vector)
        return browser, {'dimensions': len(vector), 'model': embedder.MODEL}

    browser, model = asyncio.run(features())
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), 'D14 candidate PDF offline')
    payload = doc.tobytes()
    doc.close()
    with fitz.open(stream=payload, filetype='pdf') as parsed:
        assert parsed[0].get_text().strip() == 'D14 candidate PDF offline'
    assets = files('src.computer.runtime').joinpath('assets')
    assert Path(str(assets)).is_relative_to(runtime)
    assert assets.joinpath('session.conf').read_text()
    native = {}
    for name, expected in [('odin-computer-wayland-input', 64), ('odin-hyprland-input', 64),
                           ('odin-hyprland-capture', 2)]:
        result = subprocess.run([str(runtime / 'helpers/bin' / name)], capture_output=True, timeout=10)
        assert result.returncode == expected, name
        native[name] = expected
    return {'browser': browser, 'semantic_model': model, 'pdf': {'text': 'pass', 'version': fitz.VersionBind},
            'helpers': {'packaged_assets': True, 'native_usage_exits': native, 'input_attempted': False}}

def isolation():
    assert os.getuid() != 0, 'candidate probe must be nonroot'
    assert not Path('/home/odin/desktop-p41-work').exists(), 'checkout exposed'
    assert not Path('/opt/odin').exists(), 'live install exposed'
    assert not Path('/usr/local/bin/python3').exists(), 'local Python exposed'
    for path in Path('/usr/bin').glob('*python*'):
        assert not os.access(path, os.X_OK), 'system Python exposed: ' + str(path)
    assert len([line for line in Path('/proc/net/dev').read_text().splitlines()[2:] if ':' in line]) == 1
    external = socket.socket()
    external.settimeout(.5)
    try:
        external.connect(('192.0.2.1', 443))
    except OSError:
        pass
    else:
        raise AssertionError('external network reachable')
    finally:
        external.close()
    assert Path(sys.executable).resolve().is_relative_to(Path('/candidate with spaces'))
    assert Path(sys.prefix).is_relative_to(Path('/candidate with spaces'))
    for directory in ['home', 'run', 'profile', 'profile/config', 'profile/data']:
        Path('/work', directory).mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod('/work/run', 0o700)

def core(resources):
    import src
    assert Path(src.__file__).resolve().is_relative_to(Path(resources)), 'engine not from candidate'
    token = secrets.token_hex(32)
    token_file = Path('/work/profile/config/ipc.token')
    token_file.write_text(token)
    token_file.chmod(0o600)
    sock_path = '/work/run/core.sock'
    command = [sys.executable, '-I', '-B', '-m', 'src', '--socket', sock_path,
               '--token-file', str(token_file), '--profile', 'qualification',
               '--data-dir', '/work/profile/data']
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(10)
    with Path('/work/core.stderr').open('wb') as stderr:
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr)
        try:
            deadline = time.monotonic() + 45
            while not Path(sock_path).exists():
                if child.poll() is not None:
                    raise RuntimeError('core exited before socket: ' + Path('/work/core.stderr').read_text())
                if time.monotonic() > deadline:
                    raise TimeoutError('core socket startup deadline')
                time.sleep(.05)
            sock.connect(sock_path)
            def send(value):
                data = json.dumps(value).encode()
                sock.sendall(struct.pack('!I', len(data)) + data)
            def exact(size):
                data = b''
                while len(data) < size:
                    chunk = sock.recv(size - len(data))
                    if not chunk:
                        raise RuntimeError('unexpected IPC EOF')
                    data += chunk
                return data
            def receive():
                size = struct.unpack('!I', exact(4))[0]
                assert 0 < size <= 4 * 1024 * 1024
                return json.loads(exact(size))
            def request(method, params=None):
                identity = str(uuid.uuid4())
                send({'t': 'req', 'id': identity, 'method': method, 'params': params or {}})
                response = receive()
                assert response['t'] == 'res' and response['id'] == identity and response['ok'], response
                return response['result']
            send({'t': 'hello', 'protocol': {'major': 0, 'minor': 2},
                  'client': {'name': 'candidate-qualification', 'version': '1'},
                  'profile_id': 'qualification', 'token': token, 'features': []})
            welcome = receive()
            assert welcome['t'] == 'welcome', welcome
            instance = welcome['core']['instance_id']
            assert str(uuid.UUID(instance)) == instance
            assert {'status.get', 'events.subscribe', 'runtime.shutdown'} <= set(welcome['capabilities'])
            status = request('status.get')
            assert status['phase'] == 'ready' and status['core_instance_id'] == instance
            send({'t': 'ping', 'n': 17})
            assert receive() == {'t': 'pong', 'n': 17}
            subscription = request('events.subscribe', {'after': '0'})
            assert subscription['reset_required'] is False
            ready = receive()
            assert ready['t'] == 'evt' and ready['type'] == 'runtime.status'
            assert ready['payload']['phase'] == 'ready'
            assert request('runtime.shutdown', {'reason': 'candidate-qualification'}) == {'disposition': 'accepted'}
            quiescing = receive()
            assert quiescing['type'] == 'runtime.status' and quiescing['payload']['phase'] == 'quiescing'
            assert int(quiescing['seq']) > int(ready['seq'])
            assert child.wait(timeout=30) == 0, Path('/work/core.stderr').read_text()
            assert not Path(sock_path).exists(), 'socket not removed after shutdown'
            resources_proof = d14(resources)
            print(json.dumps({'real_core': True, 'python': sys.version.split()[0],
                  'executable': sys.executable, 'engine': src.__file__, 'instance': instance,
                  'handshake': 'pass', 'status': 'pass', 'events': 'pass', 'ping': 'pass',
                  'shutdown': 'pass', 'offline': 'network namespace',
                  'system_python': 'masked', 'checkout': 'not mounted', 'd14': resources_proof}))
        finally:
            sock.close()
            if child.poll() is None:
                child.stdin.close()
                try:
                    child.wait(timeout=25)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()

def gui(executable):
    display = subprocess.Popen(['/usr/bin/Xvfb', ':71', '-screen', '0', '1280x900x24', '-nolisten', 'tcp',
                                '-extension', 'GLX'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not Path('/tmp/.X11-unix/X71').exists():
            if display.poll() is not None:
                raise RuntimeError('Xvfb exited: ' + display.stderr.read().decode())
            if time.monotonic() > deadline:
                raise TimeoutError('private Xvfb startup')
            time.sleep(.05)
        env = dict(os.environ, DISPLAY=':71', ODIN_SMOKE_OUT='/work/smoke.png')
        env['ODIN_DESKTOP_CORE_CMD'] = '["/no-such-fixture"]'
        result = subprocess.run([executable, '--smoke-test', '--disable-gpu'], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=80)
        if result.returncode or 'smoke: ok link=ready core=' not in result.stdout:
            raise RuntimeError('sandbox-intact GUI smoke failed: ' + result.stdout[-8000:])
        png = Path('/work/smoke.png').read_bytes()
        assert png[:8] == b'\x89PNG\r\n\x1a\n' and len(png) > 1000
        print(json.dumps({'full_app': True, 'sandbox': 'intact, no bypass flags',
                          'private_xvfb': True, 'development_override_ignored': True,
                          'screenshot_bytes': len(png), 'stdout': result.stdout[-2000:]}))
    finally:
        display.terminate()
        display.wait(timeout=5)

if __name__ == '__main__':
    isolation()
    if sys.argv[1] == '--gui':
        gui(sys.argv[2])
    else:
        core(sys.argv[1])
