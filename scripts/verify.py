#!/usr/bin/env python3
"""Verify clean rootfs/release archives without extracting untrusted tar paths."""
import argparse
import hashlib
from finalize import MASKS
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile

PUBLIC_SELF_TEST_HASHES = json.loads((Path(__file__).resolve().parents[1] / 'build-config.json').read_text())['public_self_test_files_sha256']

FORBIDDEN = ('root/.ssh', 'root/.npm', 'root/.cache', 'etc/csi-storage',
             'etc/csi-credentials', 'var/lib/csi-lio', 'var/lib/csi-lio-shared',
             'var/lib/systemd/random-seed', 'opt/democratic-csi/.git',
             'usr/share/nodejs/npm', 'usr/bin/npm', 'usr/bin/npx', 'usr/bin/git')
PRIVATE_PEM = re.compile(rb'-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----[\r\n]+[A-Za-z0-9+/=\r\n]{64,}-----END (?:[A-Z ]*PRIVATE KEY)-----')


def verify(entries):
    seen = set()
    manifest = None
    machine_id = False
    host_key_generation = False
    build_info = None
    masks = {}
    for name, kind, link, data in entries:
        p = PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts:
            raise ValueError('Unsafe archive path')
        name = str(p)
        if name in ('.', ''):
            continue
        if name in seen:
            raise ValueError('Duplicate archive path')
        seen.add(name)
        if any(name == f or name.startswith(f + '/') for f in FORBIDDEN):
            raise ValueError('Instance/build data present: ' + name)
        if name.startswith('etc/ssh/ssh_host_') or name.endswith('/authorized_keys'):
            raise ValueError('SSH identity present: ' + name)
        if kind not in ('file', 'dir', 'symlink', 'hardlink'):
            raise ValueError('Device or unsupported entry present: ' + name)
        if kind == 'hardlink':
            target = PurePosixPath(link)
            if target.is_absolute() or '..' in target.parts:
                raise ValueError('Unsafe archive hardlink')
        if kind == 'symlink' and name.rsplit('/', 1)[0] == 'etc/systemd/system':
            masks[name.rsplit('/', 1)[-1]] = link
        if kind != 'file':
            continue
        if PRIVATE_PEM.search(data):
            # Signed Debian GnuTLS embeds public self-test vectors. Permit only
            # its reviewed exact ELF bytes, never arbitrary binaries/key files.
            if not (data.startswith(b'\x7fELF') and
                    PUBLIC_SELF_TEST_HASHES.get(name) == hashlib.sha256(data).hexdigest()):
                raise ValueError('Private key material present: ' + name)
        if name == 'etc/machine-id':
            if data.strip():
                raise ValueError('Machine identity present')
            machine_id = True
        if name == 'etc/shadow':
            if any(line.split(b':')[1] not in (b'!', b'*', b'!!', b'!*') for line in data.splitlines()):
                raise ValueError('Account credential present')
        if name == 'etc/systemd/system/csi-storage-ssh-host-keys.service':
            host_key_generation = b'ExecStart=/usr/bin/ssh-keygen -A' in data
        if name == 'usr/share/csi-storage/template.json':
            manifest = json.loads(data)
        if name == 'usr/share/csi-storage/build-info.json':
            build_info = json.loads(data)
    if not machine_id or not host_key_generation or not manifest:
        raise ValueError('Missing template/first-boot contract')
    if manifest['schema_version'] != 1 or manifest['configuration_contract'] != 'csi-storage-template/v1' or manifest['configured'] is not False:
        raise ValueError('Unsupported or already configured template')
    if (not build_info or build_info.get('schema_version') != 1 or
            build_info.get('template_version') != manifest['template_version']):
        raise ValueError('Missing or mismatched build provenance')
    if manifest['masked_units'] != list(MASKS):
        raise ValueError('Invalid activation mask contract')
    for unit in MASKS:
        if masks.get(unit) != '/dev/null':
            raise ValueError('Missing storage activation mask: ' + unit)
    required = ['opt/csi-gatekeeper/csi-gatekeeper',
                'opt/democratic-csi/package-lock.json',
                'opt/democratic-csi/node_modules/@grpc/grpc-js/package.json',
                'etc/ssh/sshd_config.d/10-csi-storage-template.conf']
    if not all(p in seen for p in required):
        raise ValueError('Missing application or SSH policy')
    return manifest


def root_entries(root):
    for p in sorted(root.rglob('*')):
        name = p.relative_to(root).as_posix()
        if p.is_symlink():
            yield name, 'symlink', p.readlink().as_posix(), b''
        elif p.is_dir():
            yield name, 'dir', '', b''
        elif p.is_file():
            yield name, 'file', '', p.read_bytes()
        else:
            yield name, 'unsupported', '', b''


def tar_entries(tar):
    for m in tar:
        kind = 'file' if m.isfile() else 'dir' if m.isdir() else 'symlink' if m.issym() else 'hardlink' if m.islnk() else 'unsupported'
        yield m.name, kind, m.linkname, tar.extractfile(m).read() if m.isfile() else b''


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--rootfs', type=Path)
    group.add_argument('--archive', type=Path)
    args = parser.parse_args()
    if args.rootfs:
        manifest = verify(root_entries(args.rootfs))
    else:
        process = subprocess.Popen(['zstd', '-dc', str(args.archive)], stdout=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=process.stdout, mode='r|') as tar:
                manifest = verify(tar_entries(tar))
            process.stdout.close()
            if process.wait() != 0:
                raise ValueError('Archive decompression failed')
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait()
    print('Clean template verified: ' + manifest['template_version'])


if __name__ == '__main__':
    main()
