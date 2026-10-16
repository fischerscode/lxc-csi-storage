"""Reject identity leaks, unsafe archive entries and active storage defaults."""
import importlib.util
from pathlib import Path
import unittest
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('verify', ROOT / 'scripts/verify.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def clean():
    import json
    manifest = {'schema_version': 1, 'template_version': 'v0.0.0-test',
                'configuration_contract': 'csi-storage-template/v1', 'configured': False,
                'masked_units': list(module.MASKS)}
    files = {'etc/machine-id': b'', 'etc/shadow': b'root:!:0:0:0:0:::\n',
             'etc/systemd/system/csi-storage-ssh-host-keys.service': b'ExecStart=/usr/bin/ssh-keygen -A',
             'usr/share/csi-storage/template.json': json.dumps(manifest).encode(),
             'usr/share/csi-storage/build-info.json': json.dumps({
                 'schema_version': 1, 'template_version': 'v0.0.0-test'}).encode(),
             'opt/csi-gatekeeper/csi-gatekeeper': b'PUBLIC TEST EXECUTABLE PLACEHOLDER',
             'opt/democratic-csi/package-lock.json': b'{}',
             'opt/democratic-csi/node_modules/@grpc/grpc-js/package.json': b'{}',
             'etc/ssh/sshd_config.d/10-csi-storage-template.conf': b'PasswordAuthentication no'}
    return [(n, 'file', '', v) for n, v in files.items()] + [('etc/systemd/system/'+n, 'symlink', '/dev/null', b'') for n in manifest['masked_units']]


class PolicyTests(unittest.TestCase):
    def test_clean_contract_and_merged_usr_symlink(self):
        self.assertFalse(module.verify(clean() + [('bin', 'symlink', 'usr/bin', b'')])['configured'])

    def test_instance_data_and_archive_escapes(self):
        for path in ['root/.ssh/authorized_keys', 'etc/ssh/ssh_host_ed25519_key',
                     'etc/csi-storage/customer.json', 'var/lib/csi-lio/shared.json',
                     'opt/democratic-csi/.git/config', 'usr/share/nodejs/npm/package.json',
                     'usr/bin/npm', 'usr/bin/npx', 'usr/bin/git',
                     '../outside', '/etc/passwd']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                module.verify(clean() + [(path, 'file', '', b'PUBLIC TEST PLACEHOLDER')])

    def test_missing_or_mismatched_provenance(self):
        path = 'usr/share/csi-storage/build-info.json'
        with self.assertRaises(ValueError):
            module.verify([entry for entry in clean() if entry[0] != path])
        entries = [(n,k,l,b'{"schema_version":1,"template_version":"v9.0.0"}'
                    if n == path else data) for n,k,l,data in clean()]
        with self.assertRaises(ValueError):
            module.verify(entries)

    def test_build_tool_symlinks_are_also_rejected(self):
        with self.assertRaises(ValueError):
            module.verify(clean()+[('usr/bin/npm', 'symlink', '../share/nodejs/npm/bin/npm-cli.js', b'')])

    def test_device_and_hardlink_escape(self):
        for entry in [('dev/zfs', 'unsupported', '', b''), ('copy', 'hardlink', '../secret', b'')]:
            with self.assertRaises(ValueError):
                module.verify(clean()+[entry])

    def test_machine_identity_and_missing_mask(self):
        entries = clean()
        entries = [(n, k, l, b'public-test-machine-id' if n == 'etc/machine-id' else v) for n,k,l,v in entries]
        with self.assertRaises(ValueError):
            module.verify(entries)
        with self.assertRaises(ValueError):
            module.verify([e for e in clean() if e[0] != 'etc/systemd/system/nfs-server.service'])

    def test_duplicate_paths_and_account_password(self):
        with self.assertRaises(ValueError):
            module.verify(clean()+[('etc/machine-id','file','',b'')])
        entries = [(n,k,l,b'root:REPLACE_WITH_PASSWORD_HASH:0:0:0:0:::\n' if n=='etc/shadow' else v) for n,k,l,v in clean()]
        with self.assertRaises(ValueError):
            module.verify(entries)

    def test_nested_wants_link_cannot_override_canonical_mask(self):
        entries = clean()+[('etc/systemd/system/zfs-import.target.wants/zfs-import-cache.service',
                           'symlink', '/usr/lib/systemd/system/zfs-import-cache.service', b'')]
        self.assertFalse(module.verify(entries)['configured'])

    def test_mask_contract_cannot_omit_required_units(self):
        import json
        entries = []
        for n,k,l,data in clean():
            if n == 'usr/share/csi-storage/template.json':
                v = json.loads(data); v['masked_units'] = []; data = json.dumps(v).encode()
            entries.append((n,k,l,data))
        with self.assertRaises(ValueError):
            module.verify(entries)

    def test_private_material_only_permits_exact_public_selftest_elf(self):
        import hashlib
        from unittest.mock import patch
        # Construct an inert detector fixture at runtime; it is not a key.
        data = b'\x7fELF' + b'-----' + b'BEGIN PRIVATE KEY-----\n' + b'A'*64 + b'\n-----' + b'END PRIVATE KEY-----'
        path = 'usr/lib/public-test-library.so'
        with self.assertRaises(ValueError):
            module.verify(clean()+[(path,'file','',data)])
        with patch.dict(module.PUBLIC_SELF_TEST_HASHES, {path:hashlib.sha256(data).hexdigest()}):
            self.assertFalse(module.verify(clean()+[(path,'file','',data)])['configured'])
            with self.assertRaises(ValueError):
                module.verify(clean()+[(path,'file','',data+b'changed')])
