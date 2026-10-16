#!/usr/bin/env bash
set -euo pipefail
# Called through unshare --mount --propagation private; mounts disappear on exit.
rootfs=${1:?Clean rootfs required}
mount --rbind /proc "$rootfs/proc"
mount -t tmpfs tmpfs "$rootfs/dev"
for name in null zero random urandom full tty; do
    touch "$rootfs/dev/$name"
    mount --bind "/dev/$name" "$rootfs/dev/$name"
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
chroot "$rootfs" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root \
    python3 -B /tmp/check-gatekeeper-runtime.py /opt/csi-gatekeeper/csi-gatekeeper
