"""Real Windows ACL/reparse checks on owned disposable synthetic fixtures only."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.recovery.runtime import RecoveryError, digest, run
from src.recovery.s3_safety import (
    _powershell, assert_private, generate_key, load_key, prepare_directory, safe_path, session_permissions,
)


@unittest.skipUnless(os.name == 'nt', 'Real Windows ACLs run in the Windows recovery CI job')
class WindowsACLTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='football-synthetic-acl-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / 'private'
        prepare_directory(self.directory, confirmed=True)

    def test_private_directory_and_file_pass_real_acl_audit(self):
        (self.directory / 'synthetic.txt').write_bytes(b'fixture')
        assert_private(self.directory, children=True)

    def test_broad_grant_is_refused_and_preflight_does_not_repair_it(self):
        run(['icacls', str(self.directory), '/grant', '*S-1-1-0:(OI)(CI)R'])
        for check in (assert_private, session_permissions):
            with self.assertRaisesRegex(RecoveryError, 'S3_UNSAFE_PERMISSIONS'):
                check(self.directory)
        missing_key = self.directory / 'must-not-create-synthetic.key'
        with self.assertRaisesRegex(RecoveryError, 'S3_UNSAFE_PERMISSIONS'):
            generate_key(missing_key, confirmed=True)
        self.assertFalse(missing_key.exists())
        # Remove only the injected test grant, on this new empty fixture.
        session_permissions(self.directory, initialize=True)
        assert_private(self.directory)

    def test_broad_key_file_grant_is_refused_without_repair(self):
        key = self.directory / 'synthetic.key'
        key.write_bytes(os.urandom(32))
        load_key(key)
        run(['icacls', str(key), '/grant', '*S-1-1-0:R'])
        with self.assertRaisesRegex(RecoveryError, '^S3_UNSAFE_PERMISSIONS$'):
            load_key(key)
        with self.assertRaisesRegex(RecoveryError, '^S3_UNSAFE_PERMISSIONS$'):
            load_key(key)  # No silent repair of the existing fixture ACL.

    def test_new_synthetic_restore_removes_extra_grants_before_writing(self):
        from src.recovery import s3_archive
        payload = b'synthetic-acl-fixture'
        item = {'object_id': 1, 'key': 'fixture', 'metadata': {},
                'size_bytes': len(payload), 'sha256': digest(payload)}
        verified = SimpleNamespace(core={'scope': 'synthetic-local', 'chunk_size': 64}, directory=self.directory,
                                   index={'objects': [item]}, _chunks=lambda _: iter([payload]),
                                   summary=lambda: {'scope': 'synthetic-local'})
        original_private = s3_archive.private_directory
        def extra_grant(path):
            original_private(path)
            run(['icacls', str(path), '/grant', '*S-1-1-0:(OI)(CI)R'])
        destination = self.root / 'restored'
        with patch.object(s3_archive, 'verify_archive', return_value=verified), \
             patch.object(s3_archive, 'private_directory', side_effect=extra_grant):
            s3_archive.restore_synthetic(self.directory, b'fixture-not-used-by-mocked-verifier', destination)
        assert_private(destination, children=True)

    def test_nonempty_directory_cannot_be_reinitialized(self):
        (self.directory / 'synthetic.txt').write_bytes(b'fixture')
        with self.assertRaisesRegex(RecoveryError, 'NEW_EMPTY_PRIVATE_DIRECTORY_REQUIRED'):
            session_permissions(self.directory, initialize=True)

    def test_acl_transport_failure_is_fail_closed(self):
        with patch('src.recovery.s3_safety.run', side_effect=RecoveryError('SYNTHETIC_ACL_FAILURE')):
            with self.assertRaisesRegex(RecoveryError, 'SYNTHETIC_ACL_FAILURE'):
                assert_private(self.directory)

    def test_junction_is_refused(self):
        target = self.root / 'junction'
        quote = lambda p: str(p).replace("'", "''")
        _powershell("$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path '" + quote(target)
                    + "' -Target '" + quote(self.directory) + "' | Out-Null")
        with self.assertRaisesRegex(RecoveryError, 'S3_LINK_REFUSED'):
            safe_path(target)
