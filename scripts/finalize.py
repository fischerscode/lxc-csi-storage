#!/usr/bin/env python3
"""Install the Alpine/OpenRC contract and remove instance/build identities."""
import json
from pathlib import Path
import re
import shutil
import sys

BLOCKED_SERVICES = ('nfs', 'nfsclient', 'nfsdcld', 'nfsmount', 'rpc.gssd',
                    'rpc.idmapd', 'rpc.pipefs', 'rpc.statd', 'rpc.svcgssd',
                    'rpcbind', 'targetcli', 'zfs-import', 'zfs-load-key',
                    'zfs-mount', 'zfs-share', 'zfs-zed')
RUNLEVELS = {'boot': ('bootmisc', 'hostname', 'networking', 'sysctl', 'machine-id'),
             'default': ('sshd', 'syslog'), 'shutdown': ('killprocs', 'savecache')}
NETWORK = 'auto lo\niface lo inet loopback\nsource /etc/network/interfaces.d/*\n'
SSH_POLICY = 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n'


def write(root, path, content, mode=0o644):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    p.chmod(mode)


def remove(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def finalize(root, version, config):
    # Package scripts never own host-wide storage recovery, even on explicit start.
    for name in BLOCKED_SERVICES:
        p = root / 'etc/init.d' / name
        remove(p)
        p.symlink_to('/dev/null')
    levels = root / 'etc/runlevels'
    remove(levels)
    for level, services in RUNLEVELS.items():
        (levels / level).mkdir(parents=True, exist_ok=True)
        for service in services:
            (levels / level / service).symlink_to('/etc/init.d/' + service)
    rc = root / 'etc/rc.conf'
    rc.write_text(re.sub(r'^#?rc_sys=.*$', '', rc.read_text(), flags=re.M) + '\nrc_sys="lxc"\n')
    inittab = root / 'etc/inittab'
    inittab.write_text(re.sub(r'^(?:tty[0-9].*:respawn:.*|::respawn:/sbin/getty 38400 console)\n', '', inittab.read_text(), flags=re.M)
                       + '\n::respawn:/sbin/getty 38400 console\n')
    write(root, 'etc/ssh/sshd_config.d/10-csi-storage-template.conf', SSH_POLICY)
    write(root, 'etc/conf.d/sshd', 'sshd_disable_keygen="no"\n')
    write(root, 'etc/network/interfaces', NETWORK)
    (root / 'etc/network/interfaces.d').mkdir(exist_ok=True)
    remove(root / 'etc/resolv.conf')
    write(root, 'etc/resolv.conf', '')
    write(root, 'etc/hosts', '127.0.0.1 localhost\n::1 localhost ip6-localhost ip6-loopback\n')
    write(root, 'etc/hostname', 'csi-storage-unconfigured\n')
    write(root, 'etc/sysctl.d/90-csi-storage.conf',
          'net.ipv4.ip_forward=0\nnet.ipv6.conf.all.forwarding=0\n')
    write(root, 'etc/nftables.nft', '# No rules installed. Configure explicitly before enabling nftables.\n')
    # Alpine's root:* permits key authentication without a password (no PAM).
    shadow = (root / 'etc/shadow').read_text()
    if not re.search(r'^root:\*:', shadow, re.M):
        raise ValueError('Expected Alpine root no-password marker (*)')
    for p in (root / 'etc/ssh').glob('ssh_host_*'):
        remove(p)
    for p in (root / 'etc').glob('*-'):
        remove(p)
    for path in ['etc/machine-id', 'var/lib/dbus/machine-id', 'root/.ssh',
                 'root/.npm', 'root/.cache', 'root/.ash_history', 'root/.bash_history',
                 'opt/democratic-csi/node_modules/ssh2/test',
                 'etc/csi-storage', 'etc/csi-credentials', 'var/lib/csi-lio',
                 'var/lib/csi-lio-shared', 'var/lib/seedrng', 'var/lib/nfs/etab',
                 'etc/exports', 'etc/iscsi/initiatorname.iscsi', 'etc/apk/cache']:
        remove(root / path)
    for path in ['dev', 'run', 'tmp', 'var/tmp', 'var/log', 'var/cache/apk']:
        p = root / path
        p.mkdir(parents=True, exist_ok=True)
        for child in p.iterdir():
            remove(child)
    (root / 'tmp').chmod(0o1777)
    (root / 'var/tmp').chmod(0o1777)
    branch = config['alpine_branch']
    mirror = config['alpine_mirror']
    write(root, 'etc/apk/repositories', f'{mirror}/{branch}/main\n{mirror}/{branch}/community\n')
    write(root, 'etc/apk/world', '\n'.join(config['runtime_packages']) + '\n')
    manifest = {
        'schema_version': 2, 'template_version': version, 'architecture': config['architecture'],
        'os': {'id': 'alpine', 'version': config['alpine_version'], 'branch': branch,
               'architecture': config['alpine_architecture'], 'init': 'openrc'},
        'applications': {'democratic_csi': {'commit': config['democratic_csi_commit'],
                         'upstream_driver_sha256': config['democratic_csi_driver_sha256'],
                         'consumer_overlays_applied': False},
                         'csi_gatekeeper': {'version': config['gatekeeper_version'],
                          'download_sha256': config['gatekeeper_sha256'], 'compatibility': 'gcompat'}},
        'configuration_contract': 'csi-storage-template/v2', 'configured': False,
        'required_host_bindings': ['owned_dataset_mount', 'dev_zfs', 'owned_zvol_access',
                                   'lio_configfs_target', 'shared_lio_lock'],
        'activation_owner': 'consumer', 'blocked_openrc_services': list(BLOCKED_SERVICES),
    }
    write(root, 'usr/share/csi-storage/template.json', json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    finalize(Path(sys.argv[1]), sys.argv[2], json.loads(Path(sys.argv[3]).read_text()))
