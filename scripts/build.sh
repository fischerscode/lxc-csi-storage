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
for tool in mmdebstrap dpkg-deb curl sha256sum unzip zstd python3 git chroot tar unshare; do
 command -v "$tool" >/dev/null
done
export LC_ALL=C TZ=UTC
export SOURCE_DATE_EPOCH
SOURCE_DATE_EPOCH=$(git -C "$repo" log -1 --format=%ct)
mkdir -p -- "$(dirname -- "$out")"
mkdir -m 0700 -- "$out"
work=$(mktemp -d "$out/.work.XXXXXXXX")
trap 'status=$?; if (( status == 0 )); then rm -rf -- "$work"; else echo "Failed build retained at $work" >&2; fi' EXIT
rootfs=$work/rootfs
python3 "$repo/scripts/build_info.py" "$version" > "$out/build-info.json"
readarray -t config < <(python3 - "$repo/build-config.json" <<'PY'
import json,sys
c=json.load(open(sys.argv[1]))
for key in ['debian_suite','debian_snapshot','architecture','democratic_csi_commit','gatekeeper_url','gatekeeper_sha256','democratic_csi_driver_sha256','gatekeeper_version','debian_keyring_url','debian_keyring_sha256','democratic_csi_source_sha256']:
 print(c[key])
PY
)
suite=${config[0]}; snapshot=${config[1]}; arch=${config[2]}; commit=${config[3]}
curl --fail --location --proto '=https' --tlsv1.2 --retry 3 "${config[8]}" -o "$work/keyring.deb"
printf '%s  %s\n' "${config[9]}" "$work/keyring.deb" | sha256sum --check --status
dpkg-deb -x "$work/keyring.deb" "$work/keyring"
runtime_packages=systemd-sysv,dbus,ifupdown,openssh-server,iproute2,iputils-ping,procps,ca-certificates,curl,python3,nodejs,zfsutils-linux,nfs-kernel-server,targetcli-fb,nftables
# Archive freshness is intentionally disabled for the immutable snapshot;
# package signatures and HTTPS certificate verification remain mandatory.
# Hook variables are expanded by mmdebstrap, not by this shell.
# shellcheck disable=SC2016
mmdebstrap --mode=root --variant=minbase --architectures="$arch" --components=main,contrib \
 --keyring="$work/keyring/usr/share/keyrings/debian-archive-keyring.gpg" \
 --aptopt='Acquire::Check-Valid-Until "false"' --aptopt='Acquire::Retries "3"' \
 --aptopt='Acquire::Languages "none"' --aptopt='APT::Sandbox::User "root"' \
 --include="$runtime_packages,npm" \
 --setup-hook='mkdir -p "$1/etc/ssl/certs"' \
 --setup-hook='copy-in /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/' \
 "$suite" "$rootfs" \
 "deb https://snapshot.debian.org/archive/debian/$snapshot/ $suite main contrib" \
 "deb https://snapshot.debian.org/archive/debian/$snapshot/ $suite-updates main contrib" \
 "deb https://snapshot.debian.org/archive/debian-security/$snapshot/ $suite-security main contrib"
# mmdebstrap blocks package services during installation. No ZFS DKMS/kernel is installed.
curl --fail --location --proto '=https' --tlsv1.2 --retry 3 \
 "https://codeload.github.com/democratic-csi/democratic-csi/tar.gz/$commit" -o "$work/democratic-csi.tar.gz"
printf '%s  %s\n' "${config[10]}" "$work/democratic-csi.tar.gz" | sha256sum --check --status
mkdir -p "$rootfs/opt/democratic-csi"
tar --extract --gzip --file="$work/democratic-csi.tar.gz" --strip-components=1 \
 --no-same-owner -C "$rootfs/opt/democratic-csi"
printf '%s  %s\n' "${config[6]}" "$rootfs/opt/democratic-csi/src/driver/controller-zfs-generic/index.js" | sha256sum --check --status
# mmdebstrap removes its temporary resolver; npm still needs build-time DNS.
rm -f "$rootfs/etc/resolv.conf"
install -m 0644 /etc/resolv.conf "$rootfs/etc/resolv.conf"
# No runner credentials/environment are passed into application installation.
unshare --mount --propagation private "$repo/scripts/install-node-dependencies.sh" "$rootfs"
# Keep runtime roots before removing npm and its otherwise unused dependency tree.
IFS=, read -r -a runtime_roots <<< "$runtime_packages"
chroot "$rootfs" apt-mark manual "${runtime_roots[@]}"
chroot "$rootfs" /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin DEBIAN_FRONTEND=noninteractive \
 apt-get purge -y --auto-remove npm
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
chroot "$rootfs" /usr/bin/node -e 'require("/opt/democratic-csi/src/driver/controller-zfs-generic")'
# No configuration argument: the real ELF/runtime must reach its usage branch.
set +e
chroot "$rootfs" /opt/csi-gatekeeper/csi-gatekeeper > "$work/gatekeeper-usage.txt" 2>&1
gatekeeper_status=$?
set -e
if [[ $gatekeeper_status != 64 ]] || ! grep -q '^Usage: csi-gatekeeper ' "$work/gatekeeper-usage.txt"; then
 cat "$work/gatekeeper-usage.txt" >&2; echo 'Gatekeeper runtime smoke check failed' >&2; exit 1;
fi
install -m 0644 "$out/build-info.json" "$rootfs/usr/share/csi-storage/build-info.json"
# dpkg-query expands its own format fields.
# shellcheck disable=SC2016
chroot "$rootfs" /usr/bin/dpkg-query -W '-f=${binary:Package}\t${Version}\n' > "$out/packages.tsv"
python3 "$repo/scripts/verify.py" --rootfs "$rootfs"
name="debian-13-csi-storage-${arch}_${version}.tar.zst"
# Preserve owners, xattrs, ACLs and symlinks; normalize archive metadata like lxc-wireguard.
tar --numeric-owner --xattrs --acls --sort=name --mtime="@$SOURCE_DATE_EPOCH" \
 --pax-option=delete=atime,delete=ctime -C "$rootfs" -cf - . | zstd -T1 -10 -o "$out/$name"
cp "$rootfs/usr/share/csi-storage/template.json" "$out/template.json"
python3 "$repo/scripts/verify.py" --archive "$out/$name"
(cd "$out" && sha256sum "$name" template.json packages.tsv build-info.json > SHA256SUMS)
echo "Template verified: $name"
