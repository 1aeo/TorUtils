# Tor `MetricsPort` Dedicated Worker Thread (`tor-0.4.9.14`)

3-commit C99 patch series for Tor `0.4.9.14` that moves `CONN_TYPE_METRICS_LISTENER` off the main `libevent` loop onto a dedicated worker thread in `src/feature/metrics/metrics.c`, ensuring `MetricsPort` scrapes never stall or fail with `EMFILE` when the main thread is saturated.

## Patch Series (`patches/`)

1. **`patches/0001-metrics-Reject-MetricsPort-connections-when-metrics_.patch`** (`+10 / -1`)
   - `changes/bug_metrics_policy_null`, `src/core/or/policies.c`, `src/test/test_metrics.c`
   - Rejects `MetricsPort` connections when `metrics_policy == NULL` (before `policies_parse_from_options()` or after `policies_free_all()`) instead of defaulting to `ADDR_POLICY_ACCEPTED` (`1`) in `compare_tor_addr_to_addr_policy()`.
2. **`patches/0002-buf-metrics-Make-chunk-allocation-counter-and-label-.patch`** (`+16 / -10`)
   - `src/lib/buf/.may_include`, `src/lib/buf/buffers.c`, `src/lib/metrics/metrics_common.c`
   - Converts `total_bytes_allocated_in_chunks` in `buffers.c` to Tor's C99 `atomic_counter_t` (matching `src/lib/compress/compress.c`) and indexes a two-slot static buffer in `metrics_format_label()` by `in_main_thread()`.
3. **`patches/0003-metrics-Service-MetricsPort-connections-on-a-dedicat.patch`** (`+135 / -4`)
   - `changes/feature_metrics_worker`, `src/core/mainloop/connection.c`, `src/feature/metrics/metrics.h`, `src/feature/metrics/metrics.c`, `src/test/test_metrics.c`
   - Hands `CONN_TYPE_METRICS_LISTENER` to `metrics_configure_listener(conn)` in `connection_listener_new()` (following `dnsserv_configure_listener(conn)`), services scrapes on `metrics_worker_threadfn()`, preserves Linux `Sandbox 1` (`seccomp` `sb_accept4`) compatibility, and temporarily releases the listener's open-socket count slot during `accept4()` so `MetricsPort` can use 1 of the 32 reserved `ULIMIT_BUFFER` file descriptors even when `get_n_open_sockets() >= max_sockets - 1`.

## Upstream GitLab Issue Text

See [`GITLAB-ISSUE.md`](./GITLAB-ISSUE.md) for the upstream `tpo/core/tor` GitLab work item text with production telemetry, code snippets, and source links.
