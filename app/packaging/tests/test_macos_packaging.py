"""The macOS packaging pins, sealing rules and Mach-O audit (phase 4), on any system.

The locks are checked against uv.lock and the Linux lane's pins offline; the Mach-O audit reads
small hand-built binaries; the darwin sealing rules run on plain lists and a temporary tree.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import struct
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE / 'python'))
import macos_macho  # noqa: E402, I001 - after the lane folder joins the path
import macos_runtime  # noqa: E402
import pdf  # noqa: E402
import runtime  # noqa: E402

spec = importlib.util.spec_from_file_location('seal_macos', HERE / 'finalize-manifest.py')
seal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seal)

UV_LOCK = tomllib.loads((REPO / 'uv.lock').read_text())


def locked_wheels(name: str) -> dict[str, str]:
    package = next(item for item in UV_LOCK['package'] if item['name'] == name)
    return {wheel['url']: wheel['hash'] for wheel in package.get('wheels', [])}


class MacRuntimeLockTests(unittest.TestCase):
    def setUp(self):
        self.mac = json.loads(macos_runtime.LOCK_PATH.read_text())
        self.linux = json.loads(runtime.LOCK_PATH.read_text())

    def test_it_shares_the_linux_lanes_inputs_and_pins_its_own(self):
        self.assertEqual(macos_runtime.lock(), self.mac)
        self.assertEqual((self.mac['platform'], self.mac['minimum_macos']), ('macos-arm64', '26.0'))
        self.assertEqual(self.mac['python']['version'], self.linux['python']['version'])
        self.assertIn('aarch64-apple-darwin-install_only', self.mac['python']['url'])
        self.assertIn('uv-aarch64-apple-darwin', self.mac['uv']['url'])
        self.assertEqual(self.mac['uv']['version'], self.linux['uv']['version'])
        for pin in (self.mac['python'], self.mac['uv']):
            self.assertTrue(pin['url'].startswith('https://github.com/astral-sh/'))
            self.assertRegex(pin['sha256'], r'^[0-9a-f]{64}$')
            self.assertIsInstance(pin['size'], int)

    def test_a_shared_input_that_drifts_is_refused(self):
        for key in macos_runtime.SHARED:
            drifted = copy.deepcopy(self.mac)
            drifted[key] = 'drifted'
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / 'lock.json'
                path.write_text(json.dumps(drifted))
                with self.subTest(key=key), mock.patch.object(macos_runtime, 'LOCK_PATH', path):
                    with self.assertRaisesRegex(ValueError, key):
                        macos_runtime.lock()

    def test_pip_is_the_linux_wheel_under_the_macs_own_named_exception(self):
        self.assertEqual({k: v for k, v in self.mac['pip'].items() if k != 'named_change'},
                         {k: v for k, v in self.linux['pip'].items() if k != 'named_change'})
        self.assertEqual(runtime._locked_pip(self.mac, named=macos_runtime.NAMED_PIP),
                         self.mac['pip'])
        with self.assertRaises(ValueError):
            runtime._locked_pip(self.mac)  # Linux's named exception is not the Mac's
        with self.assertRaises(ValueError):
            runtime._locked_pip(self.linux, named=macos_runtime.NAMED_PIP)

    def test_the_license_files_are_linuxs_less_what_macos_itself_supplies(self):
        mac, linux = self.mac['python_license_hashes'], self.linux['python_license_hashes']
        self.assertTrue(set(mac) < set(linux))
        self.assertEqual({name: linux[name] for name in mac}, mac)
        for gone in ('LICENSE.libX11.txt', 'LICENSE.libXau.txt', 'LICENSE.libxcb.txt',
                     'LICENSE.libuuid.txt', 'LICENSE.libedit.txt', 'LICENSE.ncurses.txt',
                     'LICENSE.zlib.txt', 'LICENSE.openssl-1.1.txt'):
            self.assertNotIn(gone, mac)
        for kept in ('LICENSE.cpython.txt', 'LICENSE.openssl-3.txt', 'LICENSE.sqlite.txt',
                     'LICENSE.tcl.txt', 'LICENSE.libffi.txt'):
            self.assertIn(kept, mac)

    def test_the_lane_runs_only_on_apple_silicon(self):
        with mock.patch.object(macos_runtime.platform, 'system', return_value='Linux'):
            with self.assertRaisesRegex(ValueError, 'Apple silicon'):
                macos_runtime.stage_macos_runtime(REPO, Path(tempfile.gettempdir()), Path('/x'))


class MacChromiumAndPdfLockTests(unittest.TestCase):
    def test_the_browser_lock_pins_uv_locks_arm64_wheel_and_playwrights_shell(self):
        mac = json.loads((HERE / 'python/chromium.lock.macos_arm64.json').read_text())
        linux = json.loads((HERE / 'python/chromium.lock.json').read_text())
        wheel = mac['playwright']
        self.assertEqual(locked_wheels('playwright').get(wheel['url']), 'sha256:' + wheel['sha256'])
        self.assertTrue(wheel['url'].endswith('-py3-none-macosx_11_0_arm64.whl'))
        self.assertEqual(wheel['version'], linux['playwright']['version'])
        shell = mac['chromium']
        for key in ('name', 'revision', 'version'):
            self.assertEqual(shell[key], linux['chromium'][key])
        root = shell['archive_root']
        self.assertEqual(root, 'chrome-headless-shell-mac-arm64')
        self.assertTrue(shell['executable'].startswith(root + '/'))
        self.assertTrue(shell['license_file'].startswith(root + '/'))
        self.assertIn(f"/{shell['version']}/mac-arm64/{root}.zip", shell['url'])

    def test_the_pdf_lock_pins_uv_locks_arm64_wheel_and_staging_copies_it(self):
        lock = json.loads((HERE / 'python/pdf.lock.macos_arm64.json').read_text())
        linux = json.loads(pdf.LOCK_PATH.read_text())
        self.assertEqual(pdf._locked_wheel(lock)['hash'], 'sha256:' + lock['sha256'])
        self.assertTrue(lock['wheel'].endswith('-macosx_11_0_arm64.whl'))
        self.assertEqual({k: lock[k] for k in ('version', 'license', 'license_sha256')},
                         {k: linux[k] for k in ('version', 'license', 'license_sha256')})
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(pdf.sys, 'platform', 'darwin'):
            result = pdf.stage_pdf(Path(temporary), Path(temporary))
            staged = json.loads((Path(temporary) / 'pdf.lock.json').read_text())
        self.assertEqual(staged, lock)
        self.assertEqual(result['provenance']['input_lock'],
                         'app/packaging/python/pdf.lock.macos_arm64.json')


class MacSealingTests(unittest.TestCase):
    def test_the_mac_refuses_linux_and_windows_payloads(self):
        for name in ('apparmor-profile', 'runtime/helpers/foo', 'odin-desktop.appimage',
                     'runtime/browser/chromium/chrome-headless-shell-linux64/chrome-headless-shell',
                     'runtime/browser/chromium/chrome-headless-shell-win64/chrome.exe',
                     'tools/curl/curl.exe', 'runtime/foo.dll'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Forbidden darwin'):
                seal.assert_platform_resources([{'path': name}], 'darwin')
        seal.assert_platform_resources([
            {'path': 'runtime/python/lib/python3.12/lib-dynload/_dbm.cpython-312-darwin.so'},
            {'path': 'runtime/odin-guardian'}, {'path': 'ownership.py'},
            {'path': 'runtime/browser/chromium/chrome-headless-shell-mac-arm64/libEGL.dylib'}],
            'darwin')

    def test_the_mac_keeps_the_pinned_pip_launcher_data_only(self):
        prefix = 'runtime/python/lib/python3.12/site-packages/pip/_vendor/distlib/'
        sha, size = seal.PIP_LINUX_LAUNCHER_DATA['t64.exe']
        seal.assert_platform_resources([{'path': prefix + 't64.exe', 'sha256': sha, 'size': size}],
                                       'darwin')
        with self.assertRaisesRegex(ValueError, 'Forbidden darwin'):
            seal.assert_platform_resources([{'path': prefix + 't64.exe', 'sha256': '0' * 64,
                                             'size': size}], 'darwin')

    def test_a_mac_tree_is_inventoried_and_verified_like_linux(self):
        with tempfile.TemporaryDirectory() as temporary:
            resources = Path(temporary)
            (resources / 'runtime').mkdir()
            (resources / 'runtime' / 'odin-guardian').write_bytes(b'guardian')
            (resources / 'bundle-manifest.json').write_text(json.dumps(
                {'schema': 1, 'platform': 'darwin', 'files': [],
                 'source': {'mode': 'worktree', 'immutable': False}}))
            result = seal.finalize(resources)
            manifest = json.loads((resources / 'bundle-manifest.json').read_text())
            self.assertEqual([item['path'] for item in manifest['files']],
                             ['runtime/odin-guardian'])
            self.assertEqual(result['files'], 1)
            (resources / 'runtime' / 'odin-guardian').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                seal.verify_resources(resources)


def macho(*commands: bytes, cputype: int = 0x0100000C, filetype: int = 6) -> bytes:
    """A thin 64-bit Mach-O: header, then the given load commands."""
    body = b''.join(commands)
    return struct.pack('<IiiIIIII', 0xFEEDFACF, cputype, 0, filetype, len(commands), len(body),
                       0, 0) + body


def build_version(minos: tuple[int, int], platform: int = 1) -> bytes:
    return struct.pack('<IIIIII', 0x32, 24, platform, (minos[0] << 16) | (minos[1] << 8), 0, 0)


def path_command(command: int, value: str) -> bytes:
    offset = 24 if command != 0x8000001C else 12
    data = value.encode() + b'\0'
    size = (offset + len(data) + 7) // 8 * 8
    head = struct.pack('<III', command, size, offset)
    if command != 0x8000001C:
        head += struct.pack('<III', 2, 0, 0)  # timestamp, current, compatibility versions
    return (head + data).ljust(size, b'\0')


class MachOAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, name: str, data: bytes) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_a_library_found_in_the_bundle_passes(self):
        self.write('lib/libfoo.dylib', macho(build_version((11, 0))))
        self.write('lib/mod.so', macho(build_version((13, 0)),
                                       path_command(0x8000001C, '@loader_path'),
                                       path_command(0xC, '@rpath/libfoo.dylib'),
                                       path_command(0xC, '/usr/lib/libSystem.B.dylib')))
        report = macos_macho.audit(self.root, '26.0')
        self.assertEqual((report['macho_files'], report['problems'], report['warnings']),
                         (2, [], []))
        self.assertEqual(macos_macho.list_macho(self.root)[0].name, 'libfoo.dylib')  # deepest first

    def test_a_newer_floor_another_platform_or_arch_and_missing_loads_are_problems(self):
        self.write('new.dylib', macho(build_version((27, 0))))
        self.write('ios.dylib', macho(build_version((15, 0), platform=2)))
        self.write('intel.dylib', macho(build_version((11, 0)), cputype=0x01000007))
        self.write('none.dylib', macho())
        self.write('loads.dylib', macho(build_version((11, 0)),
                                        path_command(0xC, '@rpath/gone.dylib'),
                                        path_command(0x80000018, '@loader_path/weak.dylib')))
        report = macos_macho.audit(self.root, '26.0')
        problems = '\n'.join(report['problems'])
        self.assertIn('new.dylib: needs macOS 27.0.0', problems)
        self.assertIn('ios.dylib: platform 2 is not macOS', problems)
        self.assertIn("intel.dylib: no arm64 slice (['x86_64'])", problems)
        self.assertIn('none.dylib: no minimum macOS recorded', problems)
        self.assertIn('loads.dylib: unresolved load @rpath/gone.dylib', problems)
        self.assertEqual(report['warnings'],
                         ['loads.dylib: unresolved load @loader_path/weak.dylib'])

    def test_a_load_found_outside_the_bundle_first_is_a_problem(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        library = Path(outside.name) / 'libout.dylib'
        library.write_bytes(macho(build_version((11, 0))))
        self.write('uses.dylib', macho(build_version((11, 0)), path_command(0xC, str(library))))
        problems = macos_macho.audit(self.root, '26.0')['problems']
        self.assertEqual(len(problems), 1)
        self.assertIn('resolves outside the bundle first', problems[0])

    def test_a_universal_binary_is_read_slice_by_slice(self):
        arm = macho(build_version((11, 0)))
        intel = macho(build_version((10, 15)), cputype=0x01000007)
        header = struct.pack('>II', 0xCAFEBABE, 2)
        first = 8 + 2 * 20
        second = first + len(arm)
        header += struct.pack('>iiIII', 0x0100000C, 0, first, len(arm), 0)
        header += struct.pack('>iiIII', 0x01000007, 0, second, len(intel), 0)
        path = self.write('fat.dylib', header + arm + intel)
        self.assertEqual(macos_macho.macho_kind(path), 'fat')
        self.assertEqual([item['arch'] for item in macos_macho.slices(path)], ['arm64', 'x86_64'])
        self.assertEqual(macos_macho.audit(self.root, '26.0')['problems'], [])

    def test_other_files_are_not_mach_o(self):
        self.write('notes.txt', b'plain text, long enough')
        self.write('Class.class', struct.pack('>II', 0xCAFEBABE, 52))  # Java shares the magic
        self.assertEqual(macos_macho.list_macho(self.root), [])


@unittest.skipUnless(sys.platform == 'darwin', 'builds with the Mac compiler')
class MacGuardianLaneTests(unittest.TestCase):
    def test_it_builds_the_guardian_once(self):
        import macos_guardian
        with tempfile.TemporaryDirectory() as temporary:
            result = macos_guardian.stage_guardian(Path(temporary), Path(temporary))
            self.assertEqual(result['executable'], 'odin-guardian')
            self.assertRegex(result['executable_sha256'], r'^[0-9a-f]{64}$')
            report = macos_macho.audit(Path(temporary), '26.0')
            self.assertEqual((report['macho_files'], report['problems']), (1, []))
            with self.assertRaisesRegex(ValueError, 'staged once'):
                macos_guardian.stage_guardian(Path(temporary), Path(temporary))


if __name__ == '__main__':
    unittest.main()
