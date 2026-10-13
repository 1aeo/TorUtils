# tor#41339 — HSDir onion-service-descriptor flood: defensive patch series

A small, upstreamable patch series for **Tor 0.4.9.14** that bounds the resource
cost of the 2026 BEGIN_DIR / onion-service-descriptor flood on a directory cache
(HSDir) while preserving all legitimate directory traffic, plus a **closed-lab
benchmark** to measure the effect without waiting for live-network data.

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
field data (public operator reports) show the flood is **fetch** traffic
(write:read ~170:1) that reuses one circuit for many descriptor requests.

## The series (`patches/`)

Apply with `git am` onto Tor 0.4.9.14, upstream `main`, or `maint-0.4.9`.

| # | What it does | Default |
|---|---|---|
| 0001 | At most one onion-service directory request per circuit (the stock-client invariant). Counts reuse; optionally closes the circuit. | enforcement **off** (count-only) |
| 0002 | HS descriptor requests must arrive from a *known* relay previous hop, as exits have required since 0.4.2.1-alpha. | enforcement **off** (count-only) |
| 0003 | Rate-limit / down-level the malformed-HTTP-request warnings a dir server logs. | — |
| 0004 | Non-authorities don't buffer an upload body larger than an HS descriptor; reject an oversized declared `Content-Length` at once. | — |
| 0005 | A dir server discards anything a client sends after its request. | — |
| 0006 | Check the descriptor signature length before the Ed25519 certificate verification. | — |
| 0007 | Credit an HSDir "download" only once the response is fully written out. | — |

Both behavioral defenses (0001, 0002) ship **observe-only**: a binary with no
consensus or torrc opinion only *counts* (heartbeat + `tor_relay_dos_total`
MetricsPort metric) and never closes a circuit. Each has independent controls —
a torrc `AUTOBOOL` option overriding a consensus parameter overriding the
count-only default — so operators and the directory authorities can measure
before enabling enforcement, and 0002 is fully independent of
`RefuseUnknownExits`. `connection_edge.c` is untouched.

See `patches/torspec-draft.txt` for the companion param-spec and rend-spec-v3
text.

## Status / evidence

Verified on aarch64 (native amd64 is still pending — see `HANDOFF.md`):
full unit suite green on `main` and `maint-0.4.9`; behavioral mutation testing;
upstream CI jobs (make check, distcheck, hardened ASan/UBSan, module-disabled,
gpl, nss, docs, chutney integration 8/8 flavours); ~378M-exec fuzzing of the
touched parsers with no findings; an installable deb.torproject.org noble `.deb`
with the new metric live and enforcement off by default. The adjudicated claim
ledger (31 PROVEN / 10 PARTLY / 0 REFUTED) and its corrections are in
`analysis/claims-ledger.md`.

**First lab result (`simulator/results/`).** A closed arm64 chutney run
(`micro_bench.txt`) shows the mechanism working: with enforcement **off**
(default), a circuit-reusing client's 5 and 22 descriptor fetches are all served
and nothing is closed; with enforcement **on**, the reusing client gets **0**
served (the circuit is closed on its second request) while a **stock
one-request-per-circuit client still completes 22/22 fetches with 0 failures**.
So the circuit-reuse multiplier collapses to ~1 request/circuit with no
collateral to legitimate traffic. This is a small arm64 proof-of-mechanism, not
a scaled measurement: absolute CPU/byte numbers are not x86-representative, and
the broader `matrix-results.csv` had flaky cells (chutney consensus timing under
load). The scaled measurement, the attacker-adaptation cost, and the amd64 +
seccomp numbers are the x86 tasks in `HANDOFF.md`. Any "% reduction" figure in
the analysis remains a conditional upper bound, not a measured counterfactual.

## Benchmark (`simulator/`)

A closed, **loopback-only** chutney test network (its own directory
authorities and consensus; no connection to the real Tor network) that drives a
controllable rate of ordinary HS descriptor requests to one target HSDir and
measures, off vs on, the served-response volume and CPU **and** the stock
client's success rate. The "load" is only a high rate of normal, well-formed
requests on throwaway nodes you created — there is no exploit and nothing that
targets the real network. Design in `simulator/SIMULATOR.md`; the test-only
load client and control-port driver are `simulator/loadclient-testonly.diff`
and `simulator/ctl.py`.

## Continuing the work

`HANDOFF.md` is a self-contained prompt for continuing on native x86-64 Linux
(amd64 build + seccomp sandbox + native CI, the simulator at scale, and the
0002 consensus-churn false-positive measurement).

## Scope

Defensive relay hardening only. The patches and the benchmark exist to protect
directory caches; the benchmark runs only in a private lab. Intended for
coordinated upstreaming to the Tor Project.
