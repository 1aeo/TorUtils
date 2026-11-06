# amd64 `.deb` for Ubuntu 24.04 and 26.04: build + install evidence

> **Not yet upstream-reviewed.** `+tor41339.9` is tor 0.4.9.15 with patches
> 0001–0020 as built (`build-reordered/debian-patches/`; `../../patches/`
> has since changed 0011–0013). `+tor41339.10`, a canary build, is `.9`'s
> series as built plus 0021. Every defense of the series (0011, 0013) is
> off: the AUTOBOOL options default to `auto` and no consensus sets their
> parameters. Tor 0.4.9.15's own BEGIN_DIR rate limit and limit of one onion
> service request per circuit are on, as in stock. The MetricsPort counters
> (0006–0010, 0012, 0013's, 0015–0020, and 0021 on `.10`) are on (those of
> 0018 and 0019 only while a MetricsPort is configured), and the hardening
> patches 0001–0005 and 0014 are always active, so the build is not
> equivalent to stock. The crash-at-scale review
> (`../../operator/patch-crash-at-scale-critique.md`: 0 critical / 0 high)
> covered the legacy 7-patch series behind `+tor41339.3`, not 0006–0008 or
> 0012–0021. It is not a released package; do not enable enforcement
> fleet-wide before measuring with the counters.

## Packages (`../../packages/`)

Two builds per Ubuntu LTS, `.9` (fleet) and `.10` (canary), each for both
releases from the same patches and the same configure line:

| Host | Package |
|---|---|
| Ubuntu 24.04 (noble) | `tor_0.4.9.15-1~noble+1+tor41339.9_amd64.deb` |
| Ubuntu 26.04 (resolute) | `tor_0.4.9.15-1~resolute+1+tor41339.9_amd64.deb` |
| Ubuntu 24.04 (noble), canary | `tor_0.4.9.15-1~noble+1+tor41339.10_amd64.deb` |
| Ubuntu 26.04 (resolute), canary | `tor_0.4.9.15-1~resolute+1+tor41339.10_amd64.deb` |

`.9` stays the fleet build. `.10` is `.9` plus 0021: the same options,
defaults and metric names, and the 78 series of
`tor_relay_begindir_close_reason_total` (`../../operator/BEGIN_DIR-BREAKDOWN.md`).

- The `tor_…_amd64.deb` is the patched daemon (`/usr/bin/tor` + the systemd
  units); **it alone contains the patches.** The current plan unpacks it to
  `/opt` and switches one instance at a time
  (`../../operator/DEPLOY-AND-MEASURE.md` §1, §1.1).
- `tor-geoipdb_…_all.deb` (one per release) — optional, arch-independent GeoIP
  *data* (no code), unchanged from stock; it is only a `Recommends` of `tor`.
- `SHA256SUMS`, `BUILD-INFO.txt` (provenance: source and patch hashes, branch
  commit, builder image digests, test results, the 24.04/26.04 parity
  summary), and the `.buildinfo` / `.changes` Debian build metadata (not
  installable).

**26.04 native artifact for the build handoff:** `resolute/DELIVERY.md` records
the `+tor41339.3` handoff and has not been redone for `+tor41339.9`; it has the
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
`ubuntu:24.04` on `tor_0.4.9.15-1~noble+1`, `SUITE=resolute` in `ubuntu:26.04`
on `tor_0.4.9.15-1~resolute+1`. The two source packages share the orig tarball
(sha256 `1911f5b2…63f3`, identical to dist.torproject.org), and their Debian
packaging differs only in the changelog entry. By the time of `.10`,
deb.torproject.org no longer had those 0.4.9.15 sources, so `.10` is built
on the same two, rebuilt from Debian's tor 0.4.9.15-1 with the same sha256
(`REBUILD-FROM-CURRENT-SERIES.md`). The quilt series in
`debian-patches/` is `0000` (restores `doc/nofooter.conf`, which the release
tarball omits), then `0001`–`0020` as they were at the build; it is the
same for both releases. `debian-patches/` also holds `0021`, and `.10`'s
series is `.9`'s with `0021` added: the driver writes it from the staged
patches, `series` stays `.9`'s, and `BUILD-INFO.txt` has `.10`'s sha256.
`../../patches/` has since corrected three comments in 0011 and 0013 and
added a `BUG()` guard in 0012, which the packages don't have
(`BUILD-INFO.txt`). `changelog` is the 24.04 build's `debian/changelog`;
`resolute/changelog` is the 26.04 one. Both are `.9`'s; `.10`'s go beside
them, with its suffix in their names.

- `dh_auto_test` (`make test`, the full unit binary), `.9`, both
  releases: **1639 tests ok, 24 skipped (the same environment-conditional
  set), 0 failed.** `.10` adds 0021's two tests (1641 ok, 24 skipped in a
  native build), but its packages were built under amd64 emulation, where
  tor's seccomp sandbox cannot load, so 7 sandbox tests were skipped: 1634
  ok, 31 skipped, 0 failed in both releases (`BUILD-INFO.txt`).
- No compiler warning on any line the series adds (gcc 13 and gcc 15). The
  only warnings in files the series touches are in unchanged upstream test
  code (`BUILD-INFO.txt` lists them).
- Each binary contains the 5 new option names and every new metric name, and
  none of the names `.8` dropped; its manual renders the new entries
  correctly.

**24.04 / 26.04 parity.** Identical configure feature summary and configure
line, 64-entry package file list, `Depends`/`Recommends`/`Suggests`, and
NEEDED sonames. Only the system libraries each release ships differ, plus the
compiler (`BUILD-INFO.txt`). `resolute/parity-vs-noble.txt` is the fuller
`+tor41339.3` record.

To rebuild after `patches/` changes, follow `REBUILD-FROM-CURRENT-SERIES.md`.

## Install + run test (`install-run-reordered/`, `resolute/`)

`run-deb-test.sh` (host driver; `IMAGE=ubuntu:26.04` for the 26.04 package),
`in-container.sh` and `lab-net` reproduce the test. A private loopback chutney
network (its own directory authorities and consensus; nothing touches the real
Tor network) is brought up, then a fresh container of the matching release
installs **only the `tor` package** (`tor-geoipdb` not installed) and runs an
unpublished relay joined to that network. Results for `.9`, the same for
both releases:

- `tor --verify-config` returns 0 for the default and the lab torrc, and the
  installed version ends in `+tor41339.9`.
- All 5 new options exist, with every defense off:
  `HSDirRefuseUnknownPrevHop auto`, `HSDirDescriptorFetchRate 5`,
  `HSDirDescriptorFetchBurst 20`, `HSDirFetchShedding auto`,
  `HSDirFetchBudget 0`. Tor 0.4.9.15's own `DoSBeginDirRateEnabled` is
  `auto`, which its consensus default turns on.
- A torrc that sets an option `.8` dropped fails `--verify-config` with
  "Unknown option": `HSDirOneRequestPerCircuit`, `DoSBeginDirLimitEnabled`,
  `DoSBeginDirMaxStreams` and `HSDirDescriptorFetchLimit`.
- Under `Sandbox 1`: `Seccomp_filters: 2` (Docker's own filter plus tor's),
  Bootstrapped 100%, 0 bad syscalls.
- All 121 new MetricsPort series are present, each with exactly its expected
  labels. None is under a name `.7` replaced or `.8` dropped, and tor
  0.4.9.15's three `begindir_*` counts are there. The values are near 0,
  since an unpublished relay gets no HS traffic.
- On `.10` the check also requires the 78 series of
  `tor_relay_begindir_close_reason_total`, each with exactly its labels
  (`type`, `prev_hop`, `reason`, in that order): 199 in all. It checks
  their names and labels, not that each type's reasons add up to its
  requests. `.10`'s check did not run in this lab but offline, under amd64
  emulation: the built `.deb` was installed with apt (its dependencies,
  curl and procps from the Ubuntu archive) into a container that was then
  committed, and `in-container.sh` ran from it with no network, against a
  fake loopback authority and with `Sandbox 0`. Every check passed except
  bootstrap, which cannot succeed there, so each transcript ends
  `RESULT: FAIL`; all 78 series were present and 0. With `Sandbox 0`,
  tor's seccomp filter never loaded (`Seccomp_filters: 1`, Docker's
  alone), so the bad-syscall check could not fire: `.10` has not yet run
  under `Sandbox 1`, and its 7 sandbox unit tests were skipped. Run it once
  under `Sandbox 1` on amd64 (`run-deb-test.sh`) before a relay that uses
  `Sandbox 1` takes the canary. The live controls and the breakdown lab
  were not rerun (`../../packages/BUILD-INFO.txt`).

`resolute/controls/` drives real HS-directory traffic through a private net
in which every node runs the packaged binary under `Sandbox 1`, and switches
each defense on and off live at one target HSDir, with a reuse load (5
fetches per circuit), a one-hop load from an unlisted relay, and a stock
client. Results for both `+tor41339.9` packages (`controls-result.json`
for 26.04, `controls-result-noble.json` for 24.04; not rerun for `.10`):

| Phase (40 s each) | Stock prober (target only) | Reuse load | One-hop load | Refused at the target |
|---|---|---|---|---|
| Defaults, or every option off | all of 37 to 43 fetches¹ | 0–2 of 96 to 100 | 9–11/20 | 28–30, by tor's limit of one HSDir request per circuit |
| `HSDirRefuseUnknownPrevHop 1` | 43/43 (24.04), 27/28 (26.04)² | 0/100 (26.04: 0/95) | 0/20 | 40: tor's 20, and 20 circuits closed by `HSDirRefuseUnknownPrevHop` (26.04: 37, 18 and 19) |
| 0012 rate 1, burst 2 (count only) | 43/43 | 0/100 | 10/20 | 30; 29 fetches counted over the rate |
| `HSDirFetchShedding 1`, `HSDirFetchBudget 28000` | 13/15 (24.04), 7/10 (26.04) | 0/100 | 10/20 | 32: tor's 27, and 5 shed (26.04: 33, 29 and 4) |

¹ Except the first phase on 24.04: 13/15, and 4/20 for the one-hop load.
A test network's onion service time periods last minutes, and the
target answered 24 fetches `not_found` until the service uploaded its
descriptor for the new period.
² The failure was a 15-second timeout, not a refusal at the target: its 37
refusals are tor's 18 second requests and the 19 fetches it refused from
the unknown relay identity.

In every phase:
- **Tor's own limit.** Tor 0.4.9.15 closed each circuit at its second onion
  service request, counted as `begindir_hsdir_rejected`. That covered the
  reuse load's 20 circuits and, with `HSDirRefuseUnknownPrevHop` off, the
  one-hop load's 10, so the one-hop load received half of its fetches. The
  reuse load received at most two: the close at a circuit's second request
  also discards the first's response still in flight, an artifact of this
  pipelining test client. Of the reuse load's later streams on a closed
  circuit, about one per circuit had sent its request (`circuit_dead`, 17
  to 24 a phase) and one hadn't (`no_request`, 14 to 20); `.8` counted both
  as `circuit_dead`.
- **`hsdir_unknown_prev_hop`** counted the one-hop load's first request on
  each circuit: 10 with `HSDirRefuseUnknownPrevHop` off. With it on, each
  of those closed its circuit, so the load made every fetch on a new
  circuit, and the counter equals the refusals: 20 (26.04: 19).
- **One bucket per stream.** Every tunneled BEGIN_DIR stream was counted in
  exactly one of `tor_relay_hsdir_fetch_total`,
  `tor_relay_hsdir_upload_total`, the other types of
  `tor_relay_begindir_request_total`, or
  `tor_relay_begindir_connections{state="command_wait"}`.

After each "on" phase, switching the option off live on the same process
restored the loads, and the target kept its PID throughout.

In the shedding phase, 20 fetches (24.04) and 15 (26.04) reached the target
while it was over its budget, and it shed 5 and 4 of them. The shed fetches
are counted as `refused`, and equal `hsdir_fetch_shed`. The stock prober
fetches only from the target HSDir (`HSFETCH … SERVER=`), so it shows the
per-HSDir refusal rate, not what a client sees. Real clients retry another
HSDir: in `../client-lab/`, stock C tor and Arti clients reached the shed
onion service on every request. No node logged a bad syscall.

The install check exits nonzero if any of these fails.

Evidence: `install-run-reordered/` (24.04) and `resolute/` (26.04):
`install-run-transcript.txt`, `labnet.log`, `torrc-lab` (local paths replaced
by `<work>`), for `.9`; `.10`'s transcript and torrc go beside them, with
its suffix in their names (no lab log: its check ran offline). The earlier
`+tor41339.1`–`.4` builds are superseded.

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
| `+tor41339.4` install runs, `Sandbox 1` | — | 24.04 exited; 26.04 stuck |
| `+tor41339.5` install runs, `Sandbox 1` | — | exited |
| `+tor41339.6` install runs, `Sandbox 1` | — | 24.04 stuck; 26.04 exited |
| First `+tor41339.7` install runs, `Sandbox 1` | — | 24.04 exited; 26.04 stuck |
| Final `+tor41339.7` install runs, `Sandbox 1` | — | both stuck |
| `+tor41339.8` install runs, `Sandbox 1` | — | 24.04 exited; 26.04 stuck |
| First `+tor41339.9` install runs, `Sandbox 1` | — | both stuck |
| Final `+tor41339.9` install runs (the same binaries), `Sandbox 1` | — | both exited |
| Ubuntu 26.04.1, glibc 2.43 (`resolute/sigterm-trials.txt`), `Sandbox 1` | stuck 6/15 | stuck 5/15 |
| Ubuntu 26.04.1, `Sandbox 0` | exited 5/5 | exited 5/5 |

This series does not touch that code. Operators running `Sandbox 1` should
expect systemd to fall back to SIGKILL at `TimeoutStopSec` on some restarts,
and should confirm the PID changed after a restart.
