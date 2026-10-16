# CSI storage LXC template

Public, unconfigured Debian 13 (amd64) rootfs for a dedicated trusted
storage container. Each customer or cluster receives an independent instance.
Builds never export a running container or read a control-plane checkout or runtime.

The image contains SSH, systemd/ifupdown, NFS tools, ZFS userspace tools,
targetcli/LIO tools, the pinned democratic-csi upstream source and production
npm dependencies, and the pinned csi-gatekeeper binary. It has no customer
configuration, operational CA/client/server keys, authorized SSH keys, dataset bindings,
exports, targets or storage manifests. It does not contain a second ZFS kernel
or pool, and does not install ZFS DKMS.

## Build and releases

`build-config.json` pins a signed Debian snapshot, backend commit/source digest
and gatekeeper release/archive digest. The bootstrap archive keyring is also
HTTPS-downloaded and hash-pinned, independently of the Ubuntu runner keyring.
The backend is downloaded as a checksum-pinned upstream source archive; no Git
history or Git executable is installed in the image. Dependency installation uses
`npm ci` and the upstream lockfile. npm and its unused package dependencies are
removed before verification and packing. Consumers launch the backend directly
with Node.js, rather than `npm start`.

Release assets include final package versions and public build provenance
(source commit, clean/dirty state, build input hashes, pins and builder versions).
Archive ordering and timestamps are normalized to the source commit timestamp;
single-threaded zstd bounds compression concurrency. This is a repeatable
pinned-input build, not a claim of bit-identical output: npm scripts and
package-generated file contents can vary.

Use release tags `vMAJOR.MINOR.PATCH` (an optional prerelease suffix is allowed).
Publishing a GitHub Release triggers a build of that release's tag. The build
job has read-only repository permissions, checks scripts/tests, creates the
rootfs and verifies it before packing and again after packing. A separate job
with release-write permission attaches:

- `debian-13-csi-storage-amd64_<version>.tar.zst`
- `template.json` (the public configuration contract)
- `packages.tsv` (the actual installed package versions)
- `build-info.json` (also installed in `/usr/share/csi-storage/`)
- `SHA256SUMS`

PR/main/manual builds produce temporary Actions artifacts only. A failed build
uploads no release files. Uploads do not overwrite existing assets; delete an
explicitly reviewed failed release's assets before deliberately rebuilding it.
Actions are pinned to full commit IDs. GitHub's default workflow token suffices;
no Proxmox credentials or customer secrets belong in Actions.

For a local build, use an isolated Linux root builder with `mmdebstrap`,
`debian-archive-keyring`, `zstd`, Python 3, Git, curl, unzip, util-linux
and ShellCheck installed:

```sh
bash -n scripts/*.sh
shellcheck scripts/*.sh
python3 -B -m unittest discover -s tests
sudo scripts/build.sh v0.1.0-dev /absolute/external/new-output-directory
python3 scripts/verify.py --archive /absolute/external/new-output-directory/debian-13-csi-storage-amd64_v0.1.0-dev.tar.zst
```

The output directory must be new and outside the checkout. A failed build keeps
its hidden work directory there for diagnosis; do not publish that directory.
The snapshot build disables archive freshness checks while retaining signature
and HTTPS validation. The resulting guest uses normal current signed Debian
repositories and normal expiry checking for subsequent operator updates.

## Instance configuration contract: v1

`/usr/share/csi-storage/template.json` identifies the image version, application
pins and required host bindings. The backend source is upstream, without consumer
portal/persistence overlays. A consumer installer applies and verifies its own
reviewed overlays. This repository imports no control-plane implementation.

The consumer creates the LXC, injects the operator public key and instance network
configuration, then provides configuration over operator SSH. Cluster clients
never receive that SSH access. The consumer supplies the privileged LXC device/mount
permissions, owning dataset mount, `/dev/zfs`, owning ZVOL access, LIO target
configfs and the common host-backed persistence lock. The host owns discovery
authentication. Exact per-customer TLS, CHAP, paths, exports, quotas and policies
are configured by the consumer after creation; they are not baked into this image.

The empty machine-id is populated on boot. A service required before SSH generates
fresh instance host keys. Password/interactive login is disabled. Global ZFS,
NFS and LIO package activation is masked; The consumer must enable only its reviewed
scoped recovery/services after checking host bindings. Do not unmask Debian's
whole-tree LIO save/restore service. Merely booting the image must not activate
storage exports or targets. Forwarding is disabled for both address families.

The privileged LXC and its consumer configuration are trusted. This template does
not create a security boundary against a compromised container-root process.
Customer isolation is provided by the gatekeeper, network rules, NFS exports and
iSCSI authentication configured outside the image.

## Acceptance

Unused upstream SSH test fixtures are removed. The signed Debian GnuTLS library
contains embedded public self-test key vectors; the scanner permits only that
reviewed ELF path with its exact pinned SHA-256. It rejects other key material
and does not exempt arbitrary binaries. Those public vectors authenticate no
consumer.

Archive verification checks identity/configuration leaks and activation masks.
The build also imports the actual backend driver after npm removal and executes
the gatekeeper's no-argument usage branch inside the rootfs (expected exit 64).
This catches missing dynamic loaders, libraries and application dependencies
without configuring or activating storage. Archive checks require matching build
provenance and reject shipped Git/npm build tools.
It does not prove Proxmox boot, SSH uniqueness, provider integration, CSI/PVC
functionality, snapshots or recovery. Those require a separate bounded live
acceptance batch on a real host. Record actual build/live results separately.

## Alpine migration assessment

The Alpine/OpenRC build in [lxc-wireguard v0.1.0](https://github.com/fischerscode/lxc-wireguard/tree/v0.1.0)
is a useful reference for verified inputs, build provenance and normalized archive
metadata. This image retains Debian because its pinned gatekeeper v0.1.1 is a
glibc executable. See [the migration assessment](docs/alpine-assessment.md) for
the binary evidence and prerequisites. Lower disk usage from removing build
tools does not establish lower guest RAM usage; measure that in live acceptance.
