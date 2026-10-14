#!/usr/bin/env bash
set -euo pipefail
# Called through unshare --mount --propagation private; mounts disappear on exit.
rootfs=${1:?Clean rootfs required}
mount -t proc proc "$rootfs/proc"
mount -t tmpfs tmpfs "$rootfs/dev"
for spec in 'null 1 3' 'zero 1 5' 'random 1 8' 'urandom 1 9' 'full 1 7' 'tty 5 0'; do
    read -r name major minor <<< "$spec"
    mknod -m 0666 "$rootfs/dev/$name" c "$major" "$minor"
done
ln -s /proc/self/fd "$rootfs/dev/fd"
ln -s /proc/self/fd/0 "$rootfs/dev/stdin"
ln -s /proc/self/fd/1 "$rootfs/dev/stdout"
ln -s /proc/self/fd/2 "$rootfs/dev/stderr"
chroot "$rootfs" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root \
    npm --prefix /opt/democratic-csi ci --omit=dev --no-audit --no-fund
mkdir -p "$rootfs/run/sshd"
chroot "$rootfs" /usr/bin/ssh-keygen -A
chroot "$rootfs" /usr/sbin/sshd -t
