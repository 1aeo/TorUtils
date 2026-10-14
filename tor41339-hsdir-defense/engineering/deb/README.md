# amd64 noble `.deb`: build + install evidence

> **Cleared for a count-only canary; not yet upstream-reviewed.** This package
> ships the two behavioral defenses **observe-only** (enforcement off until a
> consensus parameter or torrc `AUTOBOOL` flips it live), so installing it on a
> relay only adds the `hsdir_circ_reused` / `hsdir_unknown_prev_hop` counters and
> changes no behavior. The crash-at-scale review
> (`../../operator/patch-crash-at-scale-critique.md`) returned 0 critical / 0
> high, which is why it is cleared for the count-only canary in
> `../../operator/`. It has **not** completed upstream series review; do not
> treat it as a released package or enable enforcement fleet-wide before the
> canary measurement.

The built packages are at the top of this subtree in `../../packages/`:
`tor_0.4.9.14-1~noble+1+tor41339.2_amd64.deb` and `tor-geoipdb_…_all.deb`, with
`SHA256SUMS`, `.buildinfo` and `.changes`.

## How it was built (`build-reordered/`)

A fresh `ubuntu:24.04` container ran `build-in-container-reordered.sh` on the
deb.torproject.org noble source package `tor_0.4.9.14-1~noble+1`. The orig
tarball sha256 is `182449ac…5e4a`, identical to dist.torproject.org. The quilt
series in `debian-patches/` is:

- `0000` restores `doc/nofooter.conf`, which the release tarball omits;
- `0001`–`0007` are the v3 patches in the **reordered** (upstream-proposed)
  order — the same order as `../../patches/`.

`dh_auto_test` passed: 1613 tests ok.

The source order matches the series proposed upstream, so this build
(`…+tor41339.2`) is the provenance-correct artifact. An earlier build in the
original patch order (`…+tor41339.1`) produced a byte-identical `/usr/bin/tor`
in `.text`, `.rodata` and `.data` (only `.note.gnu.build-id` differs); the
reorder changes only commit boundaries and `exceptions.txt`, not compiled code.

## Install + run test (`install-run-reordered/`)

A second fresh `ubuntu:24.04` container installed the packages and ran
`tor --verify-config` on the default and lab torrcs (both return 0). It then ran
an unpublished relay (MetricsPort, `Sandbox 1`) joined only to a private
loopback chutney network:

- Reached Bootstrapped 100%, `Seccomp: 2`, **0 bad syscalls** over 120 s.
- `tor_relay_dos_total{type="hsdir_circ_reused"}` and
  `{type="hsdir_unknown_prev_hop"}` stayed at **0** for 120 s.
- `tor --dump-config full` shows `HSDirOneRequestPerCircuit auto` and
  `HSDirRefuseUnknownPrevHop auto`. The lab consensus has no `hsdir_*` params,
  so enforcement is off and the relay only counts.
- `defaults-and-libs.txt` records the installed conffile defaults and linked
  shared libraries.

## Shutdown with `Sandbox 1`

In this run tor did **not** exit within 5 s of SIGTERM. This is the known
upstream bug tor#41060, present on unpatched `main` too. On glibc 2.39, after
the seccomp filter is installed, `pthread_create`'s `rt_sigprocmask(SIG_BLOCK)`
is refused with EPERM, and glibc then restores an uninitialized signal mask that
blocks TERM/INT/QUIT. See `../seccomp/out/anomaly/`. A controlled repro gave:
Sandbox 1, stuck 15/15 for patched and for stock; Sandbox 0, exited 15/15 for
both. Operators running `Sandbox 1` should expect systemd to fall back to
SIGKILL at `TimeoutStopSec`. This is independent of this series.
