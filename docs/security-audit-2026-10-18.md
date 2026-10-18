# Security audit: 2026-10-18

## Assessment and scope

Audited source revision: `4a947e2` (existing checkout). This is a source and
local policy-verifier audit, not a certification of a released image or a live
Proxmox installation. No confirmed critical vulnerability or existing compromise
was established. One high-impact build trust-boundary weakness and four medium
policy/verification weaknesses were identified. The severity describes potential
impact under the stated prerequisites, not proof of present exploitability.

Reviewed all tracked build scripts, configuration, package lock, workflow,
application runtime probe, tests and deployment documentation. Executed the
existing local checks and synthetic mutations through both the verifier function
and the compressed archive CLI. No synthetic executable, boot command or archive
was executed/restored. No customer data, host storage or running guest was used.
The synthetic fixture is deliberately minimal; its successful baseline is not
evidence that the real application distribution is safe or unsafe.

The security boundaries are upstream inputs to the builder, builder output to
release consumers, and the privileged guest to host storage. The repository
explicitly trusts container root and consumer configuration. None of the verifier
findings demonstrates an unauthenticated network attack against the default
template. Input hashes prevent an ordinary mirror attacker from silently
substituting pinned files. A compromised pinned dependency, unsafe pin update,
build-time mutation or artifact supplied without independent authentication is
the relevant prerequisite for the artifact findings.

## F01 — High: build code has builder-root authority

Evidence: `scripts/install-node-dependencies.sh:5-16`,
`scripts/check-final-runtime.sh:5-11`, `scripts/build.sh:79-86`.

The builder bind-mounts its existing `/proc` into a root chroot and creates only
a private mount namespace. It does not isolate the PID/user/network namespaces
or drop root capabilities. npm installation does not explicitly disable lifecycle
scripts. The final check also imports the complete backend module as root.
Consequently upstream application/dependency code runs with builder-root
authority. A private mount namespace prevents mount propagation; it does not
make this code a sandboxed tenant. Access through another visible process's
`/proc/<pid>/root` is one possible path outside the chroot, subject to procfs and
ptrace restrictions; root capabilities provide additional escape mechanisms.
Clearing environment variables does not remove this filesystem/process access.

Prerequisite: malicious code must be present in an accepted pinned input or
be introduced during a reviewed input update. Hashes authenticate bytes, not
behavior. This finding does not assert that any current dependency is malicious
or that a lifecycle hook in the exact pinned npm version was observed running.
Even disabling every installation hook would leave the explicit Node import.

Impact: compromise of the builder, its accessible files/processes and generated
assets. The documented disposable builder and GitHub-hosted runner reduce the
persistence risk; the separate release-write job limits direct token exposure.
Neither prevents malicious artifacts from being produced by a compromised build.
No privileged escape was attempted during this audit.

Recommendation: enforce a disposable VM boundary with no host storage,
credentials or private checkouts. Run dependency installation and application
probes without host-root privileges; explicitly disable install scripts and
allow only reviewed required steps. If using namespaces, use a separately
reviewed user/PID/mount setup with a fresh procfs, capability restrictions and
bounded network access. Do not treat additional namespace flags alone as a
complete fix. Validate isolation with harmless sentinel access tests on a
disposable builder, separately from application tests.

References: Linux documents the limitations of
[chroot](https://www.man7.org/linux/man-pages/man2/chroot.2.html);
npm documents [lifecycle scripts](https://docs.npmjs.com/cli/v11/using-npm/scripts/)
and [ignore-scripts](https://docs.npmjs.com/cli/v11/commands/npm-ci/).

## F02 — Medium: the verifier does not establish effective SSH policy

Evidence: `scripts/verify.py:99-114,131-135`,
`scripts/install-node-dependencies.sh:19`, `scripts/build.sh:83-86`.

The verifier requires the template drop-in's exact contents, but only searches
for the Include substring in the main configuration. Both a commented Include
and a lexically earlier `00-override.conf` enabling password/interactive login
and root login pass. OpenSSH generally uses the first obtained value, so the
later template drop-in does not enforce the desired settings in that case.
The build's `sshd -t` checks syntax before finalization; it does not assert
effective values after the final configuration has been installed.

Impact: an altered or regressed image can be labeled clean without the promised
authentication policy. The current root `*` password marker still prevents
ordinary password login; acceptance of these mutations alone is not proof of a
working password-login exploit. Password provisioning or other subsequent
configuration can make the discrepancy consequential.

Recommendation: check `sshd -T` after finalization with temporary host keys,
assert the required authentication values, and use representative `-C`
connection contexts where Match blocks exist. Remove temporary keys afterward.
Require an active Include and reject unreviewed authentication overrides.
Add negative regression tests for both demonstrated configurations.

Reference: [OpenSSH sshd_config](https://man.openbsd.org/sshd_config).

## F03 — Medium: critical system metadata and extra boot execution are unchecked

Evidence: `scripts/application_permissions.py:8-10,51-68`,
`scripts/verify.py:48,125-130`.

Ownership/mode checks cover application trees and selected ancestors, but not
the SSH policy, shadow/passwd, init configuration or their full ancestor chains.
A UID/GID 1000, mode `0666` SSH policy is accepted with its expected contents.
An extra root-owned `04755` file is also accepted. The init checks require
known command substrings but permit additional `::sysinit:` commands.

Impact: the clean-image verdict permits configurations that a non-root guest
process could alter and unexpected privileged startup/persistence mechanisms.
The extra SUID probe uses inert placeholder text, not a working exploit binary.
No additional boot command or privilege-escalation file was found in an actual
release. Some upstream SUID programs are legitimate; removing all special bits
indiscriminately would be inappropriate.

Recommendation: enforce reviewed ownership/modes and real directory ancestors
for security-critical system files, allowlist required SUID/SGID files and
capabilities, and validate init entries semantically against an explicit set.
Inventory extended ACLs and security capability xattrs too: the build preserves
xattrs/ACLs, while the Entry policy currently models only basic owner/mode data.
Acceptance tests must use inert fixtures and reject unintended privilege grants.

## F04 — Medium: link topology is not validated as a filesystem

Evidence: `scripts/verify.py:39-64,137-144`,
`scripts/application_permissions.py:51-68`.

The archive checker validates member names and hardlink target syntax but does
not resolve symlinks or reject a non-directory ancestor with descendants. It
accepts `opt/csi-gatekeeper` as a symlink to `/tmp/replacement` while accepting
headers beneath that path. It also accepts an application symlink whose relative
target leaves the rootfs. Gatekeeper's ancestor lacks the driver's explicit
real-directory requirement. An application package manifest can likewise meet
the presence check without necessarily being a regular file.

Impact: archive policy acceptance does not establish a usable, confined restored
filesystem. A later consumer might encounter redirection or dangling targets.
GNU tar may reject dangerous combinations; these probes do not establish an
overwrite outside its extraction directory. The production build's additional
root restoration/reverification provides defense for some combinations, but the
standalone archive verifier still produces an unjustified clean verdict.

Recommendation: build a normalized member/link graph, reject descendants of
non-directory members, require real application ancestors, and resolve link
chains with cycle and root-boundary checks. Interpret permitted absolute guest
links relative to the guest root; retain legitimate `/dev/null` service blocks
and other reviewed Alpine links. Add restoration tests in a disposable namespace
without ever extracting an adversarial fixture onto the real host filesystem.

## F05 — Medium: the clean verdict does not bind applications to provenance

Evidence: `scripts/verify.py:76-84,137-144`, `scripts/build.sh:82,102`,
`.github/workflows/build.yml:56-64`.

A changed backend driver passes the standalone verifier despite the driver's
SHA-256 pin being available in the repository. Provenance with an unrelated
commit, empty input hashes and `working_tree_clean: false` also passes; only
schema/version agreement is required. Application pins and required binding
fields in the template are not comprehensively compared with trusted config.
The package database comparison establishes recorded versions, not integrity
of every installed file. The production build does independently hash the driver
after npm installation, so the standalone omission is not evidence that this
build step is missing.

The release contains SHA256SUMS alongside the files it describes, with no
independent signature or attestation step in this workflow. This detects transfer
corruption, but replacement of both files and checksums is not detectable from
those files alone. GitHub/TLS/account security remains an external trust anchor;
no release replacement or account compromise was demonstrated.

Impact: consumers can mistake structural policy checks and self-reported build
metadata for authenticated application provenance.

Recommendation: check the driver's hash in both verification modes, validate the
full manifest/provenance schema and expected source revision, and add a reviewed
final application-file inventory. Bind the archive digest and source revision
to independently verifiable release attestations/signatures, with consumer-side
verification. A file inventory stored only inside the same untrusted archive is
not an independent trust anchor. Document explicitly which checks prove content
policy and which prove authenticity.

## Reproduction and completed checks

Run from the checkout:

```sh
python3 -B tests/security_audit_probes.py
```

The utility uses public synthetic fixtures and temporary compressed archives.
On the audited implementation all nine mutations are accepted through both the
function and archive CLI. Exit status **1 is intentional** when any unsafe probe
is accepted; 0 means all probes were rejected, and 2 means zstd is unavailable.
It is deliberately separate from unittest discovery. It detects these specific
gaps and is not a complete malware, secret or archive-safety scanner.

Existing baseline checks passed: 20 unittest cases, Bash syntax, ShellCheck and
`git diff --check`. No complete authenticated root build, real gatekeeper runtime
execution, release download verification or privileged restoration was performed
for this audit. The runtime harness was reviewed as source only. Historical
validation records were not counted as newly executed tests.

## Positive controls and outstanding acceptance

Useful existing controls include authenticated Alpine bootstrap, offline signed
APK installation with a complete hash lock, application source/release hashes,
full-commit Action pins, no persisted checkout credentials, split release-write
permissions, no automatic overwrite of existing release assets, blocked global
storage services, application permission normalization and archive-header tests.
No private credential was observed in the reviewed tracked source. This was not
a full Git-history or binary-secret scan; the verifier's PEM pattern and path
denylist cannot establish the absence of all credential formats.

No dependency-CVE clearance is claimed: no current advisory correlation against
the complete Alpine/npm/Dart dependency inventories was executed. A package
version lock is not a vulnerability assessment. Add a dated inventory/advisory
review with reachability and accepted-risk decisions rather than assuming the
existing `--no-audit` installation establishes dependency safety.

Live Proxmox boot, host/guest ZFS compatibility, actual NFS exports, LIO ownership,
CHAP/discovery policy, host binding scope, shared locking, gatekeeper/backend
socket isolation and real CSI/PVC/snapshot/recovery behavior remain unassessed.
The privileged guest is explicitly trusted; this audit makes no tenant-isolation
claim. Use concrete targets and bounded operations for that separate acceptance.

Priority: contain build-time code first (F01); enforce effective SSH policy and
critical filesystem metadata next (F02/F03); then tighten link and provenance
validation (F04/F05). Convert the demonstrated cases into rejection regression
tests as fixes land. This audit changes documentation and adds inert probes only.
