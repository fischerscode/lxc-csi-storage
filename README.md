# CSI storage LXC template

Public, unconfigured Alpine 3.24.2 (x86_64/amd64) rootfs for a dedicated trusted
storage container. Each customer or cluster receives an independent instance.
Builds start from an authenticated minirootfs and never export a running guest
or read a consumer checkout or runtime.

The image contains BusyBox init/OpenRC, ifupdown-ng, SSH, NFS tools, ZFS userspace,
targetcli/LIO tools, pinned democratic-csi source and production npm dependencies,
and the original pinned csi-gatekeeper release with gcompat. No guest kernel or
ZFS kernel module is installed. Consumers provide reviewed overlays, configuration,
keys, datasets, exports, targets and host bindings after instantiation.

## Build and releases

`build-config.json` pins the base archive and signing-key fingerprint, application
sources and release digests. `packages.lock` pins the complete Alpine main/community
APK dependency closure by version and SHA-256, with separate runtime/build roles.
The base signature is checked against the committed public release key. APK
signatures are checked with the keys from that authenticated base; installation
is offline, with no untrusted or force flags. Removed upstream APK versions cause
a build failure, rather than a silent dependency update.

The backend source archive contains no Git history. `npm ci --omit=dev` uses its
upstream lockfile. npm, openssl and the HTTP/2 probe dependencies are build-only
and removed before packing. Consumers launch the backend directly with Node.js,
rather than `npm start`. Runtime repositories and APK world permit normal signed
updates on the pinned stable Alpine branch; update validation is the operator's
responsibility.

Release tags use `vMAJOR.MINOR.PATCH`, optionally with a prerelease suffix.
Publishing a GitHub Release triggers a build of that release tag. Read-only build
jobs run local checks, build the rootfs, test the real applications and verify the
rootfs and final archive. A separate release-write job attaches:

- `alpine-3.24.2-csi-storage-x86_64_<version>.tar.zst`
- `template.json` (configuration contract)
- `packages.tsv` (final installed package versions)
- `build-info.json` (also installed in `/usr/share/csi-storage/`)
- `SHA256SUMS`

PR/main/manual builds produce temporary Actions artifacts only. Failed builds
upload no release files. Existing release assets are never overwritten. Actions
are pinned to full commits. No Proxmox credentials or consumer secrets belong in
Actions. Build provenance records the source commit, dirty state, input hashes,
pins and tool versions. Tar ordering and timestamps are normalized to the source
commit timestamp and zstd uses one thread. Package-generated file contents and
npm scripts can still vary; bit-identical output is not promised.

Before packing, both `/opt` application trees (including production npm
dependencies) and the gatekeeper notices are normalized to root ownership with
group/other write bits removed. Executable bits and symlinks are preserved.
Rootfs and final tar-header checks enforce ownership/modes independently of
extraction umask, including the backend driver's complete ancestor chain.

On a disposable x86_64 Linux root builder, install curl, CA certificates, GnuPG,
zstd, Python 3, Git, unzip, util-linux and ShellCheck, then run:

```sh
bash -n scripts/*.sh
shellcheck scripts/*.sh
python3 -B -m unittest discover -s tests -v
sudo scripts/build.sh v0.1.0-dev /absolute/external/new-output-directory
python3 -B scripts/verify.py --archive /absolute/external/new-output-directory/alpine-3.24.2-csi-storage-x86_64_v0.1.0-dev.tar.zst
```

The output directory must be new and outside the checkout. Failed builds retain
a hidden work directory for diagnosis; never publish that directory. The builder
needs root, private mount namespaces, loopback/Unix sockets and network access.
No service is started against host storage. Temporary test credentials, sockets,
resolver configuration, APK downloads, host keys and caches are removed.

To update packages, resolve runtime roots and runtime plus build roots from
`build-config.json` separately in a fresh authenticated Alpine rootfs using
`apk fetch --no-cache --recursive --url`. Download the complete sets, verify APK
signatures, record SHA-256 and `main/filename.apk` or `community/filename.apk`,
and label the runtime closure `runtime` and the remaining closure `build`.
Review the lock diff and run a complete clean build; never reuse WireGuard's
smaller package lock for storage.

## Instance configuration contract: v2

`/usr/share/csi-storage/template.json` identifies the Alpine/OpenRC image, application
pins and required host bindings. The outer architecture remains `amd64`; Alpine's
package and asset architecture is `x86_64`. This is an explicit breaking change
from the Debian/systemd v1 contract. Consumers must support Alpine networking,
OpenRC services and the new asset name, or reject the image before instantiation.
Do not apply a Debian/systemd installer to this rootfs.

The consumer creates the LXC and injects an operator public key and network
configuration, then configures the instance over operator SSH. Cluster clients
never receive that SSH access. Consumer installers apply and verify their own
reviewed backend overlays; this image imports no consumer implementation files.
Alpine's root `*` password marker permits public-key authentication without a
usable password. Password and interactive authentication are disabled.

Packaged OpenRC sshd generates missing host keys before starting. No host keys
or machine-id are shipped; OpenRC generates the machine-id at boot. Only basic
networking, identity, SSH, logging and shutdown services are enabled. OpenRC runs
in LXC mode; BusyBox init retains the boot/shutdown sequence and a container
console. The host must provide `/proc`, `/dev` and `/run`; gcompat's loader uses
`/proc/self/exe`.

Global ZFS/NFS/LIO OpenRC scripts are blocked by `/dev/null` symlinks listed in
`blocked_openrc_services`. No storage service or nftables policy is activated on
boot. Consumers implement only reviewed scoped services after checking bindings;
never restore targetcli's whole-tree save/restore script. APK maintenance can
restore packaged scripts, so consumers must recheck the block/runlevel policy
before restarting services after updates. IPv4 and IPv6 forwarding are disabled.

Consumers supply privileged LXC device/mount permissions, the owned dataset,
`/dev/zfs`, owned ZVOL access, LIO target configfs and the common host-backed
persistence lock. The host owns discovery authentication. Per-customer TLS, CHAP,
exports, quotas and policies are configured after creation. Match ZFS userspace
to the real Proxmox host module during acceptance; the guest contains no pool or
second kernel. Container root and consumer configuration are trusted. Isolation
comes from externally configured gatekeeper policy, network rules, NFS exports
and iSCSI authentication.

## Validation and Alpine compatibility

Both gcompat and native musl gatekeeper variants were exercised under Alpine;
see [the assessment](docs/alpine-assessment.md). The shipped image uses the
original upstream release and its complete license notices with locked gcompat.
The native musl SDK is not shipped or downloaded by the production build.

Every build tests the actual gatekeeper executable with temporary mTLS identities
and a fake CSI Unix-socket backend for both NFS and iSCSI profiles: allowed/rejected
clients, leaf pinning, hostname/CA validation, gRPC forwarding, policy denials,
error sanitization, repeated/concurrent calls, restart, SIGTERM/SIGINT and invalid
configuration. After removing build tools it rechecks the backend driver import
and gatekeeper loader. Archive checks reject instance data, private keys, build
residue, active storage, package drift and missing boot/SSH policy. Unused
upstream SSH test fixtures are removed; there are no binary private-key exemptions.

These checks do not prove Proxmox boot, kernel/NFS/LIO integration, CSI/PVC storage
operations, snapshots or recovery. Those require a separate bounded live batch.
[Validation records](docs/validation.md) distinguish local runtime/archive checks
from live guest acceptance. No RAM or performance saving is claimed without a
comparable live workload measurement.
