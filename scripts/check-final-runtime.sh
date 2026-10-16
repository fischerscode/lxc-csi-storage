#!/usr/bin/env bash
set -euo pipefail
# Called in a private mount namespace. gcompat's loader needs /proc/self/exe.
rootfs=${1:?Clean rootfs required}
mount --rbind /proc "$rootfs/proc"
chroot "$rootfs" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root \
    node --check /opt/democratic-csi/src/driver/controller-zfs-generic/index.js
chroot "$rootfs" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root \
    node -e 'require("/opt/democratic-csi/src/driver/controller-zfs-generic")'
set +e
output=$(chroot "$rootfs" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root \
    /opt/csi-gatekeeper/csi-gatekeeper 2>&1)
status=$?
set -e
if [[ $status != 64 || $output != 'Usage: csi-gatekeeper '* ]]; then
    printf '%s\n' "$output" >&2
    echo 'Gatekeeper runtime smoke check failed' >&2
    exit 1
fi
