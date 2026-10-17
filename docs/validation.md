# Local validation record

## 2026-10-16: issue #1 application archive permissions

The public v0.2.0 archive was downloaded and its SHA-256 independently matched
`333903e912d1c15c6518594df01773273ef93dad46b4fd92408df7090db67190`.
Tar headers confirmed the reported `0775` driver directories and `0664` driver
file. An audit found 268 group/other-writable entries in democratic-csi; none
in the gatekeeper binary/notices tree. All inspected application entries were
already root-owned.

The builder now normalizes application ownership and removes group/other write
bits after finalization, before the final runtime smoke check and packing. The
verifier reads numeric ownership and modes from the final compressed archive,
requires the driver and its ancestors with exact `0644`/`0755` modes, and rejects
writable or non-root-owned application entries, including production dependencies
and notices. Symlink modes are exempt because POSIX symlinks conventionally use
`0777`; their ownership is checked without dereferencing them.

Local checks passed: 20 Python tests (including compressed-header mutations for
both write bits and both owner IDs), Bash syntax, ShellCheck and `git diff --check`.
Regression coverage preserves executables, symlink targets and driver contents,
checks hardlink headers and missing ancestors, and explicitly preserves `0775`/
`0664` during GNU tar extraction with `--same-permissions` under umask `022`.
The local builder lacks noninteractive sudo; the complete authenticated root
build and application smoke tests are delegated to the existing CI workflow.

No Proxmox guest boot, CSI/PVC lifecycle, snapshot, reboot or host-storage
acceptance is claimed. Consumers must repeat those checks with the corrected
release. No application/package pins, storage-service blocks or consumer safety
checks were changed.

## 2026-10-16: CI npm residue cleanup

[The first Alpine CI run](https://github.com/fischerscode/lxc-csi-storage/actions/runs/38939996790)
successfully installed the authenticated base/APKs, ran npm installation and both
gatekeeper runtime profiles, pruned to 159 packages and passed the final runtime
smoke check. Rootfs verification then rejected a residual
`usr/lib/node_modules/npm` directory. Finalization now explicitly removes that
build-only tree after APK removal. Regression coverage rejects both empty and
populated residue before cleanup, verifies cleanup and preserves the backend's
production dependencies. Archive policy remains unchanged.

## 2026-10-16: Alpine/gcompat follow-up and migration

Passed local checks:

- Bash syntax, ShellCheck, 15 Python unit/regression tests and `git diff --check`.
- Official Alpine 3.24.2 minirootfs SHA-256 and detached release signature.
- All 167 locked APK hashes and signatures; offline installation and pruning
  result in exactly the locked 159 runtime package versions.
- `npm ci --omit=dev` installed the upstream lockfile (194 packages). The actual
  backend driver imports successfully after build package removal and cleanup.
- Original gatekeeper v0.1.1 with gcompat 1.1.0-r4 passed the external executable
  probe for NFS and iSCSI: 5,600 repeated/concurrent Probe RPCs total, plus mTLS,
  pinning, trust/hostname rejection, Unix backend forwarding, policy and metadata
  checks, sanitized backend errors, restart, SIGTERM/SIGINT and malformed config.
- A native musl executable compiled from the unchanged v0.1.1 source with the
  checksum-verified community musl Dart SDK 3.13.4. It passed the same external
  probe. All 50 upstream tests passed under that SDK after adding zip/unzip.
- Packaged OpenRC `sshd checkconfig` passed twice and generated different
  ed25519 host key fingerprints; the keys were then removed. No sshd was started.
- The post-cleanup runtime check passes with a private proc mount (required by
  the gcompat loader). Final rootfs policy and compressed archive content checks
  pass. The local content-check archive is about 59 MiB, from a 217 MiB tar stream;
  this is not a measured saving relative to a comparable Debian image.

Scope and limits: these experiments used isolated user/mount namespaces and
public inputs in disposable temporary directories. The production builder still
requires real root with full owner/group preservation. Noninteractive sudo is
unavailable here. The single-ID user namespace cannot preserve the base shadow
file's group or two APK owners (`usr/libexec/dbus-daemon-launch-helper` and
`var/lib/nfs/state`). APK installation/pruning reports those ownership errors.
They were not suppressed or accepted by the production build script, which fails
on APK errors. Therefore the local archive validates content and policy only;
it is not a release candidate or proof of a successful complete root build.
CI or a disposable root builder must run `scripts/build.sh` unchanged before
release. No experimental SDK, binary, certificates, rootfs or archive is committed.

Live acceptance: no Proxmox guest boot, host storage access, NFS/LIO integration,
real gatekeeper-to-storage mTLS, CSI/PVC lifecycle, snapshot or recovery test was
performed. No host configuration was changed. These require separately bounded
real targets. No RAM, throughput or comparative resource saving is claimed.

## 2026-10-16: build slimming and Alpine assessment

Local checks passed:

- `bash -n scripts/*.sh`
- `shellcheck scripts/*.sh`
- `python3 -B -m unittest discover -s tests -v` (13 tests)
- `python3 -B scripts/build_info.py v0.1.0-test` produced public provenance
  with a dirty working tree recorded, public input hashes and builder versions.
- `git diff --check`

Downloaded public inputs were checked independently:

- democratic-csi's pinned commit archive matched the new SHA-256 in
  `build-config.json`. The extracted controller driver matched its existing
  pinned SHA-256. The upstream lockfile contains no Git URL dependencies.
- The gatekeeper ZIP matched its existing SHA-256. `readelf` confirmed the
  glibc loader and dependencies documented in the Alpine assessment. The
  executable reached its usage branch with exit 64 on this Ubuntu 26.04 builder.
  This is a builder-runtime check, not a Debian guest check.

Archive checks: tests exercise the verifier against a synthetic compressed
template contract and reject a truncated compressed stream. No full storage
rootfs or release archive was built in this session. The available builder lacks
noninteractive sudo; its unprivileged user namespace cannot create the device
nodes required by the current root build. CI or a disposable root builder must
still run the complete bootstrap, npm installation/removal, application checks,
rootfs verification and final archive verification.

Live acceptance: no Proxmox guest was created or booted. SSH uniqueness, host ZFS
compatibility, NFS/LIO recovery, gatekeeper mTLS and CSI/PVC behavior were not
tested. No host configuration was changed and no resource savings were measured.
