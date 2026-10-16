# Alpine migration assessment

## 2026-10-16 follow-up: compatibility established

The earlier assessment identified glibc dependencies but did not test gcompat or
a musl build. Follow-up experiments establish both paths on Alpine 3.24.2 x86_64.
The repository now builds an Alpine/OpenRC image with the original upstream
Gatekeeper v0.1.1 artifact and pinned gcompat. No gatekeeper source changes or
compatibility patches were required.

## Tested inputs

- Reference: lxc-wireguard v0.1.0, commit
  `d428b3e3799c931c7d6b468c4da89bd95bb5a7da`.
- Alpine minirootfs 3.24.2 SHA-256
  `c5ca053cfe1d85c5b96dff8b9bc57045f7f184a30ffb6b65776409ca90388677`,
  with a valid detached signature by
  `0482D84022F52DF1C4E7CD43293ACD0907D9495A`.
- Original csi-gatekeeper 0.1.1 ZIP SHA-256
  `e65398b435b94a93bb73733b97672a52451e66d0aa9a28d37be44d399cf5e838`.
- gcompat 1.1.0-r4, musl-obstack 1.2.3-r2 and libucontext 1.5.1-r0;
  exact APK hashes and dependency closure are in `packages.lock`.

The original ELF requests `/lib64/ld-linux-x86-64.so.2` and glibc libraries.
gcompat provides that interface. Its loader requires `/proc/self/exe`; a bare
chroot without proc fails with `readlink: No such file or directory`. The build
checks runtime behavior with a private proc mount. A real LXC must mount proc.

## Runtime evidence

`scripts/check-gatekeeper-runtime.py` executes the real binary in Alpine with
short-lived generated certificates and a simulated CSI backend over a Unix
socket. It tests both NFS and iSCSI profiles, with 2,800 repeated/concurrent Probe
RPCs per profile, plus:

- Original no-argument usage exit 64 and malformed configuration exit 1.
- Successful mTLS and identity/version RPCs.
- CA-signed but unpinned client rejected at the RPC boundary.
- Missing/untrusted client certificates, incorrect server hostname and CA rejected.
- Valid controller request forwarding; unsafe IDs and disabled methods rejected
  before reaching the fake backend; client metadata is not forwarded.
- Backend status propagation with sanitized errors.
- Eight concurrent clients, process restart, and clean SIGTERM/SIGINT exit 0.

Both original/glibc+gcompat and native-musl executables passed the same checks.
This supports the tested application paths; it is not a claim of exhaustive
compatibility or indefinite soak testing. The production build repeats the
original binary tests against its locked Alpine packages before packing.

## Native musl build

The community [dart-musl SDK](https://github.com/dart-musl/dart) provides a 3.13.4
release matching the gatekeeper's build SDK. Its x64 SDK archive SHA-256 is
`7afa876f30423a6991539f0b6317963ca5fa430ac215bfeaed27cb4ccb0b7b4d`,
verified against the release metadata. In an Alpine rootfs:

```sh
# Public csi-gatekeeper v0.1.1 source, commit c18aac8b74098f36f41c152fbd9fbc2f0e489ed5
/opt/dart-sdk/bin/dart pub get --enforce-lockfile
/opt/dart-sdk/bin/dart compile exe bin/csi_gatekeeper.dart -o /tmp/gatekeeper-musl
/opt/dart-sdk/bin/dart test
```

Compilation succeeded without source changes. `readelf -lW` reports
`/lib/ld-musl-x86_64.so.1`. All 50 upstream tests passed on the musl SDK after
installing its documented zip/unzip build requirements. The standalone musl
executable also passed the external process/mTLS probe.

Dart's [upstream discussion](https://github.com/dart-lang/sdk/issues/61374)
distinguishes official glibc builds from the community musl runtime. We retain
the upstream gatekeeper ZIP and its legal notices instead of introducing a
second SDK/build supply chain into this repository. A future upstream musl
release can replace gcompat after pinning its complete distributable and rerunning
these checks. The experimental musl SDK/binary are not release assets here.

## Remaining acceptance

The migration changes the consumer contract to `csi-storage-template/v2`, with
OpenRC service ownership and Alpine asset names. Before deployment, run a bounded
Proxmox boot/SSH test, match ZFS userspace to the host module, validate NFS/LIO
recovery, gatekeeper mTLS and real CSI/PVC operations. Measure disk/RAM under a
comparable workload. None of those live checks is replaced by this assessment.
