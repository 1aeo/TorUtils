# Deliverable 3: Prioritized Metrics Specification

## 1. Design Principles and Tor Metrics Subsystem Constraints

1. **Smallest useful metric set**: Every proposed metric answers a specific unresolved question (`[UNKNOWN-U1..U4]`, `H1..H6`) that could not be answered from stock `MetricsPort` counters or the 4 initial `tor_hsdir_*` pilot counters.
2. **Strict $O(1)$ hot-path and scrape-path cost**:
   * All hot-path updates are single static `uint64_t` increments or gauge updates (`< 5 ns` per increment, zero heap allocations, zero locks on the single-threaded main loop).
   * All scrape-time gauge collections read `smartlist_len(...)` (`sl->num_used`, an $O(1)$ integer field load) or static `uint64_t` accumulators in `src/feature/relay/relay_metrics.c`. No new `SMARTLIST_FOREACH` scans over `connection_array`, `active_linked_connection_lst`, `closeable_connection_lst`, or circuit lists are introduced on either the hot path or the `MetricsPort` scrape path.
3. **Bounded fixed cardinality (no identifiers or payloads)**:
   * Zero circuit IDs, stream IDs, IP addresses, relay fingerprints, blinded pubkeys, descriptor IDs, or URL strings are ever used as label values. Total time series added across all tiers is **32 fixed series**.
4. **Integer histogram bucket constraint in Tor (`src/lib/metrics/metrics_common.h:41`)**:
   * In Tor's metrics library, `metrics_histogram_bucket_t` defines `int64_t bucket;`. Fractional `double` bucket boundaries (such as `0.01` or `0.1` seconds) **cannot** be represented in `METRICS_HISTOGRAM`. Therefore, any duration or lifetime histogram in Tor must use integer **microseconds (`_microseconds`)** or **milliseconds (`_milliseconds`)**, or fixed integer counter buckets.
5. **Fixing the `tor_hsdir_request_total` guard-ordering blind spot**:
   * In `HS_PATCHES` `0001` and `0002` (`src/feature/dircommon/directory.c:2320-2375` for `GET` and `2500-2540` for `POST`), `hs_metrics_new_request()` (`tor_hsdir_request_total`) is called **after** the two defense checks (`hsdir_unknown_prev_hop` and `hsdir_req_reused`). If either defense is enabled in the future (or if a request fails HTTP parsing earlier in `directory_handle_command`), `tor_hsdir_request_total` is **not** incremented, breaking denominator conservation. Worse, `BEGIN_DIR - tor_hsdir_request_total` is invalid as an ordinary-request counter even when both defenses are disabled because `BEGIN_DIR` counts stream starts (`connection_exit_begin_conn`), whereas `tor_hsdir_request_total` counts parsed HTTP `/tor/hs/3/...` requests. Our Tier 1 metrics enforce exact stream-level and HTTP-level conservation laws.

---

## 2. Summary Table of Prioritized Metrics (Tiers 0–2)

| Tier | Metric Name (`tor_relay_...`) | Type | Fixed Labels / Buckets | Series Count | Unresolved Question / Hypothesis Targeted | Exact Code Hook (`file:function:line`) |
| :---: | :--- | :---: | :--- | :---: | :--- | :--- |
| **Tier 0** | `tor_relay_mainloop_connection_list_entries` | Gauge | `list="connection_array" \| "active_linked" \| "closeable"` | 3 | `[UNKNOWN-U1]`, **H1**, **H3**: What are the actual runtime list occupancies $(N, A, C)$ during normal load vs. floods? | `src/core/mainloop/mainloop.c`: $O(1)$ `smartlist_len()` accessors called from `fill_mainloop_values()` in `src/feature/relay/relay_metrics.c` |
| **Tier 0** | `tor_relay_mainloop_connection_list_max_entries` | Gauge (Watermark) | `list="connection_array" \| "active_linked" \| "closeable"` | 3 | `[UNKNOWN-U1]`, **H1**: What peak $(N, A, C)$ occurred *between* `MetricsPort` scrapes (e.g. inside a single cleanup wave)? | Updated in `connection_add_impl` (`mainloop.c:290`), `connection_start_reading_from_linked_conn` (`mainloop.c:868`), `add_connection_to_closeable_list` (`mainloop.c:248`) |
| **Tier 0** | `tor_relay_mainloop_connection_transitions_total` | Counter | `event="conn_added" \| "conn_removed" \| "active_linked_added" \| "active_linked_removed" \| "closeable_added" \| "closeable_closed" \| "closeable_deferred_held_open"` | 7 | **H1**, **H3**: Is `active_linked` churn driven by one-shot teardown (`closeable_closed`) or repeated read/write throttling (`active_linked_added/removed` $\gg$ `conn_added`), or held-open backlog (`closeable_deferred_held_open`)? | `mainloop.c`: `connection_add_impl`, `connection_remove`, `connection_start_reading_from_linked_conn`, `connection_stop_reading_from_linked_conn`, `add_connection_to_closeable_list`, `close_closeable_connections` |
| **Tier 0** | `tor_relay_mainloop_cleanup_passes_total` | Counter | `batch_bucket="1_16" \| "17_64" \| "65_256" \| "257_1024" \| "1025_plus"` | 5 | **H1**: Distribution of closures $C$ per `close_closeable_connections()` pass. | `src/core/mainloop/mainloop.c`: `close_closeable_connections()` (`mainloop.c:914-943`) |
| **Tier 0** | `tor_relay_mainloop_cleanup_duration_microseconds_total` | Counter | `phase="close_closeable" \| "active_linked_cb"` | 2 | **H1**, `[UNKNOWN-U4]`: Exact wall/monotonic microseconds spent in `close_closeable_connections()` and `run_active_linked_connections_cb()`. | `src/core/mainloop/mainloop.c`: `close_closeable_connections()` (`mainloop.c:914`) and `run_active_linked_connections_cb()` (`mainloop.c:787`) using `monotime_coarse_get_nsec()` |
| **Tier 0** | `tor_relay_mainloop_heartbeat_delay_microseconds_max` & `_over_10ms_total` | Gauge & Counter | `metric="max_delay_us" \| "stalls_over_10ms" \| "stalls_over_100ms"` | 3 | **H1**, **H2**: Does the main event loop still experience $>10\text{ ms}$ or $>100\text{ ms}$ callback stalls after Patch `0001`? | `src/core/mainloop/mainloop.c`: 1-second periodic callback (`second_elapsed_callback`, `mainloop.c:1671`) measuring excess over `1,000,000 us` + per-cleanup-pass stall check |
| **Tier 1** | `tor_relay_dir_streams_total` | Counter | `stage="begindir_opened" \| "closed_completed" \| "closed_aborted_pre_http" \| "closed_aborted_mid_http" \| "closed_aborted_writing" \| "rejected_busy"` | 6 | `[UNKNOWN-U2]`, `[UNKNOWN-U3]`, **H3**, **H5**: How many `BEGIN_DIR` streams abort before HTTP parsing vs. mid-write vs. complete cleanly? | Open: `src/core/or/connection_edge.c:connection_exit_begin_conn` (`L4395`); Close: `src/core/mainloop/connection.c:connection_about_to_close_connection` (`L1068`) & `directory.c:connection_dir_finished_flushing` (`L4812`) |
| **Tier 1** | `tor_relay_dir_active_streams` | Gauge | `state="reading_request" \| "writing_response"` | 2 | **H3**: How many `CONN_TYPE_DIR` server streams are concurrently open in `SERVER_COMMAND_WAIT` vs. `SERVER_WRITING`? | Incremented/decremented on `DIR_PURPOSE_SERVER` state transitions in `connection_exit_begin_conn`, `directory_handle_command`, and `connection_about_to_close_connection` |
| **Tier 1** | `tor_relay_dir_http_requests_total` | Counter | `req_class="hs_v3_get" \| "hs_v3_post" \| "ordinary_consensus" \| "ordinary_descriptor" \| "ordinary_other" \| "malformed_or_unsupported"`, `status_class="2xx" \| "3xx" \| "4xx" \| "5xx" \| "rejected_guard" \| "conn_closed"` | 12 (compact `class:status` pairs) | `[UNKNOWN-U2]`, **H2**, **H5**: Direct, pre-guard classification of all incoming directory HTTP requests into ordinary vs. HS v3 vs. malformed, plus HTTP response status class. | `src/feature/dircommon/directory.c`: `directory_handle_command()` (`L2215`), `directory_handle_command_get()` (`L2295`), `directory_handle_command_post()` (`L2485`), `write_http_status_line()` (`L3955`) |
| **Tier 1** | `tor_relay_dir_bytes_total` | Counter | `dir="request_read" \| "response_written"`, `req_class="hs_v3" \| "ordinary" \| "unclassified"` | 6 | `[UNKNOWN-U3]`, **H2**: Exact directory request bytes read and directory response bytes flushed to the linked stream (separated from whole-process OR relay traffic). | `src/core/mainloop/connection.c`: when `conn->type == CONN_TYPE_DIR && conn->purpose == DIR_PURPOSE_SERVER` moves bytes across the linked connection buffer (`connection_Fetch_from_buf` / `write_to_buf`) |
| **Tier 2** | `tor_relay_begindir_circuit_stream_ordinal_total` | Counter | `ordinal_bucket="1" \| "2_4" \| "5_16" \| "17_plus"` | 4 | **H4**: Are `BEGIN_DIR` floods multiplexing dozens/hundreds of `BEGIN_DIR` streams per OR circuit (`17_plus`), or using 1–4 sequential streams per circuit like normal Tor clients? | `src/core/or/connection_edge.c:connection_exit_begin_conn` (`L4395`), incrementing `uint16_t begindir_streams_opened` on `or_circuit_t` (`src/core/or/or_circuit_st.h`) |

---

## 3. Detailed Per-Metric Specification

### 3.1 Tier 0: Main-Loop Global List Occupancy, Churn, Cleanup Cost, and Event-Loop Delay

#### M0.1 `tor_relay_mainloop_connection_list_entries` & `tor_relay_mainloop_connection_list_max_entries`
* **Unresolved Question**: `[UNKNOWN-U1]` — What are the true runtime sizes $N = \text{smartlist\_len}(\text{connection\_array})$, $A = \text{smartlist\_len}(\text{active\_linked\_connection\_lst})$, and $C = \text{smartlist\_len}(\text{closeable\_connection\_lst})$, and their peak watermarks between scrapes?
* **Exact Code Hooks**:
  * In `src/core/mainloop/mainloop.c`, track three static `uint64_t` high-watermarks (`max_connection_array_len`, `max_active_linked_conn_len`, `max_closeable_conn_len`) updated via a 2-line branch `if ((uint64_t)len > max_...) max_... = (uint64_t)len;` in `connection_add_impl()`, `connection_start_reading_from_linked_conn()`, and `add_connection_to_closeable_list()`.
  * Expose $O(1)$ getter `mainloop_get_connection_list_metrics(mainloop_list_metrics_t *out)` called by `fill_mainloop_values()` in `src/feature/relay/relay_metrics.c`.
* **Overhead**: Scrape-time read of 3 `int` fields (`sl->num_used`) + 3 static `uint64_t` watermarks (`~2 ns`).
* **Hypothesis Discrimination**:
  * **Supports H1/H3**: Under `>=500 BEGIN_DIR/s`, if `max_active_linked_conn_len` ($A$) stays low (`< 200`) after Patch `0001`, then the high $A$ on `sarkodie` was a self-reinforcing artifact of the `92.36%` cleanup stall starving linked-connection reads (**H1**). Conversely, if $A$ climbs to `2,000–10,000+` even with $O(1)$ cleanup, clients are deliberately holding directory streams open / slow-reading (**H3**).

#### M0.2 `tor_relay_mainloop_connection_transitions_total`
* **Unresolved Question**: Is `active_linked_connection_lst` churn dominated by one-shot stream creation/teardown (`conn_added` $\approx$ `active_linked_added`), or by multi-chunk streaming backpressure (`active_linked_added` $\gg$ `conn_added`), or by held-open connections (`closeable_deferred_held_open`)?
* **Exact Code Hooks (`src/core/mainloop/mainloop.c`)**:
  * `conn_added`: `connection_add_impl()` (`L292`)
  * `conn_removed`: `connection_remove()` (`L350`)
  * `active_linked_added`: `connection_start_reading_from_linked_conn()` (`L869`, inside `if (!conn->active_on_link)`)
  * `active_linked_removed`: `connection_stop_reading_from_linked_conn()` (`L895`, inside `if (conn->active_on_link)`)
  * `closeable_added`: `add_connection_to_closeable_list()` (`L249`, inside `if (!connection_is_on_closeable_list(conn))`)
  * `closeable_closed` vs. `closeable_deferred_held_open`: `close_closeable_connections()` (`L920-940`, incremented when a connection is unlinked/closed vs. when `conn_close_if_marked` returns `0` and advances `++i`).
* **Conservation Identities**:
  $$\text{conn\_added} - \text{conn\_removed} = \text{tor\_relay\_mainloop\_connection\_list\_entries\{list="connection\_array"\}}$$
  $$\text{active\_linked\_added} - \text{active\_linked\_removed} = \text{tor\_relay\_mainloop\_connection\_list\_entries\{list="active\_linked"\}}$$
  $$\text{closeable\_added} - \text{closeable\_closed} = \text{tor\_relay\_mainloop\_connection\_list\_entries\{list="closeable"\}}$$
* **Hypothesis Discrimination**:
  * On `antglizzy` and `joji`, `36–40%` of `smartlist_remove` samples came from `connection_stop_reading`/`connection_stop_writing` tailcalls rather than `connection_unlink`. A ratio $\Delta\text{active\_linked\_removed} / \Delta\text{conn\_removed} \gg 2$ confirms multi-chunk streaming backpressure (**H2/H3**), whereas a ratio $\approx 1$ confirms single-shot setup/teardown (**H1/H5**).

#### M0.3 `tor_relay_mainloop_cleanup_passes_total`, `tor_relay_mainloop_cleanup_duration_microseconds_total`, and `tor_relay_mainloop_heartbeat_delay_microseconds_max`
* **Unresolved Question**: `[UNKNOWN-U4]` — After deploying Patch `0001`, how much wall/CPU time does `close_closeable_connections()` actually consume in production under flood, what is the batch size $C$ per pass, and does the Libevent main loop still stall?
* **Exact Code Hooks (`src/core/mainloop/mainloop.c`)**:
  * In `close_closeable_connections()`: if `smartlist_len(closeable_connection_lst) > 0`, capture `uint64_t t0 = monotime_coarse_get_nsec();` on entry and `uint64_t dt_us = (monotime_coarse_get_nsec() - t0) / 1000;` on exit. Increment `cleanup_duration_us_total` by `dt_us` and increment `cleanup_passes_total` in the bucket matching `closed_in_this_pass` (`1..16`, `17..64`, `65..256`, `257..1024`, `1025+`).
  * In `run_active_linked_connections_cb()`: capture coarse monotonic delta `dt_us` and add to `cleanup_duration_microseconds_total{phase="active_linked_cb"}`.
  * In `second_elapsed_callback()` (`mainloop.c:1671`): compare `monotime_coarse_get_nsec()` delta against the expected `1,000,000 us` interval; record any positive scheduling delay `delay_us` in `heartbeat_delay_microseconds_max` and increment `stalls_over_10ms` / `stalls_over_100ms` if `delay_us >= 10000` or `>= 100000`.
* **Overhead**: Two `clock_gettime(CLOCK_MONOTONIC_COARSE)` VDSO calls per non-empty cleanup pass (`~12 ns` total on Linux `aarch64`/`x86_64`).
* **Hypothesis Discrimination**:
  * **Validates Fix 1 (`0001-mainloop-index-cleanup-scans.patch`)**: Under `>=500 BEGIN_DIR/s`, `rate(tor_relay_mainloop_cleanup_duration_microseconds_total{phase="close_closeable"}[1m]) / 1e6` directly measures the fraction of main-thread wall time spent in `close_closeable_connections()`. If this fraction is `< 0.01` (`< 1%` of 1 core) while main-thread CPU is still `> 90%`, then **H1** is completely solved and the remaining bottleneck has shifted to **H2** (`active_linked_cb`, compression, crypto, cell packaging).

---

### 3.2 Tier 1: `BEGIN_DIR` Stream Lifecycle, Pre-Guard Request Classification, and Directory Byte Accounting

#### M1.1 `tor_relay_dir_streams_total` and `tor_relay_dir_active_streams`
* **Unresolved Question**: `[UNKNOWN-U2]`, `[UNKNOWN-U3]`, **H3**, **H5** — What fraction of `BEGIN_DIR` streams complete a full HTTP request/response cycle vs. aborting before sending a complete HTTP header (`closed_aborted_pre_http`, e.g. `BEGIN_DIR` + immediate `RELAY_END`) vs. aborting while the relay is still writing out the response (`closed_aborted_writing`)?
* **Exact Code Hooks**:
  * Add a 1-byte bitfield/enum `uint8_t dir_metrics_phase` on `dir_connection_t` (`src/feature/dircommon/dir_connection_st.h`):
    * `DIR_METRICS_PHASE_NONE = 0` (non-server dir conn)
    * `DIR_METRICS_PHASE_WAIT_REQ = 1` (set in `connection_exit_begin_conn`, `src/core/or/connection_edge.c:4425`, when creating the `DIR_PURPOSE_SERVER` connection: increments `tor_relay_dir_streams_total{stage="begindir_opened"}` and `active_streams{state="reading_request"}++`)
    * `DIR_METRICS_PHASE_WRITING_RESP = 2` (set in `directory_handle_command`, `src/feature/dircommon/directory.c:2255`, when a complete HTTP command is parsed and transitions to `DIR_CONN_STATE_SERVER_WRITING`: `active_streams{state="reading_request"}--`, `active_streams{state="writing_response"}++`)
    * `DIR_METRICS_PHASE_COMPLETED = 3` (set in `connection_dir_finished_flushing`, `src/feature/dircommon/directory.c:4815`, when `outbuf` finishes flushing: increments `tor_relay_dir_streams_total{stage="closed_completed"}`)
  * In `connection_about_to_close_connection()` (`src/core/mainloop/connection.c:1075`): for `conn->type == CONN_TYPE_DIR && conn->purpose == DIR_PURPOSE_SERVER`:
    * Decrement the active gauge matching `dir_conn->dir_metrics_phase`.
    * If `dir_metrics_phase == DIR_METRICS_PHASE_WAIT_REQ`: increment `closed_aborted_pre_http` (if `inbuf` is empty) or `closed_aborted_mid_http` (if `inbuf` has partial unparsed bytes).
    * If `dir_metrics_phase == DIR_METRICS_PHASE_WRITING_RESP`: increment `closed_aborted_writing` (closed while unflushed response bytes remained or before `connection_dir_finished_flushing`).
* **Conservation Identity**:
  $$\text{begindir\_opened} = \text{closed\_completed} + \text{closed\_aborted\_pre\_http} + \text{closed\_aborted\_mid\_http} + \text{closed\_aborted\_writing} + \sum \text{active\_streams}$$
* **Hypothesis Discrimination**:
  * **Supports H5**: If `closed_aborted_pre_http` or `closed_aborted_mid_http` spikes during low-output floods (`sarkodie` / `krsone` regime), attackers are churning `BEGIN_DIR` streams without completing HTTP requests.
  * **Supports H3**: If `active_streams{state="writing_response"}` climbs into the thousands and `closed_aborted_writing` spikes, slow-reading clients are holding response buffers open.

#### M1.2 `tor_relay_dir_http_requests_total`
* **Unresolved Question**: `[UNKNOWN-U2]` — During a flood, what are the incoming HTTP requests (`hs_v3_get`, `hs_v3_post`, `ordinary_consensus`, `ordinary_descriptor`, `ordinary_other`, `malformed_or_unsupported`) and what HTTP status class (`2xx`, `3xx`, `4xx`, `5xx`, `rejected_guard`) do they receive?
* **Exact Code Hooks (`src/feature/dircommon/directory.c`)**:
  * Classify the parsed `url` **at the top** of `directory_handle_command_get()` (`L2295`) and `directory_handle_command_post()` (`L2485`), **before** any defense guard (`hsdir_unknown_prev_hop`, `hsdir_req_reused`) or status return:
    * `url` starts with `"/tor/hs/3/"` -> `hs_v3_get` (in GET) or `hs_v3_post` (in POST)
    * `url` starts with `"/tor/status-vote/"` -> `ordinary_consensus`
    * `url` starts with `"/tor/server/"` or `"/tor/extra/"` or `"/tor/micro/"` or `"/tor/keys/"` -> `ordinary_descriptor`
    * Any other valid GET/POST URL -> `ordinary_other`
    * Parse failure in `parse_http_command` (`directory_handle_command`, `L2228`) -> `malformed_or_unsupported`
  * Store `dir_conn->dir_req_class` (`uint8_t`) on `dir_connection_t` and increment `tor_relay_dir_http_requests_total` when `write_http_status_line(dir_conn, status, ...)` (`directory.c:3955`) sends the response status (`2xx`, `3xx`, `4xx`, `5xx`) or when a defense guard closes the connection (`rejected_guard`).
* **Overhead**: Single `strcmp_start` prefix check (already performed by `directory_handle_command_get`) + 1 array increment (`~5 ns`).
* **Hypothesis Discrimination**:
  * Directly separates **ordinary directory floods** (`ordinary_consensus`, `ordinary_descriptor`) from **HS v3 floods** (`hs_v3_get`, `hs_v3_post`) and **malformed HTTP floods** (`malformed_or_unsupported`), regardless of whether `HSDirRefuseUnknownPrevHop` or `HSDirOneRequestPerCircuit` is enabled.

#### M1.3 `tor_relay_dir_bytes_total`
* **Unresolved Question**: `[UNKNOWN-U3]`, **H2** — How many bytes are actually read from and written to `DIR_PURPOSE_SERVER` directory connections (broken down by `hs_v3` vs. `ordinary`), independent of whole-process OR relay traffic?
* **Exact Code Hooks**:
  * In `src/core/mainloop/connection.c`:
    * In `connection_handle_read_impl()` (`L3920`, when transferring bytes from `conn->linked_conn->outbuf` into `conn->inbuf` for `conn->type == CONN_TYPE_DIR && conn->purpose == DIR_PURPOSE_SERVER`): add transferred byte count to `tor_relay_dir_bytes_total{dir="request_read"}`.
    * In `connection_write_to_buf_impl_()` (`src/core/mainloop/connection.c:4295`, when queuing response bytes into `conn->outbuf` for `conn->type == CONN_TYPE_DIR && conn->purpose == DIR_PURPOSE_SERVER`): add `len` to `tor_relay_dir_bytes_total{dir="response_written", req_class=...}` (using `TO_DIR_CONN(conn)->dir_req_class`).
* **Overhead**: One `uint64_t += len` addition per buffer read/write on `CONN_TYPE_DIR` (`~2 ns`).

---

### 3.3 Tier 2: Per-Circuit `BEGIN_DIR` Stream Multiplexing / Reuse Distribution

#### M2.1 `tor_relay_begindir_circuit_stream_ordinal_total`
* **Unresolved Question**: **H4** — Are flood `BEGIN_DIR` streams heavily multiplexed over single circuits (`17+` `BEGIN_DIR` streams per circuit), or modestly reused (`2..4` sequential streams per circuit like normal Tor clients), or `1` stream per circuit?
* **Why `tor_hsdir_req_reused_total` and `tor_hsdir_circ_reused_total` in `HS_PATCHES` `0002` cannot answer this**:
  1. `0002` only increments `dir_req_num` inside `directory_handle_command_get`/`_post` on `/tor/hs/3/` URLs. Ordinary directory requests and pre-HTTP aborted `BEGIN_DIR` streams never increment `dir_req_num`.
  2. `0002` only distinguishes `dir_req_num == 1` vs. `dir_req_num > 1` (a binary bit `has_counted_reuse`), so it cannot distinguish legitimate client sequential reuse of 2–3 requests on a circuit from an attacker multiplexing 500 `BEGIN_DIR` streams on one circuit.
* **Exact Code Hook**:
  * Add `uint16_t begindir_stream_count;` to `or_circuit_t` (`src/core/or/or_circuit_st.h:158`, fitting into existing struct padding alongside `uint8_t dir_req_num`).
  * In `connection_exit_begin_conn()` (`src/core/or/connection_edge.c:4395`), when `rh->command == RELAY_COMMAND_BEGIN_DIR` on an `OR_CIRCUIT`:
    ```c
    if (circ->purpose == CIRCUIT_PURPOSE_OR) {
      or_circuit_t *or_circ = TO_OR_CIRCUIT(circ);
      if (or_circ->begindir_stream_count < UINT16_MAX)
        or_circ->begindir_stream_count++;
      relay_metrics_note_begindir_circuit_ordinal(or_circ->begindir_stream_count);
    }
    ```
  * Bucket `begindir_stream_count` into 4 fixed ordinal buckets:
    * `ordinal_bucket="1"` (`count == 1`: first `BEGIN_DIR` on this circuit)
    * `ordinal_bucket="2_4"` (`2 <= count <= 4`: normal sequential reuse range)
    * `ordinal_bucket="5_16"` (`5 <= count <= 16`: moderate burst/bootstrap reuse)
    * `ordinal_bucket="17_plus"` (`count >= 17`: heavy stream multiplexing on a single circuit)
* **Overhead**: 2 bytes on `or_circuit_t` (0 net bytes due to alignment padding after `uint8_t dir_req_num`) + 1 integer increment per `BEGIN_DIR` cell (`~3 ns`).
* **Hypothesis Discrimination**:
  * **Confirms H4** if `ordinal_bucket="17_plus"` dominates during `>=500 BEGIN_DIR/s` floods while `ordinal_bucket="1"` and `"2_4"` dominate during normal traffic. More importantly, this distribution directly informs where a safe per-circuit rate/concurrency limit (e.g. allowing 4–8 streams per circuit before throttling) can be placed **without** breaking normal Tor client directory reuse (`2_4`).
