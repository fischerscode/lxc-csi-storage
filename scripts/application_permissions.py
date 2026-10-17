#!/usr/bin/env python3
"""Normalize packaged applications without dereferencing their symlinks."""
import os
from pathlib import Path
import stat
import sys

APPLICATION_TREES = ('opt/democratic-csi', 'opt/csi-gatekeeper',
                     'usr/share/doc/csi-gatekeeper')
APPLICATION_ANCESTORS = {'opt', 'usr', 'usr/share', 'usr/share/doc'}
DRIVER = 'opt/democratic-csi/src/driver/controller-zfs-generic/index.js'
DRIVER_DIRECTORIES = ('opt', 'opt/democratic-csi', 'opt/democratic-csi/src',
                      'opt/democratic-csi/src/driver',
                      'opt/democratic-csi/src/driver/controller-zfs-generic')


def application_path(name):
    return name in APPLICATION_ANCESTORS or any(
        name == tree or name.startswith(tree + '/') for tree in APPLICATION_TREES)


def normalize(root):
    # Walk only real directories. In particular, npm's executable symlinks must
    # retain their targets and must never cause chmod/chown outside these trees.
    paths = [root / 'opt']
    for tree in APPLICATION_TREES:
        base = root / tree
        if not base.is_dir() or base.is_symlink():
            raise ValueError('Missing application directory: ' + tree)
        paths.append(base)
        paths.extend(base.rglob('*'))
    for path in paths:
        mode = path.lstat().st_mode
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
            raise ValueError('Unsupported application entry: ' + str(path))
        os.chown(path, 0, 0, follow_symlinks=False)
        if not stat.S_ISLNK(mode):
            # Retain all read/execute bits, including executable npm entrypoints.
            path.chmod(stat.S_IMODE(mode) & ~0o022)


def verify_permissions(name, kind, uid, gid, mode):
    if not application_path(name):
        return
    if (uid, gid) != (0, 0):
        raise ValueError('Application path is not root-owned: ' + name)
    # POSIX symlinks conventionally have mode 0777; the target's own entry is
    # checked separately. Hardlink headers are checked like regular files.
    if kind != 'symlink' and mode & 0o022:
        raise ValueError('Group/other-writable application path: ' + name)
    if name in DRIVER_DIRECTORIES and (kind != 'dir' or mode != 0o755):
        raise ValueError('Unexpected driver directory permissions: ' + name)
    if name == DRIVER and (kind != 'file' or mode != 0o644):
        raise ValueError('Unexpected driver file permissions: ' + name)
    if name == 'opt/csi-gatekeeper/csi-gatekeeper' and (kind != 'file' or mode != 0o755):
        raise ValueError('Unexpected gatekeeper executable permissions')


if __name__ == '__main__':
    normalize(Path(sys.argv[1]))
