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
for tool in curl gpg gpgv sha256sum unzip zstd python3 git chroot tar unshare; do
 command -v "$tool" >/dev/null
done
export LC_ALL=C TZ=UTC SOURCE_DATE_EPOCH
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
for key in ['alpine_branch','alpine_version','alpine_architecture','alpine_mirror',
            'alpine_minirootfs_sha256','alpine_release_key_fingerprint',
            'democratic_csi_commit','democratic_csi_source_sha256',
            'democratic_csi_driver_sha256','gatekeeper_url','gatekeeper_sha256','gatekeeper_version']:
 print(c[key])
print(' '.join(c['runtime_packages']))
print(' '.join(c['build_packages']))
PY
)
branch=${config[0]}; alpine_version=${config[1]}; arch=${config[2]}; mirror=${config[3]}
download() { curl --fail --location --proto '=https' --tlsv1.2 --retry 3 --connect-timeout 20 --max-time 300 "$1" -o "$2"; }
base="$mirror/$branch/releases/$arch/alpine-minirootfs-$alpine_version-$arch.tar.gz"
download "$base" "$work/base.tar.gz"
download "$base.asc" "$work/base.tar.gz.asc"
printf '%s  %s\n' "${config[4]}" "$work/base.tar.gz" | sha256sum --check --status
mkdir -m 0700 "$work/gnupg"
export GNUPGHOME=$work/gnupg
fingerprint=$(gpg --batch --show-keys --with-colons "$repo/keys/alpine-release.asc" | awk -F: '$1 == "fpr" { print $10; exit }')
[[ $fingerprint == "${config[5]}" ]]
gpg --batch --dearmor -o "$work/release-key.gpg" "$repo/keys/alpine-release.asc"
gpgv --keyring "$work/release-key.gpg" "$work/base.tar.gz.asc" "$work/base.tar.gz"
mkdir "$rootfs"
tar --numeric-owner -xzf "$work/base.tar.gz" -C "$rootfs"
# Validate the entire lock before downloading; never silently resolve newer APKs.
python3 "$repo/scripts/package_lock.py" > "$work/locked.tsv"
while read -r checksum relative _role; do
 mkdir -p "$rootfs/packages/$(dirname "$relative")"
 download "$mirror/$branch/${relative%%/*}/$arch/${relative#*/}" "$rootfs/packages/$relative"
 printf '%s  %s\n' "$checksum" "$rootfs/packages/$relative" | sha256sum --check --status
done < "$work/locked.tsv"
# APK verifies signatures using keys from the authenticated base and installs offline.
chroot "$rootfs" /bin/sh -ec 'apk verify /packages/*/*.apk; apk --cache-dir /packages --no-network add /packages/*/*.apk'
printf '%s\n' "$mirror/$branch/main" "$mirror/$branch/community" > "$rootfs/etc/apk/repositories"
read -r -a runtime_roots <<< "${config[12]}"
read -r -a build_roots <<< "${config[13]}"
# Local file installs pin world to checksums. Keep only upgradeable explicit roots.
printf '%s\n' "${runtime_roots[@]}" "${build_roots[@]}" > "$rootfs/etc/apk/world"
download "https://codeload.github.com/democratic-csi/democratic-csi/tar.gz/${config[6]}" "$work/democratic-csi.tar.gz"
printf '%s  %s\n' "${config[7]}" "$work/democratic-csi.tar.gz" | sha256sum --check --status
mkdir -p "$rootfs/opt/democratic-csi"
tar -xzf "$work/democratic-csi.tar.gz" --strip-components=1 --no-same-owner -C "$rootfs/opt/democratic-csi"
printf '%s  %s\n' "${config[8]}" "$rootfs/opt/democratic-csi/src/driver/controller-zfs-generic/index.js" | sha256sum --check --status
rm -f "$rootfs/etc/resolv.conf"
install -m 0644 /etc/resolv.conf "$rootfs/etc/resolv.conf"
download "${config[9]}" "$work/gatekeeper.zip"
printf '%s  %s\n' "${config[10]}" "$work/gatekeeper.zip" | sha256sum --check --status
unzip -q "$work/gatekeeper.zip" -d "$work/gatekeeper"
gatekeeperdir=$work/gatekeeper/csi-gatekeeper-${config[11]}-linux-x64
install -D -m 0755 "$gatekeeperdir/csi-gatekeeper" "$rootfs/opt/csi-gatekeeper/csi-gatekeeper"
mkdir -p "$rootfs/usr/share/doc/csi-gatekeeper"
install -m 0644 "$gatekeeperdir/LICENSE" "$gatekeeperdir/THIRD_PARTY_NOTICES.txt" "$gatekeeperdir/BUILD_INFO.json" "$rootfs/usr/share/doc/csi-gatekeeper/"
install -m 0644 "$repo/scripts/check-gatekeeper-runtime.py" "$rootfs/tmp/check-gatekeeper-runtime.py"
# Mounts and test sockets exist only inside this disposable build namespace.
unshare --mount --propagation private "$repo/scripts/install-node-dependencies.sh" "$rootfs"
chroot "$rootfs" apk --cache-dir /packages --no-network del "${build_roots[@]}"
rm -rf "$rootfs/packages"
printf '%s  %s\n' "${config[8]}" "$rootfs/opt/democratic-csi/src/driver/controller-zfs-generic/index.js" | sha256sum --check --status
python3 "$repo/scripts/finalize.py" "$rootfs" "$version" "$repo/build-config.json"
python3 "$repo/scripts/application_permissions.py" "$rootfs"
# Check that cleanup did not remove required dependencies; no test identities are created.
unshare --mount --propagation private "$repo/scripts/check-final-runtime.sh" "$rootfs"
install -m 0644 "$out/build-info.json" "$rootfs/usr/share/csi-storage/build-info.json"
python3 "$repo/scripts/package_lock.py" --installed "$rootfs/lib/apk/db/installed" > "$out/packages.tsv"
python3 "$repo/scripts/verify.py" --rootfs "$rootfs"
name="alpine-$alpine_version-csi-storage-${arch}_${version}.tar.zst"
tar --numeric-owner --xattrs --acls --sort=name --mtime="@$SOURCE_DATE_EPOCH" \
 --pax-option=delete=atime,delete=ctime -C "$rootfs" -cf - . | zstd -T1 -10 -o "$out/$name"
cp "$rootfs/usr/share/csi-storage/template.json" "$out/template.json"
python3 "$repo/scripts/verify.py" --archive "$out/$name"
# Exercise the final artifact as a root restore, retaining the header modes
# despite the builder's umask. A default unprivileged extraction can hide 0775/
# 0664 source permissions and is not a substitute for the header checks above.
mkdir "$work/archive-check"
tar --zstd --extract --same-owner --same-permissions --numeric-owner \
 --file "$out/$name" --directory "$work/archive-check"
python3 "$repo/scripts/verify.py" --rootfs "$work/archive-check"
(cd "$out" && sha256sum "$name" template.json packages.tsv build-info.json > SHA256SUMS)
echo "Template verified: $name"
