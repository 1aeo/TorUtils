# Capturing the real tor#41339 flood and validating the defense against it

**Audience:** a relay operator who runs one or more HSDirs and is receiving the
BEGIN_DIR / HSDir-descriptor flood tracked in tor#41339.
**Goal:** answer the operator's two questions directly —

1. *How do we know the lab attacker generates the same pattern our relays receive?*
2. *Can we enable logging on our own relays to capture the real attack, so we can
   simulate it faithfully and confirm the patch would block it?*

Everything below instruments **your own relays**. It captures **metadata only**
(aggregate counters, no stream content, no client IPs — a multi-hop relay never
sees them). Raw per-key / per-fingerprint tables stay **operator-confidential**;
only derived aggregate parameters are ever published.

---

## 1. The fidelity gap (be honest about it)

We do **not** currently know that the lab attacker matches *your* relay's flood.
The lab's attack parameters are inferred from a handful of **public field
reports**, not measured on your relay. Specifically:

- **Grounded in public data (trust these as shape, not as your numbers):**
  BEGIN_DIR is the flood's stream type and it runs at 10^3–10^4 requests/sec in
  the field; the traffic is *descriptor fetches*, not consensus/network-status
  requests, with a heavily write-skewed dir byte profile (~170:1 dir
  write:read); the self-generated-relay **one-hop** request vector is a real
  code path.
- **Modeling choices (not measured on anyone's relay):** the requests-per-circuit
  reuse set **{1, 5, 22}** — the endpoints 5 and 22 are *derived* from field
  BEGIN_DIR-vs-circuit ratios, and the `n=1` floor is an assumption; the 60-second
  run window; the single-target / 3-onion topology; and the unknown-prev-hop
  vector modeled as a **binary** on/off load rather than a measured fraction.
- **Not reproduced at all:** absolute request **rate**. The lab load generator is
  open-loop and serial (~0.5–5 req/s, i.e. 30–308 requests per 60 s), orders of
  magnitude below the field's 10^3–10^4/s. There is no rate knob.

**Consequence for everything that follows:** the lab reproduces **dimensionless
ratios** (requests-per-circuit, unknown-prev-hop fraction, onionskins-per-request)
and the **direction/bound of the enforcement effect** — never absolute Gbit/s or
BEGIN_DIR/s. The capture below exists precisely to *replace* the assumed inputs
with **your measured distribution**, and then prove the lab reproduces it before
any on/off prediction is trusted.

---

## 2. The defense's count-only mode IS the instrument

The two tor#41339 patches add exactly the logging you asked for. By default they
**only count** — they change no behavior, close no circuit, refuse no request —
so you can run them on a production HSDir and read the attack's two defining
features off the real traffic.

### 2.1 The count-only counters (patch-only)

| Feature | MetricsPort key | Heartbeat line | Patch |
|---|---|---|---|
| Per-circuit request **reuse** (circuits carrying ≥2 HS-dir requests) | `tor_relay_dos_total{type="hsdir_circ_reused"}` | `"<N> circuits with repeated HSDir requests"` | 0002 |
| **Repeat** HS requests (every request on a circuit that already made one) | `tor_relay_dos_total{type="hsdir_req_reused"}` | — | 0002 |
| **Total** anonymous HS directory requests (the exact denominator) | `tor_relay_dos_total{type="hsdir_request_total"}` | — | 0002 |
| HS requests whose **previous hop is not a known relay** (one-hop / self-gen) | `tor_relay_dos_total{type="hsdir_unknown_prev_hop"}` | `"<N> HSDir requests with an unknown previous hop"` | 0001 |

All four are counted in one place, `connection_dir_allow_hs_request()`
(`src/feature/dircommon/directory.c`), which both HS call sites (descriptor GET
and POST) run **before** any enforcement decision — so the counters mean the
same thing in observe and enforce mode:

- `hsdir_circ_reused` counts **circuits**, incremented **once** per circuit the
  first time a 2nd HS request arrives on it (a circuit carrying 22 requests adds
  **1**, not 21). Per-circuit state is a 2-bit saturating counter
  `or_circuit_t.n_hsdir_requests` (0 → 1 → 2); the helper passes its previous
  value to `dos_note_hsdir_request(prev_count)` (`src/core/or/dos.c`), which
  bumps `num_hsdir_circ_reused` only when `prev_count == 1`.
- `hsdir_req_reused` counts **requests** — every repeat HS request on a circuit
  that already made one (`prev_count >= 1`; a circuit carrying 22 requests adds
  21). MetricsPort only.
- `hsdir_request_total` counts **every** anonymous HS directory request (same
  `dos_note_hsdir_request()` call) — the exact HS-only denominator for the reuse
  fraction (`req_reused / request_total`) and for φ
  (`unknown_prev_hop / request_total`).
- `hsdir_unknown_prev_hop` counts **requests** (every unknown-prev-hop request,
  not per circuit): the helper tests
  `connection_or_digest_is_known_relay(p_chan->identity_digest)` against the
  consensus / held descriptors and calls `dos_note_hsdir_unknown_prev_hop()`.

The two heartbeat substrings above are emitted together on the one DoS
heartbeat line (`dos_log_heartbeat()`). Enforcement reads the torrc AUTOBOOL
first and otherwise a consensus value cached in `set_dos_parameters()`, so the
per-request check is O(1).

All are monotonic process-wide uint64 totals since relay start — **take deltas
across a window**, and expect a reset only on restart. Counting is
**unconditional**: both notes run *before* any enforce check, so they count even
with enforcement off.

### 2.2 Enabling count-only (observe) mode — nothing changes for users

Deploy the patched binary (patches 0001 + 0002) and **leave the two options at
their default**:

```
# torrc — observe-only. Both default to "auto"; auto + silent consensus = count-only.
# (You may state them explicitly to be unambiguous:)
HSDirOneRequestPerCircuit auto
HSDirRefuseUnknownPrevHop auto

# Expose the counters on loopback only:
MetricsPort 127.0.0.1:9035          # example port; keep your relay's own
MetricsPortPolicy accept 127.0.0.1

# Tighten log resolution during the incident (6h default is too coarse):
HeartbeatPeriod 30 minutes    # tor's minimum; smaller values are raised to it
```

**Precedence (for both options):** an explicit torrc value (anything other than
`auto`/`-1`) overrides the consensus parameter, which overrides the built-in
count-only default.

- `HSDirOneRequestPerCircuit` (AUTOBOOL, default `auto`) → consensus param
  `hsdir_one_request_per_circ` → default `DOS_HSDIR_ONE_REQUEST_PER_CIRC_DEFAULT 0`.
  Gate: `dos_should_enforce_hsdir_one_request_per_circ()`.
- `HSDirRefuseUnknownPrevHop` (AUTOBOOL, default `auto`) → consensus param
  `hsdir_refuse_unknown_prev_hop` → default
  `DOS_HSDIR_REFUSE_UNKNOWN_PREV_HOP_DEFAULT 0`. Gate:
  `dos_should_refuse_unknown_hsdir_prev_hop()`. **Independent of
  `RefuseUnknownExits`** — an Exit+HSDir can set HS behavior without touching exit
  protection.

**Safety / reversibility:** with both at `auto` and no consensus opinion set,
there is **zero effect on real users** — the 2nd/3rd request on a circuit is
still served and the circuit stays open; an unknown-prev-hop request still gets
its normal response (e.g. a 404 / the descriptor), **never** a 503. Nothing an
external party can detect changes. Enabling enforcement later is a one-line
change and **rollback is instant** via the same AUTOBOOL (`=auto` or `=0`); the
network-wide consensus params stay off, so no other relay is affected.

---

## 3. Capture on a STOCK relay today

If you cannot deploy the patched binary yet, stock tor **0.4.9.14** already
exposes enough to measure the flood's **volume and shape** (but *not* decompose
it into reuse vs unknown-prev-hop — that needs the patch; see §5).

### 3.1 MetricsPort keys (enable `MetricsPort` + `MetricsPortPolicy` as in §2.2)

| Signal | Keys | Semantics |
|---|---|---|
| **Primary flood signal — dir-request rate** | `tor_relay_streams_total{type="BEGIN_DIR"}` (compare to `{type="BEGIN"}`, `{type="RESOLVE"}`) | Lifetime monotonic count of BEGIN_DIR streams terminated here. Each tunneled HS-descriptor GET/POST opens one. Rate = Δcounter / Δt. |
| **Byte / traffic profile** | `tor_relay_traffic_bytes{direction="read"}`, `{direction="written"}` | Relay-wide lifetime totals. Compute written/read ratio and bytes/sec. Descriptor floods are strongly asymmetric. |
| **Onionskin / handshake load** | `tor_relay_load_onionskins_total{type="ntor_v3",action="processed"}` and `{action="dropped"}` (also `ntor`, `tap`, `fast`) | `processed` = handshakes assigned to a cpuworker (lifetime); any non-zero `dropped` means the relay is shedding handshakes under overload. |
| **Circuit churn** | `tor_relay_congestion_control_total{state="cc_circuits",action="circs_created"}` and `{action="circs_closed"}` | Lifetime; created-rate and (created − closed) approximate live churn. |
| **Live open-circuit gauge** | `tor_relay_circuits_total{state="opened"}` | **Instantaneous** gauge (length of the global circuit list) — not a counter. |
| **Stock DoS-subsystem reactions** | `tor_relay_dos_total{type="circuit_rejected"\|"stream_rejected"\|"concurrent_conn_rejected"\|"conn_rejected"\|"single_hop_refused"\|"introduce2_rejected"\|"circuit_killed_max_cell"\|"circuit_killed_max_cell_outq"\|"marked_address"\|"marked_address_maxq"}` | Only increment when the matching `DoS*` options / consensus params are active. **For a BEGIN_DIR descriptor flood these are largely the wrong tool** — the flood rides existing circuits rather than tripping per-address circuit/conn limits — so expect them to stay flat. |

> **Counter semantics reminder:** `streams_total`, `traffic_bytes`,
> onionskins `processed`, and the `cc_circuits` counters are **lifetime
> monotonic totals — difference successive scrapes for a rate**.
> `circuits_total{state="opened"}` is an **instantaneous gauge**.

### 3.2 Heartbeat (operator log — no scraper needed)

Read your notice-level log. With a lowered `HeartbeatPeriod` you get a coarse
timeline:

- **Main line:** `Heartbeat: Tor's uptime is ..., with N circuits open. I've sent X and received Y. I've received U connections on IPv4 and V on IPv6. ...`
- **Circuit-handshake line (resets each period):** `Circuit handshake stats since last time: a/b TAP, c/d NTor, e/f NTor (v3).` — NTor (v3) `requested` spiking is the per-period view of circuit-creation load.
- **DoS-mitigation line (since startup):** `Heartbeat: DoS mitigation since startup: N circuits killed with too many cells, ... circuits rejected, ... marked addresses, ... , ... stream rejected, ... INTRODUCE2 rejected.` — confirms whether stock DoS defenses engaged (for this flood, usually not).

### 3.3 dirreq / extra-info (longer horizon, coarse corroborator only)

`DirReqStatistics 1` (default on) writes `$DATADIR/stats/dirreq-stats` every 24h
(`dirreq-stats-end`, `dirreq-v3-reqs`, `dirreq-v3-resp served=/ok=/...`,
`dirreq-v3-direct-dl`, `dirreq-v3-tunneled-dl`). **Caveat:** these count v3
**network-status** requests (`GEOIP_CLIENT_NETWORKSTATUS`), **not** HS-descriptor
fetches. A BEGIN_DIR HS flood will reliably move
`tor_relay_streams_total{type="BEGIN_DIR"}` but will **not** necessarily be broken
out in `dirreq-v3-*`. Treat BEGIN_DIR as primary; dirreq as a coarse corroborator.
For the ~170:1 dir write:read field signature, read `dirreq-write-history` /
dir-read stats, **not** MetricsPort total `traffic_bytes` (which is relay-wide).

### 3.4 Minimal scrape-every-N-seconds recipe

The lab scraper `simulator/scripts/metrics.py` already encodes the exact
regexes for all the keys above. Minimal loop (loopback only):

```sh
# Run on the relay host. Appends timestamp + raw counters every 10 s.
sudo install -d -m 0700 /var/operator-private
while true; do
  printf '%s ' "$(date -u +%s)"
  curl -s http://127.0.0.1:9035/metrics | \
    grep -E 'tor_relay_(streams_total\{type="BEGIN(_DIR)?"|traffic_bytes|load_onionskins_total\{type="ntor_v3"|congestion_control_total\{state="cc_circuits"|circuits_total\{state="opened"|dos_total)'
  echo
  sleep 10
done | sudo tee -a /var/operator-private/41339-capture.log >/dev/null
```

Post-process by **differencing adjacent samples** to get req/s, bytes/s,
onionskins/s, and circuit churn; the per-sample deltas give you **burstiness**
(peak vs p95 vs mean) over the window. Or just call `metrics.py` directly:
`python3 metrics.py 9035` returns the parsed dict (and reads the four `hsdir_*`
keys as `None`/absent on a stock relay — correctly).

---

## 4. Optional targeted capture of DISTRIBUTIONS

Totals and the two scalar counters tell you *how much* and *whether reuse /
unknown-hop is present*. To capture the flood's **distributions** (the inputs the
simulator needs), add these **count-only, observe-only** instrumentation hooks on
top of patches 0001/0002. All are small, O(1)-memory, scraped via the existing
MetricsPort `fill_dos_values()` path — **no per-request I/O**.

**(a) requests-per-circuit DISTRIBUTION (not just the one-reuse flag).** Widen the
2-bit `or_circuit_t.n_hsdir_requests` (or add a small `uint16_t` beside it,
capped at ~64) and increment it in `connection_dir_allow_hs_request()`, where
reuse is already detected. At teardown in
`circuit_about_to_free()` (the `if (! CIRCUIT_IS_ORIGIN(circ))` branch), fold the
count into a fixed-bucket histogram — **{1, 2, 3–5, 6–10, 11–22, 23+}** (the
report cites 5–22 req/circuit). A legitimate stock Tor / Arti / Onionbalance
client always lands in bucket **1**, so this cannot deanonymize a normal user.

**(b) prev-hop-known FRACTION over time.** Patch 0001 gives the numerator
(`hsdir_unknown_prev_hop`); patch 0002 now ships the exact denominator
`hsdir_request_total` (every anonymous HS request) plus `hsdir_req_reused`
(every repeat request). So both exact fractions are read directly at the
MetricsPort — φ = `unknown_prev_hop / request_total` and the HS-only reuse
fraction `r_hs = req_reused / request_total` — each with its trend via `rate()`.

**(c) descriptor / ring concentration — bucketed, never the address.** The
requested id is the **blinded ed25519 key** in the GET URL
(`handle_get_hs_descriptor_v3()` sets `pubkey_str`), decoded into
`conn->hs_ident.blinded_pk`. This is **not** the onion address (which is never
sent to the HSDir and rotates each period). To separate "flood hammers one/few
descriptors" from "spread across the ring" **without** a per-service fingerprint:
compute a coarse bucket from `pubkey_str` **before** `hs_cache_lookup_as_dir()`
(so 404 flood traffic is counted too) — e.g. top byte of a digest → 256 ring
buckets — keep a bounded in-memory `count[bucket]` table, and publish **only** a
derived spread statistic (entropy, Gini, or top-bucket share). **Never publish or
log raw blinded keys.** Prefer GET-side bucketing; the upload/POST path (inside
`hs_cache_store_as_dir()`) is more invasive — skip it.

**(d) inter-arrival / burstiness — derived rates, not per-request timestamps.**
Keep a fixed-resolution in-memory ring of per-second counts (e.g. 60 slots)
updated by one increment in `connection_dir_allow_hs_request()` using monotonic
time, and publish **peak req/s, p95 req/s, and coefficient of variation** as
gauges. Zero-code crude signal: the delta of `num_hsdir_circ_reused` between
heartbeats (`dos_log_heartbeat()` already logs it at `log_notice(LD_HEARTBEAT)`).
For a finer sample use a **1-in-N sampled `LOG_INFO`** line carrying only a
relative ms delta, gated by a `ratelim_t` (`log_fn_ratelim()` /
`rate_limit_log()`).

**(supporting) attacker-identity cardinality — operator-private, count-only.** On
an unknown-prev-hop request, the prev-hop channel identity
(`CONST_TO_OR_CIRCUIT(circ)->p_chan->identity_digest`) is the **attacker relay's
claimed fingerprint** — a relay identity, not a client. Keep a bounded
operator-private tally (top-N, or a HyperLogLog estimate) and publish **only the
cardinality** (how many distinct self-generated identities the flood cycles
through). Honor `SafeLogging` / `safe_str()` on anything logged. **Only on the
unknown-prev-hop path** — never on multi-hop circuits, where the prev hop is a
legitimate middle relay.

### What NOT to log (hard privacy line)

- **Never** log raw blinded descriptor keys, raw prev-hop fingerprints, absolute
  wall-clock per-request timestamps, or any per-service / per-identity
  fingerprint.
- **Never** read stream/body content for instrumentation.
- The human onion/identity address is never observable at the HSDir — never
  captured. Client IPs are never visible on these multi-hop OR circuits — none can
  be logged.
- At 10^3–10^4 req/s a per-request log line is unsafe (disk + side channel).
  Prefer in-memory counters/histograms scraped via MetricsPort; use `LOG_INFO` +
  `ratelim_t` + 1-in-N sampling only for optional human-readable samples.

---

## 5. Feature → simulator parameter mapping

Capture each feature on your relay, derive the **dimensionless ratio**, then set
the matching simulator knob. The simulator lives in
`simulator/scripts/` (`sim.py`, `run_matrix.py`, `metrics.py`,
`aggregate.py`); loads are `ALL_LOADS = ["none","fetch","reuse-5","reuse-22","onehop","adapted"]`.

| Field feature | Captured counter(s) | Derived quantity | Sim knob | Grounded or assumed? |
|---|---|---|---|---|
| Requests-per-circuit multiplier | `hsdir_request_total`, `hsdir_req_reused`, `hsdir_circ_reused` (patch); `BEGIN_DIR`, `circs_created` (stock) | ρ_hs = T / (T − R) (HS requests per HS circuit); r_hs = R / T | `reuse-N` → `load_reuse()` (`EVIL_ISO_SESSIONGRP`, ctl **8020**); set `n ≈ round(ρ)`, bracketed to {1,5,22} | **Assumed** set; endpoints 5/22 semi-grounded from field ratios |
| BEGIN_DIR absolute rate | `tor_relay_streams_total{type="BEGIN_DIR"}` (`begin_dir_recv`) | req/s over window | **No knob** — sim is open-loop serial (~0.5–5 req/s). Match the per-circuit **ratio**, not absolute rate | Rate **not reproduced** |
| write:read byte ratio | `tor_relay_traffic_bytes{direction=...}`; for dir-only use `dirreq-write-history` | writes/reads | No direct knob (emerges from ~16 KB response size). Use only as a **sanity direction** (writes ≫ reads) | Grounded shape; weak lab mapping (sim scrapes *total* bytes) |
| One-hop / unknown-prev-hop fraction | `hsdir_unknown_prev_hop`, `hsdir_request_total` (patch) | φ = U / T (exact HS-only denominator) | `onehop` → `EVIL_ONEHOP` unpublished relay-client (`PublishServerDescriptor 0`, `AssumeReachable 1`, ctl **8022**) | Vector grounded; sim is **binary** on/off, not a tunable fraction |
| Onionskin / CREATE-cell rate | `onionskins_ntor_v3`, `circs_created` (stock); network-wide `net_onionskins`/`nontgt_*` via `scrape_network()` | onionskins per BEGIN_DIR | `adapted` / `fetch` (one well-formed req per fresh circuit, ctl **8021**) — the post-adaptation cost | Grounded as the "after adaptation" cost |
| Target / descriptor concentration | §4(c) spread stat; your own relay fpr + targeted onion(s) | top-bucket share / entropy | `choose_target()` / `probe_hsdirs.py` (single-target) | **Not reproduced** at population scale (field: 310–433 rotating HSDirs/day) |

**How to retune:** over a fixed window W on the flooded relay, diff
`B=ΔBEGIN_DIR`, `T=Δhsdir_request_total`, `R=Δhsdir_req_reused`,
`K=Δhsdir_circ_reused`, `U=Δhsdir_unknown_prev_hop`, `C=Δcircs_created`,
`O=Δonionskins_ntor_v3`. Derive ρ_hs = T/(T−R), r_hs = R/T, φ = U/T, and O/B.
Pick the `reuse-N` nearest ρ_hs; add the `onehop` load if φ is non-trivial. Then
run the sim in observe mode and recompute the **same** ratios from its
`hsdir_request_total` / `hsdir_req_reused` / `hsdir_unknown_prev_hop` /
`begin_dir_recv` / `onionskins_ntor_v3`.

---

## 6. The fidelity check + production A/B

### 6.1 Fidelity check (scale-free — compare ratios, never absolute counts)

The sim is faithful for **this** operator iff its observe-mode ratios land inside
tolerance of the captured ratios:

- **ρ_hs (HS requests per HS circuit)** and **φ (unknown-prev-hop fraction)**
  within **±20%** (or `n` chosen to the {1,5,22} bracket around ρ_hs).
- **O/B (onionskins-per-request)** within a factor of **~2** (loose, because of
  the total-vs-dir bytes and open-loop-rate caveats).

Only match ratios and the **enforcement-effect bounds** — the lab runs ~0.5–5
req/s while the field is 10^3–10^4/s, so absolute load does not transfer.
**Pass = the sim's observe ratios land inside tolerance; only then are its on/off
predictions trustworthy for this operator.** Average several reps (`aggregate.py`
takes medians); `hsdir_circ_reused` is noisy per-run for the reuse load.

**Honesty gates (decide which patch, if any, helps you):**

- **Gate A — reuse ≈ 1.** If `R` stays ≈0 (r_hs ≈ 0, ρ_hs ≈ 1: each circuit
  makes one HS request), **0002 has nothing to remove and will not help you.** Report that
  rather than shipping 0002 — the "served ≤ number of circuits" bound collapses to
  ≈0 benefit at ρ=1.
- **Gate B — unknown_prev_hop is high.** If φ is large, the vector is
  one-hop / self-generated-relay and **0001 is the right lever** (expected refusals
  under enforcement ≈ φ·T = U as 503s; false-positive risk ≈1.2e-6 per request,
  worst-hour upper bound ≈4.2e-3, during the brief window before a fresh consensus
  is seen).
- **Neither (R≈0 and φ≈0):** pure high-rate one-per-circuit from known relays —
  **neither 0001 nor 0002 helps**; cost is pure circuit creation, and
  DoSCircuitCreation does not cover relay channels. Report this plainly.

### 6.2 Ultimate validation — short enforcement-ON window on ONE production HSDir

After observe mode confirms the pattern (Gate A or B), flip **one** relay live via
the control port — unilateral, affects only that relay, **no restart**:

```
# Enable the lever(s) your capture justified:
SETCONF HSDirOneRequestPerCircuit=1      # reuse case — closes reused circuits with END_CIRC_REASON_RESOURCELIMIT
SETCONF HSDirRefuseUnknownPrevHop=1      # unknown-prev-hop case — returns 503 "previous hop is not a known relay"
```

During the window, read on your own relay: a **drop in `bytes_written`**
(served-descriptor bytes), a **drop in `target_cpu_pct` and `onionskins_ntor_v3`**,
and — **critically** — **legitimate success stays ~100%** via a stock probe
(`LegitProber`: `HSFETCH <known-good onion> SERVER=<this relay fpr>`; success =
presence of an `HS_DESC RECEIVED` event). Compare to the observe window.

> **Measurement gotcha:** a 503 on an HS fetch emits **no** `HS_DESC FAILED`
> control event. Measure legitimate success by the **presence of
> `HS_DESC RECEIVED`**, never by the absence of `FAILED`.

**Rollback is one command, instant, reversible:**

```
SETCONF HSDirOneRequestPerCircuit=0     # 0 = never enforce; auto would follow the consensus
SETCONF HSDirRefuseUnknownPrevHop=0
```

Network-wide consensus params stay off, so no other relay is affected. Because
there has been no prior under-attack real-network test, **this short, watched,
instantly-reversible window is the first real-network evidence** — keep it short.

---

## 7. Privacy & safety constraints

- **Metadata only.** Every observable here is an aggregate counter, gauge, or
  derived statistic. No stream payloads, no destination addresses.
- **No client IPs — structurally.** These requests arrive over multi-hop OR
  circuits (`connection_dir_is_anonymous()`); the relay never sees the originating
  client. The prev-hop identity is consulted **only** to classify known/unknown and
  is **not** emitted.
- **No onion address.** The human onion/identity key is never sent to an HSDir;
  only the rotating blinded key is visible, and §4(c) hashes/buckets even that.
- **Operator-confidentiality.** Raw per-key / per-fingerprint / per-timestamp
  tables stay local to the operator. **Publish only derived aggregates** — histogram
  bucket counts, fractions, entropy/Gini, peak/p95 rates, distinct-identity
  cardinality — and **never** raw blinded keys, raw prev-hop fingerprints, or
  absolute timestamps (these would let an outside adversary learn which services are
  under attack and correlate across relays).
- **Loopback only.** MetricsPort is bound to `127.0.0.1` behind
  `MetricsPortPolicy accept 127.0.0.1`. Heartbeat lines go only to the operator's
  own log.
- **SafeLogging.** Honor `SafeLogging` / `safe_str()` on anything that could ever
  carry an address or digest.
- **Observe mode is invisible and harmless.** With both AUTOBOOLs at `auto` and no
  consensus opinion, real users see no change and no external party can detect that
  logging is on.
