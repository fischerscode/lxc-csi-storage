# Alpine migration assessment

Reviewed on 2026-10-16 against lxc-wireguard v0.1.0, commit
`d428b3e3799c931c7d6b468c4da89bd95bb5a7da`.

## Decision

Retain Debian 13 for this template until a supported gatekeeper runtime for
Alpine is available and the storage stack has passed acceptance. A smaller base alone is
insufficient evidence for the storage template's complete runtime.

The pinned [csi-gatekeeper v0.1.1 release documentation](https://github.com/fischerscode/csi-gatekeeper/blob/v0.1.1/docs/releases.md)
supports Linux x64/glibc built on Ubuntu 24.04. Inspection of the downloaded ZIP,
after matching its existing pinned SHA-256
`e65398b435b94a93bb73733b97672a52451e66d0aa9a28d37be44d399cf5e838`, confirms:

```text
readelf -lW csi-gatekeeper
  Requesting program interpreter: /lib64/ld-linux-x86-64.so.2
readelf -dW csi-gatekeeper
  NEEDED: libdl.so.2, libpthread.so.0, libm.so.6, libc.so.6,
          ld-linux-x86-64.so.2
```

[Alpine uses musl](https://wiki.alpinelinux.org/wiki/Running_glibc_programs).
The existing artifact therefore requires additional compatibility work on Alpine.
No gcompat compatibility test or native musl build was established in this review.
Do not replace glibc with a loader symlink or assume a compatibility package proves
TLS, signals and Dart runtime behavior. This does not assert that porting is
impossible; it identifies why an unconditional switch is premature.

## Adopted build changes

Following [lxc-wireguard's build](https://github.com/fischerscode/lxc-wireguard/blob/v0.1.0/scripts/build.sh):

- Verify a pinned backend source archive, avoiding a full Git clone in the guest.
- Keep build provenance beside and inside the image; checksum the release asset.
- Normalize tar timestamps and ordering and use single-threaded compression.
- Execute the actual packaged applications during the build and keep archive
  checks separate from live guest acceptance.

The Debian-specific signed snapshot bootstrap and service masks remain in place.
Git and unzip are no longer installed in the guest; npm and unused dependencies
are removed after installation. Node.js and all explicit runtime package roots
are retained. Backend consumers must use its Node.js entry point directly.

## Conditions for a future switch

1. Pin a supported gatekeeper Alpine artifact with its matching legal notices,
   or explicitly validate a reviewed compatibility runtime, including mTLS and
   shutdown behavior. Keep upstream build tooling outside the guest.
2. Lock and verify the complete Alpine APK dependency closure for this storage
   image, including community packages. WireGuard's package lock is insufficient.
3. Port the systemd consumer contract to OpenRC, preserve disabled global
   ZFS/NFS/LIO activation, and verify unique SSH host keys on first boot.
4. Validate ZFS userspace against the actual Proxmox host module, targetcli/LIO
   recovery, NFS exports, gatekeeper and CSI/PVC operations on bounded live targets.
5. Measure archive size, installed disk use and idle/working memory under the same
   workload. No resource saving measurements are claimed by this assessment.
