# Alpine minirootfs release signing key

`alpine-release.asc` is the public Natanael Copa release-signing key copied from
[lxc-wireguard v0.1.0](https://github.com/fischerscode/lxc-wireguard/blob/v0.1.0/keys/alpine-release.asc).
It authenticates the detached signature for the pinned official Alpine minirootfs.
It is not an SSH key or an instance credential.

The expected primary fingerprint is pinned independently in `build-config.json`:
`0482D84022F52DF1C4E7CD43293ACD0907D9495A`.
The build checks both this fingerprint and the archive SHA-256 before extraction.
Review key rotations independently of an archive hash update.
