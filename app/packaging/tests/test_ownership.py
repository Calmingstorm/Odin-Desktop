import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BOOT_A = 'a1b2c3d4-0000-4000-8000-00000000000a'
BOOT_B = 'a1b2c3d4-0000-4000-8000-00000000000b'
BOOT_C = 'a1b2c3d4-0000-4000-8000-00000000000c'

MODULE = Path(__file__).resolve().parents[1] / 'ownership.py'
spec = importlib.util.spec_from_file_location('ownership_fixture', MODULE)
own = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = own
spec.loader.exec_module(own)
# The resource manifest as finalize-manifest writes it.
spec = importlib.util.spec_from_file_location('manifest_fixture',
                                              MODULE.parent / 'python' / 'manifest.py')
manifest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifest)


def acl_grants(*paths):
    """Off macOS, the lease's ACL reading: one allow entry on exactly these folders or files."""
    granted = {Path(path) for path in paths}

    def entries(fd):
        return int(Path(os.readlink(f'/proc/self/fd/{fd}')) in granted)
    return entries


@contextlib.contextmanager
def mac(*granted):
    """The Mac kind. Off macOS its ACL reading is acl_grants'; on a Mac, the kernel's own."""
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(own, 'DARWIN', True))
        stack.enter_context(mock.patch.object(own, 'WINDOWS', False))
        if sys.platform != 'darwin':
            stack.enter_context(mock.patch.object(own, '_allow_entries', acl_grants(*granted)))
        elif granted:
            raise unittest.SkipTest('a Mac reads real ACLs: the native cases set them')
        yield


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        # These cases model the Linux boot identity file (BOOT_ID), on any system; the Mac kind's
        # own cases turn DARWIN on.
        darwin = mock.patch.object(own, 'DARWIN', False)
        darwin.start()
        self.addCleanup(darwin.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = own.OwnershipPaths(self.root / 'install')
        self.app = self.root / 'app.json'
        self.core = self.root / 'core.json'

    def tearDown(self):
        self.temp.cleanup()

    def clean(self):
        self.app.write_text(json.dumps({'journalVersion': 2, 'warning': None, 'current': {
            'state': 'process-exited', 'shutdownAccepted': True, 'processOutcome': 'exited',
            'unsaved': False, 'unreceipted': 0, 'eventId': os.urandom(8).hex()}}))
        self.core.write_text(json.dumps({'version': 1, 'state': 'complete',
            'previous_unknown': None, 'resources': {'processes': {'state': 'released'},
                                                  'computer': {'state': 'not_started'}},
            'at': os.urandom(8).hex()}))

    def lease(self, role='app'):
        return own.acquire_lifetime(self.paths, role, self.app, self.core)

    def test_token_action_reports_the_token_as_one_lf_json_line(self):
        facts = {'elevated': False, 'elevation_type': 3, 'integrity': 'S-1-16-8192',
                 'owner': 'S-1-5-21-1-2-3-1001', 'session': 1, 'user': 'S-1-5-21-1-2-3-1001'}
        raw = io.BytesIO()
        stdout = io.TextIOWrapper(raw, newline='\r\n')  # Windows' text newline
        engine = SimpleNamespace(win32=SimpleNamespace(token_facts=lambda: facts))
        with mock.patch.object(own, 'WINDOWS', True), \
                mock.patch.dict(sys.modules, {'src.desktop.platform': engine}), \
                mock.patch.object(sys, 'stdout', stdout):
            self.assertEqual(own.main(['token']), 0)
        self.assertEqual(raw.getvalue(), json.dumps(facts, sort_keys=True).encode() + b'\n')

    def test_token_action_fails_closed_and_needs_no_kind(self):
        def unreadable():
            raise OSError('Access is denied')
        stderr = io.StringIO()
        engine = SimpleNamespace(win32=SimpleNamespace(token_facts=unreadable))
        with mock.patch.object(own, 'WINDOWS', True), \
                mock.patch.dict(sys.modules, {'src.desktop.platform': engine}), \
                mock.patch.object(sys, 'stderr', stderr):
            self.assertEqual(own.main(['token']), 1)
        self.assertIn('Access is denied', stderr.getvalue())
        with mock.patch.object(own, 'WINDOWS', False), \
                mock.patch.object(sys, 'stderr', io.StringIO()):
            self.assertEqual(own.main(['token']), 1)  # Windows only
        with mock.patch.object(sys, 'stderr', io.StringIO()), \
                self.assertRaises(SystemExit) as raised:
            own.main(['hold'])  # the lease actions still need their kind
        self.assertEqual(raised.exception.code, 2)

    def test_app_and_core_independent_lifetimes(self):
        app, core = self.lease(), self.lease('core')
        try:
            with self.assertRaises(own.OwnershipError):
                with own.replacement_guard(self.paths):
                    pass
            self.clean()
            app.finish()
            app.close()
            with self.assertRaises(own.OwnershipError):
                with own.replacement_guard(self.paths):
                    pass
            core.finish()
            core.close()
            with own.replacement_guard(self.paths):
                pass
        finally:
            app.close()
            core.close()

    def test_a_pending_transaction_is_its_own_refusal_for_the_windows_app(self):
        self.paths.directory.mkdir(parents=True, mode=0o700)  # private, as the guardian makes it
        self.paths.pending.write_text('{}')
        with mock.patch.object(own, 'ownership_paths', lambda kind, env=None: self.paths), \
                mock.patch.object(sys, 'stderr', io.StringIO()):
            self.assertEqual(own.main(['hold', '--kind', 'nsis', '--app-cleanup', str(self.app),
                                       '--core-cleanup', str(self.core)]), own.PENDING_EXIT)
            self.assertEqual(own.main(['hold', '--kind', 'appimage', '--app-cleanup', str(self.app),
                                       '--core-cleanup', str(self.core)]), 1)  # Linux unchanged

    def test_pending_transaction_denies_launch_before_receipts(self):
        with own.replacement_guard(self.paths):
            self.paths.pending.write_text('{}')
        with self.assertRaises(own.OwnershipError):
            self.lease()
        self.assertEqual(list(self.paths.receipts.iterdir()), [])

    def test_readonly_refused_start_leaves_no_dirty_lifetime_receipt(self):
        with own.acquire_lifetime(self.paths, 'core', self.app, self.core,
                                  provisional=True):
            with self.assertRaises(own.OwnershipError):
                with own.replacement_guard(self.paths):
                    pass
            self.assertEqual(list(self.paths.receipts.iterdir()), [])
        with own.replacement_guard(self.paths):
            pass

    def test_provisional_admission_publishes_before_owned_work(self):
        with own.acquire_lifetime(self.paths, 'app', self.app, self.core,
                                  provisional=True) as lease:
            lease.begin()
            self.assertEqual(len(list(self.paths.receipts.iterdir())), 1)
            self.clean()
            lease.finish()
        with own.replacement_guard(self.paths):
            pass

    def test_the_mac_lease_is_per_user_inside_the_profile_namespace(self):
        home = self.root / 'home'
        paths = own.ownership_paths('macos', {'HOME': str(home)})
        self.assertEqual(paths.directory, home / 'Library/odin-desktop/.install-ownership/macos')
        with mac():
            fd = own._open(paths)
        try:
            for folder in (home / 'Library', home / 'Library/odin-desktop',
                           home / 'Library/odin-desktop/.install-ownership', paths.directory,
                           paths.receipts):
                self.assertEqual(folder.stat().st_mode & 0o777, 0o700, folder)
            self.assertEqual(paths.lease.stat().st_mode & 0o777, 0o600)
        finally:
            os.close(fd)

    def test_the_mac_lease_holds_and_cleans_like_the_appimage_one(self):
        self.paths = own.ownership_paths('macos', {'HOME': str(self.root / 'home')})
        self.clean()
        with mac(), mock.patch.object(own, '_boot_id', lambda: BOOT_A):
            with self.lease('core') as core:
                with self.assertRaises(own.OwnershipError):
                    with own.replacement_guard(self.paths, check_receipts=False):
                        pass  # a held lease fences an exclusive taker
                self.clean()
                core.finish()
            own.verify_receipts(self.paths)

    def test_the_mac_app_has_no_launcher_and_its_defaults_are_the_mac_profile(self):
        error = io.StringIO()
        with mock.patch.object(sys, 'stderr', error):
            self.assertEqual(own.main(['exec', '--kind', 'macos', '--', 'true']), 1)
        self.assertIn('The Mac app holds its own lease; there is no launcher', error.getvalue())
        home = self.root / 'home'
        with mock.patch.object(own, 'DARWIN', True), mock.patch.object(own, 'WINDOWS', False):
            app, core = own._profile({'HOME': str(home)})
        root = home / 'Library/odin-desktop/default'
        self.assertEqual((app, core), (root / 'default-cleanup-state.json',
                                       root / 'data/resource-cleanup.json'))

    def test_the_mac_boot_identity_is_the_cores(self):
        darwin = SimpleNamespace(current_boot_id=lambda: BOOT_C)
        platform = SimpleNamespace(darwin=darwin)
        with mock.patch.object(own, 'DARWIN', True), mock.patch.object(own, 'WINDOWS', False), \
                mock.patch.dict(sys.modules, {'src.desktop.platform': platform,
                                              'src.desktop.platform.darwin': darwin}):
            self.assertEqual(own._boot_id(), BOOT_C)
            darwin.current_boot_id = lambda: 'not-a-boot'
            self.assertIsNone(own._boot_id())
            darwin.current_boot_id = lambda: None
            self.assertIsNone(own._boot_id())

    @unittest.skipUnless(sys.platform == 'darwin', 'reads this Mac\'s kernel')
    def test_the_mac_boot_identity_reads_this_macs_kernel(self):
        with mock.patch.object(own, 'DARWIN', True):
            first, second = own._boot_id(), own._boot_id()
        self.assertRegex(first, own._BOOT_ID_SHAPE)
        self.assertEqual(first, second)

    def test_appimage_recovery_guard_allowed_but_launcher_denied(self):
        with own.replacement_guard(self.paths):
            (self.paths.directory / 'appimage-replacement.json').write_text('{}')
        with self.assertRaises(own.OwnershipError):
            self.lease()
        with own.replacement_guard(self.paths):
            pass

    def test_stale_clean_receipt_does_not_clean_new_lifetime(self):
        self.clean()
        lease = self.lease()
        try:
            with self.assertRaises(own.OwnershipError):
                lease.finish()
        finally:
            lease.close()
        with self.assertRaises(own.OwnershipError):
            with own.replacement_guard(self.paths):
                pass

    def boot(self, identity):
        path = self.root / 'boot_id'
        path.write_text(identity + '\n')
        return mock.patch.object(own, 'BOOT_ID', path)

    def guard_refuses(self):
        with self.assertRaisesRegex(own.OwnershipError, 'Unresolved lifetime evidence'):
            with own.replacement_guard(self.paths):
                pass

    def history(self, boot):
        """The core's retained unknown from an earlier lifetime, stamped with its boot."""
        core = json.loads(self.core.read_text())
        core['previous_unknown'] = {'state': 'unknown', 'boot_id': boot}
        self.core.write_text(json.dumps(core))

    def receipts_verdict(self):
        stderr = io.StringIO()
        with mock.patch.object(own, 'ownership_paths', lambda kind, env=None: self.paths), \
                mock.patch.object(sys, 'stderr', stderr):
            return own.main(['receipts', '--kind', 'appimage']), stderr.getvalue()

    def test_receipts_action_is_the_replacement_verdict_without_the_lock(self):
        self.assertEqual(self.receipts_verdict(), (0, ''))  # nothing admitted: no receipts yet
        with self.boot(BOOT_A):
            crashed = self.lease('core')
            crashed.close()  # ended without finish: its receipt stays running
            code, message = self.receipts_verdict()
            self.assertEqual(code, own.RECEIPTS_RESTART)
            self.assertIn('Unresolved lifetime evidence', message)
        with self.boot(BOOT_B):
            self.assertEqual(self.receipts_verdict(), (0, ''))  # an earlier boot no longer fences
            # The installer holds the lease exclusively while it asks: the verdict only reads.
            with own.replacement_guard(self.paths):
                self.assertEqual(self.receipts_verdict(), (0, ''))

    def test_receipts_verdict_exit_says_whether_a_restart_ends_the_refusal(self):
        with self.boot(BOOT_A):
            self.lease('core').close()  # this boot's lifetime, unresolved: the next boot ends it
            self.assertEqual(self.receipts_verdict()[0], own.RECEIPTS_RESTART)
        with mock.patch.object(own, 'BOOT_ID', self.root / 'missing'):
            # No readable boot identity: a restart may change nothing.
            code, message = self.receipts_verdict()
            self.assertEqual(code, 2)
            self.assertIn('Unresolved lifetime evidence', message)
        with self.boot(BOOT_B):
            self.assertEqual(self.receipts_verdict(), (0, ''))
            (self.paths.receipts / 'damaged.json').write_text('{"version": 1, "ro')
            # Evidence that can't be read: a restart changes nothing.
            code, message = self.receipts_verdict()
            self.assertEqual(code, 2)
            self.assertIn('Odin install ownership refusal', message)

    def test_a_receipt_bound_to_no_boot_never_gets_restart_advice(self):
        # Admitted while the boot identity was unreadable: it records none, so no boot ever makes
        # it an earlier boot's, before a restart or after one.
        with mock.patch.object(own, 'BOOT_ID', self.root / 'missing'):
            self.lease('core').close()
        receipt = json.loads(next(self.paths.receipts.iterdir()).read_text())
        self.assertIsNone(receipt['boot_id'])
        for boot in (BOOT_A, BOOT_B):
            with self.boot(boot):
                code, message = self.receipts_verdict()
                self.assertEqual(code, 2, boot)
                self.assertIn('Unresolved lifetime evidence', message)

    def test_a_lasting_refusal_outranks_restart_advice_in_any_order(self):
        with self.boot(BOOT_A):
            self.lease('core').close()  # bound to boot A: a restart ends it
        bound = next(self.paths.receipts.iterdir())
        damaged = self.paths.receipts / 'damaged.json'
        damaged.write_text('{"version": 1, "ro')
        for order in ([bound, damaged], [damaged, bound]):
            # The folder's listing order, as the file system happens to give it.
            listing = mock.patch.object(own.Path, 'iterdir', lambda path, order=order: iter(order))
            with self.boot(BOOT_A), listing:
                code, message = self.receipts_verdict()
            self.assertEqual(code, 2, order)
            self.assertEqual(message.count('Odin install ownership refusal'), 2)  # both reported
        damaged.unlink()
        with self.boot(BOOT_A):
            self.assertEqual(self.receipts_verdict()[0], own.RECEIPTS_RESTART)
        with self.boot(BOOT_B):
            self.assertEqual(self.receipts_verdict(), (0, ''))  # restarted: it no longer fences

    def verdict_process(self, boot):
        """The receipts action as the installer runs it: its own process, its exit status."""
        boot_file = self.root / f'boot-{boot[-1]}'
        boot_file.write_text(boot + '\n')
        driver = ('import importlib.util, sys\n'
                  'from pathlib import Path\n'
                  'spec = importlib.util.spec_from_file_location("ownership_cli", sys.argv[1])\n'
                  'own = sys.modules[spec.name] = importlib.util.module_from_spec(spec)\n'
                  'spec.loader.exec_module(own)\n'
                  'own.BOOT_ID = Path(sys.argv[2])\n'
                  'own.DARWIN = False\n'
                  'root = own.OwnershipPaths(Path(sys.argv[3]))\n'
                  'own.ownership_paths = lambda kind, env=None: root\n'
                  'sys.exit(own.main(["receipts", "--kind", "appimage"]))\n')
        return subprocess.run([sys.executable, '-I', '-c', driver, str(MODULE), str(boot_file),
                               str(self.paths.directory)], capture_output=True, text=True,
                              timeout=60)

    def test_a_wrong_typed_cleanup_record_is_a_classified_refusal(self):
        # Odin's round 8 case: a clean receipt bound to no boot, whose core journal holds a
        # list where a state belongs. Judging it raises TypeError; as an uncaught exception that
        # was Python's exit 1, the old restart answer, which no restart could make true. The codes
        # are the numbers the installer matches: 2 lasting, 3 restart, 0 clear.
        self.paths.directory.mkdir(mode=0o700)
        self.paths.receipts.mkdir(mode=0o700)
        self.core.write_text(json.dumps({
            'version': 1, 'state': 'complete', 'previous_unknown': None,
            'resources': {'computer': {'state': []}, 'processes': {'state': 'released'}}}))
        (self.paths.receipts / 'unbound.json').write_text(json.dumps(
            {'version': 1, 'role': 'core', 'state': 'clean', 'boot_id': None,
             'app_cleanup': str(self.app), 'core_cleanup': str(self.core)}))
        for boot in (BOOT_A, BOOT_B):
            run = self.verdict_process(boot)
            self.assertEqual(run.returncode, 2, (boot, run.stderr))
            self.assertIn('unbound.json: TypeError', run.stderr)
            self.assertNotIn('Traceback', run.stderr)
        # One receipt's failure never stops the others being judged.
        with self.boot(BOOT_A):
            self.lease('core').close()  # bound to boot A, unresolved
        run = self.verdict_process(BOOT_A)
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertEqual(run.stderr.count('Odin install ownership refusal'), 2, run.stderr)
        # Without it, the bound one alone: restart advice now, nothing after a restart.
        (self.paths.receipts / 'unbound.json').unlink()
        self.assertEqual(self.verdict_process(BOOT_A).returncode, 3)
        self.assertEqual(self.verdict_process(BOOT_B).returncode, 0)

    def test_an_interrupted_windows_receipt_write_is_not_a_receipt(self):
        with self.boot(BOOT_A):
            self.lease('core').close()  # an earlier boot's lifetime, below
        # Windows' publish primitive's temporary, cut off mid-write and never renamed into place.
        name = f'.{os.urandom(16).hex()}-app.json.{os.urandom(16).hex()}.tmp'
        leftover = self.paths.receipts / name
        leftover.write_text('{"version": 1, "ro')

        def plain(path):  # the Windows reader's result, without the Windows file API
            return json.loads(Path(path).read_text())

        with mock.patch.object(own, '_read', plain), \
                mock.patch.object(own, '_boot_id', lambda: BOOT_B):
            with mock.patch.object(own, 'WINDOWS', True):
                own.verify_receipts(self.paths)
                # Only that exact shape is skipped: anything else is still read, and refused.
                leftover.unlink()
                for name in ('.short.tmp', f'.x.{os.urandom(15).hex()}.tmp',
                             f'x.{os.urandom(16).hex()}.tmp', f'.x.{os.urandom(16).hex()}.tmp.old',
                             f'.X.{os.urandom(16).hex().upper()}.tmp', 'stray.json'):
                    near = self.paths.receipts / name
                    near.write_text('{"version": 1, "ro')
                    with self.assertRaises(ValueError, msg=name):
                        own.verify_receipts(self.paths)
                    near.unlink()
                leftover.write_text('{"version": 1, "ro')
            with mock.patch.object(own, 'WINDOWS', False), self.assertRaises(ValueError):
                own.verify_receipts(self.paths)  # Linux reads every file, as before

    def test_earlier_unknown_fences_its_boot_not_the_next(self):
        with self.boot(BOOT_A):
            crashed = self.lease('core')
            crashed.close()  # ended without finish: its receipt stays running
            later = self.lease()
            try:
                self.clean()
                self.history(BOOT_A)  # this lifetime's own Exit is clean
                app = json.loads(self.app.read_text())
                app['warning'] = {'id': 'notice', 'records': [{'state': 'unknown'}]}
                self.app.write_text(json.dumps(app))
                with self.assertRaisesRegex(own.OwnershipError, 'Core resource cleanup'):
                    later.finish()
            finally:
                later.close()
            states = sorted(json.loads(path.read_text())['state']
                            for path in self.paths.receipts.iterdir())
            self.assertEqual(states, ['running', 'running'])
            self.guard_refuses()
        with self.boot(BOOT_B):
            with own.replacement_guard(self.paths):
                pass
            # The same retained history no longer fences a lifetime in a later boot.
            lease = self.lease()
            try:
                self.clean()
                self.history(BOOT_A)
                lease.finish()
            finally:
                lease.close()
            with own.replacement_guard(self.paths):
                pass

    def test_an_unknown_this_boot_fences_another_installation_on_the_profile(self):
        # The .deb and AppImage keep separate registries but share one profile.
        other = own.OwnershipPaths(self.root / 'other-installation')
        with self.boot(BOOT_A):
            crashed = own.acquire_lifetime(other, 'core', self.app, self.core)
            crashed.close()  # unknown cleanup, fenced in its own registry
            lease = self.lease()
            try:
                self.clean()
                self.history(BOOT_A)  # the next core retains it in the shared profile
                with self.assertRaisesRegex(own.OwnershipError, 'Core resource cleanup'):
                    lease.finish()
            finally:
                lease.close()
            self.guard_refuses()
        with self.boot(BOOT_B):
            lease = self.lease()
            try:
                self.clean()
                self.history(BOOT_A)
                lease.finish()
            finally:
                lease.close()
            with own.replacement_guard(self.paths):
                pass

    def test_a_newer_unknown_this_boot_fences_despite_older_history(self):
        def newer(lease):
            try:
                self.clean()
                core = json.loads(self.core.read_text())
                core['previous_unknown'] = {'state': 'unknown', 'boot_id': BOOT_A}
                core['latest_unknown_boot_id'] = BOOT_B
                self.core.write_text(json.dumps(core))
                lease.finish()
            finally:
                lease.close()
        with self.boot(BOOT_B):
            with self.assertRaisesRegex(own.OwnershipError, 'Core resource cleanup'):
                newer(self.lease())
        with self.boot(BOOT_C):
            newer(self.lease())

    def test_history_without_a_boot_identity_stays_fenced(self):
        with self.boot(BOOT_B):
            lease = self.lease()
            try:
                self.clean()
                core = json.loads(self.core.read_text())
                core['previous_unknown'] = {'state': 'unknown'}
                self.core.write_text(json.dumps(core))
                with self.assertRaisesRegex(own.OwnershipError, 'Core resource cleanup'):
                    lease.finish()
            finally:
                lease.close()

    def test_an_empty_binding_never_falls_back_to_the_notice_boot(self):
        # A newer unknown whose boot could not be read must not lift with the older notice.
        with self.boot(BOOT_B):
            lease = self.lease()
            try:
                self.clean()
                self.history(BOOT_A)
                core = json.loads(self.core.read_text())
                core['latest_unknown_boot_id'] = None
                self.core.write_text(json.dumps(core))
                with self.assertRaisesRegex(own.OwnershipError, 'Core resource cleanup'):
                    lease.finish()
            finally:
                lease.close()

    def test_malformed_boot_identity_is_not_an_earlier_boot(self):
        self.paths.directory.mkdir(mode=0o700)
        self.paths.receipts.mkdir(mode=0o700)
        (self.paths.receipts / 'forged.json').write_text(json.dumps(
            {'version': 1, 'role': 'app', 'state': 'running', 'boot_id': 'not-a-kernel-boot-id'}))
        with self.boot(BOOT_B):
            self.guard_refuses()

    def test_own_unclean_exit_stays_unclean_with_history_present(self):
        lease = self.lease()
        try:
            self.clean()
            app = json.loads(self.app.read_text())
            app['current']['shutdownAccepted'] = False
            self.app.write_text(json.dumps(app))
            with self.assertRaises(own.OwnershipError):
                lease.finish()
        finally:
            lease.close()

    def test_receipt_without_boot_identity_stays_fenced(self):
        self.paths.directory.mkdir(mode=0o700)
        self.paths.receipts.mkdir(mode=0o700)
        (self.paths.receipts / 'older.json').write_text(json.dumps(
            {'version': 1, 'role': 'app', 'state': 'running'}))
        with self.boot(BOOT_B):
            self.guard_refuses()

    def test_unreadable_boot_identity_keeps_every_unclean_receipt_fenced(self):
        with self.boot(BOOT_A):
            self.lease('core').close()
        with mock.patch.object(own, 'BOOT_ID', self.root / 'missing'):
            self.guard_refuses()

    def test_hold_guardian_outlives_stop_signals_and_records_a_clean_exit(self):
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.root),
               'XDG_STATE_HOME': str(self.root / 'state')}
        child = subprocess.Popen(
            [sys.executable, '-I', '-B', str(MODULE), '--kind', 'appimage', '--role', 'app',
             '--app-cleanup', str(self.app), '--core-cleanup', str(self.core), 'hold'],
            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline(), 'READY\n')
            child.stdin.write('ADMIT\n')
            child.stdin.flush()
            self.assertEqual(child.stdout.readline(), 'ADMITTED\n')
            for number in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
                child.send_signal(number)
                with self.assertRaises(subprocess.TimeoutExpired):
                    child.wait(timeout=0.5)
            self.clean()
            child.stdin.close()
            self.assertEqual(child.wait(timeout=10), 0)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            child.stdout.close()
        receipts = self.root / 'state/odin-desktop/install-ownership/appimage/receipts'
        rows = [json.loads(path.read_text()) for path in receipts.iterdir()]
        self.assertEqual([(row['role'], row['state']) for row in rows], [('app', 'clean')])
        self.assertTrue(rows[0]['boot_id'])

    def test_incomplete_or_malformed_core_evidence_refuses(self):
        for resources in ({}, [], {'processes': {'state': 'released'}, 'computer': []}):
            with self.subTest(resources=resources):
                lease = self.lease()
                try:
                    self.clean()
                    value = json.loads(self.core.read_text())
                    value['resources'] = resources
                    self.core.write_text(json.dumps(value))
                    with self.assertRaises(own.OwnershipError):
                        lease.finish()
                finally:
                    lease.close()



class MacStartCheckTests(unittest.TestCase):
    """The Mac app's start check: a replacement guard, run at the next start."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.temp.name))
        self.home = self.root / 'home'
        self.paths = own.ownership_paths('macos', {'HOME': str(self.home)})
        profile = self.home / 'Library/odin-desktop/default'
        self.app = profile / 'default-cleanup-state.json'
        self.core = profile / 'data/resource-cleanup.json'
        self.core.parent.mkdir(parents=True)
        os.chmod(self.home / 'Library/odin-desktop', 0o700)
        self.boot = BOOT_A
        boot = mock.patch.object(own, '_boot_id', lambda: self.boot)
        boot.start()
        self.addCleanup(boot.stop)
        self.resources = self.bundle('Odin.app', version='1.0.0')

    def tearDown(self):
        self.temp.cleanup()

    def bundle(self, name, *, version):
        """An app's resources folder and its manifest, as finalize-manifest makes them."""
        resources = self.root / name / 'Contents/Resources'
        python = resources / 'runtime/python/lib/python3.12'
        python.mkdir(parents=True)
        (python / 'odin.py').write_text(f'VERSION = {version!r}\n')
        (resources / 'runtime/odin-guardian').write_bytes(b'\xcf\xfa\xed\xfe guardian')
        os.chmod(resources / 'runtime/odin-guardian', 0o755)
        (resources / 'ownership.py').write_text('# ownership\n')
        os.symlink('lib/python3.12', resources / 'runtime/python/current')
        os.symlink('odin.py', python / 'entry.py')
        self.write_manifest(resources)
        return resources

    @staticmethod
    def write_manifest(resources):
        files = manifest.inventory(resources, prefix='', exclude=('bundle-manifest.json',))
        (resources / 'bundle-manifest.json').write_text(
            json.dumps({'schema': 1, 'platform': 'darwin', 'files': files}))

    def record(self):
        return (self.paths.directory / own.BUNDLE_RECORD).read_bytes()

    def start(self, resources=None):
        """The app's lease holder up to READY: its start check, then the provisional lease."""
        return own.acquire_lifetime(self.paths, 'app', self.app, self.core, provisional=True,
                                    resources=resources or self.resources)

    def refused(self, code, resources=None):
        with self.assertRaises(own.StartRefusal) as caught:
            with self.start(resources):
                pass
        self.assertEqual(caught.exception.code, code, caught.exception)
        return str(caught.exception)

    def clean_evidence(self, core_state='complete'):
        self.app.write_text(json.dumps({'journalVersion': 2, 'warning': None, 'current': {
            'state': 'process-exited', 'shutdownAccepted': True, 'processOutcome': 'exited',
            'unsaved': False, 'unreceipted': 0, 'eventId': os.urandom(8).hex()}}))
        self.core.write_text(json.dumps({'version': 1, 'state': core_state,
            'previous_unknown': None, 'resources': {'processes': {'state': 'released'},
                                                  'computer': {'state': 'not_started'}},
            'at': os.urandom(8).hex()}))

    def lifetime(self, *, app_clean=True, core_state='complete'):
        """One app lifetime with its core, ended as described."""
        with self.start() as app:
            app.begin()
            with own.acquire_lifetime(self.paths, 'core', self.app, self.core) as core:
                self.clean_evidence(core_state)
                with contextlib.suppress(own.OwnershipError):
                    core.finish()
            if app_clean:
                with contextlib.suppress(own.OwnershipError):
                    app.finish()  # as the holder does: an unclean core keeps it unclean too

    def replace(self, version='2.0.0'):
        """Finder's replacement: a different app at the same path."""
        shutil.rmtree(self.root / 'Odin.app')
        self.resources = self.bundle('Odin.app', version=version)

    def test_a_first_start_checks_every_file_and_an_unchanged_one_only_its_metadata(self):
        with mac():
            with self.start():
                pass
            record = json.loads(self.record())
            digest = hashlib.sha256((self.resources / 'bundle-manifest.json').read_bytes())
            self.assertEqual(record['manifest'], digest.hexdigest())
            self.assertEqual((self.paths.directory / 'bundle.json').stat().st_mode & 0o777, 0o600)
            with mock.patch.object(own, '_verify_bundle', side_effect=AssertionError('again')):
                with self.start():
                    pass

    def test_changed_missing_or_extra_files_refuse_and_nothing_is_recorded(self):
        python = 'runtime/python/lib/python3.12'

        def same_size(resources):
            (resources / python / 'odin.py').write_text("VERSION = '9.9.9'\n")

        def executable(resources):
            os.chmod(resources / 'ownership.py', 0o755)

        def missing(resources):
            (resources / 'ownership.py').unlink()

        def extra(resources):
            (resources / 'runtime/extra.py').write_text('extra = 1\n')

        def retargeted(resources):
            (resources / python / 'entry.py').unlink()
            os.symlink('../python3.12/odin.py', resources / python / 'entry.py')

        def manifest_gone(resources):
            (resources / 'bundle-manifest.json').unlink()

        def manifest_garbage(resources):
            (resources / 'bundle-manifest.json').write_text('{"schema": 1, "files": 7}')

        for change in (same_size, executable, missing, extra, retargeted, manifest_gone,
                       manifest_garbage):
            with self.subTest(change.__name__), mac():
                resources = self.bundle(f'{change.__name__}.app', version='1.0.0')
                with self.start(resources):
                    pass
                before = self.record()
                change(resources)
                self.refused(own.MAC_FILES_CHANGED, resources)
                self.assertEqual(self.record(), before)

    def test_finders_settings_and_pythons_caches_are_accepted(self):
        with mac():
            with self.start():
                pass
            (self.resources / '.DS_Store').write_bytes(b'Bud1')
            (self.resources / 'runtime/.DS_Store').write_bytes(b'Bud1')
            cache = self.resources / 'runtime/python/lib/python3.12/__pycache__'
            cache.mkdir()
            (cache / 'odin.cpython-312.pyc').write_bytes(b'\x00' * 16)
            with self.start():
                pass

    def test_the_check_reads_the_manifest_as_finalize_writes_it(self):
        walked = sorted(relative for relative, info in own._bundle_walk(self.resources)
                        if not own.stat.S_ISDIR(info.st_mode)
                        and relative != 'bundle-manifest.json')
        listed = json.loads((self.resources / 'bundle-manifest.json').read_text())['files']
        self.assertEqual(walked, sorted(item['path'] for item in listed))
        self.assertIn('runtime/python/current', walked)  # a link to a folder, never descended
        own._verify_bundle(self.resources, self.resources / 'bundle-manifest.json')

    def test_a_clean_replacement_starts_and_records_the_new_app(self):
        with mac():
            self.lifetime()
            self.replace()
            with self.start():
                pass
            digest = hashlib.sha256((self.resources / 'bundle-manifest.json').read_bytes())
            self.assertEqual(json.loads(self.record())['manifest'], digest.hexdigest())

    def test_a_replacement_after_an_unclean_lifetime_this_boot_waits_for_a_restart(self):
        for version, unclean in (('2.0.0', {'app_clean': False}),
                                 ('3.0.0', {'core_state': 'unknown'})):
            with self.subTest(**unclean), mac():
                self.boot = BOOT_A
                shutil.rmtree(self.paths.directory, ignore_errors=True)
                self.lifetime(**unclean)
                self.replace(version)
                before = self.record()
                reason = self.refused(own.MAC_RESTART)
                self.assertRegex(reason, r'-(app|core)\.json: ')  # names the lifetime's receipt
                self.assertEqual(self.record(), before)
                self.boot = BOOT_B  # the restart ended every process of that lifetime
                with self.start():
                    pass

    def test_reinstalling_the_same_app_is_not_a_replacement(self):
        with mac():
            self.lifetime(app_clean=False)
            self.replace('1.0.0')  # the same bytes again: new files, the same manifest
            with self.start():
                pass

    def test_unreadable_lifetime_evidence_after_a_replacement_is_a_lasting_refusal(self):
        with mac():
            self.lifetime()
            (self.paths.receipts / f'{os.getuid()}-{"0" * 32}-app.json').write_text('{not json')
            self.replace()
            self.refused(own.MAC_LASTING)
            self.boot = BOOT_B  # a restart doesn't change an unreadable record
            self.refused(own.MAC_LASTING)

    def test_an_unclean_lifetime_without_a_replacement_starts_as_on_linux_and_windows(self):
        with mac():
            self.lifetime(app_clean=False)
            with self.start():
                pass  # the app's own cleanup notice reports the earlier lifetime

    def test_a_lifetime_still_running_is_never_judged_as_an_old_one(self):
        with mac():
            self.lifetime()
            with own.acquire_lifetime(self.paths, 'core', self.app, self.core) as core:
                self.replace()
                self.refused(own.MAC_STILL_STOPPING)  # not judged unclean while it runs
                self.clean_evidence()
                core.finish()
            with self.start():
                pass

    def test_an_unreadable_record_checks_everything_again(self):
        with mac():
            self.lifetime(app_clean=False)
            (self.paths.directory / own.BUNDLE_RECORD).write_text('{torn')
            self.refused(own.MAC_RESTART)  # no record: as if replaced, so the lifetime is judged

    def test_only_the_app_checks_its_files_at_start(self):
        with mac(), self.assertRaisesRegex(own.OwnershipError, 'Only the app'):
            own.acquire_lifetime(self.paths, 'core', self.app, self.core,
                                 resources=self.resources)

    def test_the_holder_exits_with_each_refusals_own_code(self):
        def hold():
            stdout, stderr = io.TextIOWrapper(io.BytesIO()), io.StringIO()
            with mock.patch.dict(os.environ, {'HOME': str(self.home)}), \
                    mock.patch.object(sys, 'stdin', io.StringIO('')), \
                    mock.patch.object(sys, 'stdout', stdout), \
                    mock.patch.object(sys, 'stderr', stderr):
                code = own.main(['hold', '--kind', 'macos', '--role', 'app',
                                 '--resources', str(self.resources)])
            stdout.flush()
            return code, stdout.buffer.getvalue(), stderr.getvalue()

        with mac():
            self.assertEqual(hold()[:2], (0, b'READY\n'))  # EOF before ADMIT: a refused start
            (self.resources / 'ownership.py').write_text('# changed\n')
            code, out, err = hold()
            self.assertEqual((code, out), (own.MAC_FILES_CHANGED, b''))
            self.assertIn('App files differ from its manifest', err)

    def test_receipts_and_the_record_are_private(self):
        with mac():
            self.lifetime()
            published = [*self.paths.receipts.iterdir(), self.paths.directory / 'bundle.json']
            self.assertEqual(len(published), 3)
            for path in published:
                self.assertEqual(path.stat().st_mode & 0o777, 0o600, path)


class MacLeaseFolderTests(unittest.TestCase):
    """The Mac lease's folders: unsafe existing state is refused, never repaired."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def fresh(self, name):
        home = self.root / name
        paths = own.ownership_paths('macos', {'HOME': str(home)})
        with mac():
            os.close(own._open(paths))
        return home, paths

    def refused(self, paths, *granted):
        with mac(*granted), self.assertRaises(own.OwnershipError):
            os.close(own._open(paths))

    def test_links_owners_and_open_modes_are_refused_and_left_as_they_are(self):
        namespace = 'Library/odin-desktop'
        for folder, mode in ((namespace, 0o775), (f'{namespace}/.install-ownership', 0o750),
                             (f'{namespace}/.install-ownership/macos', 0o701),
                             (f'{namespace}/.install-ownership/macos/receipts', 0o744)):
            with self.subTest(folder=folder, mode=oct(mode)):
                home, paths = self.fresh(f'mode-{len(folder)}')
                os.chmod(home / folder, mode)
                self.refused(paths)
                self.assertEqual((home / folder).stat().st_mode & 0o777, mode)  # not repaired
        home, paths = self.fresh('readable-root')
        os.chmod(home / namespace, 0o755)  # the profiles' shared root: no write for others
        with mac():
            os.close(own._open(paths))
        home, paths = self.fresh('link')
        elsewhere = self.root / 'elsewhere'
        shutil.move(home / namespace / '.install-ownership', elsewhere)
        os.symlink(elsewhere, home / namespace / '.install-ownership')
        self.refused(paths)
        self.assertTrue((home / namespace / '.install-ownership').is_symlink())

    def test_an_unsafe_lease_file_is_refused(self):
        for case in ('open mode', 'second link', 'link'):
            with self.subTest(case):
                home, paths = self.fresh(case.replace(' ', '-'))
                if case == 'open mode':
                    os.chmod(paths.lease, 0o644)
                elif case == 'second link':
                    os.link(paths.lease, self.root / f'{case}-copy')
                else:
                    paths.lease.unlink()
                    os.symlink(self.root / 'target', paths.lease)
                self.refused(paths)

    @unittest.skipIf(sys.platform == 'darwin', 'a Mac reads real ACLs: see the native case')
    def test_an_allow_entry_anywhere_in_the_namespace_is_refused(self):
        home, paths = self.fresh('acl')
        namespace = home / 'Library/odin-desktop'
        for path in (namespace, namespace / '.install-ownership', paths.directory,
                     paths.receipts, paths.lease):
            with self.subTest(path=path.relative_to(home)):
                self.refused(paths, path)
        with mac(home / 'Library'):
            os.close(own._open(paths))  # the Library folders above aren't inspected

    def test_the_library_folders_above_are_never_changed(self):
        home = self.root / 'library'
        (home / 'Library').mkdir(parents=True)
        os.chmod(home / 'Library', 0o755)
        with mac():
            os.close(own._open(own.ownership_paths('macos', {'HOME': str(home)})))
        self.assertEqual((home / 'Library').stat().st_mode & 0o777, 0o755)

    @unittest.skipUnless(sys.platform == 'darwin', 'sets real ACLs on this Mac')
    def test_a_real_inherited_allow_entry_is_refused(self):
        home = self.root / 'inherited'
        (home / 'Library').mkdir(parents=True)
        # The Library folder above isn't inspected, but the namespace created below inherits it.
        subprocess.run(['/bin/chmod', '+a', 'everyone allow list,search,add_file,file_inherit,'
                        'directory_inherit', str(home / 'Library')], check=True)
        paths = own.ownership_paths('macos', {'HOME': str(home)})
        with mac(), self.assertRaisesRegex(own.OwnershipError, 'odin-desktop'):
            os.close(own._open(paths))
        home, paths = self.fresh('direct')
        subprocess.run(['/bin/chmod', '+a', 'everyone allow list,search', str(paths.receipts)],
                       check=True)
        self.refused(paths)

if __name__ == '__main__':
    unittest.main()
