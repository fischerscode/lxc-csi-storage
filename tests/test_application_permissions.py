"""Normalize source/npm metadata while preserving executables and symlinks."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fixtures import prepare
from application_permissions import DRIVER, DRIVER_DIRECTORIES, normalize
from verify import root_entries


class ApplicationPermissionTests(unittest.TestCase):
    def test_normalization_preserves_content_executables_and_symlink_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare(root)
            driver = root / DRIVER
            content = driver.read_bytes()
            for name in DRIVER_DIRECTORIES:
                (root / name).chmod(0o775)
            driver.chmod(0o664)
            module = root / 'opt/democratic-csi/node_modules/tool'
            module.mkdir()
            executable = module / 'cli.js'
            executable.write_text('#!/usr/bin/env node\n')
            executable.chmod(0o777)
            binary = root / 'opt/csi-gatekeeper/csi-gatekeeper'
            binary.chmod(0o775)
            notice = root / 'usr/share/doc/csi-gatekeeper/LICENSE'
            notice.chmod(0o666)
            outside = root / 'outside'
            outside.mkdir()
            (outside / 'untouched').write_text('outside application trees')
            (outside / 'untouched').chmod(0o666)
            link = module / 'external'
            link.symlink_to(outside, target_is_directory=True)
            command = module / 'command'
            command.symlink_to('cli.js')
            # Production requires root. Record every lchown without granting the
            # unit test privileges; chmod and symlink behavior are exercised.
            with patch('application_permissions.os.chown') as chown:
                normalize(root)
            changed = {call.args[0] for call in chown.call_args_list}
            self.assertIn(link, changed)
            self.assertNotIn(outside / 'untouched', changed)
            for call in chown.call_args_list:
                self.assertEqual(call.args[1:], (0, 0))
                self.assertEqual(call.kwargs, {'follow_symlinks': False})
            for name in DRIVER_DIRECTORIES:
                self.assertEqual((root / name).stat().st_mode & 0o7777, 0o755)
            self.assertEqual(driver.stat().st_mode & 0o7777, 0o644)
            self.assertEqual(driver.read_bytes(), content)
            self.assertEqual(executable.stat().st_mode & 0o7777, 0o755)
            self.assertEqual(binary.stat().st_mode & 0o7777, 0o755)
            self.assertEqual(notice.stat().st_mode & 0o7777, 0o644)
            self.assertEqual(command.readlink(), Path('cli.js'))
            self.assertEqual(link.readlink(), outside)
            self.assertEqual((outside / 'untouched').stat().st_mode & 0o7777, 0o666)
            # The rootfs reader must retain real ownership, not invent root IDs.
            entry = next(e for e in root_entries(root) if e.name == DRIVER)
            self.assertEqual((entry.uid, entry.gid), (driver.stat().st_uid, driver.stat().st_gid))
