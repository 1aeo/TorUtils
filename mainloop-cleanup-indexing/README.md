# Tor `BEGIN_DIR` Flood Bottleneck Analysis, `tor-0.4.9.15` Rebase & `MetricsPort` Observability Patch

This directory contains the complete technical deliverables for the independent source, profile, metrics, and remediation analysis of Tor `BEGIN_DIR` floods, **rebased onto upstream `tor-0.4.9.15` (`4d8efff53a`)**.

## Upstream `tor-0.4.9.15` Rebase & Coverage Summary

1. **Dropped (100% Covered Upstream in `tor-0.4.9.15`)**:
   - Our `0.4.9.14` global connection-list indexing patch (`0001-mainloop-index-cleanup-scans*`) is **fully covered** by upstream `tor-0.4.9.15` commit `b035c0f582` (*"mainloop: Index global connection lists and membership checks"*), which indexes `connection_array`, `closeable_connection_lst`, and `active_linked_connection_lst` in $O(1)$ and fixes the unit-test index invariants in `test_conflux_pool.c` and `test_hs_client.c`.
   - Upstream `tor-0.4.9.15` also merged `BEGIN_DIR` DoS rate limiting and the per-circuit HSDir request allowance (`4c0ce0febb`, `7d9b3b11ef`), superseding the standalone `0.4.9.14` `#41339` rebase variants (`0008-*`, `0009-*`).
2. **Retained & Minimized on `tor-0.4.9.15` (`patches/0001-relay-metrics-mainloop-and-directory-observability.patch`)**:
   - Stock `tor-0.4.9.15` still lacks `MetricsPort` observability for mainloop connection-list sizes, `close_closeable_connections()` pass work/deferrals/duration, event-loop tick stalls, and server-side `BEGIN_DIR` stream lifecycle, circuit reuse, HTTP request class/status, and application bytes.
   - Our single remaining patch (`+541` net production C/H lines across 12 files, zero new `#include`s in `core/mainloop/*` or `core/or/*`, `--disable-module-relay` stubs in `relay_stub.c`, `changes/mainloop_and_dir_metrics`, and unit tests in `test_mainloop.c`) applies cleanly onto `tor-0.4.9.15` (`4d8efff53a`), passes `checkSpace.pl`, `lintChanges.py`, `includes.py`, and `practracker.py` with zero new warnings, and passes all `1,612 / 1,612` Tor unit tests.

All raw evidence under `/Users/joey/tor/1aeo/private/hsdir-metrics-analysis-20261020/` (`BASE`), `/Users/joey/tor/1aeo/dos/tor-source-0.4.9.14/` (`SOURCE`), `/Users/joey/tor/1aeo/private/tor-mainloop-stall-fix-20261018/` (`CANDIDATE`), and `/Users/joey/tor/1aeo/dos/torutils/tor41339-hsdir-defense/patches/` (`HS_PATCHES`) was verified read-only and remains unmodified.

---

## Directory Index

### 1. Technical Reports (`docs/` & `GITLAB-ISSUE.md`)

| File | Deliverable | Description |
|---|---|---|
| [`GITLAB-ISSUE.md`](GITLAB-ISSUE.md) | **Upstream Ticket** | Ready-to-file Tor Project GitLab issue for `tor-0.4.9.15` summarizing the `0.4.9.14` `perf` motivation, what `0.4.9.15` (`b035c0f582`, `4c0ce0febb`, `7d9b3b11ef`) resolved, and the 9 fixed-cardinality `MetricsPort` metrics in `0001-relay-metrics-mainloop-and-directory-observability.patch`. |
| [`docs/01-facts-hypotheses-unknowns.md`](docs/01-facts-hypotheses-unknowns.md) | **Deliverable 1** | **Verified Facts, Hypotheses, and Unknowns Ledger**: Independent audit of all 4 live `0.4.9.14` `perf` event/control pairs (`sarkodie`/`goodiemob`, `antglizzy`/`ludacris7`, `joji`/`xalisoflow`, `kojofunds`/`richthekid`), exact instruction-level disassembly, source trace, audit of the 14 historical `2026-10-20` comparisons, and ranked hypothesis matrix (`H1`–`H6`). |
| [`docs/02-ranked-fixes-and-patch-review.md`](docs/02-ranked-fixes-and-patch-review.md) | **Deliverable 2** | **Ranked Fixes, `tor-0.4.9.15` Coverage Audit, and Patch Review**: Upstream `tor-0.4.9.15` coverage audit (`b035c0f582`, `4c0ce0febb`, `7d9b3b11ef`) alongside the original `0.4.9.14` candidate patch review, mutation/lifecycle audit, and ASan/UBSan test-suite triage. |
| [`docs/03-prioritized-metrics-specification.md`](docs/03-prioritized-metrics-specification.md) | **Deliverable 3** | **Prioritized Minimal Observability Specification**: Specification, conservation laws, overhead analysis, and hypothesis discrimination rules for mainloop cleanup/stall metrics and `BEGIN_DIR` stream/HTTP/byte metrics. |
| [`docs/04-reproducible-benchmarks-and-tests.md`](docs/04-reproducible-benchmarks-and-tests.md) | **Deliverable 4** | **Reproducible Local Benchmarks and Normal-Traffic Tests**: Historical `0.4.9.14` baseline-vs-indexed scaling and Libevent whole-loop benchmarks plus `tor-0.4.9.15` unit-test verification. |
| [`docs/05-canary-validation-and-profiling-plan.md`](docs/05-canary-validation-and-profiling-plan.md) | **Deliverable 5** | **Unexecuted Canary Validation, Profiling, and Rollback Plan**: Staged canary observability validation plan, host-paired control selection, `/metrics` and `perf` capture runbook, safety gates, and rollback triggers. |

---

### 2. Reviewable Patch (`patches/`)

| Patch File | Base Target | Description |
|---|---|---|
| [`patches/0001-relay-metrics-mainloop-and-directory-observability.patch`](patches/0001-relay-metrics-mainloop-and-directory-observability.patch) | `tor-0.4.9.15` (`4d8efff53a`) | **Single Minimized Upstream Patch (`+541` net production C/H lines)**: Exposes 9 fixed-cardinality `MetricsPort` families (`112` series total) across `mainloop.{h,c}`, `connection.c`, `or_circuit_st.h`, `connection_edge.c`, `dir_connection_st.h`, `directory.{h,c}`, `dircache.c`, `relay_metrics.{h,c}`, `relay_stub.c`, `changes/mainloop_and_dir_metrics`, and `test_mainloop.c`. |

---

### 3. Benchmark Harnesses & Unit Tests (`benchmarks/` & `tests/`)

| File | Description |
|---|---|
| [`benchmarks/bench_cleanup_scaling.c`](benchmarks/bench_cleanup_scaling.c) | Historical `0.4.9.14` 29-point (`9` trials/point) microbenchmark linked against `libtor-app.a`, auditing full-scan `smartlist_remove` and `smartlist_contains` comparisons. |
| [`benchmarks/bench_whole_loop_reproducer.c`](benchmarks/bench_whole_loop_reproducer.c) | Historical `0.4.9.14` 5-trial Libevent event-loop benchmark driving concurrent directory streams, slow flushes, 10 ms timer jitter, and loopback `/metrics` HTTP scrapes. |
| [`tests/test_mainloop.c`](tests/test_mainloop.c) | Rebased `tor-0.4.9.15` `src/test/test_mainloop.c` including `test_mainloop_normal_directory_and_metrics` (multi-stream circuit reuse, `4c0ce0febb` 2nd-HSDir rejection, `7d9b3b11ef` closing-circuit suppression, dying-peer flush protection, slow-client `hold_open_until_flushed` completion, and Prometheus output verification). |

---

### 4. Raw Experimental & Verification Data (`results/`)

| File | Description |
|---|---|
| [`results/scaling-baseline.json`](results/scaling-baseline.json) | Historical `0.4.9.14` 9-trial JSON distribution across all 29 `(A, N, C, mode)` points before indexing. |
| [`results/scaling-patched.json`](results/scaling-patched.json) | Historical `0.4.9.14` 9-trial JSON distribution with indexed connection lists (`0` scan comparisons at every point). |
| [`results/whole-loop-baseline.json`](results/whole-loop-baseline.json) | Historical `0.4.9.14` 5-trial Libevent whole-loop JSON output before indexing. |
| [`results/whole-loop-patched.json`](results/whole-loop-patched.json) | Historical `0.4.9.14` 5-trial Libevent whole-loop JSON output with indexed lists + metrics. |
| [`results/asan_test_suite_triage.json`](results/asan_test_suite_triage.json) | Structured triage of all 8 pre-existing Automake ASan/UBSan container test failures on stock `0.4.9.14`. |
| [`results/unit-test-verification.log`](results/unit-test-verification.log) | Execution log of `253/253` focused unit tests (`mainloop/..`, `connection/..`, `dir/..`, `dir_handle_get/..`, `hs_cache/..`, `hs_service/..`, `hs_client/..`, `dos/..`, `status/..`, `metrics/..`, `relay/..`, `relaycell/..`, `conflux/pool/..`, `oom/..`) on patched `tor-0.4.9.15` (`1,612/1,612` full binary passing). |
| [`SHA256SUMS.txt`](SHA256SUMS.txt) | Per-file SHA256 checksums for all deliverables in this directory. |
