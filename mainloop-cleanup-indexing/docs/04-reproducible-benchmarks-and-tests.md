# Deliverable 4: Reproducible Benchmarks, Comparison Counter Audit, and Compatibility Tests

## 1. Audit of the Prior Benchmark Comparison Counter (`CANDIDATE/benchmarks/bench_cleanup_scaling.c`)

Before reusing any comparison totals from `CANDIDATE`, we audited `CANDIDATE/benchmarks/bench_cleanup_scaling.c` against `src/lib/smartlist_core/smartlist_core.c` and `src/core/mainloop/mainloop.c`:

### 1.1 Two Undercount Bugs in `CANDIDATE`'s Benchmark Harness
1. **`__wrap_smartlist_remove` stopped counting at the first match (`if (sl->list[i] == element) break;`)**:
   * In `src/lib/smartlist_core/smartlist_core.c:150-162`, `smartlist_remove(smartlist_t *sl, const void *element)` does **not** return on the first match:
     ```c
     for (i = 0; i < sl->num_used; i++)
       if (sl->list[i] == element) {
         sl->list[i] = sl->list[--sl->num_used]; /* swap with the end */
         i--; /* so we process the new i'th element */
         sl->list[sl->num_used] = NULL;
       }
     ```
   * Because `smartlist_remove` swaps the tail element into `sl->list[i]`, decrements `i--`, and continues to the end of the array, **every call to `smartlist_remove` performs `sl_len_before` pointer comparisons** (where `sl_len_before` is the list length on entry), regardless of where `element` sits in the list!
   * In `CANDIDATE`'s `bench_cleanup_scaling.c`, `__wrap_smartlist_remove` broke out of its counting loop on the first match. Since `close_closeable_connections` processes `closeable_connection_lst[0]` at the head (`i == 0`), `CANDIDATE` counted only **`1` comparison per `smartlist_remove(closeable_connection_lst, conn)` call** instead of $C - k$ comparisons, undercounting `closeable_connection_lst` removal comparisons by:
     $$\Delta_{\text{closeable}} = \sum_{k=0}^{C-1} (C - k - 1) = \frac{C(C-1)}{2}$$
   * Furthermore, when the $C$ victims are **active** on `active_linked_connection_lst` (appended after $A$ background active connections, so initial length is $A + C$), `CANDIDATE` counted $A + 1$ comparisons per call instead of $A + C - k$, undercounting `active_linked_connection_lst` removal comparisons by another $\frac{C(C-1)}{2}$ (for a total undercount of **$C(C-1)$ comparisons**!).
   * For example, at $(A=4000, N=32000, C=4000)$ with active victims:
     * True `smartlist_remove` comparisons = $32,004,000$
     * `CANDIDATE` first-match count = $16,008,000$
     * **`CANDIDATE` undercount = $15,996,000$ comparisons (`49.98%` of `smartlist_remove` work)**.
2. **Omission of `add_connection_to_closeable_list` (`connection_mark_for_close`) comparisons**:
   * In stock `tor-0.4.9.14`, `add_connection_to_closeable_list(conn)` (`mainloop.c:225`) executes `tor_assert(!smartlist_contains(closeable_connection_lst, conn))` when marking each of the $C$ connections for close, performing $\frac{C(C-1)}{2}$ linear comparisons (`7,998,000` comparisons at $C=4000$). `CANDIDATE` only enabled its counter after `connection_mark_for_close()` had finished.

### 1.2 Audited Closed-Form Comparison Identities (Verified in `results/scaling-baseline.json`)

Our rewritten `benchmarks/bench_cleanup_scaling.c` separately records:
* `mark_contains_comparisons`: exact comparisons in `add_connection_to_closeable_list()` (`Phase 1`):
  $$M(C, H) = C \cdot H + \frac{C(C-1)}{2}$$
* `smartlist_remove_full_comparisons`: true comparisons performed by `smartlist_remove()` (`Phase 2`):
  * For **inactive** victims (absent from `active_linked_connection_lst` of size $A$):
    $$R_{\text{inactive}}(A, C) = C \cdot A + \frac{C(C+1)}{2}$$
  * For **active** victims (present in `active_linked_connection_lst` of initial size $A + C$):
    $$R_{\text{active}}(A, C) = C \cdot A + C(C+1)$$
* `teardown_contains_comparisons`: exact comparisons performed by `smartlist_contains()` inside `connection_free_()` (`!connection_in_array` and `!connection_is_on_closeable_list`) and `connection_stop_reading_from_linked_conn()`:
  * For **active** victims in `connection_array`:
    $$T_{\text{active}}(N, C, H) = C \cdot N - \frac{C(C+1)}{2} + C \cdot H$$
  * For **inactive** victims in `connection_array`:
    $$T_{\text{inactive}}(A, N, C, H) = C \cdot A + C \cdot N - \frac{C(C+1)}{2} + C \cdot H$$
* **Patched build (`results/scaling-patched.json`)**:
  Across all 29 benchmark points and all 6 sweeps, `mark_contains_comparisons = 0`, `smartlist_remove_full_comparisons = 0`, and `teardown_contains_comparisons = 0` (`total_lifecycle_linear_comparisons = 0`), replaced by $2C$ (inactive) or $3C$ (active) $O(1)$ `smartlist_del` swap-deletes.

---

## 2. Explicit Occupancy Disclaimer

> **Important Validation Caution**: Production live captures (`sarkodie`, `antglizzy`, `joji`, `kojofunds`) did not capture runtime values of $A = \text{smartlist\_len}(\text{active\_linked\_connection\_lst})$, $N = \text{smartlist\_len}(\text{connection\_array})$, or $C = \text{smartlist\_len}(\text{closeable\_connection\_lst})$. All $(A, N, C, H)$ parameter tuples in `bench_cleanup_scaling.c` and `bench_whole_loop_reproducer.c` are **explicit synthetic occupancy assumptions** spanning plausible relay operating regimes (`N = 200 .. 64,000`, `A = 0 .. 12,000`, `C = 10 .. 4,000`). Synthetic benchmark speedups prove that the $O(C \cdot A + C \cdot N + C^2)$ scaling term is eliminated locally, **not** what net main-thread CPU reduction will occur on a production relay.

---

## 3. Baseline vs. Patched Microbenchmark Results (`9` Trials per Point, Container `tor41350-build:2404`)

Full machine-readable distributions (`min, p25, median, mean, p95, max, stdev`) are saved in `results/scaling-baseline.json` and `results/scaling-patched.json`.

### 3.1 Struct Size and Memory Overhead
* Baseline `sizeof(connection_t)` = **`152` bytes**
* Patched `sizeof(connection_t)` = **`160` bytes** (`+8` bytes per connection: `+5.26%` on the base struct; `+312.5 KB` at $N=40,000$ connections).

### 3.2 Scaling Sweeps Summary Table (`9` Unperturbed Trials per Point)

| Sweep / Mode | $A$ (`active_linked`) | $N$ (`conn_array`) | $C$ (`closeable`) | $H$ (`held`) | Baseline True Teardown Comparisons | Prior Legacy Undercount (`smartlist_remove`) | Baseline Mark `contains` Comparisons | Patched Linear Comparisons (`smartlist_del`) | Baseline CPU `ms` Median (`p25..p95`, `sd`) | Patched CPU `ms` Median (`p25..p95`, `sd`) | Median CPU Speedup |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- | ---: |
| `vary_A` (inactive) | `0` | `32,000` | `1,000` | `0` | `32,499,500` | `-499,500` | `499,500` | `0` (`2,000`) | `8.8935` (`8.88..9.40`, `0.24`) | `0.1340` (`0.13..0.16`, `0.01`) | **`66.4x`** |
| `vary_A` (inactive) | `2,000` | `32,000` | `1,000` | `0` | `34,499,500` | `-499,500` | `499,500` | `0` (`2,000`) | `10.0333` (`9.67..10.54`, `0.44`) | `0.1414` (`0.14..0.16`, `0.01`) | **`71.0x`** |
| `vary_A` (inactive) | `4,000` | `32,000` | `1,000` | `0` | `36,499,500` | `-499,500` | `499,500` | `0` (`2,000`) | `10.3012` (`10.19..10.89`, `0.30`) | `0.1528` (`0.15..0.18`, `0.01`) | **`67.4x`** |
| `vary_A` (inactive) | `8,000` | `32,000` | `1,000` | `0` | `40,499,500` | `-499,500` | `499,500` | `0` (`2,000`) | `11.9143` (`11.02..12.80`, `0.75`) | `0.1363` (`0.13..0.16`, `0.01`) | **`87.4x`** |
| `vary_A` (inactive) | `12,000` | `32,000` | `1,000` | `0` | `44,499,500` | `-499,500` | `499,500` | `0` (`2,000`) | `12.3610` (`12.02..12.80`, `0.36`) | `0.1385` (`0.13..0.17`, `0.01`) | **`89.2x`** |
| `vary_A` (active) | `0` | `32,000` | `1,000` | `0` | `33,000,000` | `-999,000` | `499,500` | `0` (`3,000`) | `9.4640` (`9.29..10.13`, `0.46`) | `0.1456` (`0.13..0.19`, `0.02`) | **`65.0x`** |
| `vary_A` (active) | `4,000` | `32,000` | `1,000` | `0` | `37,000,000` | `-999,000` | `499,500` | `0` (`3,000`) | `11.0780` (`10.11..11.71`, `0.68`) | `0.1542` (`0.15..0.18`, `0.01`) | **`71.8x`** |
| `vary_A` (active) | `8,000` | `32,000` | `1,000` | `0` | `41,000,000` | `-999,000` | `499,500` | `0` (`3,000`) | `11.2668` (`11.20..12.14`, `0.37`) | `0.1507` (`0.15..0.16`, `0.01`) | **`74.8x`** |
| `vary_A` (active) | `12,000` | `32,000` | `1,000` | `0` | `45,000,000` | `-999,000` | `499,500` | `0` (`3,000`) | `12.5220` (`12.41..13.12`, `0.32`) | `0.1578` (`0.16..0.17`, `0.01`) | **`79.4x`** |
| `vary_N` (active) | `2,000` | `4,000` | `1,000` | `0` | `7,000,000` | `-999,000` | `499,500` | `0` (`3,000`) | `2.0813` (`2.01..2.21`, `0.11`) | `0.1467` (`0.14..0.16`, `0.005`) | **`14.2x`** |
| `vary_N` (active) | `2,000` | `16,000` | `1,000` | `0` | `19,000,000` | `-999,000` | `499,500` | `0` (`3,000`) | `5.3204` (`5.26..5.77`, `0.21`) | `0.1456` (`0.14..0.17`, `0.01`) | **`36.5x`** |
| `vary_N` (active) | `2,000` | `32,000` | `1,000` | `0` | `35,000,000` | `-999,000` | `499,500` | `0` (`3,000`) | `9.9518` (`9.80..10.40`, `0.36`) | `0.1482` (`0.14..0.16`, `0.01`) | **`67.2x`** |
| `vary_N` (active) | `2,000` | `64,000` | `1,000` | `0` | `67,000,000` | `-999,000` | `499,500` | `0` (`3,000`) | `18.3468` (`18.02..20.22`, `1.02`) | `0.1452` (`0.14..0.17`, `0.01`) | **`126.4x`** |
| `vary_C` (active) | `4,000` | `32,000` | `100` | `0` | `3,610,000` | `-9,900` | `4,950` | `0` (`300`) | `1.0133` (`0.96..1.09`, `0.06`) | `0.0167` (`0.016..0.023`, `0.003`) | **`60.7x`** |
| `vary_C` (active) | `4,000` | `32,000` | `500` | `0` | `18,250,000` | `-249,500` | `124,750` | `0` (`1,500`) | `4.9545` (`4.92..5.01`, `0.11`) | `0.0712` (`0.071..0.080`, `0.004`) | **`69.6x`** |
| `vary_C` (active) | `4,000` | `32,000` | `1,000` | `0` | `37,000,000` | `-999,000` | `499,500` | `0` (`3,000`) | `10.4918` (`10.43..11.01`, `0.38`) | `0.1455` (`0.14..0.17`, `0.01`) | **`72.1x`** |
| `vary_C` (active) | `4,000` | `32,000` | `2,000` | `0` | `76,000,000` | `-3,998,000` | `1,999,000` | `0` (`6,000`) | `22.1293` (`21.32..23.26`, `0.89`) | `0.2869` (`0.29..0.30`, `0.005`) | **`77.1x`** |
| `vary_C` (active) | `4,000` | `32,000` | `4,000` | `0` | `160,000,000` | `-15,996,000` | `7,998,000` | `0` (`12,000`) | `47.0201` (`44.81..50.49`, `2.21`) | `0.5843` (`0.55..0.65`, `0.05`) | **`80.5x`** |
| `absent_victims` | `4,000` | `32,000` | `1,000` | `0` | `37,000,000` | `-499,500` | `499,500` | `0` (`1,000`) | `10.7212` (`10.57..11.46`, `0.54`) | `0.0871` (`0.083..0.093`, `0.004`) | **`123.1x`** |
| `mixed_with_held` | `4,000` | `32,000` | `1,000` | `200` | `37,149,500` | `-624,250` | `699,500` | `0` (`2,500`) | `10.5113` (`10.00..11.38`, `0.68`) | `0.1533` (`0.14..0.21`, `0.02`) | **`68.6x`** |
| `ordinary_small` | `20` | `200` | `10` | `0` | `2,300` | `-90` | `45` | `0` (`30`) | `0.0025` (`0.0025..0.003`, `0.0002`) | `0.0018` (`0.0017..0.0023`, `0.0003`) | **`1.4x`** |
| `ordinary_medium` | `50` | `1,500` | `25` | `5` | `39,457` | `-378` | `425` | `0` (`63`) | `0.0156` (`0.015..0.020`, `0.0016`) | `0.0038` (`0.0037..0.0083`, `0.0015`) | **`4.1x`** |

---

## 4. Whole-Loop Libevent Reproducer & Concurrent Normal-Traffic Results (`5` Trials per Scenario)

In `benchmarks/bench_whole_loop_reproducer.c` (results in `results/whole-loop-baseline.json` and `results/whole-loop-patched.json`), we run a real Libevent event base with:
1. A 10ms periodic timer measuring event-loop scheduling jitter (`max_timer_gap_ms`).
2. An ephemeral loopback HTTP `/metrics` listener scraped every 5ms by a client thread (`http_p50_ms`, `http_p95_ms`, `http_max_ms`).
3. Concurrent normal `exit_conn <-> dir_conn` linked pairs (`normal_linked_pairs`) performing multi-chunk read/write throttling and sequential circuit-reuse replacement on every wave while asserting 100% survival and index coherence across all waves.

| Scenario | $(A, N, C \times \text{waves})$ | Normal Pairs (Chunk Ops / Reuse Cycles) | Baseline Cleanup Callback Median `ms` (`p25..p95`, `sd`) | Patched Cleanup Callback Median `ms` (`p25..p95`, `sd`) | Cleanup Callback Speedup | `10ms` Timer Max Gap Median (`Base -> Patched`) | `/metrics` HTTP `p95` Latency (`Base -> Patched`) | `/metrics` HTTP `max` Latency (`Base -> Patched`) |
| :--- | :--- | :---: | :--- | :--- | ---: | :---: | :---: | :---: |
| `ordinary_load` | $(20, 200, 10 \times 10)$ | `4` (`40` / `10`) | `0.234` (`0.23..0.41`, `0.09`) | `0.332` (`0.25..0.45`, `0.09`) | `0.7x` (noise `<0.1ms`) | `10.87 ms -> 10.94 ms` | `0.38 ms -> 0.46 ms` | `0.41 ms -> 0.65 ms` |
| `normal_concurrent_dir_and_slow_flush` | $(64, 500, 16 \times 10)$ | `24` (`240` / `10`) | `0.303` (`0.29..0.43`, `0.07`) | `0.265` (`0.25..0.30`, `0.03`) | **`1.1x`** | `11.17 ms -> 10.98 ms` | `0.44 ms -> 0.41 ms` | `0.52 ms -> 0.46 ms` |
| `moderate_backlog` | $(4000, 16000, 500 \times 5)$ | `16` (`80` / `5`) | `15.385` (`15.22..32.63`, `8.61`) | `1.261` (`1.22..1.42`, `0.09`) | **`12.2x`** | `12.47 ms -> 10.80 ms` | **`2.99 ms -> 0.71 ms`** | **`3.46 ms -> 1.20 ms`** |
| `high_backlog` | $(8000, 32000, 1000 \times 5)$ | `16` (`80` / `5`) | `60.622` (`58.42..61.85`, `1.87`) | `2.337` (`2.16..3.01`, `0.39`) | **`25.9x`** | **`23.13 ms -> 11.18 ms`** | **`13.49 ms -> 0.51 ms`** | **`13.49 ms -> 0.86 ms`** |
| `extreme_burst` | $(12000, 48000, 2000 \times 5)$ | `16` (`80` / `5`) | `177.171` (`177.08..180.52`, `1.58`) | `4.749` (`4.74..5.49`, `0.65`) | **`37.3x`** | **`45.63 ms -> 12.14 ms`** | **`39.49 ms -> 0.62 ms`** | **`39.49 ms -> 0.75 ms`** |

---

## 5. Correctness and Normal-Traffic Compatibility Unit Tests (`tests/test_mainloop.c`)

We expanded `src/test/test_mainloop.c` and validated the combined patch series (`HS_PATCHES 0001..0007` + `0001-mainloop-index-cleanup-scans-with-test-fixes.patch` + `0002-relay-metrics-mainloop-and-directory-observability.patch`):
1. `mainloop/active_linked_list_indexing`: Tests head, middle, tail, singleton, and idempotent removal on `active_linked_connection_lst`.
2. `mainloop/linked_peer_teardown_and_oom_reorder`: Tests linked peer activation during `connection_unlink`, already-removed `!connection_in_array` teardown, and held-open `conn_close_if_marked == 0` interleaving.
3. `mainloop/index_corruption_assertions`: Forked death-tests proving that `connection_in_idx_list` immediately catches `idx < -1`, `idx >= len`, wrong-slot pointer mismatch, and freeing a connection while still on `connection_array`, `closeable_connection_lst`, or `active_linked_connection_lst`.
4. `mainloop/randomized_cleanup_lifecycle`: 250-step deterministic PRNG state-machine fuzz test checking双向 index coherence after every step.
5. `mainloop/normal_directory_and_slow_flush_lifecycle`: Tests sequential directory stream reuse on a circuit, 8 concurrent directory downloads, slow-client `hold_open_until_flushed` multi-pass response flushing, and a 24-pair bootstrap burst with partial aborts.
6. `mainloop/observability_metrics_conservation`: Verifies that `conn_added - conn_removed == conn_array_len`, `active_linked_added - active_linked_removed == active_linked_len`, `closeable_added - closeable_closed == closeable_len`, cleanup batch buckets, and Prometheus `/metrics` output for all new `tor_relay_mainloop_*` and `tor_relay_dir_*` series.
