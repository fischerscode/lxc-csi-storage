"""Finalization removes instance identities and preserves safe first-boot behavior."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('finalizer', ROOT / 'scripts/finalize.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FinalizeTests(unittest.TestCase):
    def test_identity_cleanup_and_first_boot_contract(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for folder in ['etc/systemd/system','etc/ssh','root/.ssh','var/lib/csi-lio','tmp','var/tmp','dev']:
                (root/folder).mkdir(parents=True)
            for name in ['etc/ssh/ssh_host_ed25519_key','root/.ssh/authorized_keys',
                         'var/lib/csi-lio/manifest.json','etc/machine-id','etc/resolv.conf','dev/bootstrap-placeholder']:
                (root/name).write_text('PUBLIC TEST PLACEHOLDER')
            config = json.loads((ROOT/'build-config.json').read_text())
            module.finalize(root,'v0.1.0-test',config)
            self.assertEqual((root/'etc/machine-id').read_text(),'')
            self.assertEqual((root/'etc/resolv.conf').read_text(),'')
            self.assertFalse((root/'root/.ssh').exists())
            self.assertFalse((root/'var/lib/csi-lio').exists())
            self.assertEqual(list((root/'dev').iterdir()),[])
            self.assertEqual(list((root/'etc/ssh').glob('ssh_host_*')),[])
            for mask in module.MASKS:
                self.assertEqual((root/'etc/systemd/system'/mask).readlink().as_posix(),'/dev/null')
            policy = (root/'etc/ssh/sshd_config.d/10-csi-storage-template.conf').read_text()
            self.assertIn('PasswordAuthentication no',policy)
            self.assertIn('ssh-keygen -A',(root/'etc/systemd/system/csi-storage-ssh-host-keys.service').read_text())
            self.assertNotIn('Check-Valid-Until',(root/'etc/apt/sources.list.d/csi-storage.sources').read_text())
            self.assertFalse(json.loads((root/'usr/share/csi-storage/template.json').read_text())['configured'])
