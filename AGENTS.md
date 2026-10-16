# Repository instructions

This repository is public. Use English for repository content and commit messages.
Never include customer configuration, credentials, SSH keys, storage manifests,
Consumer runtime data or private repository content in source or release assets.
Build from a clean, authenticated Alpine rootfs; never export a running storage container.
Keep the build and template contract independent of any consumer implementation files.
The image contains upstream applications; Consumers supply their reviewed overlays,
per-customer configuration and host bindings after instantiation.
Use the existing checkout. Do not create worktrees or delegate without a request.
Run focused local checks and commit coherent changes. Do not push or publish
without explicit owner authorization. Record local archive checks separately
from real Proxmox guest boot/CSI acceptance. A maintenance window alone does not
approve arbitrary host changes; live batches need concrete targets and bounds.
