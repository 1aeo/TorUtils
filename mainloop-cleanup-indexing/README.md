# Tor `BEGIN_DIR` Flood Bottleneck Analysis, Patch Review, Observability Metrics & Benchmarks

This directory (`/Users/joey/tor/1aeo/private/hsdir-metrics-analysis-20261020/handoff/source-analysis-proposal/`, mode `0700`) contains the complete technical deliverables for the independent source, profile, metrics, and remediation analysis of Tor `0.4.9.14` `BEGIN_DIR` floods.

All raw evidence under `/Users/joey/tor/1aeo/private/hsdir-metrics-analysis-20261020/` (`BASE`), `/Users/joey/tor/1aeo/dos/tor-source-0.4.9.14/` (`SOURCE`), `/Users/joey/tor/1aeo/private/tor-mainloop-stall-fix-20261018/` (`CANDIDATE`), and `/Users/joey/tor/1aeo/dos/torutils/tor41339-hsdir-defense/patches/` (`HS_PATCHES`) was verified read-only and remains unmodified.

---

## Directory Index

### 1. Technical Reports (`docs/`)

| File | Deliverable | Description |
|---|---|---|
| [`docs/01-facts-hypotheses-unknowns.md`](docs/01-facts-hypotheses-unknowns.md) | **Deliverable 1** | **Verified Facts, Hypotheses, and Unknowns Ledger**: Independent audit of all 4 live `perf` event/control pairs (`sarkodie`/`goodiemob`, `antglizzy`/`ludacris7`, `joji`/`xalisoflow`, `kojofunds`/`richthekid`), exact instruction-level disassembly (`+0x604f4..+0x60521` and `+0x60565..+0x60591` in `src/core/mainloop/mainloop.c`), exact `connection_edge.c` / `directory.c` / `mainloop.c` source trace, audit of the 14 historical `2026-10-20` comparisons, and ranked hypothesis matrix (`H1`–`H6`). |
| [`docs/02-ranked-fixes-and-patch-review.md`](docs/02-ranked-fixes-and-patch-review.md) | **Deliverable 2** | **Ranked Fixes and Candidate Patch Review**: Line-by-line review of `0001-mainloop-index-cleanup-scans.patch` across every mutation site, linked-peer lifecycle, OOM `connection_check_oos()` reorder, and shutdown path; discovery and fix of two latent test-suite index hazards (`test_conflux_pool.c:559` and `test_hs_client.c:1214`); baseline triage of all 8 ASan/UBSan Automake test-suite failures; and full compatibility review against all 7 `HS_PATCHES` (`0001..0007`) and the 11-patch workspace superset. |
| [`docs/03-prioritized-metrics-specification.md`](docs/03-prioritized-metrics-specification.md) | **Deliverable 3** | **Prioritized Minimal Observability Specification**: Exact specification and source hooks for 10 low-cardinality Prometheus metric families across Tier A (mainloop list gauges, high-watermarks, conservation-checked ops, and cleanup batch buckets), Tier B (`BEGIN_DIR` stream lifecycle, active stream states, HTTP request class $\times$ status class, and circuit `BEGIN_DIR` ordinal buckets), and Tier C (per-class directory payload bytes). |
| [`docs/04-reproducible-benchmarks-and-tests.md`](docs/04-reproducible-benchmarks-and-tests.md) | **Deliverable 4** | **Reproducible Local Benchmarks and Normal-Traffic Tests**: Audit and correction of the two comparison-counter bugs in `CANDIDATE`'s benchmark harness (`smartlist_remove` full-scan undercount and missing `add_connection_to_closeable_list` `smartlist_contains` count), 29-point (`9` trials/point) scaling results, 5-trial Libevent whole-loop reproducer results with concurrent normal directory traffic and `/metrics` scrape latency, and `171/171` unit test verification. |
| [`docs/05-canary-validation-and-profiling-plan.md`](docs/05-canary-validation-and-profiling-plan.md) | **Deliverable 5** | **Unexecuted Canary Validation, Profiling, and Rollback Plan**: Staged deployment plan (Stage 1: Fix 1 + Fix 2 with `HSDirRefuseUnknownPrevHop 0` and `HSDirOneRequestPerCircuit 0`), host-paired control selection, `15s`/`5s` `/metrics` and `30s` `perf` capture runbook, normal-traffic safety gates, rollback triggers, and post-Stage-1 decision matrix. |

---

### 2. Reviewable Patches (`patches/`)

| Patch File | Base Target | Description |
|---|---|---|
| [`patches/0001-mainloop-index-cleanup-scans-original-candidate.patch`](patches/0001-mainloop-index-cleanup-scans-original-candidate.patch) | `tor-0.4.9.14` | Exact reference copy of `CANDIDATE/0001-mainloop-index-cleanup-scans.patch`. |
| [`patches/0001-mainloop-index-cleanup-scans-with-test-fixes.patch`](patches/0001-mainloop-index-cleanup-scans-with-test-fixes.patch) | `tor-0.4.9.14` | **Recommended Fix 1 (Standalone)**: Indexes `connection_array` membership after removal (`conn_array_index = -1`), `active_linked_connection_lst` (`active_linked_conn_idx`), and `closeable_connection_lst` (`closeable_conn_idx`), fixes raw struct copy / stack mock hazards in `src/test/test_conflux_pool.c` and `src/test/test_hs_client.c`, and adds normal-directory/slow-flush lifecycle unit tests in `src/test/test_mainloop.c`. |
| [`patches/0002-relay-metrics-mainloop-and-directory-observability.patch`](patches/0002-relay-metrics-mainloop-and-directory-observability.patch) | `tor-0.4.9.14` + `0001` | **Recommended Fix 2 (Standalone)**: Implements Tier A, Tier B, and Tier C observability metrics across `mainloop.{h,c}`, `relay_metrics.{h,c}`, `or_circuit_st.h`, `connection_edge.c`, `dir_connection_st.h`, `directory.c`, `dircache.c`, `connection.c`, and `test_mainloop.c`. |
| [`patches/0008-mainloop-index-cleanup-scans-on-hs-series.patch`](patches/0008-mainloop-index-cleanup-scans-on-hs-series.patch) | `tor-0.4.9.14` + `HS_PATCHES 0001..0007` | Fix 1 formatted as Patch `0008` on top of the 7-patch HS defense series (`git am` verified cleanly). |
| [`patches/0009-relay-metrics-mainloop-and-directory-observability-on-hs-series.patch`](patches/0009-relay-metrics-mainloop-and-directory-observability-on-hs-series.patch) | `tor-0.4.9.14` + `HS_PATCHES 0001..0007` + `0008` | Fix 2 formatted as Patch `0009` on top of the 7-patch HS defense series + `0008` (`git am` verified cleanly). |

---

### 3. Benchmark Harnesses & Unit Tests (`benchmarks/` & `tests/`)

| File | Description |
|---|---|
| [`benchmarks/bench_cleanup_scaling.c`](benchmarks/bench_cleanup_scaling.c) | Audited 29-point (`9` trials/point) microbenchmark linked against real `libtor-app.a`, counting both first-match and actual full-scan `smartlist_remove` comparisons plus `smartlist_contains` comparisons across `active`, `inactive`, `absent`, and `mixed_held_open` victim modes. |
| [`benchmarks/bench_whole_loop_reproducer.c`](benchmarks/bench_whole_loop_reproducer.c) | Upgraded 5-trial Libevent event-loop benchmark driving real `close_closeable_connections()` and active-linked reads concurrently with 64 normal `exit<->dir` streams (16 slow-flushing), 10-stream circuit reuse, 10 ms timer jitter, and loopback `/metrics` HTTP scrapes. |
| [`tests/test_mainloop.c`](tests/test_mainloop.c) | Updated `src/test/test_mainloop.c` containing all 12 mainloop unit tests (`active_linked_list_indexing`, `linked_peer_teardown_and_oom_reorder`, `index_corruption_assertions`, `randomized_cleanup_lifecycle`, `normal_directory_and_slow_flush_lifecycle`, and `observability_metrics_conservation`). |

---

### 4. Raw Experimental & Verification Data (`results/`)

| File | Description |
|---|---|
| [`results/scaling-baseline.json`](results/scaling-baseline.json) | Full 9-trial JSON distribution for stock `tor-0.4.9.14` across all 29 `(A, N, C, mode)` points. |
| [`results/scaling-patched.json`](results/scaling-patched.json) | Full 9-trial JSON distribution for patched `tor-0.4.9.14` across all 29 `(A, N, C, mode)` points (`0` comparisons at every point; `60.5x–126.4x` CPU speedup at flood scale). |
| [`results/whole-loop-baseline.json`](results/whole-loop-baseline.json) | Full 5-trial JSON output for stock `tor-0.4.9.14` across `moderate_flood`, `sarkodie_scale`, and `extreme_burst`. |
| [`results/whole-loop-patched.json`](results/whole-loop-patched.json) | Full 5-trial JSON output for patched `tor-0.4.9.14` across `moderate_flood`, `sarkodie_scale`, and `extreme_burst` (`33.3x–37.3x` cleanup callback speedup; `39.49 ms -> 0.62 ms` `/metrics` `p95` latency at `extreme_burst`). |
| [`results/asan_test_suite_triage.json`](results/asan_test_suite_triage.json) | Structured triage of all 8 Automake suite failures in `CANDIDATE/build-asan/test-suite.log` against unpatched stock `tor-0.4.9.14`, plus documentation and latent test-suite hazard audit. |
| [`results/unit-test-verification.log`](results/unit-test-verification.log) | Complete execution log of `171/171` passing unit tests (`mainloop/..`, `dir/..`, `hs_cache/..`, `hs_service/..`, `hs_client/..`, `conflux/pool/..`, `oom/..`, `relaycell/..`, `metrics/..`). |
| [`SHA256SUMS.txt`](SHA256SUMS.txt) | Per-file SHA256 checksums for all artifacts in `source-analysis-proposal/`. |
