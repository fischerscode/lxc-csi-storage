#!/usr/bin/env python3
"""Verify Alpine rootfs/release policy without extracting untrusted tar paths."""
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile

from finalize import BLOCKED_SERVICES, NETWORK, RUNLEVELS, SSH_POLICY
from package_lock import installed

CONFIG = json.loads((Path(__file__).resolve().parents[1] / 'build-config.json').read_text())
FORBIDDEN = ('root/.ssh', 'root/.npm', 'root/.cache', 'etc/csi-storage',
             'etc/csi-credentials', 'var/lib/csi-lio', 'var/lib/csi-lio-shared',
             'var/lib/seedrng', 'opt/democratic-csi/.git', 'usr/share/nodejs/npm',
             'usr/lib/node_modules/npm', 'usr/bin/npm', 'usr/bin/npx', 'usr/bin/git',
             'etc/machine-id', 'var/lib/dbus/machine-id', 'etc/exports',
             'etc/systemd', 'usr/lib/systemd', 'etc/apt', 'var/lib/dpkg', 'packages')
PRIVATE_PEM = re.compile(rb'-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----[\r\n]+[A-Za-z0-9+/=\r\n]{64,}-----END (?:[A-Z ]*PRIVATE KEY)-----')


def verify(entries):
    seen, files, links = set(), {}, {}
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
        if (name.startswith('etc/ssh/ssh_host_') or name.endswith(('/authorized_keys', '/authorized_keys2',
                '/.ash_history', '/.bash_history', '/random-seed'))):
            raise ValueError('Instance identity present: ' + name)
        if kind not in ('file', 'dir', 'symlink', 'hardlink'):
            raise ValueError('Device or unsupported entry present: ' + name)
        if kind == 'hardlink':
            target = PurePosixPath(link)
            if target.is_absolute() or '..' in target.parts:
                raise ValueError('Unsafe archive hardlink')
        if kind != 'dir' and any(name.startswith(p + '/') for p in
                ('dev', 'run', 'tmp', 'var/tmp', 'var/log', 'var/cache/apk', 'etc/network/interfaces.d')):
            raise ValueError('Build or instance residue: ' + name)
        if kind == 'symlink':
            links[name] = link
        if name.startswith('etc/runlevels/') and kind != 'dir':
            level, _, service = name.removeprefix('etc/runlevels/').partition('/')
            if service not in RUNLEVELS.get(level, ()) or link != '/etc/init.d/' + service or kind != 'symlink':
                raise ValueError('Unexpected enabled service: ' + name)
        if kind != 'file':
            continue
        if PRIVATE_PEM.search(data):
            raise ValueError('Private key material present: ' + name)
        if name.startswith(('etc/', 'usr/lib/sysctl.d/', 'lib/sysctl.d/')) or name in ('lib/apk/db/installed',
                'usr/share/csi-storage/template.json', 'usr/share/csi-storage/build-info.json'):
            files[name] = data
    manifest = json.loads(files.get('usr/share/csi-storage/template.json', b'null'))
    provenance = json.loads(files.get('usr/share/csi-storage/build-info.json', b'null'))
    if (not manifest or manifest.get('schema_version') != 2 or
            manifest.get('configuration_contract') != 'csi-storage-template/v2' or
            manifest.get('configured') is not False):
        raise ValueError('Unsupported or already configured template')
    if (not provenance or provenance.get('schema_version') != 1 or
            provenance.get('template_version') != manifest.get('template_version')):
        raise ValueError('Missing or mismatched build provenance')
    if manifest.get('blocked_openrc_services') != list(BLOCKED_SERVICES):
        raise ValueError('Invalid storage activation contract')
    for service in BLOCKED_SERVICES:
        if links.get('etc/init.d/' + service) != '/dev/null':
            raise ValueError('Missing storage activation block: ' + service)
    for level, services in RUNLEVELS.items():
        for service in services:
            if links.get(f'etc/runlevels/{level}/{service}') != '/etc/init.d/' + service:
                raise ValueError('Missing required boot service: ' + service)
    expected_os = {'id': 'alpine', 'version': CONFIG['alpine_version'],
                   'branch': CONFIG['alpine_branch'], 'architecture': CONFIG['alpine_architecture'],
                   'init': 'openrc'}
    if manifest.get('os') != expected_os:
        raise ValueError('Unexpected OS contract')
    exact = {
        'etc/alpine-release': CONFIG['alpine_version'] + '\n',
        'etc/resolv.conf': '', 'etc/network/interfaces': NETWORK,
        'etc/hostname': 'csi-storage-unconfigured\n',
        'etc/hosts': '127.0.0.1 localhost\n::1 localhost ip6-localhost ip6-loopback\n',
        'etc/conf.d/sshd': 'sshd_disable_keygen="no"\n',
        'etc/ssh/sshd_config.d/10-csi-storage-template.conf': SSH_POLICY,
        'etc/sysctl.d/90-csi-storage.conf': 'net.ipv4.ip_forward=0\nnet.ipv6.conf.all.forwarding=0\n',
        'etc/nftables.nft': '# No rules installed. Configure explicitly before enabling nftables.\n',
        'etc/apk/repositories': ''.join(CONFIG['alpine_mirror'] + '/' + CONFIG['alpine_branch'] + '/' + r + '\n'
                                      for r in ('main', 'community')),
        'etc/apk/world': '\n'.join(CONFIG['runtime_packages']) + '\n',
    }
    for name, content in exact.items():
        if files.get(name) != content.encode():
            raise ValueError('Unexpected configuration: ' + name)
    for name, data in files.items():
        if (name == 'etc/sysctl.conf' or name.startswith(('etc/sysctl.d/', 'usr/lib/sysctl.d/', 'lib/sysctl.d/'))) and re.search(
            rb'^\s*(?:net[./]ipv4[./](?:ip_forward|conf[./][\w-]+[./]forwarding)|net[./]ipv6[./]conf[./][\w-]+[./]forwarding)\s*=\s*[1-9]', data, re.M):
            raise ValueError('Forwarding enabled: ' + name)
    if not re.search(rb'^root:\*:', files.get('etc/shadow', b''), re.M):
        raise ValueError('Expected Alpine root no-password marker')
    for line in files['etc/shadow'].splitlines():
        fields = line.split(b':')
        if len(fields) < 2 or not re.fullmatch(rb'[!*]+', fields[1]):
            raise ValueError('Account credential present')
    if b'rc_sys="lxc"' not in files.get('etc/rc.conf', b''):
        raise ValueError('Missing OpenRC LXC mode')
    for command in (b'::sysinit:/sbin/openrc sysinit', b'::sysinit:/sbin/openrc boot',
                    b'::wait:/sbin/openrc default', b'::shutdown:/sbin/openrc shutdown'):
        if command not in files.get('etc/inittab', b''):
            raise ValueError('Missing BusyBox/OpenRC init entry')
    if (b'ssh-keygen -A' not in files.get('etc/init.d/sshd', b'') or
            b'generate_host_keys' not in files.get('etc/init.d/sshd', b'')):
        raise ValueError('Missing packaged SSH key generation')
    if b'Include /etc/ssh/sshd_config.d/*.conf' not in files.get('etc/ssh/sshd_config', b''):
        raise ValueError('SSH policy is not included')
    installed(files.get('lib/apk/db/installed', b'').decode())
    required = ['sbin/init', 'sbin/openrc', 'opt/csi-gatekeeper/csi-gatekeeper',
                'usr/share/doc/csi-gatekeeper/LICENSE',
                'usr/share/doc/csi-gatekeeper/THIRD_PARTY_NOTICES.txt',
                'usr/share/doc/csi-gatekeeper/BUILD_INFO.json',
                'opt/democratic-csi/package-lock.json',
                'opt/democratic-csi/node_modules/@grpc/grpc-js/package.json']
    if not all(p in seen for p in required):
        raise ValueError('Missing applications or init')
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
