# amd64 noble `.deb`: build + install evidence

> **Cleared for a count-only canary; not yet upstream-reviewed.**
> `+tor41339.3` is built from the current series (`../../patches/` at branch
> commit `2b8ae1a`). It ships both behavioral defenses **observe-only**
> (enforcement stays off until a torrc `AUTOBOOL` or a consensus parameter turns
> it on), so installing it on a relay only adds the four count-only
> `hsdir_*` MetricsPort counters and changes no behavior. The crash-at-scale
> review (`../../operator/patch-crash-at-scale-critique.md`: 0 critical / 0 high,
> re-verified after the later fixes — see its addendum) is why it is cleared for
> the count-only canary in `../../operator/`. It is not a released package; do
> not enable enforcement fleet-wide before the canary measurement.

## Packages (`../../packages/`)

- `tor_0.4.9.14-1~noble+1+tor41339.3_amd64.deb` — the patched daemon
  (`/usr/bin/tor` + the systemd units); **it alone contains all 7 patches.**
  For a canary, unpack it to `/opt` and switch one instance
  (`../../operator/DEPLOY-AND-MEASURE.md` §1 Path A + §1.1).
- `tor-geoipdb_0.4.9.14-1~noble+1+tor41339.3_all.deb` — optional,
  arch-independent GeoIP *data* (no code), unchanged from stock; it is only a
  `Recommends` of `tor`, and relays already have it from the stock package.
- `SHA256SUMS`, `BUILD-INFO.txt` (provenance: source and patch hashes, branch
  commit, builder image digest, test result), and the `.buildinfo` / `.changes`
  Debian build metadata (not installable).

On a host running several `tor@NAME` instances, do **not** install the package
host-wide: its postinst restarts every instance. Use
`../../operator/DEPLOY-AND-MEASURE.md` §1.1 to switch one instance only.

That §1.1 switch and the §6 rollback were dry-run as written on a booted
systemd `ubuntu:24.04` container with no network interface (a loopback-only
`tor-instance-create` relay pointed at a fake loopback authority). The drop-in
took effect; the stock `ExecStartPre` verify passed; the patched binary ran as
`_tor-NAME` under `Sandbox 1` (`Seccomp: 2`) with all four counters; `SETCONF
…=0` and the reload revert worked; an `HSDir*` torrc line failed the stock
verify, as §1.1 warns; and the rollback restored `/usr/bin/tor`. Stock tor under
`Sandbox 1` took the full 60 s `TimeoutStopSec` to stop (tor#41060).

## How it was built (`build-reordered/`)

A fresh `ubuntu:24.04` container (Canonical's LTS image) ran
`build-in-container-reordered.sh` on the deb.torproject.org noble source
package `tor_0.4.9.14-1~noble+1`. The orig tarball sha256 is `182449ac…5e4a`,
identical to dist.torproject.org. The quilt series in `debian-patches/` is
`0000` (restores `doc/nofooter.conf`, which the release tarball omits) followed
by `0001`–`0007`, byte-identical to `../../patches/`. `changelog` is the
build's `debian/changelog`.

- `dh_auto_test` (`make test`): **1613 tests ok, 24 skipped, 0 failed.**
- No compiler warnings in any file the series touches.
- The binary contains all four counter names and both options.

To rebuild after `patches/` changes, follow `REBUILD-FROM-CURRENT-SERIES.md`.

## Install + run test (`install-run-reordered/`)

`run-deb-test.sh` (host driver), `in-container.sh` and `lab-net` reproduce the
test. A private loopback chutney network (its own directory authorities and
consensus; nothing touches the real Tor network) is brought up, then a fresh
`ubuntu:24.04` container installs **only the `tor` package** (`tor-geoipdb` not
installed) and runs an unpublished relay joined to that network:

- `tor --verify-config` returns 0 for the default and the lab torrc.
- Option defaults: `HSDirOneRequestPerCircuit auto`,
  `HSDirRefuseUnknownPrevHop auto`, `RefuseUnknownExits auto` — count-only
  (`defaults-and-libs.txt`, with the linked libraries).
- Under `Sandbox 1`: `Seccomp: 2`, Bootstrapped 100%, 0 bad syscalls.
- All four counters present (`hsdir_circ_reused`, `hsdir_req_reused`,
  `hsdir_request_total`, `hsdir_unknown_prev_hop`; 0, since an unpublished
  relay gets no HS traffic), and no enforcement log lines.

Evidence: `install-run-transcript.txt`, `labnet.log`, `torrc-lab`. The earlier
`+tor41339.1` (original order) and `+tor41339.2` (reordered) builds predate the
0002 call-order/telemetry fix and the upstream-polish refactor and are
superseded.

## Shutdown with `Sandbox 1`

Earlier builds did not exit within 5 s of SIGTERM under `Sandbox 1`. That is the
upstream bug tor#41060, present on unpatched `main` too: on glibc 2.39, once the
seccomp filter is installed, `pthread_create`'s `rt_sigprocmask(SIG_BLOCK)` is
refused with EPERM and glibc then restores an uninitialized signal mask that
blocks TERM/INT/QUIT (`../seccomp/out/anomaly/`; controlled repro: stuck 15/15
for patched and stock under `Sandbox 1`, exited 15/15 under `Sandbox 0`). In
both `+tor41339.3` install runs, in a current Ubuntu 24.04.5 container, tor
**did** exit on SIGTERM. This series does not touch that code, so treat the bug
as environment-dependent rather than fixed: operators running `Sandbox 1`
should still expect systemd may fall back to SIGKILL at `TimeoutStopSec`, and
should confirm the PID changed after a restart.
