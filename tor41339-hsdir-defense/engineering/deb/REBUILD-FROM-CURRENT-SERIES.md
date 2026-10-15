# Rebuild the `.deb`s (24.04 noble, 26.04 resolute) from the current series

The attached packages in `../../packages/` are `+tor41339.3` for Ubuntu 24.04
(`~noble+1`) and 26.04 (`~resolute+1`), built from `../../patches/` at branch
commit `6ce9b53` (`2b8ae1a` before the branch was rebased) (provenance: `../../packages/BUILD-INFO.txt`). Use this
runbook whenever `patches/` changes, bumping the suffix (`+tor41339.4`, …) so
`dpkg` sees the new build as newer. Rebuild **both** releases from the same
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
  `tor_0.4.9.14.orig.tar.gz` (sha256
  `182449ac1c8ff43278da27b69b02040e11d03d0327db6d9126e4190ec6235e4a`, identical
  to dist.torproject.org, shared by both releases), plus
  `tor_0.4.9.14-1~noble+1.{diff.gz,dsc}` and
  `tor_0.4.9.14-1~resolute+1.{diff.gz,dsc}`. Check the `.diff.gz` sha256
  against its `.dsc`; the two Debian packagings should differ only in the
  changelog entry (`diff <(zcat …noble…) <(zcat …resolute…)`).
- `build-reordered/debian-patches/0000-restore-doc-nofooter.conf.patch` and the
  current `../../patches/0001-*.patch … 0007-*.patch`.
- The driver `build-reordered/build-in-container-reordered.sh`.

## Build

1. In the driver, bump the suffix and the one-line changelog entry in the
   `dch -v "${BASE}+tor41339.N"` line (`BASE` is derived from `SUITE`).
2. Run once per release (the driver runs with `set -o pipefail`, so a failed
   `dpkg-buildpackage` fails the run):
   - `docker run --rm --network host -e SUITE=noble -v /in:/in:ro -v /out-noble:/out ubuntu:24.04 bash /in/build-in-container-reordered.sh`
   - `docker run --rm --network host -e SUITE=resolute -v /in:/in:ro -v /out-resolute:/out ubuntu:26.04 bash /in/build-in-container-reordered.sh`

   Expect `dh_auto_test` green in both — `+tor41339.3` gave 1613 tests ok, 24
   skipped, on both.
3. Check: no compiler warning on any line the series adds (warnings in
   unchanged upstream code in touched files are listed in `BUILD-INFO.txt`),
   and `strings usr/bin/tor` (after `dpkg-deb -x`) contains all four `hsdir_*`
   counter names.
4. Parity: the configure feature summary (`Tor Version:` … `Configure Line:` in
   each `dpkg-buildpackage.log`), the package file lists, `Depends`, the NEEDED
   sonames, the systemd units / default torrcs, `--list-modules` and the
   option defaults must be identical between the two builds
   (`resolute/parity-vs-noble.txt` is the `+tor41339.3` record).

## Verify (private loopback lab only)

Run `install-run-reordered/run-deb-test.sh` once per package (see its header
for the variables: the output dir, a chutney checkout and venv, a tor +
tor-gencert for the lab's own authorities, and `IMAGE=ubuntu:26.04` for the
resolute package). It brings up a private chutney net, installs **only** the
`tor` package in a fresh container of that release, runs an unpublished relay
under `Sandbox 1`, and must report: `--verify-config` rc 0 for both torrcs,
both options `auto`, Bootstrapped 100%, `Seccomp_filters: 2` (Docker's filter
plus tor's), `HSDIR_COUNTER_SERIES=4`, no enforcement log lines, 0 bad
syscalls. (Not exiting on SIGTERM under `Sandbox 1` is the pre-existing
upstream bug tor#41060; `../seccomp/sigterm-repro.sh` compares stock and
patched.)

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
