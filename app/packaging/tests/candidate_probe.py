"""Mounted individually inside a namespace. Imports no checkout code."""
import asyncio
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import secrets
import shutil
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
    pdf = first_use_pdf(runtime)
    assets = files('src.computer.runtime').joinpath('assets')
    assert Path(str(assets)).is_relative_to(runtime)
    assert assets.joinpath('session.conf').read_text()
    native = {}
    for name, expected in [('odin-computer-wayland-input', 64), ('odin-hyprland-input', 64),
                           ('odin-hyprland-capture', 2)]:
        result = subprocess.run([str(runtime / 'helpers/bin' / name)], capture_output=True, timeout=10)
        assert result.returncode == expected, name
        native[name] = expected
    return {'browser': browser, 'semantic_model': model, 'pdf': pdf,
            'helpers': {'packaged_assets': True, 'native_usage_exits': native, 'input_attempted': False}}


def first_use_pdf(runtime):
    assert importlib.util.find_spec('fitz') is None, 'PDF payload is bundled'
    assert importlib.util.find_spec('pymupdf') is None, 'PyMuPDF payload is bundled'
    from src.runtime import pdf_resources
    from src.tools.handlers.files_docs import FilesDocsTools
    lock = json.loads((runtime / 'pdf.lock.json').read_text())
    assert hashlib.sha256(Path('/pdf-fixture.whl').read_bytes()).hexdigest() == lock['sha256']
    downloads = []
    def local_download(url, destination):
        assert url == lock['url'], 'download did not retain pinned provenance'
        downloads.append(url)
        shutil.copyfile('/pdf-fixture.whl', destination)
    pdf_resources._download_wheel = local_download
    # Build a valid fixture without importing the not-yet-installed PDF engine.
    content = b'BT /F1 12 Tf 72 720 Td (D14 candidate PDF offline) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'\nendstream']
    payload, offsets = b'%PDF-1.4\n', [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(payload))
        payload += str(number).encode() + b' 0 obj\n' + value + b'\nendobj\n'
    xref = len(payload)
    payload += b'xref\n0 6\n0000000000 65535 f \n'
    payload += b''.join(('%010d 00000 n \n' % offset).encode() for offset in offsets[1:])
    payload += b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n' + str(xref).encode() + b'\n%%EOF\n'
    class Stub:
        def _acquire_host(self, name):
            return type('Lease', (), {'target': type('Target', (), {'address': 'local', 'ssh_user': 'none',
                        'key_path': None, 'known_hosts_path': None, 'port': 22, 'host_key_alias': None})(),
                        'release': lambda self: None,
                        'run': lambda self, operation: asyncio.sleep(0, result=(payload, ''))})()
    result = asyncio.run(FilesDocsTools._handle_analyze_pdf(Stub(), {'host': 'offline-proof', 'path': '/fixture.pdf'}))
    assert result.strip() == '## Page 1\nD14 candidate PDF offline', repr(result)
    fitz = pdf_resources._ensure_pdf()
    assert downloads == [lock['url']], 'first use must download exactly once'
    assert Path(fitz.__file__).resolve().is_relative_to(Path('/work/home')), 'PDF was not installed in private user state'
    assert not Path(fitz.__file__).resolve().is_relative_to(runtime), 'immutable runtime was modified'
    assert fitz.VersionBind == lock['version']
    return {'text': 'pass', 'version': fitz.VersionBind, 'bundled': False,
            'first_use_downloads': len(downloads), 'wheel_sha256': lock['sha256'],
            'module': fitz.__file__, 'network': 'disabled; separate local pinned fixture'}

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
            # Observe real first-start provisioning, never preseed config/keys
            # or swap secret backends to make the startup gate pass.
            from src.desktop.paths import ProfilePaths
            from src.config.schema import load_config
            paths = ProfilePaths.from_app('qualification', token_file=token_file,
                                          data_dir=Path('/work/profile/data'))
            config = load_config(paths.config_file)
            key = paths.secrets_dir / 'id_ed25519'
            assert config.tools.ssh_key_path == str(key)
            assert key.is_file() and not key.is_symlink()
            assert key.stat().st_uid == os.getuid() and key.stat().st_mode & 0o777 == 0o600
            public = subprocess.run(['ssh-keygen', '-y', '-f', str(key)],
                                    capture_output=True, timeout=10, check=True)
            assert public.stdout.startswith(b'ssh-ed25519 ')
            workspace = paths.data_dir.parent / '.odin-desktop-workspaces' / paths.profile_id
            assert config.tools.local_working_dir == str(workspace) and workspace.is_dir()
            assert workspace.stat().st_uid == os.getuid()
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
                  'system_python': 'masked', 'checkout': 'not mounted',
                  'first_start': {'fresh_config': True, 'ssh_key': 'real ed25519, private profile',
                                  'workspace': 'real profile default'}, 'd14': resources_proof}))
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
        # Actual packaged app guardian and independent core must publish fresh
        # clean evidence, not merely vanish with the private namespace teardown.
        receipts = Path('/work/home/.local/state/odin-desktop/install-ownership/appimage/receipts')
        deadline = time.monotonic() + 10
        while True:
            records = [json.loads(path.read_text()) for path in receipts.glob('*.json')]
            if {row.get('role') for row in records} == {'app', 'core'} and all(
                    row.get('state') == 'clean' for row in records):
                break
            if time.monotonic() > deadline:
                raise RuntimeError('Actual packaged app/core Exit evidence remains unresolved')
            time.sleep(.05)
        print(json.dumps({'full_app': True, 'sandbox': 'intact, no bypass flags',
                          'private_xvfb': True, 'development_override_ignored': True,
                          'app_and_core_lifetime_receipts': 'fresh clean evidence, not PID absence',
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
