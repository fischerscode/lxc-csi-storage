"""Finalization removes instance data and installs safe Alpine boot behavior."""
import json
from pathlib import Path
import tempfile
import unittest

from fixtures import prepare, ROOT
from finalize import BLOCKED_SERVICES, finalize
from verify import root_entries, verify


class FinalizeTests(unittest.TestCase):
    def test_identity_cleanup_and_first_boot_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare(root)
            for name in ['etc/ssh/ssh_host_ed25519_key', 'root/.ssh/authorized_keys',
                         'var/lib/csi-lio/manifest.json', 'etc/machine-id',
                         'var/lib/dbus/machine-id', 'dev/bootstrap-placeholder', 'tmp/test.key']:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('PUBLIC TEST PLACEHOLDER')
            config = json.loads((ROOT / 'build-config.json').read_text())
            finalize(root, 'v0.0.0-test', config)
            self.assertFalse((root / 'etc/machine-id').exists())
            self.assertFalse((root / 'var/lib/dbus/machine-id').exists())
            self.assertFalse((root / 'root/.ssh').exists())
            self.assertFalse((root / 'var/lib/csi-lio').exists())
            self.assertEqual(list((root / 'dev').iterdir()), [])
            self.assertEqual(list((root / 'tmp').iterdir()), [])
            self.assertEqual(list((root / 'etc/ssh').glob('ssh_host_*')), [])
            for service in BLOCKED_SERVICES:
                self.assertEqual((root / 'etc/init.d' / service).readlink().as_posix(), '/dev/null')
            self.assertEqual((root / 'etc/conf.d/sshd').read_text(), 'sshd_disable_keygen="no"\n')
            self.assertEqual((root / 'etc/inittab').read_text().count('::respawn:/sbin/getty 38400 console'), 1)
            self.assertFalse(verify(root_entries(root))['configured'])
