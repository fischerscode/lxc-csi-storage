# Local validation record

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
