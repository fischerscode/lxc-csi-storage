# Atlas storage LXC template

Public, unconfigured Debian 13 (amd64) rootfs for a dedicated trusted Atlas
storage container. Each customer/cluster receives an independent instance.
Builds never export a running container or read an Atlas checkout/runtime.

The image contains SSH, systemd/ifupdown, NFS tools, ZFS userspace tools,
targetcli/LIO tools, the pinned democratic-csi upstream source and production
npm dependencies, and the pinned csi-gatekeeper binary. It has no customer
configuration, operational CA/client/server keys, authorized SSH keys, dataset bindings,
exports, targets or storage manifests. It does not contain a second ZFS kernel
or pool, and does not install ZFS DKMS.

## Build and releases

`build-config.json` pins a signed Debian snapshot, backend commit/source digest
and gatekeeper release/archive digest. The bootstrap archive keyring is also
HTTPS-downloaded and hash-pinned, independently of the Ubuntu runner keyring. Dependency installation uses `npm ci`
and the upstream lockfile. Release assets include package versions. This is a
repeatable pinned-input build, not a claim of bit-identical output: npm scripts,
Git metadata, package-generated timestamps and archive metadata can vary.

Use release tags `vMAJOR.MINOR.PATCH` (an optional prerelease suffix is allowed).
Publishing a GitHub Release triggers a build of that release's tag. The build
job has read-only repository permissions, checks scripts/tests, creates the
rootfs and verifies it before packing and again after packing. A separate job
with release-write permission attaches:

- `debian-13-atlas-storage-amd64_<version>.tar.zst`
- `template.json` (the public configuration contract)
- `packages.tsv` (the actual installed package versions)
- `SHA256SUMS`

PR/main/manual builds produce temporary Actions artifacts only. A failed build
uploads no release files. Uploads do not overwrite existing assets; delete an
explicitly reviewed failed release's assets before deliberately rebuilding it.
Actions are pinned to full commit IDs. GitHub's default workflow token suffices;
no Proxmox credentials or customer secrets belong in Actions.

For a local build, use an isolated Linux root builder with `mmdebstrap`,
`debian-archive-keyring`, `zstd`, Python 3, Git and curl installed:

```sh
shellcheck scripts/build.sh
python3 -B -m unittest discover -s tests
sudo scripts/build.sh v0.1.0-dev /absolute/external/new-output-directory
python3 scripts/verify.py --archive /absolute/external/new-output-directory/debian-13-atlas-storage-amd64_v0.1.0-dev.tar.zst
```

The output directory must be new and outside the checkout. A failed build keeps
its hidden work directory there for diagnosis; do not publish that directory.
The snapshot build disables archive freshness checks while retaining signature
and HTTPS validation. The resulting guest uses normal current signed Debian
repositories and normal expiry checking for subsequent operator updates.

## Instance configuration contract: v1

`/usr/share/atlas-storage/template.json` identifies the image version, application
pins and required host bindings. The backend source is upstream, without Atlas
portal/persistence overlays; the Atlas installer applies and verifies its own
reviewed overlays. There are no imports of private Atlas code in this repository.

Atlas creates the LXC, injects the operator public key and instance network
configuration, then provides configuration over operator SSH. Cluster clients
never receive that SSH access. Atlas supplies the privileged LXC device/mount
permissions, owning dataset mount, `/dev/zfs`, owning ZVOL access, LIO target
configfs and the common host-backed persistence lock. The host owns discovery
authentication. Exact per-customer TLS, CHAP, paths, exports, quotas and policies
are configured by Atlas after creation; they are not baked into this image.

The empty machine-id is populated on boot. A service required before SSH generates
fresh instance host keys. Password/interactive login is disabled. Global ZFS,
NFS and LIO package activation is masked; Atlas must enable only its reviewed
scoped recovery/services after checking host bindings. Do not unmask Debian's
whole-tree LIO save/restore service. Merely booting the image must not activate
storage exports or targets. Forwarding is disabled for both address families.

The privileged LXC and its Atlas configuration are trusted. This template does
not create a security boundary against a compromised container-root process.
Customer isolation is provided by the gatekeeper, network rules, NFS exports and
iSCSI authentication configured outside the image.

## Acceptance

Unused upstream SSH test fixtures are removed. The signed Debian GnuTLS library
contains embedded public self-test key vectors; the scanner permits only that
reviewed ELF path with its exact pinned SHA-256. It rejects other key material
and does not exempt arbitrary binaries. Those public vectors authenticate no
Atlas customer.

Archive verification checks identity/configuration leaks and activation masks.
It does not prove Proxmox boot, SSH uniqueness, provider integration, CSI/PVC
functionality, snapshots or recovery. Those require a separate bounded live
acceptance batch on a real host. Record actual build/live results separately.
