# Rebuild the noble `.deb` from the current series

The attached package in `../../packages/` is `+tor41339.3`, built from
`../../patches/` at branch commit `2b8ae1a` (provenance:
`../../packages/BUILD-INFO.txt`). Use this runbook whenever `patches/` changes,
bumping the suffix (`+tor41339.4`, …) so `dpkg` sees the new build as newer, and
regenerate every artifact below together so the binary, the `debian-patches/`
build copy and the docs never diverge.

## Requirements

- An **amd64** Linux host with Docker (the build runs in a fresh `ubuntu:24.04`
  amd64 container). An arm64 machine would need `--platform linux/amd64`
  emulation (slow).
- Network access for `apt-get` build-deps and for the noble source package.
- Docker Hub may rate-limit anonymous pulls (HTTP 429). Canonical's LTS image on
  the AWS public mirror is equivalent:
  `docker pull public.ecr.aws/lts/ubuntu:24.04 && docker tag public.ecr.aws/lts/ubuntu:24.04 ubuntu:24.04`.

## Inputs (stage them in one directory, mounted read-only as `/in`)

- From `https://deb.torproject.org/torproject.org/pool/main/t/tor/`:
  `tor_0.4.9.14.orig.tar.gz` (sha256
  `182449ac1c8ff43278da27b69b02040e11d03d0327db6d9126e4190ec6235e4a`, identical
  to dist.torproject.org), `tor_0.4.9.14-1~noble+1.diff.gz`,
  `tor_0.4.9.14-1~noble+1.dsc`.
- `build-reordered/debian-patches/0000-restore-doc-nofooter.conf.patch` and the
  current `../../patches/0001-*.patch … 0007-*.patch`.
- The driver `build-reordered/build-in-container-reordered.sh`.

## Build

1. In the driver, set the new version and a one-line changelog entry in the
   `dch -v 0.4.9.14-1~noble+1+tor41339.N` line.
2. `docker run --rm --network host -v /in:/in:ro -v /out:/out ubuntu:24.04 bash /in/build-in-container-reordered.sh`
   (the driver runs with `set -o pipefail`, so a failed `dpkg-buildpackage` fails
   the run). Expect `dh_auto_test` green — `+tor41339.3` gave 1613 tests ok, 24
   skipped.
3. Check: no compiler warnings in the files the series touches, and
   `strings usr/bin/tor` (after `dpkg-deb -x`) contains all four
   `hsdir_*` counter names.

## Verify (private loopback lab only)

Run `install-run-reordered/run-deb-test.sh` (see its header for the variables:
the output dir, a chutney checkout and venv, and a tor + tor-gencert for the
lab's own authorities). It brings up a private chutney net, installs **only**
the `tor` package in a fresh container, runs an unpublished relay under
`Sandbox 1`, and must report: `--verify-config` rc 0 for both torrcs, both
options `auto`, Bootstrapped 100%, `Seccomp: 2`, `HSDIR_COUNTER_SERIES=4`,
no enforcement log lines, 0 bad syscalls. (Not exiting on SIGTERM under
`Sandbox 1` is the pre-existing upstream bug tor#41060.)

## Regenerate together

- `../../packages/`: both `.deb`s, `.buildinfo`, `.changes`, `SHA256SUMS`, and
  `BUILD-INFO.txt` (source hashes, patch hashes + branch commit, builder image
  digest, test result).
- `build-reordered/debian-patches/` (must equal `patches/`), `build-reordered/changelog`
  (the build's `debian/changelog`), and the transcript, lab log and torrc in
  `install-run-reordered/`.
- Version strings in `README.md` (this directory),
  `../../operator/DEPLOY-AND-MEASURE.md` §1/§1.1 and
  `../../operator/operator-agent-prompt.md`.
