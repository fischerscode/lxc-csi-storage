#!/usr/bin/env bash
set -euo pipefail
umask 022
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
version=${1:?Usage: build.sh VERSION EXTERNAL_OUTPUT_DIRECTORY}
out=${2:?External output directory required}
[[ $version =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.-]+)?$ ]] || { echo 'Invalid release version' >&2; exit 1; }
[[ $(id -u) == 0 && $(uname -m) == x86_64 ]] || { echo 'Build requires root on an isolated x86_64 Linux builder' >&2; exit 1; }
out=$(realpath -m -- "$out")
[[ $out != / && $out != "$repo" && $out != "$repo/"* ]] || { echo 'Output must be outside the checkout' >&2; exit 1; }
[[ ! -e $out ]] || { echo 'Output directory must be new' >&2; exit 1; }
mkdir -p -- "$(dirname -- "$out")"
mkdir -m 0700 -- "$out"
work=$(mktemp -d "$out/.work.XXXXXXXX")
trap 'status=$?; if (( status == 0 )); then rm -rf -- "$work"; else echo "Failed build retained at $work" >&2; fi' EXIT
rootfs=$work/rootfs
readarray -t config < <(python3 - "$repo/build-config.json" <<'PY'
import json,sys
c=json.load(open(sys.argv[1]))
for key in ['debian_suite','debian_snapshot','architecture','democratic_csi_commit','gatekeeper_url','gatekeeper_sha256','democratic_csi_driver_sha256','gatekeeper_version','debian_keyring_url','debian_keyring_sha256']:
 print(c[key])
PY
)
suite=${config[0]}; snapshot=${config[1]}; arch=${config[2]}; commit=${config[3]}
curl --fail --location --proto '=https' --tlsv1.2 --retry 3 "${config[8]}" -o "$work/keyring.deb"
printf '%s  %s\n' "${config[9]}" "$work/keyring.deb" | sha256sum --check --status
dpkg-deb -x "$work/keyring.deb" "$work/keyring"
packages=systemd-sysv,dbus,ifupdown,openssh-server,iproute2,iputils-ping,procps,ca-certificates,curl,python3,nodejs,npm,git,zfsutils-linux,nfs-kernel-server,targetcli-fb,unzip,nftables
# Archive freshness is intentionally disabled for the immutable snapshot;
# package signatures and HTTPS certificate verification remain mandatory.
# Hook variables are expanded by mmdebstrap, not by this shell.
# shellcheck disable=SC2016
mmdebstrap --mode=root --variant=minbase --architectures="$arch" --components=main,contrib \
 --keyring="$work/keyring/usr/share/keyrings/debian-archive-keyring.gpg" \
 --aptopt='Acquire::Check-Valid-Until "false"' --aptopt='Acquire::Retries "3"' \
 --aptopt='Acquire::Languages "none"' --aptopt='APT::Sandbox::User "root"' \
 --include="$packages" \
 --setup-hook='mkdir -p "$1/etc/ssl/certs"' \
 --setup-hook='copy-in /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/' \
 "$suite" "$rootfs" \
 "deb https://snapshot.debian.org/archive/debian/$snapshot/ $suite main contrib" \
 "deb https://snapshot.debian.org/archive/debian/$snapshot/ $suite-updates main contrib" \
 "deb https://snapshot.debian.org/archive/debian-security/$snapshot/ $suite-security main contrib"
# mmdebstrap blocks package services during installation. No ZFS DKMS/kernel is installed.
git clone --no-checkout https://github.com/democratic-csi/democratic-csi.git "$rootfs/opt/democratic-csi"
git -C "$rootfs/opt/democratic-csi" checkout --detach "$commit"
printf '%s  %s\n' "${config[6]}" "$rootfs/opt/democratic-csi/src/driver/controller-zfs-generic/index.js" | sha256sum --check --status
# mmdebstrap removes its temporary resolver; npm still needs build-time DNS.
rm -f "$rootfs/etc/resolv.conf"
install -m 0644 /etc/resolv.conf "$rootfs/etc/resolv.conf"
# No runner credentials/environment are passed into application installation.
unshare --mount --propagation private "$repo/scripts/install-node-dependencies.sh" "$rootfs"
curl --fail --location --proto '=https' --tlsv1.2 --retry 3 "${config[4]}" -o "$work/gatekeeper.zip"
printf '%s  %s\n' "${config[5]}" "$work/gatekeeper.zip" | sha256sum --check --status
mkdir -p "$rootfs/opt/csi-gatekeeper"
unzip -q "$work/gatekeeper.zip" -d "$work/gatekeeper"
gatekeeperdir=$work/gatekeeper/csi-gatekeeper-${config[7]}-linux-x64
[[ -f $gatekeeperdir/csi-gatekeeper ]] || { echo 'Unexpected gatekeeper archive layout' >&2; exit 1; }
install -m 0755 "$gatekeeperdir/csi-gatekeeper" "$rootfs/opt/csi-gatekeeper/csi-gatekeeper"
mkdir -p "$rootfs/usr/share/doc/csi-gatekeeper"
install -m 0644 "$gatekeeperdir/LICENSE" "$gatekeeperdir/THIRD_PARTY_NOTICES.txt" "$gatekeeperdir/BUILD_INFO.json" "$rootfs/usr/share/doc/csi-gatekeeper/"
printf '%s  %s\n' "${config[6]}" "$rootfs/opt/democratic-csi/src/driver/controller-zfs-generic/index.js" | sha256sum --check --status
python3 "$repo/scripts/finalize.py" "$rootfs" "$version" "$repo/build-config.json"
chroot "$rootfs" /usr/bin/node --check /opt/democratic-csi/src/driver/controller-zfs-generic/index.js
# dpkg-query expands its own format fields.
# shellcheck disable=SC2016
chroot "$rootfs" /usr/bin/dpkg-query -W '-f=${binary:Package}\t${Version}\n' > "$out/packages.tsv"
python3 "$repo/scripts/verify.py" --rootfs "$rootfs"
name="debian-13-csi-storage-${arch}_${version}.tar.zst"
# Preserve every uid/gid, xattr, ACL and Debian merged-/usr symlink.
tar --numeric-owner --xattrs --acls --sort=name -C "$rootfs" -cf - . | zstd -T0 -10 -o "$out/$name"
cp "$rootfs/usr/share/csi-storage/template.json" "$out/template.json"
python3 "$repo/scripts/verify.py" --archive "$out/$name"
(cd "$out" && sha256sum "$name" template.json packages.tsv > SHA256SUMS)
echo "Template verified: $name"
