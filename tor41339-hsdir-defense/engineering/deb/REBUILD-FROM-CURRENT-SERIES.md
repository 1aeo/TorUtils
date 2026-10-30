# Rebuild the `.deb`s (24.04 noble, 26.04 resolute) from the current series

The attached packages in `../../packages/` are `+tor41339.9` for Ubuntu 24.04
(`~noble+1`) and 26.04 (`~resolute+1`), built on tor 0.4.9.15 from
`../../patches/0001`–`0020` before two small later changes, comment fixes in
0011 and 0013 and a `BUG()` guard in 0012 (provenance:
`../../packages/BUILD-INFO.txt`). Use
this runbook whenever `patches/` changes, bumping the suffix (`+tor41339.9`,
…) so `dpkg` sees the new build as newer. Rebuild **both** releases from the same
series, and regenerate every artifact below together, so the binaries, the
`debian-patches/` build copy and the docs never diverge.

## Requirements

- An **amd64** Linux host with Docker (each build runs in a fresh amd64
  container of its release: `ubuntu:24.04` for noble, `ubuntu:26.04` for
  resolute). An arm64 machine would need `--platform linux/amd64` emulation
  (slow).
- Network access for `apt-get` build-deps and for the source packages.
- Docker Hub may rate-limit anonymous pulls (HTTP 429). Canonical's LTS images
  on the AWS public mirror are equivalent:
  `docker pull public.ecr.aws/lts/ubuntu:24.04 && docker tag public.ecr.aws/lts/ubuntu:24.04 ubuntu:24.04`
  (same for `26.04`).

## Inputs (stage them in one directory, mounted read-only as `/in`)

- From `https://deb.torproject.org/torproject.org/pool/main/t/tor/`:
  `tor_0.4.9.15.orig.tar.gz` (sha256
  `1911f5b216a6814ed143a08bbcff1c6dc96d2ca3b505df9a21876080a92963f3`, identical
  to dist.torproject.org, shared by both releases), plus
  `tor_0.4.9.15-1~noble+1.{diff.gz,dsc}` and
  `tor_0.4.9.15-1~resolute+1.{diff.gz,dsc}`. Check the `.diff.gz` sha256
  against its `.dsc`; the two Debian packagings should differ only in the
  changelog entry (`diff <(zcat …noble…) <(zcat …resolute…)`).
- Every `build-reordered/debian-patches/[0-9][0-9][0-9][0-9]-*.patch`: `0000`
  (restores `doc/nofooter.conf`, which the 0.4.9.15 tarball still omits) and
  copies of `../../patches/0001`–`0020`. `.7`'s Debian-only option alias is
  gone. Stage them into a fresh, empty directory so no stale patch is picked
  up.
- The driver `build-reordered/build-in-container-reordered.sh`.

## Build

1. The driver takes the suffix, the changelog entry and the expected patch
   count from the environment, and fails if any is unset or if the staged
   patch count differs: `REV` (the `N` in `+tor41339.N`), `CHANGELOG_MSG`, and
   `EXPECT_PATCHES` (21 for `0000`–`0020`), and `VER` (default 0.4.9.15).
2. Run once per release (the driver runs with `set -o pipefail`, so a failed
   `dpkg-buildpackage` fails the run):
   - `docker run --rm --network host -e SUITE=noble -e REV=9 -e EXPECT_PATCHES=21 -e CHANGELOG_MSG="…" -v /in:/in:ro -v /out-noble:/out ubuntu:24.04 bash /in/build-in-container-reordered.sh`
   - `docker run --rm --network host -e SUITE=resolute -e REV=9 -e EXPECT_PATCHES=21 -e CHANGELOG_MSG="…" -v /in:/in:ro -v /out-resolute:/out ubuntu:26.04 bash /in/build-in-container-reordered.sh`

   Expect `dh_auto_test` green in both (see `BUILD-INFO.txt` for the counts).
3. Check: no compiler warning on any line the series adds (warnings in
   unchanged upstream code in touched files are listed in `BUILD-INFO.txt`),
   and `strings usr/bin/tor` (after `dpkg-deb -x`) contains the new option and
   metric names.
4. Parity: the configure feature summary (`Tor Version:` … `Configure Line:` in
   each `dpkg-buildpackage.log`), the package file lists, `Depends`, the NEEDED
   sonames, the systemd units / default torrcs, `--list-modules` and the
   option defaults must be identical between the two builds
   (`resolute/parity-vs-noble.txt` is the `+tor41339.3` record).

## Verify (private loopback lab only)

Run `install-run-reordered/run-deb-test.sh` once per package (see its header
for the variables: the output dir, a chutney checkout and venv, a tor +
tor-gencert for the lab's own authorities, `REV`, and `IMAGE=ubuntu:26.04`
for the resolute package). It brings up a private chutney net, installs
**only** the `tor` package in a fresh container of that release, and runs an
unpublished relay under `Sandbox 1`. It exits nonzero unless both torrcs pass
`--verify-config`, the version ends in `+tor41339.$REV`, all 5 new options
exist (`NEW_OPTIONS=5`, every defense off), each option name that `.8`
dropped fails with "Unknown option", the relay bootstraps, all 121 new
MetricsPort series are present with exactly their expected labels
(`NEW_METRIC_SERIES=121`, and no other series in each new family), no series
is left under a name `.7` replaced or `.8` dropped, tor 0.4.9.15's three
`begindir_*` counts are there, and there are 0 bad syscalls; the
transcript ends with `RESULT: PASS`. (Not exiting on SIGTERM
under `Sandbox 1` is the pre-existing upstream bug tor#41060;
`../seccomp/sigterm-repro.sh` compares stock and patched.)

Then run `resolute/controls/run-controls.sh` (see its header) with a lab
image holding the package, once per release: every defense is switched on and
off live under HS-directory traffic in a network-less container.

## Regenerate together

- `../../packages/`: both releases' `.deb`s, `.buildinfo`, `.changes`, then
  `SHA256SUMS` over all `.deb`s, and `BUILD-INFO.txt` (source hashes, patch
  hashes + branch commit, builder image digests, test results, parity).
- `build-reordered/debian-patches/` (must equal `patches/`; the same series
  serves both builds), `build-reordered/changelog` and `resolute/changelog`
  (each build's `debian/changelog`), and the transcript, lab log and torrc in
  `install-run-reordered/` (24.04) and `resolute/` (26.04).
- Version strings and hashes in `README.md` (this directory),
  `../../packages/BUILD-INFO.txt` and `resolute/DELIVERY.md` (rerun its
  validation for a new 26.04 artifact). The operator documents take the
  artifact's values from the delivery manifest; their owner updates them after
  review, and a running cohort keeps its frozen artifact.
