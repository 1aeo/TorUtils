# tor#41339 — HSDir onion-service-descriptor flood: defensive patch series

A small, upstreamable patch series for **Tor 0.4.9.14** that bounds the resource
cost of the 2026 BEGIN_DIR / onion-service-descriptor flood on a directory cache
(HSDir), with compatibility evidence from a **closed-lab
benchmark** that measures the effect on a private network and an **operator kit**
for a live pilot and staged observation cohort.

This is defensive relay hardening for the attack tracked upstream as
[tor#41339](https://gitlab.torproject.org/tpo/core/tor/-/issues/41339) and
discussed on the public `tor-relays` list and in
[network-health/analysis#113](https://gitlab.torproject.org/tpo/network-health/analysis/-/issues/113).

## The gap

In Tor 0.4.9.14, `connection_exit_begin_conn()` dispatches a `BEGIN_DIR` stream
into `connection_exit_connect_dir()` (`src/core/or/connection_edge.c:4333`)
**before** the per-circuit stream limiter at `:4340`, so `DoSStreamCreation*`
never applies to directory streams. The HS descriptor GET/POST handlers never
consult the bandwidth `write_low` check; a request only has to arrive on an
*authenticated* channel to count as "anonymous"; and an HSDir stores/serves any
validly-signed descriptor without a hash-ring responsibility or flag check. The
field data (public operator reports, and the de-identified capture in `data/`)
show the flood is **fetch** traffic (write:read ~11:1 on the attacked relay,
~180× its baseline request rate) with several `BEGIN_DIR` requests per circuit
built (~5.7 on one relay); whether single circuits carry several HS requests is
not yet established (`analysis/flood-cost-and-constrained-hosts.md`).

## The series (`patches/`)

Apply with `git am` onto Tor 0.4.9.14, upstream `main`, or `maint-0.4.9`. The
13 patches are ordered from easiest to merge upstream (bugfixes, then
observe-only MetricsPort counters) to off-by-default enforcement, one upstream
change per commit. `patches/torspec-param-spec.patch` is the companion
param-spec and rend-spec text for the four new consensus parameters.

| # | Theme | What it does | Default |
|---|---|---|---|
| 0001 | Bugfix | Log the client-triggered HTTP parser warnings at info, and rate-limit the dir server's own warning. | — |
| 0002 | Hardening | Non-authorities don't buffer a request body larger than an HS descriptor. | — |
| 0003 | Hardening | A dir server discards anything a client sends after its request. | — |
| 0004 | Hardening | Check the descriptor signature length before verifying the signing certificate. | — |
| 0005 | Bugfix | Credit an HSDir download only once the response is written out. | — |
| 0006 | Metrics | `tor_relay_hsdir_get_total{action}` and `tor_relay_hsdir_post_total{action}`: descriptor fetch and upload outcomes. | always on |
| 0007 | Metrics | `tor_relay_dir_requests_total{type}` and `tor_relay_dir_responses_total{type}`: tunneled (BEGIN_DIR) requests that aren't HS, or never parse, and responses written out. | always on |
| 0008 | Metrics | Gauge `tor_relay_dir_server_conns{state}`: tunneled dir server connections by state. | always on |
| 0009 | Refactor | Make `fill_dos_values()` table-driven (no functional change). | — |
| 0010 | Metrics | `tor_relay_dos_total` types `hsdir_request_total`, `hsdir_req_reused`, `hsdir_circ_reused`, `hsdir_unknown_prev_hop`. | always on |
| 0011 | Enforcement | `HSDirOneRequestPerCircuit` (close a circuit on its second HS request) and `HSDirRefuseUnknownPrevHop` (503 if the previous hop isn't a known relay). AUTOBOOL torrc options over consensus parameters of the same name. | **off** |
| 0012 | Enforcement | `DoSBeginDirLimitEnabled` and `DoSBeginDirMaxStreams` (20): refuse a BEGIN_DIR on a circuit that already has that many open directory streams. Counted as `begindir_over_max`. | **off** |
| 0013 | Enforcement | `HSDirDescriptorFetchLimit` with `HSDirDescriptorFetchRate` (5/s) and `HSDirDescriptorFetchBurst` (20): per-descriptor fetch limit. Torrc only, because anyone can use up a descriptor's shared bucket. Counted as `hsdir_fetch_over_rate`. | **off** |

The metrics (0006–0010) only count, and count only tunneled (linked)
connections, so DirPort traffic stays out. Each defense (0011–0013) counts what
it would refuse whether or not it is enabled, so operators can measure before
enabling it; enabled defenses apply on public relays only, and the DoS
heartbeat shows their counts. Enabling one takes `SETCONF` or a reload, with no
restart.

Upstream merge requests, each built from fresh `main`: 0001–0003 (0002 needs
0001's context), 0004, 0005, then the stack 0006–0010 on 0005, and each of
0011, 0012 and 0013 on top of that for separate discussion. The commits are
upstream style (`subsystem: Summary`, `changes/` entries that pass
`lintChanges.py`, `check-spaces` clean). Each commit builds with
`--enable-fatal-warnings` and passes `make test`. They add no new
`practracker` problem kinds, but they grow three functions and two files that
stock already lists as over the limit.

`packages/` holds the `+tor41339.4` `.deb`s for Ubuntu 24.04 and 26.04, built
from all 13 patches with every defense off (see `packages/BUILD-INFO.txt`). The
earlier `+tor41339.3` canary packages were built from a legacy 7-patch series
that exported only the four `hsdir_*` counters of 0010 and the 0011 rules. See the [final canary plan](operator/CANARY-MEASUREMENT-PLAN.md) for
a native Ubuntu 26.04 build supplied by the designated builder agent, one pilot
on vipopen followed by staged expansion toward half its relays, and 7–14 usable
HSDir days of passive collection per patched member. Stock references remain
unchanged; later enforcement trials retain contemporaneous **patched-off
controls** on the same pinned build. This plan is documentation, not runtime
authorization or a fresh build/release-readiness attestation. See the
[native build handoff](operator/NATIVE-26.04-BUILD-HANDOFF.md); the older Noble
package is historical evidence, not an automatic fallback for this rollout.

The live study asks whether the rules improve **resource efficiency while
preserving or improving legitimate-client outcomes within the measured scope**.
The supplied comparative snapshot showed high directory activity without
exceptional CPU/RSS pressure or queue accumulation relative to peers; overload
and attack-attributable cost must be measured, not assumed. Lower request or
byte volume alone is not success. **No detectable benefit and regression are
valid outcomes**, with inconclusive reserved for insufficient evidence; all
comparisons retain uncertainty and client-impact guardrails.

## Measured results

**Closed-lab benchmark (`simulator/results/offvson-report-x86.md`).** A
loopback-only chutney net (4 dir auths, 6 HSDir relays, 3 onion services, stock
+ load clients), matrix of enforcement × load, 3 reps × 60 s, 80 cells:

These results were measured on the legacy 7-patch series, whose two rules are
now 0011.

- **The previous-hop rule refuses the unlisted-relay one-hop vector:** one-hop fetches from a
  self-minted (unpublished) relay go **100% → ~3% served** under it, counter
  `hsdir_unknown_prev_hop` firing, **legit traffic 1.000**.
- **The one-request-per-circuit rule caps circuit reuse:** under 5- and
  22-request reuse the HSDir serves at most one descriptor per circuit, so the
  pipelining test client records **~0% received** — a client-side artifact (the
  circuit-close on request #2 tears down request #1's in-flight response), not
  the defense serving nothing; served-byte volume at the target drops
  **−81% (reuse-22) / −67% (reuse-5)** within-build, while the stock
  one-request-per-circuit client stays **100% successful**.
- **Stock traffic is untouched:** one-request-per-fresh-circuit and the
  post-defense "adapted" attacker shape are **100% served under every mode**,
  including both-enforcing in this lab matrix. These results do not establish
  population-wide client compatibility or full-build equivalence to stock.
- **Legit preservation:** stock-client success **1.000 across all 24 valid
  enforcement cells**.

**Previous-hop rule false-positive bound (`analysis/prevhop-false-positive.md`).**
2,416 legitimate HS fetches, **0 false refusals** (`hsdir_unknown_prev_hop`
delta 0). This sample and the model do not establish the live canary's
legitimate-client failure rate; report controlled-client evidence separately.

**amd64 build + seccomp (`engineering/`, `simulator/results/seccomp-*`).**
Native amd64 build, full unit suite, upstream CI matrix, and installable
`.deb`s for Ubuntu 24.04 and 26.04 (same patches and build configuration).
Under `Sandbox 1` the legacy series' enforcement branches (circuit close /
503 refusal, the same kinds of action 0011–0013 take) add **no sandbox-denied syscall** — confirmed by an strace EPERM
audit, with the method validated against a known startup EPERM and the
pre-existing tor#41060 SIGTERM bug.

**Crash-at-scale review (`operator/patch-crash-at-scale-critique.md`):**
**0 critical / 0 high** findings for the legacy 7-patch series (now 0001–0005
plus the 0010 counters and 0011 rules). The new metrics (0006–0008) and 0012–0013
have not had that review.

See `analysis/claims-ledger.md` for the adjudicated claim ledger and its
corrections.

## Benchmark (`simulator/`)

A closed, **loopback-only** chutney test network (its own directory authorities
and consensus; no connection to the real Tor network) that drives a controllable
rate of ordinary HS descriptor requests to one target HSDir and measures, off vs
on, the served-response volume and the stock client's success rate. The "load"
is only a high rate of normal, well-formed requests on throwaway nodes you
created — there is no exploit and nothing that targets the real network. Design
in `simulator/SIMULATOR.md`; harness in `simulator/scripts/`; the test-only load
client and control-port driver are `simulator/loadclient-testonly.diff` and
`simulator/ctl.py`. Absolute rates are not real-flood-representative (6-relay
net); the ratios are the valid outputs, and `data/` grounds the attack *shape*.

## Operator kit (`operator/`)

Start with [the final plan](operator/CANARY-MEASUREMENT-PLAN.md). The kit includes
[deployment and incident procedures](operator/DEPLOY-AND-MEASURE.md),
[measurement and report definitions](operator/capture-and-validate-playbook.md),
[the operator handoff](operator/operator-agent-prompt.md), and
[future probe-helper acceptance tests](operator/probe-helper-acceptance.md).
The helper specification is **not implemented or tested** by this documentation
update. Passive collection comes first; any controlled probe/enforcement trial
requires a separate human decision. Keep the same native artifact and metric
set across patched members and modes. Rollout is one pilot, then small
approved batches toward half of vipopen's relays; retain stock references and
patched-off controls. No handoff counters or extra C telemetry are planned.

## Live capture (`data/`)

`realflood-capture.json` — a **de-identified** capture from live relays during
the flood (opaque `relay_A/B/C` labels; fleet-inventory counts redacted; all
rates/ratios retained). It is what the simulator's attacker shape is tuned
against. `analysis/realflood-capture-interpretation.md` reads it, including which
quantities the stock (unpatched) counters can and cannot establish.

## Layout

```
patches/       the 13-patch series (git am) + torspec patch
simulator/     closed-lab benchmark: design, harness (scripts/), results/
operator/      count-only canary + capture playbook + crash-at-scale review
analysis/      claim ledger, previous-hop FP measurement, live-capture interpretation,
               flood cost on an HSDir and constrained hosts
data/          de-identified live-relay flood capture (JSON)
engineering/   amd64 build-check, CI matrix, seccomp audit, .deb build + install
packages/      the built .debs for Ubuntu 24.04 and 26.04 (+ geoipdb), SHA256SUMS, buildinfo/changes
```

## Scope

Defensive relay hardening only. The patches and the benchmark exist to protect
directory caches; the benchmark runs only in a private lab. Intended for
coordinated upstreaming to the Tor Project.
