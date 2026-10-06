"""Filesystem behavior, run as ordinary user in an isolated PID/mount namespace."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('appimage_replace', Path(__file__).parents[1] / 'replace-appimage.py')
replacement = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replacement)


def image(path, payload):
    path.write_bytes(b'\x7fELF\x02\x01\x01\x00AI\x02\x00' + payload)
    path.chmod(0o755)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class UserReplacement(unittest.TestCase):
    def setUp(self):
        if os.getuid() == 0:
            self.fail('AppImage behavior must be tested as an ordinary owner, not root')
        self.temporary = tempfile.TemporaryDirectory(prefix='AppImage owner spaces ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.old = self.root / 'Odin current.AppImage'
        self.new = self.root / 'Odin new.AppImage'
        self.old_hash = image(self.old, b'old image')
        self.new_hash = image(self.new, b'new image')
        self.transaction = self.root / 'transaction.json'

    def run_replace(self):
        return replacement.replace_locked(self.new, self.old, self.new_hash, self.transaction)

    def test_replaces_new_inode_leaving_old_read_only_lifetime_unchanged(self):
        self.old.chmod(0o444)
        with self.old.open('rb') as old_lifetime:
            old_bytes = old_lifetime.read()
            old_inode = os.fstat(old_lifetime.fileno()).st_ino
            self.assertEqual(self.run_replace()['status'], 'replaced')
            self.assertNotEqual(self.old.stat().st_ino, old_inode)
            old_lifetime.seek(0)
            self.assertEqual(old_lifetime.read(), old_bytes)
        self.assertEqual(hashlib.sha256(self.old.read_bytes()).hexdigest(), self.new_hash)
        self.assertEqual(self.old.stat().st_mode & 0o777, 0o755)
        self.assertFalse(self.transaction.exists())

    def test_nonwritable_destination_leaves_old_bytes(self):
        self.root.chmod(0o555)
        self.addCleanup(self.root.chmod, 0o700)
        with self.assertRaises(PermissionError):
            self.run_replace()
        self.assertEqual(hashlib.sha256(self.old.read_bytes()).hexdigest(), self.old_hash)

    def test_hash_refusal_does_not_write_transaction(self):
        self.new_hash = '0' * 64
        with self.assertRaises(replacement.ReplacementError):
            self.run_replace()
        self.assertFalse(self.transaction.exists())
        self.assertEqual(hashlib.sha256(self.old.read_bytes()).hexdigest(), self.old_hash)

    def test_symlink_destination_refused_without_touching_target(self):
        target = self.root / 'target'
        self.old.rename(target)
        self.old.symlink_to(target)
        with self.assertRaises(OSError):
            self.run_replace()
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), self.old_hash)

    def test_source_is_never_executed_and_nonappimage_refused(self):
        self.new.write_bytes(b'not an executable AppImage')
        self.new_hash = hashlib.sha256(self.new.read_bytes()).hexdigest()
        with self.assertRaises(replacement.ReplacementError):
            self.run_replace()
        self.assertFalse(self.transaction.exists())

    def test_core_command_or_other_executable_cannot_be_destination(self):
        self.old.write_bytes(b'\x7fELFnot an AppImage interpreter')
        before = self.old.read_bytes()
        with self.assertRaises(replacement.ReplacementError):
            self.run_replace()
        self.assertEqual(self.old.read_bytes(), before)
        self.assertFalse(self.transaction.exists())

    def test_interrupted_before_rename_preserves_old_and_resumes_exact_stage(self):
        real_replace = os.replace
        def interrupted(source, destination, **kwargs):
            if 'src_dir_fd' in kwargs:
                raise OSError('Harmless simulated storage interruption')
            return real_replace(source, destination, **kwargs)
        with patch.object(replacement.os, 'replace', side_effect=interrupted):
            with self.assertRaises(OSError):
                self.run_replace()
        self.assertEqual(hashlib.sha256(self.old.read_bytes()).hexdigest(), self.old_hash)
        pending = json.loads(self.transaction.read_text())
        self.assertTrue((self.root / pending['stage']).exists())
        unrelated = self.root / 'unrelated.pending'
        unrelated.write_text('retain')
        self.assertEqual(self.run_replace()['status'], 'replaced')
        self.assertEqual(unrelated.read_text(), 'retain')

    def test_interrupt_after_rename_is_idempotently_recovered(self):
        unlink = Path.unlink
        def interrupt(path, *args, **kwargs):
            if path == self.transaction:
                raise OSError('Harmless simulated receipt cleanup interruption')
            return unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', interrupt):
            with self.assertRaises(OSError):
                self.run_replace()
        inode = self.old.stat().st_ino
        self.assertEqual(self.run_replace()['status'], 'recovered')
        self.assertEqual(self.old.stat().st_ino, inode)

    def test_interrupted_transaction_different_destination_requires_inspection(self):
        self.transaction.write_text(json.dumps({'schema': 1, 'destination': '/other', 'new_sha256': self.new_hash}))
        with self.assertRaises(replacement.ReplacementError):
            self.run_replace()
        self.assertEqual(hashlib.sha256(self.old.read_bytes()).hexdigest(), self.old_hash)

    def test_interrupted_copy_preserves_old_and_recovers_exact_recorded_stage(self):
        real_write = os.write
        def interrupt(fd, value):
            if bytes(value).startswith(b'\x7fELF'):
                raise OSError('Harmless simulated copy failure')
            return real_write(fd, value)
        with patch.object(replacement.os, 'write', side_effect=interrupt):
            with self.assertRaises(OSError):
                self.run_replace()
        self.assertEqual(hashlib.sha256(self.old.read_bytes()).hexdigest(), self.old_hash)
        pending = json.loads(self.transaction.read_text())
        self.assertTrue((self.root / pending['stage']).exists())
        self.assertEqual(self.run_replace()['status'], 'replaced')
        self.assertFalse((self.root / pending['stage']).exists())

    def test_crash_before_stage_identity_publication_requires_manual_inspection(self):
        real_write = replacement.write_transaction
        def interrupt(path, value):
            if 'stage_identity' in value:
                raise OSError('Harmless simulated identity publication failure')
            return real_write(path, value)
        with patch.object(replacement, 'write_transaction', side_effect=interrupt):
            with self.assertRaises(OSError):
                self.run_replace()
        pending = json.loads(self.transaction.read_text())
        with self.assertRaises(replacement.ReplacementError):
            self.run_replace()
        self.assertTrue((self.root / pending['stage']).exists())

    def test_source_mutation_after_initial_digest_does_not_replace_executable(self):
        original_digest = replacement.digest_fd
        calls = 0
        def digest(fd):
            nonlocal calls
            result = original_digest(fd)
            calls += 1
            if calls == 1:
                self.new.write_bytes(b'\x7fELF\x02\x01\x01\x00AI\x02\x00changed payload')
            return result
        with patch.object(replacement, 'digest_fd', side_effect=digest):
            with self.assertRaises(replacement.ReplacementError):
                self.run_replace()
        self.assertEqual(hashlib.sha256(self.old.read_bytes()).hexdigest(), self.old_hash)
        self.assertTrue(self.transaction.exists())

    def test_interrupted_stage_changed_identity_refuses_cleanup(self):
        real_replace = os.replace
        def interrupted(source, destination, **kwargs):
            if 'src_dir_fd' in kwargs:
                raise OSError('Harmless simulated interruption')
            return real_replace(source, destination, **kwargs)
        with patch.object(replacement.os, 'replace', side_effect=interrupted):
            with self.assertRaises(OSError):
                self.run_replace()
        stage = self.root / json.loads(self.transaction.read_text())['stage']
        changed = self.root / 'changed-stage'
        changed.write_text('unrelated owner bytes')
        changed.replace(stage)
        with self.assertRaises(replacement.ReplacementError):
            self.run_replace()
        self.assertEqual(stage.read_text(), 'unrelated owner bytes')
        self.assertEqual(hashlib.sha256(self.old.read_bytes()).hexdigest(), self.old_hash)

    def test_readonly_mount_destination_refused(self):
        mount = os.environ.get('ODIN_TEST_READONLY_IMAGE')
        if not mount:
            self.skipTest('Actual read-only bind-mount fixture supplied by namespace qualification')
        self.old = Path(mount)
        before = self.old.read_bytes()
        with self.assertRaises(OSError):
            self.run_replace()
        self.assertEqual(self.old.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
