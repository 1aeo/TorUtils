### Summary

During sustained `RELAY_BEGIN_DIR` floods on `Tor 0.4.9.14` relays, main-thread CPU pins at `99.86%` even when outbound relay traffic is modest (`45.84 Mbit/s`). Hardware `perf` profiling of the main thread shows that **`90.47%` of all userspace CPU samples** (`1,775 / 1,962` samples; `85.38%` of total kernel+userspace samples) are spent in two linear $O(N)$ `smartlist` scans inside the per-connection teardown path (`close_closeable_connections()` $\to$ `connection_unlink()`):

1. **`connection_stop_reading_from_linked_conn()` $\to$ `smartlist_remove(active_linked_connection_lst, conn)`** (**`50.58%`** of userspace main-thread CPU; `992 / 1,962` samples): scans the entire `active_linked_connection_lst` on every linked connection teardown, even when `conn->active_on_link == 0`.
2. **`connection_free_()` $\to$ `tor_assert(!connection_in_array(conn))` $\to$ `smartlist_contains(connection_array, conn)`** (**`39.89%`** of userspace main-thread CPU; `783 / 1,962` samples): scans the entire `connection_array` to prove absence after `connection_remove()` has already set `conn->conn_array_index = -1`.

We propose a 2-commit series on `tor-0.4.9.14` (available in [`1aeo/torutils` branch `mainloop-cleanup-indexing`](https://github.com/1aeo/torutils/tree/mainloop-cleanup-indexing/mainloop-cleanup-indexing)):
- **Commit 1 (`mainloop: index connection_array, active_linked, and closeable cleanup scans`, `+53` net production C lines)**: Replaces all linear membership and removal scans across `connection_array`, `active_linked_connection_lst`, and `closeable_connection_lst` with $O(1)$ index-tracked swap-delete (`CONN_IDX_LIST_ADD` / `CONN_IDX_LIST_DEL`) and $O(1)$ structural index assertions (`connection_in_idx_list()`). Also fixes 4 unit tests in `test_conflux_pool.c` and `test_hs_client.c` that pushed dummy `connection_t` objects onto `get_connection_array()` via `smartlist_add()` without initializing `conn_array_index`.
- **Commit 2 (`relay_metrics: add mainloop cleanup, tick stall, and BEGIN_DIR metrics`, `+529` net production C lines)**: Adds 9 fixed-cardinality Prometheus metrics (`112` time series total) on `MetricsPort` to expose mainloop connection-list occupancies, `close_closeable_connections()` pass work/duration, event-loop tick stalls, and server-side `BEGIN_DIR` stream lifecycle phases, circuit reuse, HTTP request classes, HTTP statuses, and application bytes.

---

### Problem & Production `perf` Evidence (`Tor 0.4.9.14`)

Each `RELAY_BEGIN_DIR` cell creates a linked `(edge_connection_t, dir_connection_t)` pair via `connection_exit_connect_dir()` (`src/core/or/connection_edge.c:4691`), adding both connections to `connection_array`. When a batch of $K$ directory streams closes in a single `close_closeable_connections()` pass while `connection_array` has $N_{\text{conn}}$ connections and `active_linked_connection_lst` has $N_{\text{active}}$ connections, stock `0.4.9.14` performs $2K \times (N_{\text{conn}} + N_{\text{active}})$ pointer comparisons per pass:

- In `src/core/mainloop/mainloop.c:876`, `connection_stop_reading_from_linked_conn()` clears `conn->active_on_link = 0` and unconditionally calls `smartlist_remove(active_linked_connection_lst, conn)`. In `src/lib/smartlist_core/smartlist_core.c:195`, `smartlist_remove()` scans every element of `sl->list[0..num_used-1]` and does **not** break on match; when `conn` is absent (`active_on_link == 0`, the common case at `connection_unlink()` time), it scans `100%` of `active_linked_connection_lst`.
- In `src/core/mainloop/connection.c:967`, `connection_free_()` asserts `tor_assert(!connection_is_on_closeable_list(conn))` and `tor_assert(!connection_in_array(conn))`. Although `connection_remove()` (`mainloop.c:320`) already used `conn->conn_array_index` for $O(1)$ `smartlist_del()` and set `conn->conn_array_index = -1`, `connection_in_array()` (`mainloop.c:453`) calls `smartlist_contains(connection_array, conn)`, scanning `100%` of `connection_array` on every connection free.

| Relay / Role (`Tor 0.4.9.14`, Build ID `8b225673...`) | `BEGIN_DIR` Rate | Outbound Traffic | Main-Thread CPU | `connection_stop_reading_from_linked_conn` (`smartlist_remove`) | `connection_free_` (`!connection_in_array` / `smartlist_contains`) | Combined Cleanup Scan Share (Userspace Main-Thread) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **`sarkodie`** (Flooded target, `38.65s` capture, `2,079` main-TID samples) | **`5,585.4 / s`** | `45.84 Mbit/s` | **`99.86%`** | **`50.58%`** (`992 / 1,962`) | **`39.89%`** (`783 / 1,962`) | **`90.47%`** (`1,775 / 1,962`) |
| **`goodiemob`** (Co-hosted control, `34.18s` capture, `1,252` main-TID samples) | `7.1 / s` | `390.61 Mbit/s` | `67.14%` | `0.10%` (`1 / 1,004`) | `0.00%` (`0 / 1,004`) | **`0.10%`** (`1 / 1,004`) |
| **`antglizzy`** (Flooded + high output, `35.24s` capture, `2,068` main-TID samples) | `1,303.7 / s` | `317.85 Mbit/s` | `99.78%` | `9.69%` (`152 / 1,568`) | `4.91%` (`77 / 1,568`) | **`14.60%`** (`229 / 1,568`) |
| **`joji`** (Ending flood + high output, `31.11s` capture, `2,020` main-TID samples) | `742.6 / s` $\to$ `2.8 / s` | `369.92 Mbit/s` | `97.92%` | `10.17%` (`166 / 1,632`) | `4.17%` (`68 / 1,632`) | **`14.34%`** (`234 / 1,632`) |

In the `sarkodie` capture, `991 / 992` samples in `connection_stop_reading_from_linked_conn()` hit the 4-instruction `smartlist_remove` loop (`0xca9c8..0xca9d4`), and `783 / 783` samples in `connection_free_()` hit the 5-instruction `smartlist_contains` -> `smartlist_pos` loop (`0x1f71e0..0x1f71f0`).

---

### Commit 1: `mainloop: index connection_array, active_linked, and closeable cleanup scans`

#### Production C Changes (`+53` net lines across 4 files)
1. **`src/core/or/connection_st.h` (`+4` lines)**: Adds `int closeable_conn_idx;` and `int active_linked_conn_idx;` to `struct connection_t` alongside the existing `int conn_array_index;`.
2. **`src/core/mainloop/connection.c` (`+3` lines)**: Initializes `conn->closeable_conn_idx = -1;` and `conn->active_linked_conn_idx = -1;` in `connection_init()`, and adds `tor_assert(!connection_in_active_linked_list(conn));` to `connection_free_()`.
3. **`src/core/mainloop/mainloop.h` (`+4` lines)**: Declares `int connection_in_active_linked_list(const connection_t *conn);`.
4. **`src/core/mainloop/mainloop.c` (`+84 / -42` lines; `+42` net lines)**:
   - Defines `CONN_IDX_LIST_ADD(sl, conn, field)` and `CONN_IDX_LIST_DEL(sl, conn, field)` to maintain `conn_array_index`, `closeable_conn_idx`, and `active_linked_conn_idx` in $O(1)$ across `connection_add_impl()`, `connection_remove()`, `add_connection_to_closeable_list()`, `connection_unlink()`, `connection_start_reading_from_linked_conn()`, and `connection_stop_reading_from_linked_conn()`.
   - Replaces the linear `smartlist_contains()` scans in `connection_in_array()`, `connection_is_on_closeable_list()`, and `connection_in_active_linked_list()` with a single $O(1)$ helper `connection_in_idx_list(sl, conn, idx)` that asserts `idx == -1` when `< 0`, or `sl != NULL && idx < smartlist_len(sl) && smartlist_get(sl, idx) == conn` when `>= 0`.
   - Simplifies `close_closeable_connections()` to iterate `closeable_connection_lst` in $O(K)$ while holding deferred connections (`conn_close_if_marked() == 0`) in place.

```c
/* src/core/mainloop/mainloop.c */
#define CONN_IDX_LIST_ADD(sl, conn, field) STMT_BEGIN {                 \
  if (PREDICT_UNLIKELY(!(sl)))                                          \
    (sl) = smartlist_new();                                             \
  (conn)->field = smartlist_len(sl);                                    \
  smartlist_add((sl), (conn));                                          \
} STMT_END

#define CONN_IDX_LIST_DEL(sl, conn, field) STMT_BEGIN {                 \
  int idx_ = (conn)->field;                                             \
  tor_assert(connection_in_idx_list((sl), (conn), idx_));               \
  smartlist_del((sl), idx_);                                            \
  if (idx_ < smartlist_len(sl)) {                                       \
    connection_t *swapped_ = smartlist_get((sl), idx_);                 \
    swapped_->field = idx_;                                             \
  }                                                                     \
  (conn)->field = -1;                                                   \
} STMT_END
```

#### Unit Test Mock Fixes (`src/test/test_conflux_pool.c`, `src/test/test_hs_client.c`)
Because `connection_in_array()` now enforces bidirectional index coherence (`conn_array_index == -1` iff absent; `connection_array[conn_array_index] == conn` iff present), 4 existing unit tests that bypassed `connection_add()` by calling `smartlist_add(get_connection_array(), ...)` on raw `tor_malloc_zero(sizeof(connection_t))` or `edge_connection_new()` structs were updated to initialize `conn_array_index` (and remove dummy connections before `connection_free_minimal()`).

#### Audited Microbenchmark Results (`N = 100 .. 50,000`, 25 Paired Iterations)

| Occupancy ($N$) | Workload | Baseline Comparisons / Pass | Patched Comparisons / Pass | Baseline Median (`usec`) | Patched Median (`usec`) | Wall-Time Speedup |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: |
| **`1,000`** | W1: `BEGIN_DIR` flood (`500` stream pairs closed) | `2,499,000` | **`1,000`** | `428.83` | **`16.58`** | **`25.86x`** |
| **`5,000`** | W1: `BEGIN_DIR` flood (`2,500` stream pairs closed) | `62,495,000` | **`5,000`** | `11,038.33` | **`90.38`** | **`122.14x`** |
| **`10,000`** | W1: `BEGIN_DIR` flood (`5,000` stream pairs closed) | `249,990,000` | **`10,000`** | `46,064.54` | **`176.31`** | **`261.26x`** |
| **`50,000`** | W1: `BEGIN_DIR` flood (`25,000` stream pairs closed) | `6,249,950,000` | **`50,000`** | `1,152,000.00` | **`920.00`** | **`1,252.17x`** |
| **`5,000`** | W3: Sparse `active_linked` (`50` active, `500` pairs closed) | `3,999,000` | **`1,000`** | `655.69` | **`14.69`** | **`44.63x`** |
| **`10,000`** | W3: Sparse `active_linked` (`50` active, `500` pairs closed) | `8,999,000` | **`1,000`** | `1,531.65` | **`14.89`** | **`102.88x`** |
| **`5,000`** | W4: Deferred flush (`hold_open_until_flushed`, `500` held) | `12,499,000` | **`2,500`** | `2,068.52` | **`15.46`** | **`133.81x`** |

---

### Commit 2: `relay_metrics: add mainloop cleanup, tick stall, and BEGIN_DIR metrics`

While Commit 1 eliminates the $O(N)$ cleanup scans, stock `Tor 0.4.9.14` has no `MetricsPort` visibility into mainloop connection-list sizes, cleanup pass duration, event-loop stall ticks, or `BEGIN_DIR` request classes (`consensus` vs `hs_v3_fetch` vs `hs_v3_publish` vs malformed/aborted streams). Commit 2 adds 9 fixed-cardinality metrics (`112` series total, no per-circuit/per-IP/per-service labels, $O(1)$ hot-path updates):

| Metric Name | Type | Labels (Cardinality) | Purpose |
| :--- | :---: | :--- | :--- |
| `tor_relay_mainloop_connection_list_size` | Gauge | `list` (`connection_array`, `closeable`, `active_linked`) (3) | Exposes the exact runtime list sizes ($N_{\text{conn}}, N_{\text{closeable}}, N_{\text{active}}$) |
| `tor_relay_mainloop_connection_list_ops_total` | Counter | `list` (`closeable`, `active_linked`), `op="add"` (2) | Measures connection closure and linked-read activation rates |
| `tor_relay_mainloop_close_pass_total` | Counter | `field` (`runs`, `visited`, `closed`, `deferred`, `duration_usec`) (5) | Quantifies `close_closeable_connections()` work, deferred-flush backlog, and CPU time |
| `tor_relay_mainloop_ticks_total` | Counter | `threshold` (`over_10ms`, `over_100ms`, `over_1000ms`) (3) | Counts `run_main_loop_once()` event-loop stalls exceeding `10 ms`, `100 ms`, and `1 s` |
| `tor_relay_mainloop_tick_max_duration_usec` | Gauge | none (1) | High-water-mark single event-loop tick duration in microseconds |
| `tor_relay_dir_streams_total` | Counter | `phase` (`opened`, `writing`, `completed`, `aborted_pre_http`, `aborted_mid_http`, `aborted_writing`, `reused_circuit`) (7) | Tracks server-side `BEGIN_DIR` stream lifecycle conservation and per-circuit stream reuse |
| `tor_relay_dir_streams_active` | Gauge | `state` (`opened_wait`, `writing`) (2) | Current server-side `BEGIN_DIR` streams waiting for HTTP headers vs writing responses |
| `tor_relay_dir_http_requests_total` | Counter | `class` (10) $\times$ `status` (`200`, `304`, `400`, `404`, `503`, `other`, `rejected_early`) (70) | Distinguishes ordinary directory fetches (`consensus`, `microdesc`, `server_desc`, `extra_info`, `authority_certs`) from `hs_v3_fetch`, `hs_v3_publish`, and `invalid`/`unclassified` requests |
| `tor_relay_dir_bytes_total` | Counter | `class` (10) $\times$ `dir` (`read`, `written`) (20) | Separates server-side directory application bytes by request class from whole-process OR traffic |

Both commits apply cleanly with `git am` on stock `tor-0.4.9.14` (`8fe2745`) as well as on top of the 7-patch `#41339` HSDir defense series (`0008` and `0009` in the repository).

---

### Code References (`tor-0.4.9.14`)

- **Linear cleanup scans in `mainloop.c` and `connection.c`**:
  - [`src/core/mainloop/mainloop.c#L870-L879`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/mainloop/mainloop.c#L870-L879) (`connection_stop_reading_from_linked_conn()` calling `smartlist_remove(active_linked_connection_lst, conn)`)
  - [`src/core/mainloop/connection.c#L964-L969`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/mainloop/connection.c#L964-L969) (`connection_free_()` asserting `!connection_is_on_closeable_list(conn)` and `!connection_in_array(conn)`)
  - [`src/core/mainloop/mainloop.c#L440-L456`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/mainloop/mainloop.c#L440-L456) (`connection_is_on_closeable_list()` and `connection_in_array()` calling `smartlist_contains()`)
  - [`src/core/mainloop/mainloop.c#L882-L905`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/mainloop/mainloop.c#L882-L905) (`close_closeable_connections()`)
  - [`src/lib/smartlist_core/smartlist_core.c#L195-L225`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/lib/smartlist_core/smartlist_core.c#L195-L225) (`smartlist_remove()` full-list scan and `smartlist_contains()` linear search)
- **Server-side `BEGIN_DIR` and `MetricsPort` hooks**:
  - [`src/core/or/connection_edge.c#L4691-L4753`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/or/connection_edge.c#L4691-L4753) (`connection_exit_connect_dir()`)
  - [`src/feature/dircache/dircache.c#L342-L476`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/feature/dircache/dircache.c#L342-L476) (`url_table[]`, `directory_handle_command_get()`, `directory_handle_command_post()`, `directory_handle_command()`)
  - [`src/feature/dircommon/directory.c#L518-L585`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/feature/dircommon/directory.c#L518-L585) (`connection_dir_about_to_close()`, `connection_dir_finished_flushing()`)
  - [`src/core/mainloop/connection.c#L3655-L3665`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/mainloop/connection.c#L3655-L3665) (`record_num_bytes_transferred_impl()`)
  - [`src/feature/relay/relay_metrics.c`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/feature/relay/relay_metrics.c) (`base_metrics[]`)

/label ~Performance ~"Denial of Service" ~Metrics
