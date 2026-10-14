# Real-flood capture — what it tells us (and what it can't)

**Source:** a relay operator's own capture of **stock** production HSDirs during
the live tor#41339 BEGIN_DIR / HSDir-descriptor flood. Metadata only — aggregate
per-second rates and since-startup DoS counters; **no fingerprints, no client
IPs** (a multi-hop relay never sees them). Operator-confidential per-key tables
stay with the operator; only the derived aggregate rates below are reproduced.

**Capture envelope.** 953 relays inventoried, **60 HSDirs** instrumented; a
28-relay analysis cohort that carried the HSDir flag in both windows. Flood
window **2026-10-13 20:20–21:20 UTC** (3600 s nominal, ~3480 s observed per
relay, 29 intervals/relay). DoS-counter observation ~**43,200 s (12 h)**. Journal
hygiene is clean: 954 notice-level records, **0** retrieval errors, **0**
malformed records, **0** warning/error records, 180 DoS heartbeats (3/relay),
**counter_decreases_detected = 0** (no wrap/reset — the deltas are trustworthy).

**Binary provenance.** `inventory_reported_version = 0.4.9.14`,
`patched_counters_present = false`, and the two HSDir counters read `null`. The
operator binary was **stock** — not our count-only build. That one fact drives
the whole "what it can't tell us" half of this note. (The source tree on this
branch *does* contain those two counters; their absence here is a cohort fact,
not a measurement failure.)

---

## 1. Confirmed from stock relays — the flood is real and large

- **Rate.** BEGIN_DIR to each HSDir ran at a **median ~1,119 req/s** (p95 ~1,201,
  **peak ~1,310**, mean ~1,118), differenced over the flood hour from the stock
  MetricsPort quantity `relay_streams_total{type="begin_dir"}`
  (`rep_hist_get_exit_stream_seen(RELAY_COMMAND_BEGIN_DIR)`, monotonic since
  startup; rephist.c:1662, relay_metrics.c:739/754). This sits squarely inside
  the 10³–10⁴ req/s band of the **public field reports** — independent
  confirmation that the flood these HSDirs received is the tor#41339 flood, at
  genuine field scale, not a lab artifact.
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
  flood never lands (see §3).

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
| **ρ** `reuse_fraction` | **null** | `num_hsdir_circ_reused{type="hsdir_circ_reused"}` | Circuits making a 2nd+ HS-dir request. | **PATCH 0001 only — absent on stock** |
| **φ** `unknown_prev_hop_fraction` | **null** | `num_hsdir_unknown_prev_hop{type="hsdir_unknown_prev_hop"}` | HS-dir requests whose previous hop is not a known relay. | **PATCH 0002 only — absent on stock** |

Of these, only `circuits_killed_for_cell_queue_limit` can be driven by the
relay-channel flood (it is not client-gated) — and at **985 over 12 h** it is
negligible against ~1,119 req/s. Every other nonzero counter is a **client-facing
guard-role** signal (circuit-creation refusals, connection floods) that is
**orthogonal** to the HSDir BEGIN_DIR flood and must not be compared to it.

---

## 2. The decisive ratios are UNMEASURED — and we must say so plainly

The two quantities that would tell this operator whether **0001** or **0002**
helps *their* flood are **ρ** (the HSDir **circuit-reuse** fraction) and **φ**
(the **unknown-previous-hop** fraction). Both come from the count-only patch
counters:

- **ρ** needs `num_hsdir_circ_reused` — added by patch **0001** (commit
  `0f7621b6ed`), incremented once per circuit on a repeated HS-dir request
  (directory.c:299), counted even in observe mode (`hsdir_one_request_per_circ=0`).
- **φ** needs `num_hsdir_unknown_prev_hop` — added by patch **0002** (commit
  `71efaa5f1f`), incremented when a request's previous hop is not a known relay
  (directory.c:357).

Neither counter exists in stock 0.4.9.14, so both read **`null`** in this
capture. **This is a null-for-absence, not a null-for-zero.**

> **Bottom line for this section:** from this stock capture we **cannot yet
> confirm whether patch 0001 (circuit reuse) or patch 0002 (unknown prev-hop)
> addresses THIS operator's flood.** The lab already shows both patches collapse
> their modeled vectors with no legit-traffic collateral (`sim-offvson-report.md`),
> but that is the *lab* attacker. Fidelity to this operator's live flood is
> exactly the ρ/φ measurement that stock cannot produce. Do not read the `null`s
> as "no reuse" or "no unknown-prev-hop."

---

## 3. The circuit-rejection signal — verdict: **INVALID**

**Hypothesis under test:** *"circuit_creation_rejection_events (~2.7/s/relay) is
tiny next to BEGIN_DIR (~1,119/s/relay), therefore the flood heavily reuses
circuits."*

**Verdict: INVALID.** (Both independent analyses reach INVALID; the arithmetic is
real but the inference does not follow.)

The arithmetic: 7,055,980 ÷ 43,200 s ÷ 60 relays = **2.72 rejections/s/relay**,
versus **1,119 BEGIN_DIR/s/relay** — a ~1:411 ratio. The inference reads that
ratio as "few new circuits per request ⇒ reuse." That step is unsupported for six
independent reasons, any one of which breaks it:

1. **Rejections ≠ creations.** `cc_num_rejected_cells` counts only CREATE cells
   *refused on an already-marked* client address (dos.c:814). Every accepted
   circuit and every creation below the burst/rate threshold is uncounted. **Stock
   Tor has no counter of total circuits created**, so there is no denominator from
   which to infer streams-per-circuit. A low rejection count is equally consistent
   with a huge number of brand-new, never-reused circuits.
2. **Client-channel scope (the load-bearing finding).** DoSCircuitCreation acts
   **only on client channels**: both `dos_cc_new_create_cell` (dos.c:746) and
   `cc_channel_addr_is_marked` (dos.c:545) short-circuit via
   `if (!channel_is_client(chan)) goto end;`, and it tracks addresses only in the
   geoip client-connect cache. An HSDir flood's circuits reach the HSDir
   **extended over an authenticated relay-to-relay channel by a middle relay** —
   so at the HSDir the CREATE arrives on a **non-client** channel and
   `cc_num_rejected_cells` is **never** incremented for it, no matter how many
   circuits the flood creates. The near-zero rejection rate may simply mean the
   flood **bypassed the counted path entirely.**
3. **Threshold slack.** Even on a client channel, the default burst (≈300) lets a
   client open hundreds of fresh circuits before being marked; only post-marking
   cells increment the counter.
4. **Window mismatch.** `circuit_rejected` here is a **12 h cumulative** delta;
   BEGIN_DIR is a **1 h flood-window** rate. The 2.72/s/relay figure is
   12 h-averaged and dilutes the single flood hour — the two numbers are not
   directly comparable.
5. **Total bytes ≠ dir bytes.** The capture's traffic bytes are the **process-wide**
   `relay_traffic_bytes` (`get_bytes_written/read`), ~**644 MB/s write : 597 MB/s
   read ≈ 1.08:1** — nothing like the ~170:1 *directory* write:read of the field
   reports. These bytes are not dir-scoped and cannot corroborate anything at the
   circuit level.
6. **BEGIN_DIR is not HS-scoped.** `rep_hist_get_exit_stream_seen(BEGIN_DIR)`
   counts **all** BEGIN_DIR streams — HS descriptor fetches **and** non-HS
   one-hop document fetches, undifferentiated. The only legitimately
   reuse-capable traffic (non-HS one-hop, ISO_SESSIONGRP) is conflated with HS
   fetches, which the proven invariant K7/K8 shows are strictly
   one-circuit-per-request.

**The inference points backwards.** K7/K8 (proven in the ledger): stock C Tor
isolates every anonymized directory request — HS descriptor fetch/upload
included — on its own `ISO_STREAM` circuit and never reuses it, and Arti uses a
fresh circuit per HSDir request. So for the HS-descriptor flood the architecture
predicts **~no reuse**, directly opposing the "heavy reuse" reading.

The only defensible statement from these stock numbers is: **"DoSCircuitCreation
rarely fired on this traffic"** — which says nothing about circuit reuse and is
**not** evidence for or against patch 0001. The reuse question is answered only by
ρ (§4).

---

## 4. What to measure next — the one step that resolves the gates

Deploy the **count-only (observe) build** on **1–2 of the operator's own HSDirs**
(the operator kit: `operator/DEPLOY-AND-MEASURE.md`, paired with
`operator/capture-and-validate-playbook.md`). Observe mode **never closes a
circuit and never refuses a request** — it only increments the two counters, is
metadata-only, and rolls back in seconds. The crash-at-scale review has green-lit
it for a production HSDir under flood.

Then, over a flood window, read from the loopback MetricsPort:

- `tor_relay_dos_total{type="hsdir_circ_reused"}` (`num_hsdir_circ_reused`) ÷ HS
  requests over the same window = **ρ**, the live reuse fraction;
- `tor_relay_dos_total{type="hsdir_unknown_prev_hop"}` (`num_hsdir_unknown_prev_hop`)
  ÷ HS requests = **φ**, the live unknown-prev-hop fraction.

Both count **with no enforcement side effects** (the one-request-per-circuit
parameter stays at 0; it still counts). **No stock counter can substitute for
this** — the client-channel scope of DoSCircuitCreation (§3) means stock never
observes relay-channel flood circuits at all. This single step converts §2's two
`null`s into measured ρ and φ, which directly decide whether 0001 and/or 0002
apply to **this** operator's flood.

---

## 5. Data gaps in this capture

- **The flood-window JSON is truncated.** It cuts off mid-key after
  `bytes_read_per_s` at `"write…`. Missing as a result: the **dir-specific
  write:read ratio**, **bytes per BEGIN_DIR**, **circuits_created/s**, the
  **baseline (pre-flood) window**, and the **gaps** field. Re-pull the full
  capture object before quoting any of these.
- **Total bytes are not dir bytes.** The only byte totals present are
  process-wide (`relay_traffic_bytes`), so the field reports' **~170:1 directory
  write:read ratio is NOT derivable from this capture** — the ~1.08:1 figure here
  is all-traffic, all-connection, and must not be presented as a dir ratio. Stock
  MetricsPort has no per-command or dir-specific byte counter (only global bytes
  and connection *counts*), so a live dir write:read needs CollecTor extra-info
  descriptors, not this capture.
- **ρ, φ, and `request_payload_characterization` are `null`** because the binary
  was stock (§2, §4) — a tooling/cohort fact, not a measurement failure.
- **"Measurable from stock" ≠ "attributable to the HS flood."** BEGIN_DIR and the
  byte totals aggregate HS and non-HS, dir and non-dir traffic. Attribution to the
  tor#41339 HS-descriptor flood specifically requires the count-only build's
  HSDir-scoped counters.
