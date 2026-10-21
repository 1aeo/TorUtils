# Deliverable 5: Unexecuted Canary Validation, Profiling, and Rollback Plan

> **Operational Constraint**: This document specifies an **unexecuted** validation and profiling plan only. In accordance with task rules, no live relays were modified, restarted, or reconfigured during this study, no public-network traffic was generated, and both HS policy defenses (`HSDirRefuseUnknownPrevHop` and `HSDirOneRequestPerCircuit`) remain disabled (`0`) throughout Stage 1.

---

## 1. Staged Canary Strategy: Why Fix + Observability Must Precede Policy Defenses

A critical finding of Deliverable 1 (`01-facts-hypotheses-unknowns.md`) is that the historical `2026-10-20` pilot deployment bundled seven patches simultaneously onto relays during a quiet network period (`begin_dir_cell_total` rate $0.89\text{--}1.85\text{/s}$), while the `2026-10-21` live `perf` profiles captured unpatched `tor 0.4.9.14` relays without the new observability counters.

To avoid confounding algorithmic main-loop remediation with directory admission policy changes, canary validation must proceed in **two strictly separated stages**:

### Stage 1 (Immediate Canary): Algorithmic Indexing + Observability Only
- **Patch Stack**:
  - **Option A (Minimal standalone stack on `tor-0.4.9.14`)**:
    1. `patches/0001-mainloop-index-cleanup-scans-with-test-fixes.patch`
    2. `patches/0002-relay-metrics-mainloop-and-directory-observability.patch`
  - **Option B (Full passive code stack on `tor-0.4.9.14`, with policy flags explicitly disabled)**:
    1. `HS_PATCHES/0001..0007` (`tor41339-hsdir-defense`)
    2. `patches/0008-mainloop-index-cleanup-scans-on-hs-series.patch`
    3. `patches/0009-relay-metrics-mainloop-and-directory-observability-on-hs-series.patch`
- **Mandatory `torrc` Configuration for Stage 1**:
  ```ini
  HSDirRefuseUnknownPrevHop 0
  HSDirOneRequestPerCircuit 0
  ```
- **Why Stage 1 Is Required First**:
  1. It eliminates the verified $O(C \cdot (A + N))$ main-thread cleanup stall (`90.47%` of `sarkodie`'s main-thread CPU; `14.11%–14.87%` of `joji`/`antglizzy`) with **zero change** to which circuits or HTTP requests are accepted.
  2. Because `HSDirRefuseUnknownPrevHop` and `HSDirOneRequestPerCircuit` remain `0`, an incoming `BEGIN_DIR` flood will still traverse the full directory request parser (`directory_handle_command_get()`) and stream lifecycle, allowing the new Tier A/B/C counters to **definitively classify the flood (`H1`–`H6`)** while proving whether `0001/0008` alone keeps main-thread CPU healthy.

### Stage 2 (Conditional Policy Evaluation — Only If Needed After Stage 1 Evidence)
- **Trigger Condition**: Stage 2 is evaluated **only if** Stage 1 `/metrics` + `perf` evidence during an active flood proves that:
  1. Main-thread cleanup CPU (`close_closeable_connections` + `connection_free_minimal`) is already reduced to $< 1\%$, **and**
  2. Residual main-thread CPU or bandwidth saturation is caused by high-rate valid HS v3 descriptor fetches (`req_class="hs_v3_fetch"`, `H3`/`H4`) rather than pre-HTTP stream churn (`H1`) or ordinary directory fetches (`H5`).
-Even in Stage 2, `HSDirOneRequestPerCircuit 1` and `HSDirRefuseUnknownPrevHop 1` must be tested on separate canaries (never toggled simultaneously on the same relay without a baseline window) while verifying that `tor_relay_begindir_circuit_stream_ordinal_total{ordinal_bucket!="1"}` and `tor_relay_dir_http_requests_total{req_class=~"ordinary_.*"}` remain unharmed (`HS_PATCHES/0002` checks `circ->hsdir_served_req` only inside `directory_handle_command_hs_get()`, never on ordinary directory URLs).

---

## 2. Canary and Control Relay Pairing

Following the host-matched control design verified in `LIVE/evidence/profile_control_selection.json`, pair one canary relay with one unpatched (or previous-baseline) control relay on the **same physical host** so both experience identical host kernel, NIC, and Tor network consensus conditions:

| Host | Canary Relay (receives Stage 1 stack) | Paired Control Relay (remains baseline during initial window) | Role in Historical/Live Evidence |
|---|---|---|---|
| **Host A (`172.81.181.209`)** | `sarkodie` | `goodiemob` | `sarkodie` exhibited the pure `90.47%` cleanup-scan stall at `5,585 BEGIN_DIR/s` |
| **Host B (`45.88.6.132`)** | `antglizzy` | `ludacris7` | `antglizzy` (`4,132 BEGIN_DIR/s`) and `joji` (`4,631 BEGIN_DIR/s`) exhibited mixed output + `14.11%–14.87%` cleanup profiles |

---

## 3. Telemetry and Profiling Protocol (Before, During, After)

### 3.1 Pre-Deployment Baseline Snapshot (`T - 30 min`)
Before deploying the Stage 1 binary to the canary relay:
1. Record the running binary path, ELF `BuildID` (`readelf -n /proc/<pid>/exe`), and SHA256 checksum.
2. Scrape `/metrics` every `15s` for `30 min` on both the canary and paired control relay.
3. Capture one `30s` baseline `perf` profile of the `tor-main` thread on both relays using the exact command in Section 3.3.

### 3.2 Continuous `/metrics` Scrape and Host Telemetry (`15s` normal / `5s` flood cadence)
On every scrape interval, collect and archive:
1. **Tor `/metrics` endpoint** (full text snapshot, timestamped in UTC with millisecond precision):
   - **Tier A (`mainloop`)**:
     - `tor_relay_mainloop_connection_list_entries{list="connection_array"|"active_linked_connection_lst"|"closeable_connection_lst"}`
     - `tor_relay_mainloop_connection_list_max_entries{list=...}`
     - `tor_relay_mainloop_connection_list_ops_total{list=...,op="added"|"removed"|"closed"|"deferred_held_open"}`
     - `tor_relay_mainloop_cleanup_passes_total{batch_bucket="0"|"1"|"2_16"|"17_64"|"65_256"|"257_1024"|"1025_plus"}`
   - **Tier B (`dir` lifecycle & HTTP classification)**:
     - `tor_relay_dir_streams_total{stage="begindir_opened"|"closed_completed"|"closed_aborted_pre_http"|"closed_aborted_mid_http"|"closed_aborted_writing"}`
     - `tor_relay_dir_active_streams{state="reading_request"|"writing_response"}`
     - `tor_relay_dir_http_requests_total{req_class=...,status_class=...}`
     - `tor_relay_begindir_circuit_stream_ordinal_total{ordinal_bucket="1"|"2_4"|"5_16"|"17_plus"}`
   - **Tier C (`dir` payload bytes)**:
     - `tor_relay_dir_bytes_total{direction="in"|"out",req_class=...}`
   - **Existing Companion Counters**:
     - `tor_relay_dir_begin_dir_cell_total`
     - `tor_relay_exit_streams_total{type="dir"}`
     - `tor_relay_load_oom_bytes_total{subsys="cell"|"dir"|"hsdir"|"geoip"}`
     - `tor_relay_traffic_bytes{direction="read"|"written"}`
2. **Host / Process Companions** (collected alongside each `/metrics` scrape):
   - `/proc/<pid>/stat` and `/proc/<pid>/task/<main_tid>/stat` (`utime`, `stime` ticks for exact per-thread CPU% denominator)
   - `/proc/<pid>/status` (`VmRSS`, `Threads`)
   - `/proc/<pid>/fd` count (`ls -1 /proc/<pid>/fd | wc -l`)
   - Scrape HTTP response latency (`curl -w '%{time_total}\n'`) as an external measure of main-loop stall duration.

### 3.3 Matched `perf` Capture Protocol During Quiet and Flood Windows
Whenever an active flood occurs (defined as `rate(tor_relay_dir_streams_total{stage="begindir_opened"}[1m]) >= 500/s` OR main-thread CPU $\ge 85\%$ for $60\text{ s}$ OR `tor_relay_mainloop_connection_list_max_entries{list="closeable_connection_lst"} >= 256`), trigger a simultaneous **30-second main-thread `perf` capture** on the canary and its paired control relay:

```bash
# 1. Identify PID and tor-main TID (never aggregate whole-process samples without TID separation)
PID=$(pgrep -xo tor)
MAIN_TID=$(grep -l '^tor-main$' /proc/$PID/task/*/comm 2>/dev/null | awk -F/ '{print $5}')
[ -z "$MAIN_TID" ] && MAIN_TID=$PID

# 2. Take immediate pre-capture /metrics and /proc/<PID>/task/<MAIN_TID>/stat snapshot
curl -sS http://127.0.0.1:<METRICS_PORT>/metrics > pre_metrics.prom
cat /proc/$PID/task/$MAIN_TID/stat > pre_main_tid_stat.txt
cat /proc/$PID/maps > proc_maps.txt
readelf -n /proc/$PID/exe > build_id.txt

# 3. Record 30s of tor-main at 99 Hz with DWARF/frame-pointer call graphs
perf record -F 99 -t "$MAIN_TID" -g --call-graph dwarf,16384 -o perf_main.data -- sleep 30

# 4. Take immediate post-capture /metrics and /proc/<PID>/task/<MAIN_TID>/stat snapshot
curl -sS http://127.0.0.1:<METRICS_PORT>/metrics > post_metrics.prom
cat /proc/$PID/task/$MAIN_TID/stat > post_main_tid_stat.txt

# 5. Export symbolicated and raw address script (preserving unresolved [unknown] samples)
perf script -i perf_main.data -F comm,tid,time,period,ip,sym,dso,symoff > perf_main.script.txt
```

**Audit Requirements for Every Captured Profile**:
- Always report **both** `sample_count` and `period` share on `MAIN_TID`.
- Preserve all `[unknown]` / unresolved samples in the denominator (`pct_of_main_samples` and `pct_of_main_userspace_samples`).
- Bracket every `30s` `perf` window with `pre_metrics.prom` and `post_metrics.prom` so exact $\Delta C = \Delta\text{ops\_total}\{\text{list}=\text{"closeable\_connection\_lst"},\text{op}=\text{"closed"}\}$, $A$, and $N$ are known for the exact `30s` profile span.

---

## 4. Quantitative Success Criteria, Safety Gates, and Rollback Triggers

### 4.1 Primary Remediation Gates (Must Hold Under Flood Load)
| Gate | Metric / Measurement | Unpatched Baseline (`sarkodie` / `joji` / `antglizzy`) | Stage 1 Target |
|---|---|---|---|
| **G1: Cleanup CPU Elimination** | Main-thread `perf` sample share in `close_closeable_connections` + `connection_free_minimal` + `connection_stop_reading_from_linked_conn` + `add_connection_to_closeable_list` | `90.47%` (`sarkodie`), `14.87%` (`joji`), `14.11%` (`antglizzy`) | **$< 1.0\%$** of `tor-main` samples even at $\ge 4,000\text{--}6,000\text{ BEGIN\_DIR/s}$ |
| **G2: List Conservation Identity** | `entries - (added - removed/closed)` across all 3 lists in `/metrics` | Unobserved | **Exactly `0`** on 100% of scrapes |
| **G3: Stream Conservation Identity** | `begindir_opened - sum(closed_*) - sum(active_streams)` | Unobserved | **Exactly `0`** on 100% of scrapes |
| **G4: Assertion Integrity** | `BUG()` or `tor_bug_once_()` warnings in `notice.log` | `0` | **Exactly `0`** |
| **G5: `/metrics` Scrape Responsiveness** | HTTP `/metrics` scrape `p95` latency during flood bursts | Stalled up to `45–177 ms` per cleanup pass in whole-loop benchmark | **$< 5\text{ ms}$** (`0.62 ms` in whole-loop benchmark) |

### 4.2 Normal-Traffic Compatibility Gates (Must Hold Continuously)
| Safety Gate | Telemetry Check | Pass Criterion |
|---|---|---|
| **S1: Ordinary Directory Success Rate** | `rate(tor_relay_dir_http_requests_total{req_class=~"ordinary_.*",status_class="2xx"}[5m])` | Within $\pm 10\%$ of host-paired control relay during non-flood periods; increases or remains stable during floods |
| **S2: Stream Completion vs Abort Ratio** | `rate(tor_relay_dir_streams_total{stage="closed_completed"}[5m])` vs `closed_aborted_*` | No increase in `closed_aborted_*` during quiet baseline relative to control |
| **S3: Legitimate Circuit Reuse** | `tor_relay_begindir_circuit_stream_ordinal_total{ordinal_bucket!="1"}` | Non-zero and advancing normally with `HSDirOneRequestPerCircuit 0` |
| **S4: Slow-Client Flush Drain** | `tor_relay_mainloop_connection_list_ops_total{list="closeable_connection_lst",op="deferred_held_open"}` vs `entries{list="closeable_connection_lst"}` | `entries{list="closeable_connection_lst"}` returns to `0–2` between bursts; no monotonic leak of held-open connections |
| **S5: Memory Stability** | `/proc/<pid>/status` `VmRSS` and `tor_relay_load_oom_bytes_total` | `sizeof(connection_t)` $+8\text{ B}$ adds $< 0.5\text{ MiB}$ at $N = 64,000$; no abnormal RSS growth |

### 4.3 Immediate Rollback Triggers
Roll back the canary relay to the stock `tor-0.4.9.14` binary immediately (preserving logs, `/metrics` history, and core/perf files) if **any** of the following occur:
1. Any `BUG()` / `tor_assert_nonfatal` message in `notice.log` referencing `mainloop.c`, `connection.c`, or `relay_metrics.c`.
2. Any non-zero discrepancy in the list or stream conservation identities (**G2** or **G3**) on a single `/metrics` snapshot.
3. Any sustained ($> 10\text{ min}$) drop $> 10\%$ in `tor_relay_dir_http_requests_total{req_class=~"ordinary_.*",status_class="2xx"}` relative to the same-host control relay.
4. Any monotonic growth in `tor_relay_mainloop_connection_list_entries{list="closeable_connection_lst"}` that does not drain when `rate(begindir_opened)` subsides.

---

## 5. Post-Stage-1 Decision Matrix: What Each Observation Establishes and Next Action

| Stage 1 Flood Observation (`/metrics` + `perf`) | Hypothesis Confirmed / Falsified | What Is Established | Next Engineering Action |
|---|---|---|---|
| **Case 1**: Cleanup CPU $< 1\%$; `sarkodie`-type flood occurs with $\Delta\text{closed\_aborted\_pre\_http} \approx \Delta\text{begindir\_opened}$, `bytes_total{direction="out"}` low, and `tor-main` total CPU drops from $\sim 99.9\%$ to $< 35\%$ | **Confirms `H1` + `H2`**; falsifies `H3`/`H4`/`H5` for low-output floods | `0001/0008` alone completely resolves the `sarkodie` main-loop stall; no policy flag is needed for pre-HTTP `BEGIN_DIR` open/abort floods | Keep `0001/0008` + `0002/0009` in production; keep `HSDirRefuseUnknownPrevHop 0` and `HSDirOneRequestPerCircuit 0` unless Case 2/3 also appears |
| **Case 2**: Cleanup CPU $< 1\%$, saving `14%–90%` CPU, **but** `tor-main` still reaches $> 85\%$ CPU during floods with high `req_class="hs_v3_fetch",status_class="2xx"`, high `bytes_total{direction="out",req_class="hs_v3_fetch"}`, and high `ordinal_bucket=~"2_4|5_16|17_plus"` | **Confirms `H3`** (same-circuit HS v3 fetch multiplexing) after removing `H2` masking | `0001/0008` removed the cleanup bottleneck, exposing real HS v3 response serving on reused circuits (`antglizzy`/`joji` residual 85% CPU) | Test `HSDirOneRequestPerCircuit 1` on a single Stage 2 canary (`HS_PATCHES/0002` only gates `directory_handle_command_hs_get()`, preserving ordinary directory circuit reuse) |
| **Case 3**: Same as Case 2 (`req_class="hs_v3_fetch"`), **but** `ordinal_bucket="1"` dominates ($> 90\%$) | **Confirms `H4`** (single-request-per-circuit HS v3 flood); falsifies `H3` | Attackers are building or using distinct circuits per HS fetch (`HSDirOneRequestPerCircuit 1` will not stop it) | Evaluate `HSDirRefuseUnknownPrevHop 1` on a Stage 2 canary if direct client-to-HSDir circuits are used, or per-circuit/per-OR-conn `BEGIN_DIR` token-bucket rate limiting if 3-hop relay circuits are used |
| **Case 4**: High `req_class=~"ordinary_.*"`, high `bytes_total{direction="out",req_class=~"ordinary_.*"}`, and zlib/zstd compression (`compress_zlib` / `libz.so`) dominates `perf` | **Confirms `H5`**; falsifies HS-specific flood | Flood is abusing uncached/compressed ordinary directory endpoints, not HSDir | Do **not** enable HS policy flags (they have zero effect on `ordinary_*`); investigate pre-compressed response caching or per-OR-conn directory queue limits |
| **Case 5**: High `ops_total{list="closeable_connection_lst",op="deferred_held_open"}` and large `entries{list="closeable_connection_lst"}` during slow-read attacks | **Confirms `H6`** (slow-client `hold_open_until_flushed` accumulation) | `0001/0008` prevents $O(C \cdot (A + N))$ scan of held-open connections, but memory/buffer pressure accumulates in `closeable_connection_lst` | Rely on `tor_relay_load_oom_bytes_total{subsys="dir"}` and evaluate tightening `hold_open_until_flushed` timeout under directory buffer pressure |
