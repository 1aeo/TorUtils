# Rebuild the `.deb`s (24.04 noble, 26.04 resolute) from the current series

The attached packages in `../../packages/` are `+tor41339.9` for Ubuntu 24.04
(`~noble+1`) and 26.04 (`~resolute+1`), built on tor 0.4.9.15 from
`../../patches/0001`–`0020` before two small later changes, comment fixes in
0011 and 0013 and a `BUG()` guard in 0012 (provenance:
`../../packages/BUILD-INFO.txt`). The `+tor41339.10` canary packages go
beside them: the same 0001–0020 as built, plus 0021. `.9` stays the fleet
build. Use
this runbook whenever `patches/` changes, bumping the suffix (`+tor41339.9`,
…) so `dpkg` sees the new build as newer. Rebuild **both** releases from the same
series, and regenerate every artifact below together, so the binaries, the
`debian-patches/` build copy and the docs never diverge.

## Requirements

- An **amd64** Linux host with Docker (each build runs in a fresh amd64
  container of its release: `ubuntu:24.04` for noble, `ubuntu:26.04` for
  resolute). An arm64 machine needs `--platform linux/amd64` emulation
  (slow), as `.10` had: run 26.04 under QEMU user-mode 10.2 or later
  (Rosetta and older QEMU lack the openat2 call that 26.04's tar uses), give
  noble one CPU (`--cpuset-cpus 0`: with more, gcc's `-flto=auto` jobserver
  crashes lto1 under emulation), and add `-e TOR_SKIP_TESTCASES=sandbox/..`
  to each `docker run`, since tor's seccomp sandbox cannot load there (this
  skips 7 tests; `../../packages/BUILD-INFO.txt`).
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
  deb.torproject.org no longer serves these 0.4.9.15 backport sources (it
  has moved on to 0.4.9.16): rebuild them from Debian's tor 0.4.9.15-1 as
  below.
- The patches. `build-reordered/debian-patches/0000` restores
  `doc/nofooter.conf`, which the 0.4.9.15 tarball still omits.
  - To reproduce `.10`, stage every
    `build-reordered/debian-patches/[0-9][0-9][0-9][0-9]-*.patch` as it is:
    `0000`, `0001`–`0020` as `.9` was built from them, and `0021`, a copy of
    `../../patches/0021` (`EXPECT_PATCHES=22`). For `.9` itself, stage
    `0000`–`0020` only (`EXPECT_PATCHES=21`).
  - For a new build from the current series, stage `0000` and copies of
    `../../patches/0001`–`0021`, which differ from `debian-patches/` in
    0011–0013 (`EXPECT_PATCHES=22`, a new `REV`), and then refresh
    `debian-patches/` from them.

  `.7`'s Debian-only option alias is gone. Stage into a fresh, empty
  directory so no stale patch is picked up.
- The driver `build-reordered/build-in-container-reordered.sh`.

### The 0.4.9.15 backport sources, rebuilt from Debian

Each 0.4.9.15 backport source package is Debian's tor 0.4.9.15-1 with one
changelog entry on top, so it can be rebuilt from Debian's signed source:

1. From snapshot.debian.org (`https://snapshot.debian.org/package/tor/0.4.9.15-1/`):
   `tor_0.4.9.15-1.dsc` (its sha256 and URL are in the `.10` block of
   `../../packages/BUILD-INFO.txt`), `tor_0.4.9.15-1.diff.gz`, and
   `tor_0.4.9.15.orig.tar.gz` (the same orig tarball, `1911f5b2…63f3`). Check the `.dsc` signature with
   `dscverify` (from `devscripts`, with `debian-keyring` installed); the
   `.dsc` lists the sha256 of the other two.
2. For each `S` in `noble` and `resolute`, in an empty directory holding
   those three files and `entry-$S`, the stanza below for that release:

   ```
   dpkg-source -x tor_0.4.9.15-1.dsc
   cat entry-$S tor-0.4.9.15/debian/changelog > changelog
   mv changelog tor-0.4.9.15/debian/changelog
   dpkg-source -b tor-0.4.9.15
   ```

   That writes `tor_0.4.9.15-1~$S+1.diff.gz` and `tor_0.4.9.15-1~$S+1.dsc`.
   Join the two with `cat` alone: the stanza already ends in its one blank
   line, and a second blank line changes the source package.
3. Check that each `.diff.gz` and `.dsc` has the sha256 that `.9` was built
   from (`../../packages/BUILD-INFO.txt`), and that the extracted
   `debian/changelog` is `build-reordered/changelog` (noble) or
   `resolute/changelog` (resolute) without its first entry. If a hash
   differs, compare the two `zcat` outputs before building.

The stanzas, exactly as in `.9`'s `debian/changelog`, each followed by one
blank line. This cuts `entry-noble` from `build-reordered/changelog` (and,
with `S=resolute`, `entry-resolute` from `resolute/changelog`):

```
S=noble
sed -n "/^tor (0.4.9.15-1~$S+1)/,/^tor (0.4.9.15-1)/p" build-reordered/changelog | sed '$d' > entry-$S
```

```
tor (0.4.9.15-1~noble+1) noble-backport; urgency=medium

  * Build for noble-backport.

 -- Peter Palfrader <build@runner-0uop2-sxc-project-1218-concurrent-0>  Wed, 28 Oct 2026 16:36:01 +0000

```

```
tor (0.4.9.15-1~resolute+1) resolute-backport; urgency=medium

  * Build for resolute-backport.

 -- Peter Palfrader <build@runner-0uop2-sxc-project-1218-concurrent-0>  Wed, 28 Oct 2026 16:36:03 +0000

```

## Build

1. The driver takes the suffix, the changelog entry and the expected patch
   count from the environment, and fails if any is unset or if the staged
   patch count differs: `REV` (the `N` in `+tor41339.N`), `CHANGELOG_MSG`, and
   `EXPECT_PATCHES` (22 for `.10`'s `0000`–`0021`; 21 for `.9`'s
   `0000`–`0020`), and `VER` (default 0.4.9.15).
2. Run once per release (the driver runs with `set -o pipefail`, so a failed
   `dpkg-buildpackage` fails the run):
   - `docker run --rm --network host -e SUITE=noble -e REV=10 -e EXPECT_PATCHES=22 -e CHANGELOG_MSG="…" -v /in:/in:ro -v /out-noble:/out ubuntu:24.04 bash /in/build-in-container-reordered.sh`
   - `docker run --rm --network host -e SUITE=resolute -e REV=10 -e EXPECT_PATCHES=22 -e CHANGELOG_MSG="…" -v /in:/in:ro -v /out-resolute:/out ubuntu:26.04 bash /in/build-in-container-reordered.sh`

   (`.9` was built with `-e REV=9 -e EXPECT_PATCHES=21`.) `CHANGELOG_MSG`
   for `.10`, exactly:

   ```
   Apply the tor#41339 HSDir defensive series (patches 0001-0021) on tor 0.4.9.15: the +tor41339.9 series unchanged, plus a MetricsPort counter of the tunneled directory streams closed without reading a request, by the first cause noted for their closing (tor_relay_begindir_close_reason_total); restore doc/nofooter.conf. The same options, defaults and other MetricsPort series as +tor41339.9.
   ```

   Expect `dh_auto_test` green in both (see `BUILD-INFO.txt` for the
   counts; `.10` has 0021's two tests more than `.9`: 1641 ok and 24
   skipped natively, 1634 ok and 31 skipped under emulation with
   `TOR_SKIP_TESTCASES=sandbox/..`).
3. Check: no compiler warning on any line the series adds (warnings in
   unchanged upstream code in touched files are listed in `BUILD-INFO.txt`),
   and `strings usr/bin/tor` (after `dpkg-deb -x`) contains the new option and
   metric names (on `.10`, also `tor_relay_begindir_close_reason_total`).
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
MetricsPort series (199 from `+tor41339.10`, with the 78 of
`tor_relay_begindir_close_reason_total`) are present with exactly their
expected labels (`NEW_METRIC_SERIES=121`, or `199`, and no other series in
each new family), no series
is left under a name `.7` replaced or `.8` dropped, tor 0.4.9.15's three
`begindir_*` counts are there, and there are 0 bad syscalls; the
transcript ends with `RESULT: PASS`. (Not exiting on SIGTERM
under `Sandbox 1` is the pre-existing upstream bug tor#41060;
`../seccomp/sigterm-repro.sh` compares stock and patched.)
`REV` must be a whole number, since it sets which series are expected; the
check fails otherwise. Point `DEBDIR` at one build's `/out`, not at
`../../packages/`, which holds the `.deb`s of both releases and both builds.
With `REV=9`, a `.10` package fails the version check.

Then run `resolute/controls/run-controls.sh` (see its header) with a lab
image holding the package, once per release: every defense is switched on and
off live under HS-directory traffic in a network-less container.

## Regenerate together

- `../../packages/`: both releases' `.deb`s, `.buildinfo`, `.changes`, then
  `SHA256SUMS` over all `.deb`s, and `BUILD-INFO.txt` (source hashes, patch
  hashes + branch commit, builder image digests, test results, parity).
  A canary built beside the fleet build (`.10` beside `.9`) adds its files
  and keeps the fleet build's: its `.deb`s, `.buildinfo` and `.changes`, its
  lines appended to `SHA256SUMS`, and its own block in `BUILD-INFO.txt`,
  with `.9`'s text left as it is.
- `build-reordered/debian-patches/`: the patches the packages were built
  from, with the series file of the fleet build. Now that is `0000`,
  `0001`–`0020` as `.9` was built from them, `0021` equal to
  `patches/0021`, and `.9`'s `series`. The driver writes each build's series
  from the staged patches, and `.10`'s sha256 is in its `BUILD-INFO.txt`
  block; each series serves both releases. After a new build from the
  current series, it is `0000` and the copies of `patches/` that were built,
  with that build's `series`.
- `build-reordered/changelog` and `resolute/changelog` (each build's
  `debian/changelog`), and the transcript, lab log and torrc in
  `install-run-reordered/` (24.04) and `resolute/` (26.04). A canary adds
  its own `debian/changelog` records, install-run transcript and torrc, and
  its lab log if its check ran in the lab, beside the fleet build's, with
  its suffix in their names (for example `changelog.tor41339.10`).
- Version strings and hashes in `README.md` (this directory),
  `../../packages/BUILD-INFO.txt` and `resolute/DELIVERY.md` (rerun its
  validation for a new 26.04 artifact). The operator documents take the
  artifact's values from the delivery manifest; their owner updates them after
  review, and a running cohort keeps its frozen artifact.
