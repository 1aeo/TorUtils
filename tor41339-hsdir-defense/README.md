# tor#41339 — HSDir onion-service-descriptor flood: defensive patch series

A small, upstreamable patch series for **Tor 0.4.9.14** that makes the 2026
BEGIN_DIR / onion-service-descriptor flood on a directory cache (HSDir)
measurable and, with off-by-default defenses, lets an HSDir refuse the parts of
it that stock clients never send and cap the descriptor bytes it serves. It
comes with compatibility evidence from **closed-lab** runs on a private network
(including stock C tor and Arti clients) and an **operator kit** for a live
pilot and staged observation cohort. It does not change the main-thread cost of
tearing down many short-lived directory connections; a separate proposal
(connection-list indexing) addresses that.

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
are consistent with **fetch** traffic (write:read ~11:1 on the attacked relay,
~180× its baseline request rate) with several `BEGIN_DIR` requests per circuit
built (~5.7 on one relay; `analysis/flood-cost-and-constrained-hosts.md`).
One relay's count-only counters, posted to tor-relays on 22 October 2026,
showed single circuits carrying several HS requests: 84% of its HS requests
came on a circuit that had already made one, all from authenticated previous
hops (`analysis/begindir-questions.md`). Whether fetches concentrate on a few
descriptors is not yet established.

## The series (`patches/`)

Apply with `git am` onto Tor 0.4.9.14, upstream `main`, or `maint-0.4.9`.
Patches 0001–0015 are ordered from easiest to merge upstream (bugfixes, then
observe-only MetricsPort counters) to off-by-default enforcement, one upstream
change per commit. 0016–0023 are the `.7` metrics for the network team's
questions (`analysis/metrics-proposal.md`). `patches/torspec-param-spec.patch`
is the companion param-spec and rend-spec text for the six new consensus
parameters.

| # | Theme | What it does | Default |
|---|---|---|---|
| 0001 | Bugfix | Log the client-triggered HTTP parser warnings at info, and rate-limit the dir server's own warning. | — |
| 0002 | Hardening | Non-authorities don't buffer a request body larger than an HS descriptor. | — |
| 0003 | Hardening | A dir server discards anything a client sends after its request. | — |
| 0004 | Hardening | Check the descriptor signature length before verifying the signing certificate. | — |
| 0005 | Bugfix | Credit an HSDir download only once the response is written out. | — |
| 0006 | Metrics | `tor_relay_hsdir_fetch_total{action}` and `tor_relay_hsdir_upload_total{action}`: descriptor fetch and upload outcomes. | always on |
| 0007 | Metrics | `tor_relay_begindir_request_total{type}` and `tor_relay_begindir_response_total{type}`: tunneled (BEGIN_DIR) requests that aren't HS, or never parse, and responses written out. | always on |
| 0008 | Metrics | Gauge `tor_relay_begindir_connections{state}`: tunneled dir server connections by state. | always on |
| 0009 | Refactor | Make `fill_dos_values()` table-driven (no functional change). | — |
| 0010 | Metrics | `tor_relay_dos_total` types `hsdir_req_reused`, `hsdir_circ_reused`, `hsdir_unknown_prev_hop`: repeated requests on one circuit, the circuits that repeat them, and requests whose previous hop isn't a known relay. | always on |
| 0011 | Enforcement | `HSDirOneRequestPerCircuit` (close a circuit on its second HS request) and `HSDirRefuseUnknownPrevHop` (503 if the previous hop isn't a known relay). AUTOBOOL torrc options over consensus parameters of the same name. Refusals are counted as action `refused` of the 0006 families. | **off** |
| 0012 | Enforcement | `DoSBeginDirLimitEnabled` and `DoSBeginDirMaxStreams` (64): refuse a BEGIN_DIR on a circuit that already has that many open directory streams. Counted as `begindir_over_max`. | **off** |
| 0013 | Metrics | Per-descriptor fetch bucket (`HSDirDescriptorFetchRate` 5/s, `HSDirDescriptorFetchBurst` 20), kept when a descriptor is replaced; fetches over it are counted as `hsdir_fetch_over_rate`. Compared with `hsdir_fetch_total{action="success"}`, it shows whether a flood concentrates on a few descriptors. Never refuses. | always on |
| 0014 | Enforcement | `HSDirFetchShedding` (AUTOBOOL over a consensus parameter) and `HSDirFetchBudget` (descriptor bytes an HSDir may be asked for per second; 0 = `HSDirFetchBudgetPercent`, default 50, of min(configured, observed bandwidth), at least 512 KB): shed descriptor fetches by closing their circuits once a second goes over the budget. No fetch is refused until then. In the second after, fetches within their descriptor's rate are answered first (up to half the budget) and the others by a lottery aimed at the budget; no second answers more than 1.5× the budget. Counted as `hsdir_fetch_pressure` and `hsdir_fetch_shed` either way; the heartbeat names the fetches selected for shedding. | **off** |
| 0015 | Hardening | Reject a declared `Content-Length` that can never fit as soon as the headers arrive, instead of waiting for the bytes (every `fetch_from_buf_http()` caller that doesn't accept a partial body). | — |
| 0016 | Metrics | Classify each circuit's previous hop when its CREATE cell arrives (`client`, `known_relay`, `unknown_relay`). `tor_relay_create_cell_total{prev_hop}`, `tor_relay_begindir_cell_total{prev_hop,nth}` (every BEGIN_DIR cell, by its place on its circuit: `1`, `2_10`, `11_100`, `101_1000`, `1001_plus`), and `tor_relay_begindir_request_total{type,prev_hop}`, which now counts each accepted stream's request once, by what it asked for, onion service requests included; action `circuit_dead`. | always on |
| 0017 | Metrics | `tor_relay_dos_total{type="circuit_over_rate"}`: client CREATE cells that find their address's `DoSCircuitCreationRate`/`Burst` bucket empty, marked or not; and `{type="circuit_untracked"}`: those from addresses tor no longer tracks, which `DoSCircuitCreation` doesn't limit. Both counted only while `DoSCircuitCreationEnabled` is on. | always on |
| 0018 | Metrics | `tor_relay_begindir_response_bytes_total{type}`: response bytes their stream read, by request type. Splits `other` into `other_get` and `other_post`. | always on |
| 0019 | Metrics | `tor_relay_begindir_request_over_max_total{type}`: requests on streams over `DoSBeginDirMaxStreams`, which is what 0012 would refuse. | always on |
| 0020 | Metrics | `tor_relay_create_cell_source_total{prev_hop,nth}` and `tor_relay_begindir_cell_source_total{prev_hop,nth}`: cells by their place among their source's that minute. A source is a client address (a client channel, if tor doesn't track its address) or a relay channel. Bridges don't count these. | with a MetricsPort |
| 0021 | Metrics | `tor_relay_hsdir_fetch_descriptor_total{lookup,nth}`: descriptor fetches by their place among the same descriptor's fetches that minute, by the decoded blinded key. Only a keyed hash of each key is kept, until the first fetch of a later minute clears the table. Bridges don't count these. | with a MetricsPort |
| 0022 | Metrics | `tor_relay_dos_total{type="hsdir_descriptor_only_prev_hop"}`: onion service requests from relays known only by descriptor. | always on |
| 0023 | Metrics | `tor_relay_dos_total{type="begindir_over_stream_rate"}`: BEGIN_DIR cells over their circuit's stream creation rate, which counts but never refuses. | with a MetricsPort |

The metric names follow stock tor's: `tor_relay_<subsystem>_<thing>_total`
for counters, with a singular noun as in `tor_relay_destroy_cell_total`, and
no `_total` for a gauge; `begindir_` for tunneled directory streams, `hsdir_`
for onion service descriptor requests, labels for dimensions. The ones
marked "with a MetricsPort" do per-cell or per-fetch work (an address lookup,
a hash, a token bucket) that only the MetricsPort shows, so a relay without
one skips it.

The metrics (0006–0010, 0013, 0016–0023) only count, and count only
tunneled (linked) connections, so DirPort traffic stays out. Each defense (0011, 0012, 0014)
counts what it would refuse whether or not it is enabled, so operators can
measure before enabling it on the MetricsPort; they apply only on public
relays, and the DoS heartbeat shows their counts while they are enabled.
Enabling one takes `SETCONF` or a reload, with no restart.

**Why 0014 sheds only over a budget.** An earlier 0013 refused every fetch
over a descriptor's own rate. That protected the relay from a flood of a few
descriptors, but it refused fetches even on an idle relay: anyone could keep
one descriptor unavailable at that HSDir with about 6 fetches a second, and
learn second by second how often others fetched it. 0014 refuses nothing
until the relay is over its budget, so denying a descriptor there takes about
as much load as overloading the relay does in stock; once over, the flooded
descriptors are shed before the others. While it sheds, someone who keeps the
HSDir over its budget can still learn roughly how often a descriptor is
fetched there, and a flood spread over many descriptors (an HSDir stores any
validly signed descriptor) is shed by the lottery like any other, at the
budget. A shed fetch closes the circuit rather than answering 503, so
clients retry another HSDir at once without treating this relay as busy for
an hour; see the client lab below.

Upstream merge requests, each built from fresh `main`: 0001–0003 (0002 needs
0001's context), 0004, 0005, then the stack 0006–0010 on top of 0001–0005
(0007's context includes a line from 0003), then 0011, 0012, 0013 and 0014,
each on the one before (0012 reuses 0011's option helper), for separate
discussion, 0015 on 0002 (its test extends 0002's), and 0016–0023 as one
stack on top. The commits are upstream style (`subsystem: Summary`; three
`changes/` files, for the hardening, the metrics and the DoS options, to
which each commit adds its own entries and which pass `lintChanges.py`;
`check-spaces` clean; the man page renders without asciidoc warnings). Each commit builds with `--enable-fatal-warnings` and passes
`make test`. They add no new `practracker` problem kinds; 0014 raises the
`dos.c` dependency-violation exception from 6 to 8 for its two bandwidth
includes. The series grows functions and files that
stock already has over the limit, among them `connection_exit_begin_conn()`,
`command_process_create_cell()`, `connection_edge.c` and `rephist.c`; the
set of problems practracker reports is the same as stock's.

`packages/` holds the `+tor41339.7` `.deb`s for Ubuntu 24.04 and 26.04, built
from 0001–0023 with every defense off (see `packages/BUILD-INFO.txt`), plus
one Debian-only patch that keeps `.6`'s option name `HSDirDescriptorFetchLimit`
working, with a deprecation warning, as `HSDirFetchShedding`. They replace
`+tor41339.6` (0001–0015) on every relay, and also the first `+tor41339.7`
build: the version did not change, so a relay that installed that build
must reinstall. `.7` renames most of `.6`'s
metric families (the table in `analysis/v7-review.md`), counts an onion
service request that reaches a closing circuit over an authenticated channel
as the new action `circuit_dead` instead of `single_hop`, and adds families,
so dashboards should not mix the two; `operator/begindir-breakdown.py` reads
both. The
earlier `+tor41339.3` canary packages were built from a legacy 7-patch series
that exported only the four `hsdir_*` counters of 0010 and the 0011 rules. The
operator documents below were written for those canary builds; for the options
and counters of this build, see the man page and the table above. See the [final canary plan](operator/CANARY-MEASUREMENT-PLAN.md) for
a native Ubuntu 26.04 build supplied by the designated builder agent, one pilot
host followed by staged expansion, and 7–14 usable
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

**Clients under shedding (`engineering/client-lab/`, `+tor41339.6`).** A
private chutney net in one `--network none` container, stock C tor and Arti
2.7.0 clients, a load client flooding one onion service D at every HSDir
holding it, and an unloaded control onion service E; Ubuntu 24.04 and 26.04
packages. With 0014 shedding on every HSDir at 1.7–2.5× its budget, both
clients reached D on **115 of 120** requests (1.7–2.9 HSDir attempts per
success; median latency 0.37–0.63 s against 0.23–0.30 s without load) and
E on **every** request; each of the 5 failures had been shed at all 6
HSDirs the client asked. With one HSDir shedding, or with shedding off
(observe mode, where the would-be sheds were counted and nothing was
refused), every request of both clients succeeded. The lab has no capacity
limit, so it shows what clients experience when HSDirs shed, not the relay
protection that motivates it. The live controls (`engineering/deb/`) switch
every defense on and off on both packages; every tunneled BEGIN_DIR stream
lands in exactly one metric bucket in every phase.

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
A live pilot's counters (posted to tor-relays on 22 October 2026, legacy
`+tor41339.3` counters, 44–57 hours, ten relays) put `hsdir_unknown_prev_hop`
at 0.06% to 7.6% of HS requests per relay (0.54% pooled over the nine relays
not under attack, 1.8% on the attacked one), far above this lab bound. Those
requests came over authenticated channels with relay identities the HSDir
didn't know; why so many on some quiet relays is not yet explained. With
`HSDirRefuseUnknownPrevHop` on, they would be refused and retried at another
HSDir, so this needs an answer before anyone enables it.

**amd64 build + seccomp (`engineering/`, `simulator/results/seccomp-*`).**
Native amd64 build, full unit suite, upstream CI matrix, and installable
`.deb`s for Ubuntu 24.04 and 26.04 (same patches and build configuration).
Under `Sandbox 1` the legacy series' enforcement branches (circuit close /
503 refusal, the same kinds of action 0011–0013 take) add **no sandbox-denied syscall** — confirmed by an strace EPERM
audit, with the method validated against a known startup EPERM and the
pre-existing tor#41060 SIGTERM bug.

**Crash-at-scale review (`operator/patch-crash-at-scale-critique.md`):**
**0 critical / 0 high** findings for the legacy 7-patch series (now 0001–0005
plus the 0010 counters and 0011 rules). The new metrics (0006–0008) and
0012–0015 have not had that review, but have had adversarial code review,
mutation testing and the lab runs below. Nor have 0016–0023, which had the
two review rounds in `analysis/v7-review.md`, mutation testing, and the
install check, live controls and breakdown lab with the `.7` packages. (That
critique's remark that ConnLimit bounds held-open directory connections does
not hold for BEGIN_DIR pairs, which have no socket.)

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
approved batches toward half of the pilot host's relays; retain stock references and
patched-off controls. `.7` adds the metrics of
[`analysis/metrics-proposal.md`](analysis/metrics-proposal.md) (0016–0023)
and no handoff counters.

To see what a relay's BEGIN_DIR traffic is during a flood, run
[`operator/begindir-breakdown.py`](operator/BEGIN_DIR-BREAKDOWN.md) against
its MetricsPort (and, optionally, its ControlPort). It answers the questions
the Tor network team asked operators on tor-relays in October 2026, as far as
the `.7` metrics allow; [`analysis/begindir-questions.md`](analysis/begindir-questions.md)
explains what they can and cannot tell.
[`analysis/metrics-coverage.md`](analysis/metrics-coverage.md) maps ten
questions about the flood to the metrics that answer them.
[`analysis/metrics-proposal.md`](analysis/metrics-proposal.md) proposes what
to add next, and records which parts `.7` built.
[`analysis/v7-review.md`](analysis/v7-review.md) is the two-round adversarial
review of `.7`: what it found, what changed, and the mutation testing.

## Live capture (`data/`)

`realflood-capture.json` — a **de-identified** capture from live relays during
the flood (opaque `relay_A/B/C` labels; fleet-inventory counts redacted; all
rates/ratios retained). It is what the simulator's attacker shape is tuned
against. `analysis/realflood-capture-interpretation.md` reads it, including which
quantities the stock (unpatched) counters can and cannot establish.

## Layout

```
patches/       the 23-patch series (git am) + torspec patch
simulator/     closed-lab benchmark: design, harness (scripts/), results/
operator/      count-only canary + capture playbook + crash-at-scale review,
               BEGIN_DIR breakdown tool
analysis/      claim ledger, previous-hop FP measurement, live-capture interpretation,
               flood cost on an HSDir and constrained hosts, the network team's
               BEGIN_DIR questions, metrics proposal and coverage, the series
               reviews (.6 and .7), what .7 means for the cleanup-indexing work
data/          de-identified live-relay flood capture (JSON)
engineering/   amd64 build-check, CI matrix, seccomp audit, .deb build + install,
               client-lab/ (C tor and Arti clients under shedding),
               breakdown-lab/ (checks the BEGIN_DIR breakdown tool),
               v7-review/ (per-commit results and mutation testing of .7's
               two review rounds; fixes for two stock tor bugs they found)
packages/      the built .debs for Ubuntu 24.04 and 26.04 (+ geoipdb), SHA256SUMS, buildinfo/changes
```

## Scope

Defensive relay hardening only. The patches and the benchmark exist to protect
directory caches; the benchmark runs only in a private lab. Intended for
coordinated upstreaming to the Tor Project.
