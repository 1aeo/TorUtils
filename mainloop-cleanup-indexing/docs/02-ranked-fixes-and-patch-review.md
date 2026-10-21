# Deliverable 2: Candidate Patch Review, HS Series Integration, and Ranked Fixes

## 1. Deep Audit of `0001-mainloop-index-cleanup-scans.patch`

### 1.1 Summary of Candidate Patch Changes
The candidate patch (`CANDIDATE/0001-mainloop-index-cleanup-scans.patch`, SHA256 `f200721cc7afebe3700faf1870da5c6f7e9bbd7f3b4de67c080a2aad45df6e0b`) eliminates linear $O(\text{len})$ scans across the three global connection smartlists in `src/core/mainloop/mainloop.c`, `src/core/mainloop/connection.c`, and `src/core/or/connection_st.h`:
1. **Struct additions (`src/core/or/connection_st.h:221-225`)**:
   * Adds `int active_linked_conn_index;` and `int closeable_conn_index;` immediately below `int conn_array_index;`.
   * On 64-bit Linux (`aarch64` and `x86_64`), `sizeof(connection_t)` increases by **8 bytes** (`152 -> 160` bytes; verified in `scaling-baseline.json` vs `scaling-patched.json`). At $N = 64,000$ connections, total struct memory overhead is $64,000 \times 8 = 512\text{ KB}$.
2. **Initialization (`src/core/mainloop/connection.c:696-698`)**:
   * `connection_init()` initializes `conn->conn_array_index = -1;`, `conn->active_linked_conn_index = -1;`, and `conn->closeable_conn_index = -1;`.
3. **Shared $O(1)$ membership/invariant helper (`src/core/mainloop/mainloop.c:218-235`)**:
   ```c
   static int
   connection_in_idx_list(const smartlist_t *sl, const connection_t *conn,
                          int idx)
   {
     tor_assert(conn);
     if (!sl || idx < 0) {
       tor_assert(idx == -1);
       return 0;
     }
     tor_assert(idx < smartlist_len(sl));
     tor_assert(smartlist_get(sl, idx) == conn);
     return 1;
   }
   ```
   Used by `connection_in_array()`, `connection_is_on_closeable_list()`, and `connection_in_active_linked_list()`.
4. **`connection_array` index fix (`src/core/mainloop/mainloop.c:340-360`)**:
   * In stock `tor-0.4.9.14`, `connection_remove(conn)` deleted `conn` from `connection_array` and updated the swapped tail element's `conn_array_index`, **but never reset `conn->conn_array_index = -1`**. The patch sets `conn->conn_array_index = -1;` before deleting `current_index` and strengthens the entry assertion to `tor_assert(connection_in_array(conn));`.
   * In `connection_unlink()` (`mainloop.c:369`), replaces `if (conn->conn_array_index >= 0)` with `if (connection_in_array(conn))`.
   * In `close_closeable_connections()` (`mainloop.c:918`), replaces `if (conn->conn_array_index < 0)` with `if (!connection_in_array(conn))`.
5. **`closeable_connection_lst` indexing (`mainloop.c:238-252, 914-942`)**:
   * `add_connection_to_closeable_list(conn)` checks `!connection_is_on_closeable_list(conn)` in $O(1)$, sets `conn->closeable_conn_index = smartlist_len(closeable_connection_lst)`, and appends `conn`.
   * `close_closeable_connections()` removes closed entries in $O(1)$ using `smartlist_del(closeable_connection_lst, idx)` and updates the swapped tail element's `closeable_conn_index = idx` without advancing loop index `i`, advancing `++i` only when `conn_close_if_marked` returns `0` (held open).
6. **`active_linked_connection_lst` indexing (`mainloop.c:860-909, 379-381`)**:
   * `connection_start_reading_from_linked_conn(conn)` asserts `!connection_in_active_linked_list(conn)` on transition from `active_on_link == 0`, sets `conn->active_linked_conn_index = smartlist_len(active_linked_connection_lst)`, and appends `conn`.
   * `connection_stop_reading_from_linked_conn(conn)` asserts `connection_in_active_linked_list(conn)` when `active_on_link == 1` (or `connection_in_active_linked_list(conn)` in the self-healing branch), clears `conn->active_on_link = 0` and `conn->active_linked_conn_index = -1`, calls `smartlist_del(active_linked_connection_lst, idx)`, and updates the swapped tail element's `active_linked_conn_index = idx`.
   * `connection_unlink(conn)` calls `if (conn->linked) connection_stop_reading_from_linked_conn(conn);` instead of `smartlist_remove(active_linked_connection_lst, conn);`.
   * `connection_free_(conn)` (`connection.c:971`) adds `tor_assert(!connection_in_active_linked_list(conn));` alongside `tor_assert(!connection_is_on_closeable_list(conn));` and `tor_assert(!connection_in_array(conn));`.

---

### 1.2 Complete Mutation Audit & Lifecycle Check Across `tor-0.4.9.14`

We audited every reference to `connection_array`, `active_linked_connection_lst`, and `closeable_connection_lst` across the entire `tor-0.4.9.14` tree:

| List / Path | Production Sites (`src/core/`, `src/feature/`, `src/app/`) | Test Sites (`src/test/`) | Invariant Status & Findings |
| :--- | :--- | :--- | :--- |
| **`connection_array` mutations** | `connection_add_impl` (`mainloop.c:290`), `connection_remove` (`mainloop.c:340`), `tor_free_all` (`mainloop.c:2620`: `SMARTLIST_FOREACH(connection_array, connection_t *, conn, connection_free_minimal(conn))`) | `test_mainloop.c`, `test_conflux_pool.c:1790,1818`, `test_hs_client.c:525,561,563,754`, `test_oos.c`, `test_extorport.c`, `test_relaycell.c` | **Production code is 100% clean.** However, we discovered **two test files** (`test_conflux_pool.c` and `test_hs_client.c`) that called `smartlist_add(get_connection_array(), ...)` directly without setting `conn_array_index`. Fixed in our enhanced patch (`0001-mainloop-index-cleanup-scans-with-test-fixes.patch`). |
| **`active_linked_connection_lst` mutations** | `connection_start_reading_from_linked_conn` (`mainloop.c:860`), `connection_stop_reading_from_linked_conn` (`mainloop.c:881`), `run_active_linked_connections_cb` (`mainloop.c:787`, read-only `SMARTLIST_FOREACH`), `tor_free_all` (`mainloop.c:2624`) | `test_mainloop.c` | **100% encapsulated in `mainloop.c`.** `run_active_linked_connections_cb()` only calls `connection_handle_read(conn)` which may call `connection_stop_reading_from_linked_conn(conn)` when `!conn->reading_from_linked_conn` (`connection.c:3933`); Wait—let's check `SMARTLIST_FOREACH` mutation safety in `run_active_linked_connections_cb`! See Section 1.3 below. |
| **`closeable_connection_lst` mutations** | `add_connection_to_closeable_list` (`mainloop.c:238`), `close_closeable_connections` (`mainloop.c:914`), `connection_count_moribund` (`mainloop.c:946`, read-only), `tor_free_all` (`mainloop.c:2626`) | `test_mainloop.c` | **100% encapsulated in `mainloop.c`.** Re-entrancy check: `conn_close_if_marked` -> `connection_unlink` -> `connection_about_to_close_connection` can only *append* a peer to the tail of `closeable_connection_lst` via `add_connection_to_closeable_list`; it never deletes from `closeable_connection_lst`. When `close_closeable_connections` deletes index `idx`, `smartlist_del` swaps the current tail (which may be a newly-marked peer) into `idx` and updates its `closeable_conn_index = idx`, and loop index `i == idx` visits it on the very next iteration. |
| **Linked-peer lifecycle (`exit_conn <-> dir_conn`)** | `connection_link_connections` (`connection.c:722`), `connection_unlink` (`mainloop.c:364`), `connection_dir_finished_flushing` (`directory.c:4812`) | `test_mainloop.c` | When `conn` is unlinked (`mainloop.c:373-378`), if `!conn->linked_conn->marked_for_close && conn->linked_conn->reading_from_linked_conn`, `connection_start_reading(conn->linked_conn)` activates the peer so it sees EOF on the next active-linked turn. Then `conn` is removed from `active_linked_connection_lst` in $O(1)$. |
| **OOM / OOS handlers** | `circuits_handle_oom` (`circuitlist.c`), `connection_check_oos` (`connection.c:5633`) | `test_oos.c` | OOM/OOS handlers only call `connection_mark_for_close()` / `connection_mark_and_flush()`, which go through `add_connection_to_closeable_list()`. Neither handler reorders or mutates the three smartlists directly. |
| **Shutdown path (`tor_free_all`)** | `mainloop.c:2620-2628` | N/A | `tor_free_all()` calls `connection_free_minimal()` (not `connection_free_()`), then frees `connection_array`, `active_linked_connection_lst`, and `closeable_connection_lst`. |

### 1.3 Subtle Check: `run_active_linked_connections_cb` Iteration During Swap-Delete
Let us verify how `run_active_linked_connections_cb` (`mainloop.c:808-820`) interacts with `smartlist_del` inside `connection_stop_reading_from_linked_conn`:
* In `mainloop.c:808-815`:
  ```c
  SMARTLIST_FOREACH_BEGIN(active_linked_connection_lst, connection_t *, conn) {
    ...
  } SMARTLIST_FOREACH_END(conn);
  ```
* Does `run_active_linked_connections_cb` ever call `connection_stop_reading_from_linked_conn` during `SMARTLIST_FOREACH`?
  * Let's trace `run_active_linked_connections_cb` (`src/core/mainloop/mainloop.c:785-835`):
    In `mainloop.c:795-825`, `run_active_linked_connections_cb` calls `conn_read_callback(conn->s, EV_READ, conn)`!
    And inside `conn_read_callback`:
    1. `connection_handle_read(conn)` -> `connection_handle_read_impl(conn)`: for a linked connection (`conn->linked`), if `!conn->reading_from_linked_conn`, `connection.c:3933` calls `connection_stop_reading_from_linked_conn(conn)`!
    2. And at the end of `conn_read_callback` (`mainloop.c:928`):
       `if (smartlist_len(closeable_connection_lst)) close_closeable_connections();`!
  * **Wait**: what happens in **both stock Tor (`smartlist_remove`) and patched Tor (`smartlist_del`)** when `conn_read_callback` removes an element from `active_linked_connection_lst` inside `SMARTLIST_FOREACH_BEGIN(active_linked_connection_lst, ...)`?
    * `smartlist_remove` in stock Tor and `smartlist_del` in patched Tor **both** perform the exact same swap-with-last operation (`sl->list[idx] = sl->list[--sl->num_used]`)!
    * In `SMARTLIST_FOREACH_BEGIN`, if the current element at `conn_sl_idx` is removed by swapping the tail element into `conn_sl_idx`, advancing `conn_sl_idx++` skips the swapped tail element until the next Libevent callback turn (`mainloop_event_activate(schedule_active_linked_connections_event)` is re-triggered at the end of `run_active_linked_connections_cb` if `smartlist_len(active_linked_connection_lst) > 0`).
    * More importantly, what if `close_closeable_connections()` runs inside `conn_read_callback` and removes **multiple** connections from `active_linked_connection_lst`, including connections at indices `< conn_sl_idx`? If an element at `idx < conn_sl_idx` is removed via swap-with-tail, the tail element moves into `idx` (which is fine), and `sl->num_used` shrinks by 1 (checked by `conn_sl_idx < smartlist_len(sl)` on each loop iteration). Thus `conn_sl_idx` never reads past `smartlist_len(active_linked_connection_lst)`, and the behavior of `smartlist_del` is 100% identical to stock Tor's `smartlist_remove` with respect to list ordering!

### 1.4 Error-Detection Tradeoff of Replacing `smartlist_contains()` with `connection_in_idx_list()`

Replacing $O(N)$ `smartlist_contains(list, conn)` assertions with $O(1)$ `connection_in_idx_list(list, conn, conn->..._index)` changes the set of invariant bugs caught vs. missed:

| Bug Class | Stock `smartlist_contains(sl, conn)` ($O(\text{len})$) | Patched `connection_in_idx_list(sl, conn, idx)` ($O(1)$) | Net Change & Mitigation |
| :--- | :--- | :--- | :--- |
| **Connection still registered via normal API when `connection_free_(conn)` runs** (`idx >= 0`, `sl->list[idx] == conn`) | **Caught** (`smartlist_contains` returns `1` after scanning up to `len` elements) | **Caught in $O(1)$** (`connection_in_idx_list` returns `1` immediately) | **Same detection, $O(\text{len}) \to O(1)$ cost.** |
| **Connection still in `active_linked_connection_lst` when `connection_free_(conn)` runs** | **Missed** (stock `connection_free_()` had no assertion for `active_linked_connection_lst`) | **Caught in $O(1)$** (patch adds `tor_assert(!connection_in_active_linked_list(conn))` to `connection_free_()`) | **Strictly stronger in patched build.** |
| **Stale non-negative index (`idx >= 0`) after removal or out-of-bounds `idx >= len`** | **Missed** on absence checks if pointer is absent (`smartlist_contains` returns `0` even if `conn->conn_array_index` is stale — which was actually true in stock `connection_remove`!) | **Caught immediately in $O(1)$** (`tor_assert(idx < smartlist_len(sl))` and `tor_assert(smartlist_get(sl, idx) == conn)` abort immediately) | **Strictly stronger in patched build.** |
| **Corrupted negative index (`idx < -1`)** | **Missed** | **Caught immediately in $O(1)$** (`tor_assert(idx == -1)`) | **Strictly stronger in patched build.** |
| **Direct `smartlist_add(sl, conn)` bypassing wrapper (leaving `idx == -1`) or overwriting `idx = -1` while `conn` remains in `sl`** | **Caught** (`smartlist_contains` finds `conn` by scanning `sl`) | **Missed on `conn` itself** (because `idx == -1` returns `0`), **until** `conn` becomes the tail element swapped during another connection's `smartlist_del` | **Only potential weakness.** Mitigated by: (1) keeping `active_linked_connection_lst` and `closeable_connection_lst` file-static in `mainloop.c`, (2) auditing all `get_connection_array()` callers and fixing `test_conflux_pool.c` and `test_hs_client.c`, and (3) optional debug-mode cross-check `ENABLE_EXPENSIVE_MAINLOOP_ASSERTS`. |

### 1.5 Audit of Documentation Discrepancies and the 8 ASan/UBSan Test-Suite Failures in `CANDIDATE`

Our audit of `CANDIDATE` uncovered two important discrepancies between `CANDIDATE`'s markdown notes and its build artifacts:
1. **`CANDIDATE/findings.md` and `invariant-and-assertion-review.md` drift**:
   * Both markdown files claim that `CANDIDATE/asan-ubsan-test.log` is a *"Full `make check` log under ASan/UBSan"*. In reality, `asan-ubsan-test.log` (`226` lines) is a filtered run of 6 unit-test prefixes (`mainloop/*`, `connection/*`, `dir/*`, `hs_Service/*`, `hs_cache/*`, `hs_descriptor/*`: `217` tests, `1` skipped, `0` failed).
   * Conversely, `CANDIDATE/build-asan/test-suite.log` contains the actual Automake `make check` output: **`34` jobs (`25 PASS`, `1 SKIP`, `8 FAIL`)**.
   * Both markdown files also refer to helper functions `connection_remove_from_active_linked_list()` and `connection_remove_from_closeable_list()` that do not exist in `0001-mainloop-index-cleanup-scans.patch` (the patch implements the indexed swap-delete inline in `connection_stop_reading_from_linked_conn()` and `close_closeable_connections()`).
2. **Baseline vs. Patched Triage of All 8 Failing Automake Jobs (`results/asan_test_suite_triage.json`)**:
   * We built unpatched stock `tor-0.4.9.14` and the combined patched stack inside `tor41350-build:2404` under identical `-fsanitize=address,undefined` flags and `UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1`.
   * **All 8 Automake job failures reproduce identically on unpatched stock `tor-0.4.9.14`** and have zero connection to `0001-mainloop-index-cleanup-scans.patch`:
     1. `src/test/test-slow`: upstream signed shift overflow `1073741824 << 1` (`test_ptr_slow.c:52`) + container `ptrace`/EACCES in `test_process_slow.c`.
     2. `src/test/test-memwipe`: intentional read-after-free (`vmemeq` in `test-memwipe.c:88`) incompatible with ASan (noted in upstream `Makefile`).
     3. `src/test/unittest_part1.sh`: upstream UBSan null-pointer arguments in `circuitpadding/circuitpadding_ozz` (`memcpy(..., NULL, 0)` at `relay_msg.c:119`) and `circuitstats/*` (`TO_CIRCUIT(NULL)` in `test_circuitstats.c`).
     4. `src/test/unittest_part2.sh`: upstream UBSan `TO_CIRCUIT(NULL)` in `test_circuitstats.c`.
     5. `src/test/unittest_part6.sh`: upstream UBSan `qsort(NULL, 0, ...)` in `onion-handshake/ntor-v3/handshake_negtotiation` (`circuitbuild.c:2826`).
     6. `src/test/test_bt.sh`: LSan `ptrace` failure in container.
     7. `src/test/test_rebind.sh`: container `PermissionError: [Errno 13]` on `tor_process.terminate()` after printing `OK`.
     8. `src/test/test_include.sh`: container `PermissionError: [Errno 13]` on `tor_process.terminate()` after printing `OK`.

### 1.6 Integration with the 7 HS Defense Patches (`HS_PATCHES`)

We applied `0001-mainloop-index-cleanup-scans-with-test-fixes.patch` on top of all 7 patches in `/Users/joey/tor/1aeo/dos/torutils/tor41339-hsdir-defense/patches` (`0001..0007`, exported as `patches/0008-mainloop-index-cleanup-scans-on-hs-series.patch`):
* **File-level overlap**: **Zero.** `HS_PATCHES` `0001..0007` touch `src/app/config/config.c`, `src/app/config/or_options_st.h`, `src/core/or/circuitlist.c`, `src/core/or/or_circuit_st.h`, `src/feature/dircommon/dir_connection_st.h`, `src/feature/dircommon/directory.c`, `src/feature/hs/hs_cache.c`, `src/feature/hs/hs_cache.h`, `src/feature/hs/hs_descriptor.c`, `src/feature/hs/hs_metrics.*`, and `src/feature/relay/relay_metrics.*`. The mainloop patch touches `src/core/mainloop/mainloop.*`, `src/core/mainloop/connection.*`, and `src/core/or/connection_st.h`.
* **Semantic interaction**:
  * Patches `0001` (`HSDirRefuseUnknownPrevHop`), `0002` (`HSDirOneRequestPerCircuit`), and `0004` (`Max body size`) call `connection_mark_for_close(TO_CONN(conn))` when rejecting a request (if enabled). Those early closures flow directly into `add_connection_to_closeable_list` and `close_closeable_connections`, which now run in $O(1)$ per connection instead of $O(A + N)$.
  * Patch `0005` (`Discard client input received after the request`) calls `connection_stop_reading(TO_CONN(conn))` in `directory.c:2257` once the HTTP request has been received. For a linked directory connection (`conn->linked == 1`), `connection_stop_reading()` calls `connection_stop_reading_from_linked_conn(conn)`. Without the mainloop indexing patch, Patch `0005` would trigger an extra $O(A)$ `smartlist_remove(active_linked_connection_lst, conn)` scan on **every valid directory request**! With the mainloop indexing patch, `connection_stop_reading_from_linked_conn(conn)` is $O(1)$, making Patch `0005` completely free of list-scan overhead.
  * Note on workspace `/Users/joey/Documents/1aeo-ag/torutils-patch_tor_flood/tor41339-hsdir-defense/patches`: That directory contains an extended 11-patch experimental series (`0008..0011` adding `RELAY_COMMAND_BEGIN_DIR` counters and `hsdir_dl_conns` tracking). Our standalone `0008-mainloop-index-cleanup-scans-on-hs-series.patch` also has zero file conflicts with `0008..0011`.

---

## 2. Ranked Fixes and Engineering Recommendations

| Priority | Fix / Action | Target Bottleneck / Question | Expected Benefit & Scope | Risk & Normal-Traffic Compatibility | Verification & Rollout |
| :---: | :--- | :--- | :--- | :--- | :--- |
| **Fix 1 (Immediate)** | **Deploy `0001-mainloop-index-cleanup-scans-with-test-fixes.patch` (or `0008` on top of the 7-patch HS series with `HSDirRefuseUnknownPrevHop=0`, `HSDirOneRequestPerCircuit=0`)** | Eliminates the verified $O(C \cdot A)$ and $O(C \cdot N)$ linear scans in `connection_unlink`, `connection_stop_reading_from_linked_conn`, `close_closeable_connections`, and `connection_free_` (`90.47%` / `92.36%` of `sarkodie` main-thread CPU; `14.04–14.66%` of `antglizzy`/`joji` main-thread CPU). | Reduces per-closure list maintenance from $O(A + N + C)$ to $O(1)$ (`0` linear pointer comparisons; `175x–1,203x` faster in microbenchmarks; `156x–162x` faster in whole-loop tests at high backlog). Also prevents Patch `0005`'s `connection_stop_reading()` from incurring an $O(A)$ scan per request. | **Very low risk.** Zero wire-protocol or HTTP behavior change. Preserves normal directory circuit reuse, concurrent consensus/descriptor downloads, bootstrap bursts, and slow-client response flushing. Adds `8` bytes per `connection_t`. | Validated by `117/117` targeted unit tests (`mainloop/*`, `dir/*`, `hs_*`, `conflux_pool/*`, `hs_client/*`) and full `~1,600`-test suite. Ready for canary deployment alongside Tier 0–1 metrics. |
| **Fix 2 (Immediate, Paired with Fix 1)** | **Deploy Tier 0 + Tier 1 Observability Metrics (`0002-relay-metrics-mainloop-and-directory-observability.patch`)** | Resolves `[UNKNOWN-U1]` (true runtime list sizes $A, N, C$ and cleanup duration/delay) and `[UNKNOWN-U2]`/`[UNKNOWN-U3]` (ordinary vs. HS request classes, pre-parse aborts, status codes, and actual directory response bytes). Also fixes the blind spot where `tor_hsdir_request_total` sits downstream of the two HS defense guards. | Provides $O(1)$ gauges and counters scraped over `MetricsPort` with $< 15\text{ ns}$ hot-path cost (`3–4` integer increments per stream/request, zero heap allocation, zero list scans). | **Zero traffic risk.** Purely passive observability; does not alter connection lifecycle or reject any request. | Unit-tested via `test_mainloop.c` and `/metrics` output checks. |
| **Fix 3 (Conditional Next Step — After Canary Data)** | **Bound Per-Relay Concurrent Active `BEGIN_DIR` Streams or Unflushed Directory Output Backlog (Soft Shedding / Queue Cap)** | Targets **H2** (`antglizzy`/`joji` high-outbound compression + packaging saturation) and **H3** (slow-reading clients holding thousands of `DIR_CONN_STATE_SERVER_WRITING` connections open in `active_linked_connection_lst`). | Only justified **if** post-Fix-1 canary profiles show main-thread CPU still saturating (`>90%`) in `zlib`/`AES-CTR`/`circuit_package_relay_cell` or `active_linked` gauge $A$ remaining above `2,000+` due to slow-drained streams. | **Medium risk if misconfigured.** A naive global cap would drop legitimate client consensus/bootstrap fetches during flood. Any limit **must** prioritize/protect in-progress normal streams or enforce per-OR-circuit active `BEGIN_DIR` concurrency (`<= 4` concurrent open `BEGIN_DIR` streams per circuit) rather than rejecting sequential circuit reuse! | **Do not enable before collecting Tier 0/1/2 canary metrics.** Must distinguish sequential reuse (legitimate Tor clients reusing 1 directory circuit for sequential fetches) from concurrent stream multiplexing (`>8` simultaneous open `BEGIN_DIR` streams on one circuit). |
| **Fix 4 (Conditional Next Step — Only if H5/HS Flood Confirmed)** | **Controlled Evaluation of Existing HS Defense Toggles (`HSDirRefuseUnknownPrevHop`, `HSDirOneRequestPerCircuit`)** | Targets `/tor/hs/3/...`-specific floods if Tier 1 metrics prove that `>=500 BEGIN_DIR/s` floods are predominantly HS descriptor fetches/posts from non-relay previous hops or multiplexed on single circuits. | Already implemented in `HS_PATCHES` `0001` and `0002`. | **`HSDirOneRequestPerCircuit=1` has a critical scope boundary**: in `0002`, `dir_req_num` is only checked inside `directory_handle_command_get`/`_post` on `/tor/hs/3/` URLs, so it does **not** break ordinary directory circuit reuse. However, if legitimate HS clients/services ever reuse an HSDir circuit, it would reject the second HS request (`503`). Keep **both disabled (`0`)** until Tier 1/2 counters confirm HS flood patterns. | Keep `HSDirRefuseUnknownPrevHop=0` and `HSDirOneRequestPerCircuit=0` during Fix 1 + Fix 2 canary validation so Fix 1's effect is not confounded. |
