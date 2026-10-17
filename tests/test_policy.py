"""Reject identities, active storage, incompatible packages and unsafe archives."""
from pathlib import Path
import tempfile
import unittest

from fixtures import prepare, policy_entries
import verify as module


def clean():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        prepare(root)
        return policy_entries(root)


def replace(entries, path, data):
    return [entry._replace(data=data) if entry.name == path else entry for entry in entries]


class PolicyTests(unittest.TestCase):
    def test_clean_alpine_contract(self):
        self.assertFalse(module.verify(clean())['configured'])

    def test_instance_data_build_tools_and_archive_escapes(self):
        for path in ['root/.ssh/authorized_keys', 'etc/ssh/ssh_host_ed25519_key',
                     'etc/csi-storage/customer.json', 'var/lib/csi-lio/shared.json',
                     'opt/democratic-csi/.git/config', 'usr/lib/node_modules/npm/package.json',
                     'usr/bin/npm', 'usr/bin/npx', 'usr/bin/git', 'etc/machine-id',
                     'var/lib/dbus/machine-id', 'tmp/forgotten-test.key', 'run/sshd.pid',
                     'etc/network/interfaces.d/customer', 'etc/systemd/system/storage.service',
                     '../outside', '/etc/passwd']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                module.verify(clean() + [(path, 'file', '', b'PUBLIC TEST PLACEHOLDER')])

    def test_missing_or_mismatched_provenance(self):
        path = 'usr/share/csi-storage/build-info.json'
        with self.assertRaises(ValueError):
            module.verify([entry for entry in clean() if entry[0] != path])
        with self.assertRaises(ValueError):
            module.verify(replace(clean(), path, b'{"schema_version":1,"template_version":"v9.0.0"}'))

    def test_build_tool_symlinks_are_also_rejected(self):
        with self.assertRaises(ValueError):
            module.verify(clean()+[('usr/bin/npm', 'symlink', '../lib/node_modules/npm/bin/npm-cli.js', b'')])

    def test_device_hardlink_escape_and_duplicate(self):
        for entry in [('dev/zfs', 'unsupported', '', b''), ('copy', 'hardlink', '../secret', b''),
                      ('etc/shadow', 'file', '', b'')]:
            with self.assertRaises(ValueError):
                module.verify(clean()+[entry])

    def test_missing_block_or_enabled_storage(self):
        with self.assertRaises(ValueError):
            module.verify([entry for entry in clean() if entry[0] != 'etc/init.d/targetcli'])
        with self.assertRaises(ValueError):
            module.verify(clean()+[('etc/runlevels/default/nfs', 'symlink', '/etc/init.d/nfs', b'')])

    def test_account_password_and_unusable_root(self):
        for shadow in (b'root:REPLACE_WITH_PASSWORD_HASH:0:0:0:0:::\n', b'root:!:0:0:0:0:::\n'):
            with self.assertRaises(ValueError):
                module.verify(replace(clean(), 'etc/shadow', shadow))

    def test_runtime_package_drift(self):
        path = 'lib/apk/db/installed'
        for data in (b'', b'P:gcompat\nV:0.0.0-r0\nA:x86_64'):
            with self.assertRaises(ValueError):
                module.verify(replace(clean(), path, data))

    def test_ssh_policy_requires_active_include_and_key_generation(self):
        for path in ('etc/ssh/sshd_config', 'etc/init.d/sshd', 'etc/conf.d/sshd'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                module.verify(replace(clean(), path, b'# disabled\n'))

    def test_private_material_has_no_elf_exemptions(self):
        data = b'\x7fELF' + b'-----' + b'BEGIN PRIVATE KEY-----\n' + b'A'*64 + b'\n-----' + b'END PRIVATE KEY-----'
        with self.assertRaises(ValueError):
            module.verify(clean()+[('usr/lib/public-test-library.so', 'file', '', data)])
