"""Non-destructive policy probes; exit 1 if any unsafe synthetic input passes.

Run explicitly with python3 -B tests/security_audit_probes.py. This is an audit
utility, not part of unittest discovery. No payload is executed or restored.
"""
import shutil

from test_archive import ArchiveTests
from test_policy import clean, replace
from verify import Entry, verify


def probes(base):
    yield 'SSH commented Include', replace(
        base, 'etc/ssh/sshd_config',
        b'PasswordAuthentication yes\nKbdInteractiveAuthentication yes\n'
        b'PermitRootLogin yes\n# Include /etc/ssh/sshd_config.d/*.conf\n')
    yield 'SSH earlier override', base + [Entry(
        'etc/ssh/sshd_config.d/00-override.conf', 'file', '',
        b'PasswordAuthentication yes\nKbdInteractiveAuthentication yes\n'
        b'PermitRootLogin yes\n')]
    yield 'Writable non-root-owned SSH policy', [
        e._replace(uid=1000, gid=1000, mode=0o666)
        if e.name == 'etc/ssh/sshd_config.d/10-csi-storage-template.conf' else e
        for e in base]
    yield 'Unexpected root SUID file', base + [Entry(
        'usr/local/bin/unexpected', 'file', '',
        b'PUBLIC SYNTHETIC PLACEHOLDER', mode=0o4755)]
    inittab = next(e.data for e in base if e.name == 'etc/inittab')
    yield 'Additional boot command', replace(
        base, 'etc/inittab', inittab + b'::sysinit:/usr/local/bin/unexpected\n')
    yield 'Modified pinned driver', replace(
        base, 'opt/democratic-csi/src/driver/controller-zfs-generic/index.js',
        b'// modified synthetic driver\n')
    yield 'Symlinked gatekeeper ancestor', [
        e._replace(kind='symlink', link='/tmp/replacement', data=b'')
        if e.name == 'opt/csi-gatekeeper' else e for e in base]
    yield 'Relative symlink leaving rootfs', base + [Entry(
        'opt/democratic-csi/escape', 'symlink', '../../../../outside', b'',
        mode=0o777)]
    yield 'Unrelated dirty provenance', replace(
        base, 'usr/share/csi-storage/build-info.json',
        b'{"schema_version":1,"template_version":"v0.0.0-test",'
        b'"working_tree_clean":false,"source_commit":"unrelated",'
        b'"inputs_sha256":{}}')


def main():
    if not shutil.which('zstd'):
        print('zstd is required; no probes executed')
        return 2
    base = clean()
    verify(base)
    archive = ArchiveTests()
    baseline = archive.check_archive(base)
    if baseline.returncode:
        raise RuntimeError('Baseline archive rejected: ' + baseline.stderr)
    accepted = 0
    for name, entries in probes(base):
        try:
            verify(entries)
        except ValueError:
            direct = False
        else:
            direct = True
        result = archive.check_archive(entries)
        packed = result.returncode == 0
        accepted += direct or packed
        print(f'{name}: entries={"ACCEPTED" if direct else "REJECTED"}; '
              f'archive={"ACCEPTED" if packed else "REJECTED"}')
    print(f'{accepted}/9 probes accepted through at least one interface')
    return 1 if accepted else 0


if __name__ == '__main__':
    raise SystemExit(main())
