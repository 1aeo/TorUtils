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
~180× its baseline request rate) that reuses one circuit for many descriptor
requests.

## The series (`patches/`)

Apply with `git am` onto Tor 0.4.9.14, upstream `main`, or `maint-0.4.9`. This
is the reordered series proposed upstream (the low-risk previous-hop check
first); `patches/torspec-param-spec.patch` and `patches/torspec-draft.txt` are
the companion consensus-parameter and rend-spec-v3 text.

| # | What it does | Default |
|---|---|---|
| 0001 | HS descriptor requests must arrive from a *known* relay previous hop, as exits have required since 0.2.2. Independent of `RefuseUnknownExits`. | enforcement **off** (count-only) |
| 0002 | At most one onion-service directory request per circuit (the stock-client invariant). Counts reuse; optionally closes the circuit. | enforcement **off** (count-only) |
| 0003 | Rate-limit / down-level the malformed-HTTP-request warnings a dir server logs. | — |
| 0004 | Non-authorities don't buffer an upload body larger than an HS descriptor; reject an oversized declared `Content-Length` at once. | — |
| 0005 | A dir server discards anything a client sends after its request. | — |
| 0006 | Check the descriptor signature length before the Ed25519 certificate verification. | — |
| 0007 | Credit an HSDir "download" only once the response is fully written out. | — |

Both behavioral defenses (0001, 0002) ship **observe-only**: a binary with no
consensus or torrc opinion only *counts* (the DoS heartbeat line plus four
`tor_relay_dos_total{type="hsdir_*"}` MetricsPort counters: `hsdir_circ_reused`,
`hsdir_req_reused`, `hsdir_request_total`, `hsdir_unknown_prev_hop`) and never
closes a circuit or refuses a request. Each has
independent controls — a torrc `AUTOBOOL` option overriding a consensus
parameter overriding the count-only default — so operators and the directory
authorities can measure before enabling enforcement, and the enforcement toggle
uses live `SETCONF` with **no restart** in the canary runbook (the configuration
mechanism also supports reloads; see `analysis/prevhop-false-positive.md`).
`connection_edge.c` is untouched.

The accepted experiment keeps **all seven patches** as one fixed baseline.
Patches 0003–0007 remain active when defenses 0001/0002 are disabled; the full
build is not behaviorally identical to stock. The existing four counters remain
unchanged. See the [final canary plan](operator/CANARY-MEASUREMENT-PLAN.md) for
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

The series is written to upstream conventions: one single-pass HS-request guard
(`connection_dir_allow_hs_request()`) for GET and POST, consensus parameters
cached in `set_dos_parameters()` (O(1) per-request check), table-driven
MetricsPort registration, rate-limited `LOG_PROTOCOL_WARN` diagnostics on
enforced rejections, and **zero** `practracker` exceptions.

## Measured results

**Closed-lab benchmark (`simulator/results/offvson-report-x86.md`).** A
loopback-only chutney net (4 dir auths, 6 HSDir relays, 3 onion services, stock
+ load clients), matrix of enforcement × load, 3 reps × 60 s, 80 cells:

- **0001 refuses the unlisted-relay one-hop vector:** one-hop fetches from a
  self-minted (unpublished) relay go **100% → ~3% served** under 0001, counter
  `hsdir_unknown_prev_hop` firing, **legit traffic 1.000**.
- **0002 caps circuit reuse at the one-per-circuit floor:** under 5- and
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

**0001 false-positive bound (`analysis/prevhop-false-positive.md`).**
2,416 legitimate HS fetches, **0 false refusals** (`hsdir_unknown_prev_hop`
delta 0). This sample and the model do not establish the live canary's
legitimate-client failure rate; report controlled-client evidence separately.

**amd64 build + seccomp (`engineering/`, `simulator/results/seccomp-*`).**
Native amd64 build, full unit suite, upstream CI matrix, and installable
`.deb`s for Ubuntu 24.04 and 26.04 (same patches and build configuration).
Under `Sandbox 1` the new enforcement branches (circuit close /
503 refusal) add **no sandbox-denied syscall** — confirmed by an strace EPERM
audit, with the method validated against a known startup EPERM and the
pre-existing tor#41060 SIGTERM bug.

**Crash-at-scale review (`operator/patch-crash-at-scale-critique.md`):**
**0 critical / 0 high** findings; the series is cleared for the count-only
canary. Re-verified after the call-order fix and the upstream-polish refactor
(addendum at the top of the critique).

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
requires a separate human decision. Keep the same native artifact and four
counters across patched members and modes. Rollout is one pilot, then small
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
patches/       the 7-patch series (git am) + torspec text
simulator/     closed-lab benchmark: design, harness (scripts/), results/
operator/      count-only canary + capture playbook + crash-at-scale review
analysis/      claim ledger, 0002 FP measurement, live-capture interpretation,
               flood cost on an HSDir and constrained hosts, tor#41350 gauge
               analysis and its adversarial review
data/          de-identified live-relay flood capture (JSON)
engineering/   amd64 build-check, CI matrix, seccomp audit, .deb build + install
packages/      the built .debs for Ubuntu 24.04 and 26.04 (+ geoipdb), SHA256SUMS, buildinfo/changes
upstream/      tor#41350 opened-connection gauge fix (patch, test results, offline
               lab, GitLab comment)
```

## Scope

Defensive relay hardening only. The patches and the benchmark exist to protect
directory caches; the benchmark runs only in a private lab. Intended for
coordinated upstreaming to the Tor Project.
