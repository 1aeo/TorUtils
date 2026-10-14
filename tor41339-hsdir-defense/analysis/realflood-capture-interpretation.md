# Real-flood capture — what it tells us (and what it can't)

**Source:** a relay operator's own capture of **stock** production HSDirs during
the live tor#41339 BEGIN_DIR / HSDir-descriptor flood. Metadata only — aggregate
per-second rates and since-startup DoS counters; **no fingerprints, no client
IPs** (a multi-hop relay never sees them). Operator-confidential per-key tables
stay with the operator; only the derived aggregate and relay-A-anonymized rates
below are reproduced. **No fingerprints, IPs, or onion addresses appear here.**

**Capture envelope.** 953 relays inventoried, **60 HSDirs** instrumented; a
28-relay analysis cohort that carried the HSDir flag in both windows. Flood
window **2026-10-13 20:20–21:20 UTC** (3600 s nominal, ~3480 s observed per
relay, 29 intervals/relay), plus a matched pre-flood **baseline window**. DoS-counter
observation ~**43,200 s (12 h)**. Journal hygiene is clean: 954 notice-level
records, **0** retrieval errors, **0** malformed records, **0** warning/error
records, 180 DoS heartbeats (3/relay), **counter_decreases_detected = 0** (no
wrap/reset — the deltas are trustworthy).

**This note now reflects the FULL capture.** The earlier version was written
against a truncated flood-window object (cut off mid-key at `bytes_read_per_s`).
The untruncated capture supplies the previously-missing fields — `circuits_created/s`,
the baseline window, per-relay byte ratios, and the `gaps` field — and those
newly-available numbers change the headline: the flood is **concentrated on one
relay**, and a **valid directional reuse proxy** is now computable (§2).

**Binary provenance.** `inventory_reported_version = 0.4.9.14`,
`patched_counters_present = false`, and the two HSDir counters read `null`. The
operator binary was **stock** — not our count-only build. That one fact still
drives the "what it can't tell us" half of this note: the *clean* HS-scoped
counters do not exist here. (The source tree on this branch *does* contain those
two counters; their absence here is a cohort fact, not a measurement failure.)

---

## 1. Confirmed from stock relays — the flood is real, large, and concentrated

- **Field scale, but concentrated on ONE relay.** Cohort BEGIN_DIR summed to
  **~1,119 req/s** across the 28-relay cohort during the flood hour (against a
  cohort baseline of **~183 req/s** — only a **×6.1** aggregate rise). That
  aggregate is *not* spread evenly. **Relay A alone carried ~950 req/s** —
  **85.2 % of the cohort's circuit starts** and **×179 over its own baseline of
  ~5.3 req/s**. Relay A's 950 req/s sits by itself inside the 10³–10⁴ req/s band
  of the **public field reports**; the cohort sum ~1,119/s coincides with the
  realflood field median per flooded HSDir. **Relays B/C and the rest of the
  cohort sit near baseline** — they were included by the ranking cut (top
  BEGIN_DIR relays), **not proven attacked.** The ×6.1 aggregate is a dilution
  artifact of pooling one hammered relay with 27 quiet ones; the real signal is
  relay A's ×179.
  (All rates differenced over the flood hour from the stock MetricsPort quantity
  `relay_streams_total{type="begin_dir"}` =
  `rep_hist_get_exit_stream_seen(RELAY_COMMAND_BEGIN_DIR)`, monotonic since
  startup; rephist.c:1662, relay_metrics.c:739/754.)
- **Write-heavy byte ratio on relay A, consistent with dir-serving.** Relay A's
  **total process-wide write:read ≈ 11.4 : 1** during the flood (vs **~1.0 : 1**
  at baseline) — directionally consistent with serving many descriptor responses
  against small inbound requests. This is **process-wide `relay_traffic_bytes`,
  not dir-scoped**, so it still cannot be quoted as the field reports' ~170:1
  *directory* ratio (stock has no per-command byte counter); but the shift from
  1.0 to 11.4 on the attacked relay corroborates that relay A is the serving
  endpoint.
- **Onionskins and circuits rose on relay A** (onionskins ~177.9/s; CC circuits
  ~167.4/s — see §2) — relevant to the attacker-adaptation cost estimate, not to
  present serving load.
- **DoSStreamCreation was OFF on all 60 HSDirs.** Every heartbeat carried the
  literal `[DoSStreamCreationEnabled disabled]` clause (dos.c:1150–1156), so the
  stock per-circuit BEGIN/RESOLVE stream limiter — the *one* stock defense that
  would rate-limit per-circuit BEGIN_DIR — was disabled network-wide. This is
  **consistent with the known dispatch-order gap**: the stream defense is not
  engaging on this traffic. Consequently `stream_rejections = null`: with the
  limiter off, stock emits no `stream_num_rejected` number at all. **Absence of a
  stream-rejection signal is expected here — it is not evidence the flood is
  benign or deduplicated.**
- **The DoS subsystem *was* active**, just not on this traffic. The nonzero
  `circuit_rejected` and connection counters only print when their subsystems are
  enabled (dos.c `if (dos_cc_enabled)` guard), so DoSCircuitCreation and
  DoSConnection were ON — on **client channels**, where a relay-channel HSDir
  flood never lands (see §4).

### The DoS rejection counters — what each one actually means

| Capture field | Value | Metric / symbol | What it counts | Scope |
|---|---|---|---|---|
| `circuit_creation_rejection_events` | **7,055,980** | `cc_num_rejected_cells` · `tor_relay_dos_total{type="circuit_rejected"}` | CREATE/CREATE2 cells **refused** because the source **client** IP was already marked a circuit-creation DoS source. **Not** a count of circuits created. | **client channels only** (dos.c:545, 746) |
| `concurrent_connection_rejections` | **207,610** | `conn_num_addr_rejected{type="concurrent_conn_rejected"}` (dos.c:858) | New conns refused: a client IP over the max concurrent OR-connection count. | client (GEOIP_CLIENT_CONNECT) |
| `connection_rate_rejections` | **1,038** | `conn_num_addr_connect_rejected{type="conn_rejected"}` (dos.c:846) | New conns refused: a client IP over the per-second **connect rate**. | client |
| `circuits_killed_for_cell_queue_limit` | **985** | `stats_n_circ_max_cell_reached{type="circuit_killed_max_cell"}` (relay.c:3492; dos.c:1115) | Circuits killed for per-circuit **cell-queue overflow**, either direction. Coarse last-resort kill. | **ungated — any circuit, incl. relay channels** |
| `INTRODUCE2_rejections` | **1** | `hs_dos intro2_rejected_count{type="introduce2_rejected"}` (hs_dos.c:210) | INTRODUCE2 cells dropped at an onion-service **introduction point**. | intro-point — **not HSDir**, unrelated to this flood |
| `single_hop_client_refusals` | **0** | `num_single_hop_client_refused{type="single_hop_refused"}` (dos.c:1029) | Refused single-hop ESTABLISH_RENDEZVOUS clients. | client (defense inactive) |
| `relays_reporting_DoSStreamCreationEnabled_disabled` | **60 / 60** | literal `[DoSStreamCreationEnabled disabled]` clause | Not a number — the stream limiter was **off** on every HSDir. | — |
| **ρ** `reuse_fraction` (clean) | **null** | `num_hsdir_circ_reused{type="hsdir_circ_reused"}` | Circuits making a 2nd+ HS-dir request. | **PATCH 0001 only — absent on stock** |
| **φ** `unknown_prev_hop_fraction` | **null** | `num_hsdir_unknown_prev_hop{type="hsdir_unknown_prev_hop"}` | HS-dir requests whose previous hop is not a known relay. | **PATCH 0002 only — absent on stock** |

Of these, only `circuits_killed_for_cell_queue_limit` can be driven by the
relay-channel flood (it is not client-gated) — and at **985 over 12 h** it is
negligible against relay A's ~950 req/s. Every other nonzero counter is a
**client-facing guard-role** signal (circuit-creation refusals, connection
floods) that is **orthogonal** to the HSDir BEGIN_DIR flood and must not be
compared to it (see §4).

---

## 2. NEW — a valid directional reuse proxy: ~5.7 requests per circuit on relay A

The full capture adds `circuits_created/s`, which lets us form a proxy the
truncated version could not:

> **ρ_proxy = BEGIN_DIR/s ÷ CC-circuits-created/s.**
> On relay A during the flood: **950 ÷ 167.4 = 5.69** requests per circuit.
> At baseline on the same relay: **0.52**. That is an **~11×** rise.

The two field deltas agree independently: BEGIN_DIR rose **×179** while
CC-circuits-created rose only **×16.5** (179 / 16.5 = 10.85 ≈ 11). Requests grew
an order of magnitude faster than circuits — the signature of **circuit reuse**:
during the flood each circuit carried ~5–6 descriptor fetches instead of ~0.5.

### What `cc_circuits_created` actually counts (verified in source)

`tor_relay_congestion_control_total{state="cc_circuits",action="circs_created"}`
is the global `cc_stats_circs_created` (declared congestion_control_common.c:132,
extern in `.h:85`), incremented **exactly once** per `congestion_control_new()`
at **congestion_control_common.c:418**, and published via relay_metrics.c:547–553.
Relay-side it is driven from **cpuworker.c:446–454**, gated on
`rpl.circ_params.cc_enabled` — i.e. only for circuits where the client requested
congestion control in the ntor-v3 handshake **and** the consensus allows it
(`congestion_control_enabled()`, common.c:346–365, true whenever consensus
`cc_alg != CC_ALG_SENDME`, line 364). Key properties:

- It is a **SUBSET** of circuits, not all of them — only **CC-negotiated** ones.
  CREATE_FAST/one-hop and TAP/plain-ntor circuits are excluded.
- It counts at **ANY position** the relay occupies (guard/middle/exit/HSDir):
  `use_congestion_control` is set per-hop in extendinfo.c:62–64 from
  protover+consensus **only** — **no position or purpose filter.** It is **not
  HSDir-specific.**
- In **0.4.9 nearly every created circuit is CC-negotiated** by consensus
  default. Empirically on relay A, cc-circs **167.4/s ≈ 0.94 × onionskins
  177.9/s**, so on the attacked relay `cc_circuits_created` ≈ *all* created
  circuits minus a ~6 % non-CC tail. It is a reasonable, slightly-low denominator.

### Proxy validity — verdict: **VALID-DIRECTIONAL** (both independent analyses concur)

The proxy is a directionally-valid estimator of HS-dir-requests-per-circuit **on
relay A specifically**, because both terms are flood-dominated and the residual
biases are small, known in sign, and largely offsetting:

- **Numerator** (950/s) over-counts true HS requests by including non-HS
  BEGIN_DIR, but the flood is ~99.4 % of begin_dir (950 vs 5.3 baseline), so
  contamination is <1 % and biases ρ **up** by <1 %.
- **Denominator** (167.4/s) counts CC objects for **all positions**, so it
  includes ~10/s of background guard/middle/exit CC circuits unrelated to the
  flood (baseline 10.15/s) — ~6 % of 167.4, biasing ρ **down** by ~6 %.
- The two main biases are small and **opposite**, so 5.69 is a slight
  net-understatement-to-flat estimate. The qualitative signal (0.52 → 5.69, ~11×)
  dwarfs the few-percent bias bands.

**Scope condition (load-bearing).** This holds **only on the relay that is the
flood's HSDir** — relay A, identified as the last hop because it absorbs the
950/s BEGIN_DIR as the dir-stream endpoint. There the flood circuits *terminate*,
so the CC-circuit count equals flood circuits ending there. **On a relay that is
merely a guard/middle for the flood, cc-circs would be inflated with no matching
BEGIN_DIR and the proxy is INVALID.** This is exactly why the **cohort aggregate
ρ (2.59) is lower than relay A's 5.69** — aggregation pools HSDir-role BEGIN_DIR
with guard/middle-role CC circuits. **Use the per-attacked-relay 5.69, never the
cohort aggregate.**

### Expected effect of patch 0001 (circuit-reuse cap) — ~82 %, proxy-grounded

If 0001 caps serving at ~1 response per circuit, served HS-dir responses/circuit
fall from ~5.69 to ~1:

> **1 − 1/5.69 = ~82 % reduction** in served dir responses (band **~78–84 %**),
> i.e. served drops from **~950/s to ~167/s** on relay A, assuming 0001 limits
> per-circuit serving and leaves the circuit-creation rate (167.4/s) unchanged.

Lab corroboration (`sim-offvson-report.md`): ρ≈5.7 maps to the **reuse-5/reuse-6**
cell; 0001 drove the reuse-5 / reuse-22 cells to within-build byte reductions of
**66 % / 81 %** with legit success **1.000** (zero measured collateral). The lab's
headline "100 % served-collapse" is a **back-to-back-firing timing artifact** (it
tears down the still-in-flight first response); the realistic **serve-1-then-close**
model gives the ~82 % here. (Sim mapping is inferred from the reuse-n convention;
confirm against the actual sim reuse-n table — the simulator source was not read
in this session.)

**Treat ~82 % as a central figure in a wide band, not a measurement, and note
two honest downside risks:**

1. **This is an estimate of served-response cut, not necessarily of attacker
   request volume.** If the attacker adapts to **1 request per fresh circuit**,
   0001 does not reduce request count — it raises attacker cost **~5.7×** by
   forcing a full 3-hop ntor-v3 circuit build (onionskin/CPU) per request. The
   benefit is converting cheap circuit-reuse flooding into expensive per-request
   circuit building; that load then falls on middle-relay circuit creation, which
   DoSCircuitCreation does **not** cover on relay channels.
2. **HS-scope vs non-HS reuse (tension with proven K7/K8).** K7/K8: stock C Tor
   (ISO_STREAM) and Arti use **one fresh circuit per HS-dir request and never
   reuse it**. If the measured reuse were legitimate-client traffic it would be
   non-HS one-hop (ISO_SESSIONGRP) document fetches — which 0001 does **not**
   touch — and 0001's HS benefit could approach 0. The resolution: the flood
   client is **custom attacker code**, not stock C Tor / Arti, and *can* reuse
   circuits for HS-dir fetches (0001's scope). Which it is cannot be decided from
   `begin_dir` (it conflates HS and non-HS). **The clean `hsdir_circ_reused`
   counter from the count-only build is exactly what disambiguates this** (§3).
   Overload-driven drops before 0001 (if relay A is already shedding some of the
   950/s) would also shrink the realized reduction below 82 %.

---

## 3. The clean ratios are STILL unmeasured — ρ-distribution and φ

The proxy in §2 gives **direction and rough order**. It does **not** give the two
clean quantities that decide 0001/0002 fidelity to *this* flood:

- **ρ is a mean, and its distribution is unmeasured.** 5.69 could be a uniform
  ~6-reuse, or a few heavily-reused circuits plus many single-use ones. 0001's
  effect — and how often it fires — differs between those and **cannot be
  predicted from the mean alone.** The clean per-circuit distribution needs
  `num_hsdir_circ_reused` (patch **0001**, commit `0f7621b6ed`, directory.c:299),
  which counts even in observe mode (`hsdir_one_request_per_circ=0`).
- **φ (unknown-previous-hop) is `null` on stock — 0002's applicability is
  UNMEASURED.** `num_hsdir_unknown_prev_hop` (patch **0002**, commit `71efaa5f1f`,
  directory.c:357) does not exist in stock 0.4.9.14. **This capture cannot decide
  whether 0002 helps this operator's flood.** Do not read the `null` as "no
  unknown-prev-hop."

Both are **null-for-absence, not null-for-zero.** No stock counter substitutes:
the proxy stands in for ρ's order of magnitude but not its distribution, and
there is **no** proxy for φ at all.

> **Bottom line for this section:** 0001 now has **proxy-level support** for this
> flood (ρ_proxy ≈ 5.7, ~82 % expected served-response reduction). 0002 remains
> **unmeasured** on this operator. Both clean ratios — and the HS-vs-non-HS
> attribution that bounds 0001's real benefit — are produced only by the
> count-only build (§5).

---

## 4. The circuit-REJECTION signal — verdict STILL **INVALID** (a different proxy)

The §2 reuse proxy (BEGIN_DIR ÷ CC-circuits-created) is valid-directional. **It
must not be confused with the earlier, invalid circuit-rejection proxy, which
remains retracted.**

**Retracted hypothesis:** *"circuit_creation_rejection_events (~2.7/s/relay) is
tiny next to BEGIN_DIR, therefore the flood heavily reuses circuits."*

**Verdict: INVALID.** The arithmetic is real (7,055,980 ÷ 43,200 s ÷ 60 =
2.72/s/relay vs ~950/s) but the inference does not follow, for reasons any one of
which breaks it:

1. **Rejections ≠ creations.** `cc_num_rejected_cells` counts only CREATE cells
   *refused on an already-marked* client address (dos.c:814). It is **not** a
   circuit-creation count and gives no streams-per-circuit denominator.
2. **Client-channel scope (load-bearing).** DoSCircuitCreation acts **only on
   client channels** — `dos_cc_new_create_cell` (dos.c:746) and
   `cc_channel_addr_is_marked` (dos.c:545) both `goto end` when
   `!channel_is_client(chan)`. An HSDir flood's circuits arrive extended over an
   authenticated **relay-to-relay** channel, so `cc_num_rejected_cells` is never
   incremented for them. The near-zero rate may just mean the flood **bypassed
   the counted path entirely.**
3. **Threshold slack**, **window mismatch** (12 h cumulative vs 1 h flood), and
   **BEGIN_DIR not HS-scoped** all compound the error.

The only defensible statement from the rejection counters is **"DoSCircuitCreation
rarely fired on this traffic"** — which says nothing about reuse. The valid reuse
signal comes from §2 (different counter, correct scope on relay A); the *clean*
reuse number comes from the count-only build (§5).

---

## 5. What to measure next — the one step that resolves the gates

Deploy the **count-only (observe) build** on **1–2 of the operator's own HSDirs**
(operator kit: `operator/DEPLOY-AND-MEASURE.md` with
`operator/capture-and-validate-playbook.md`). Observe mode **never closes a
circuit and never refuses a request** (`hsdir_one_request_per_circ` stays at 0) —
it only increments the two counters, is metadata-only, and rolls back in seconds.
The crash-at-scale review has green-lit it for a production HSDir under flood.

Then, over a flood window on relay A (or the operator's equivalent target), read
from the loopback MetricsPort:

- `tor_relay_dos_total{type="hsdir_circ_reused"}` ÷ HS requests = **clean ρ** and
  **its distribution** — replacing the §2 proxy's mean-only estimate and
  disambiguating HS reuse (0001's scope) from non-HS one-hop reuse;
- `tor_relay_dos_total{type="hsdir_unknown_prev_hop"}` ÷ HS requests = **φ**,
  which this capture cannot produce at all.

This single step converts §3's two `null`s into measured ρ-distribution and φ,
which directly decide whether 0001 and/or 0002 apply to **this** operator's flood.

---

## 6. Data gaps and caveats (updated for the full capture)

- **No longer truncated.** `circuits_created/s`, the baseline window, per-relay
  byte ratios, and the `gaps` field are now present and used above.
- **Dir-specific write:read still NOT derivable.** Stock MetricsPort has no
  per-command or dir-specific byte counter — only process-wide
  `relay_traffic_bytes` and connection *counts*. Relay A's **11.4:1** total ratio
  is all-traffic and must **not** be presented as the field reports' ~170:1
  *directory* ratio; a live dir write:read needs CollecTor extra-info descriptors,
  not this capture.
- **ρ-distribution, φ, and `request_payload_characterization` are `null`** because
  the binary was stock — a tooling/cohort fact, not a measurement failure.
- **"Measurable from stock" ≠ "attributable to the HS flood."** BEGIN_DIR and the
  byte totals aggregate HS and non-HS, dir and non-dir traffic. HS-specific
  attribution — and the bound on 0001's real benefit — requires the count-only
  build's HSDir-scoped counters.
- **`cc_circuits_created` is cumulative/monotonic**; the per-second figures are
  derived rates, so any scrape-interval artifact propagates into the §2
  denominator. (`counter_decreases_detected = 0` rules out wrap/reset.)

---

## Bottom line

For **THIS** flood, patch **0001 now has real proxy-level support**: on the one
attacked relay (relay A — 85 % of cohort starts, ×179 over its baseline) each
circuit served ~**5.7** descriptor requests versus ~0.5 at baseline (~11× reuse),
and capping serving at one-per-circuit implies roughly an **82 % cut in served
dir responses** (~78–84 % band, pre-adaptation) — corroborated by the lab
reuse-5/6 cell. That estimate is directional, not a measurement: it assumes the
reuse is HS-dir (not non-HS one-hop, which 0001 does not touch) and that the
attacker does not adapt to one-request-per-circuit (which would preserve request
volume while raising attacker cost ~5.7×). Patch **0002 remains unmeasured** here
— φ is `null` on every stock relay, so this capture cannot say whether unknown-
prev-hop filtering helps this operator. **Single next action: deploy the
count-only (observe) build on 1–2 of the operator's own HSDirs** to read the clean
`hsdir_circ_reused` distribution (confirming ρ and its HS-vs-non-HS split) and
`hsdir_unknown_prev_hop` (φ) over a flood window — the only step that turns both
remaining `null`s into measurements.
