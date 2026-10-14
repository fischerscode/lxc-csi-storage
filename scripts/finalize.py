#!/usr/bin/env python3
"""Install generic first-boot behavior and remove all instance/build identities."""
import json
from pathlib import Path
import shutil
import sys

MASKS = ('nfs-server.service', 'rtslib-fb-targetctl.service',
         'target.service', 'zfs-import-cache.service', 'zfs-import-scan.service',
         'zfs-mount.service', 'zfs-share.service', 'zfs-zed.service',
         'zfs-load-module.service', 'systemd-networkd.service',
         'systemd-networkd-wait-online.service')


def write(root, path, content, mode=0o644):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    p.chmod(mode)


def finalize(root, version, config):
    for name in MASKS:
        p = root / 'etc/systemd/system' / name
        if p.is_symlink() or p.exists():
            p.unlink()
        p.symlink_to('/dev/null')
    write(root, 'etc/ssh/sshd_config.d/10-atlas-template.conf',
          'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n')
    write(root, 'etc/systemd/system/atlas-ssh-host-keys.service', '''[Unit]
Description=Generate unique SSH host keys for this instance
Before=ssh.service
ConditionPathExists=!/etc/ssh/ssh_host_ed25519_key
[Service]
Type=oneshot
ExecStart=/usr/bin/ssh-keygen -A
RemainAfterExit=yes
''')
    write(root, 'etc/systemd/system/ssh.service.d/10-atlas-host-keys.conf',
          '[Unit]\nRequires=atlas-ssh-host-keys.service\nAfter=atlas-ssh-host-keys.service\n')
    write(root, 'etc/network/interfaces',
          'auto lo\niface lo inet loopback\nsource /etc/network/interfaces.d/*\n')
    resolver = root / 'etc/resolv.conf'
    resolver.unlink(missing_ok=True)
    write(root, 'etc/resolv.conf', '')
    write(root, 'etc/hosts', '127.0.0.1 localhost\n::1 localhost ip6-localhost ip6-loopback\n')
    write(root, 'etc/hostname', 'atlas-storage-unconfigured\n')
    write(root, 'etc/sysctl.d/90-atlas-storage.conf',
          'net.ipv4.ip_forward=0\nnet.ipv6.conf.all.forwarding=0\n')
    write(root, 'etc/machine-id', '', 0o444)
    dbus = root / 'var/lib/dbus/machine-id'
    if dbus.is_symlink() or dbus.exists():
        dbus.unlink()
    dbus.parent.mkdir(parents=True, exist_ok=True)
    dbus.symlink_to('/etc/machine-id')
    for p in (root / 'etc/ssh').glob('ssh_host_*'):
        p.unlink()
    for path in ['root/.ssh', 'root/.npm', 'root/.cache', 'root/.bash_history',
                 'opt/atlas-democratic-csi/node_modules/ssh2/test',
                 'etc/atlas-storage', 'etc/atlas-credentials', 'var/lib/atlas-lio',
                 'var/lib/atlas-lio-shared', 'var/lib/systemd/random-seed',
                 'var/lib/nfs/etab', 'etc/exports', 'etc/iscsi/initiatorname.iscsi']:
        p = root / path
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        elif p.exists() or p.is_symlink():
            p.unlink()
    for path in ['dev', 'run', 'tmp', 'var/tmp', 'var/log', 'var/lib/apt/lists', 'var/cache/apt/archives']:
        p = root / path
        for child in p.iterdir() if p.exists() else []:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    (root / 'tmp').chmod(0o1777)
    (root / 'var/tmp').chmod(0o1777)
    for p in (root / 'etc/apt/apt.conf.d').glob('*mmdebstrap*'):
        p.unlink()
    # Runtime package maintenance returns to normal signed current Debian repos.
    # Only the build is snapshot-pinned; don't leave expiry checks disabled.
    sources = root / 'etc/apt/sources.list'
    sources.unlink(missing_ok=True)
    write(root, 'etc/apt/sources.list.d/atlas.sources', '''Types: deb
URIs: https://deb.debian.org/debian
Suites: trixie trixie-updates
Components: main contrib
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: https://security.debian.org/debian-security
Suites: trixie-security
Components: main contrib
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
''')
    manifest = {
        'schema_version': 1, 'template_version': version, 'architecture': config['architecture'],
        'os': {'id': 'debian', 'version': '13', 'suite': config['debian_suite'],
               'snapshot': config['debian_snapshot']},
        'applications': {'democratic_csi': {'commit': config['democratic_csi_commit'],
                         'upstream_driver_sha256': config['democratic_csi_driver_sha256'],
                         'atlas_overlays_applied': False},
                         'csi_gatekeeper': {'version': config['gatekeeper_version'],
                          'download_sha256': config['gatekeeper_sha256']}},
        'configuration_contract': 'atlas-storage-template/v1',
        'configured': False,
        'required_host_bindings': ['owned_dataset_mount', 'dev_zfs', 'owned_zvol_access',
                                   'lio_configfs_target', 'shared_lio_lock'],
        'activation_owner': 'atlas', 'masked_units': list(MASKS),
    }
    write(root, 'usr/share/atlas-storage/template.json', json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    finalize(Path(sys.argv[1]), sys.argv[2], json.loads(Path(sys.argv[3]).read_text()))
