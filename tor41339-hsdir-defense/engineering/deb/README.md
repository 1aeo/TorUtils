# amd64 `.deb` for Ubuntu 24.04 and 26.04: build + install evidence

> **Cleared for a count-only canary; not yet upstream-reviewed.**
> `+tor41339.3` is built from the current series (`../../patches/` at branch
> commit `6ce9b53`, which was `2b8ae1a` before the branch was rebased; same
> content). It ships both behavioral defenses **observe-only** (enforcement
> stays off until a torrc `AUTOBOOL` or a consensus parameter turns it on).
> It exposes four `hsdir_*` MetricsPort counters, but patches 0003–0007
> remain active in both modes: the full build is not equivalent to stock.
> The accepted [canary plan](../../operator/CANARY-MEASUREMENT-PLAN.md) holds this
> full build constant while measuring inactive/active defenses. The crash-at-scale
> review (`../../operator/patch-crash-at-scale-critique.md`: 0 critical / 0 high,
> re-verified after the later fixes — see its addendum) is why it is cleared for
> the count-only canary in `../../operator/`. It is not a released package; do
> not enable enforcement fleet-wide before the canary measurement.

## Packages (`../../packages/`)

One build per Ubuntu LTS from the same patches and the same build
configuration:

| Host | Package |
|---|---|
| Ubuntu 24.04 (noble) | `tor_0.4.9.14-1~noble+1+tor41339.3_amd64.deb` |
| Ubuntu 26.04 (resolute) | `tor_0.4.9.14-1~resolute+1+tor41339.3_amd64.deb` |

- The `tor_…_amd64.deb` is the patched daemon (`/usr/bin/tor` + the systemd
  units); **it alone contains all 7 patches.** The current plan unpacks it to
  `/opt` and switches one instance at a time
  (`../../operator/DEPLOY-AND-MEASURE.md` §1, §1.1).
- `tor-geoipdb_…_all.deb` (one per release) — optional, arch-independent GeoIP
  *data* (no code), unchanged from stock; it is only a `Recommends` of `tor`.
- `SHA256SUMS`, `BUILD-INFO.txt` (provenance: source and patch hashes, branch
  commit, builder image digests, test results, the 24.04/26.04 parity
  summary), and the `.buildinfo` / `.changes` Debian build metadata (not
  installable).

**26.04 native artifact for the build handoff:** `resolute/DELIVERY.md` has the
package and extracted-binary SHA256s, source base, compiler and flags, linked
libraries, the comparison with the stock 26.04 package, and the validation
evidence requested by `../../operator/NATIVE-26.04-BUILD-HANDOFF.md`, including
what was not covered.

On a host running several `tor@NAME` instances, do **not** install the package
host-wide: its postinst restarts every instance.

## Dry runs of the per-instance switch

An earlier version of the §1.1 switch and §6 rollback was dry-run on a booted
systemd `ubuntu:24.04` container with no network interface (a loopback-only
`tor-instance-create` relay pointed at a fake loopback authority). The drop-in
took effect; the stock `ExecStartPre` verify passed; the patched binary ran as
`_tor-NAME` under `Sandbox 1` with all four counters; `SETCONF …=0` and the
reload revert worked; an `HSDir*` torrc line failed the stock verify, as §1.1
warns; and the rollback restored `/usr/bin/tor`. Stock tor under `Sandbox 1`
took the full 60 s `TimeoutStopSec` to stop (tor#41060).

On 26.04 (systemd 259), the builder repeated the switch mechanics with two
instances (`resolute/systemd/`). Both carried the fleet's mimalloc 2.0.9
`allocator.conf` preload and ran `Sandbox 1`. The results:
- the drop-in kept the preload;
- readiness was confirmed by `Type=notify` activation;
- tor's sandbox was distinguished from systemd's filters by filter count and
  `GETCONF Sandbox`;
- live `SETCONF` and `reload` changes kept the same PID;
- the rollback restored `/usr/bin/tor`;
- the sibling kept its PID with `NRestarts=0` throughout.

The revised preflight, maintenance-restoration, observation/trial procedures and
[probe acceptance specification](../../operator/probe-helper-acceptance.md)
are documentation updates. They were not executed or revalidated by these
dry-runs, and do not change the package or claim that the future helper passes
its tests. Pin the package/source hashes before any later authorized use.

## How it was built (`build-reordered/`)

`build-in-container-reordered.sh` ran in a fresh Canonical LTS container on the
deb.torproject.org source package for that release: `SUITE=noble` in
`ubuntu:24.04` on `tor_0.4.9.14-1~noble+1`, `SUITE=resolute` in `ubuntu:26.04`
on `tor_0.4.9.14-1~resolute+1`. The two source packages share the orig tarball
(sha256 `182449ac…5e4a`, identical to dist.torproject.org), and their Debian
packaging differs only in the changelog entry. The quilt series in
`debian-patches/` is `0000` (restores `doc/nofooter.conf`, which the release
tarball omits) followed by `0001`–`0007`, byte-identical to `../../patches/`
and the same for both builds. `changelog` is the 24.04 build's
`debian/changelog`; `resolute/changelog` is the 26.04 one.

- `dh_auto_test` (`make test`, the full unit binary), both builds: **1613 tests
  ok, 24 skipped (the same environment-conditional set), 0 failed.** Full
  `make check` on 26.04: 34 tests, 33 pass, 1 skip, 0 fail; lint steps pass
  (`resolute/make-check-summary.txt`).
- No compiler warning on any line the series adds (gcc 13 and gcc 15). The
  only warnings in files the series touches are in unchanged upstream test
  code (`BUILD-INFO.txt` lists them).
- Each binary contains all four counter names and both options.

**24.04 / 26.04 parity** (`resolute/parity-vs-noble.txt`). Identical:
- configure feature summary and configure line (OpenSSL, `--enable-gpl`,
  systemd, lzma, zstd, seccomp, scrypt; modules relay, dirauth, dircache, pow);
- the package's 64-entry file list, `Depends`/`Recommends`, and NEEDED sonames;
- systemd units and default torrcs (byte-identical, and identical to the stock
  packages);
- option defaults and the four counters.

Only the system libraries each release ships differ (26.04: OpenSSL 3.5.5,
zlib 1.3.1, liblzma 5.8.3, libzstd 1.5.7), plus the compiler.

To rebuild after `patches/` changes, follow `REBUILD-FROM-CURRENT-SERIES.md`.

## Install + run test (`install-run-reordered/`, `resolute/`)

`run-deb-test.sh` (host driver; `IMAGE=ubuntu:26.04` for the 26.04 package),
`in-container.sh` and `lab-net` reproduce the test. A private loopback chutney
network (its own directory authorities and consensus; nothing touches the real
Tor network) is brought up, then a fresh container of the matching release
installs **only the `tor` package** (`tor-geoipdb` not installed) and runs an
unpublished relay joined to that network. Results, the same for both builds:

- `tor --verify-config` returns 0 for the default and the lab torrc.
- Option defaults: `HSDirOneRequestPerCircuit auto`,
  `HSDirRefuseUnknownPrevHop auto`, `RefuseUnknownExits auto` — count-only
  (`install-run-reordered/defaults-and-libs.txt`, with the linked libraries).
- Under `Sandbox 1`: `Seccomp_filters: 2` (Docker's own filter plus tor's; a
  `Sandbox 0` control shows 1), Bootstrapped 100%, 0 bad syscalls.
- All four counters present (`hsdir_circ_reused`, `hsdir_req_reused`,
  `hsdir_request_total`, `hsdir_unknown_prev_hop`; 0, since an unpublished
  relay gets no HS traffic), and no enforcement log lines.

The 26.04 package was also driven with real HS-directory traffic, so the four
counters actually move, and each control was enabled individually and disabled
live, in a private net (`resolute/controls/`, summarized in
`resolute/DELIVERY.md`).

Evidence: `install-run-reordered/` (24.04) and `resolute/` (26.04):
`install-run-transcript.txt`, `labnet.log`, `torrc-lab`. The earlier
`+tor41339.1` (original order) and `+tor41339.2` (reordered) builds predate
the 0002 call-order/telemetry fix and the upstream-polish refactor and are
superseded.

## Shutdown with `Sandbox 1`

Under `Sandbox 1`, tor sometimes ignores SIGTERM/SIGINT. This is the upstream
bug tor#41060, on stock tor too. Once the seccomp filter is installed,
`pthread_create`'s `rt_sigprocmask(SIG_BLOCK)` is refused with EPERM. glibc
then restores an uninitialized signal mask, and whether that garbage mask
happens to block TERM/INT varies by environment and by run:

| Environment | Stock tor | Patched tor |
|---|---|---|
| glibc 2.39 (`../seccomp/out/anomaly/`), `Sandbox 1` | stuck 15/15 | stuck 15/15 |
| Both `+tor41339.3` 24.04.5 install runs, `Sandbox 1` | — | exited |
| Ubuntu 26.04.1, glibc 2.43 (`resolute/sigterm-trials.txt`), `Sandbox 1` | stuck 6/15 | stuck 5/15 |
| Ubuntu 26.04.1, `Sandbox 0` | exited 5/5 | exited 5/5 |

This series does not touch that code. Operators running `Sandbox 1` should
expect systemd to fall back to SIGKILL at `TimeoutStopSec` on some restarts,
and should confirm the PID changed after a restart.
