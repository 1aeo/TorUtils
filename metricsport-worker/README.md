# Tor `MetricsPort` worker thread (`tor-0.4.9.14`)

A 4-commit patch series for Tor `0.4.9.14` that answers `MetricsPort` scrapes from a dedicated thread, so they keep working when the relay's main event loop is saturated or at its socket limit. The main thread builds the metrics once per second. The worker thread does socket I/O and never runs metrics code; the only shared state it reads is `MetricsPortPolicy` and the socket counts, both under locks.

Upstream issue: [tpo/core/tor#41458](https://gitlab.torproject.org/tpo/core/tor/-/work_items/41458), "MetricsPort stops answering when the main loop is saturated. Dedicated thread?" Its text, as posted, is in [`GITLAB-ISSUE.md`](./GITLAB-ISSUE.md).

## Patch series (`patches/`)

| # | Commit | Files | Lines |
|---|---|---|---|
| 1 | `policies: Make metrics_policy_permits_address() thread-safe` | `src/core/or/policies.c`, `src/test/test_metrics.c` | +26 / −6 |
| 2 | `net: Add tor_accept_socket_nonblocking_unlimited()` | `src/lib/net/socket.{c,h}` | +29 / −5 |
| 3 | `metrics: Split MetricsPort request checks and response into helpers` | `src/feature/metrics/metrics.c` | +36 / −31 |
| 4 | `metrics: Answer MetricsPort requests from a dedicated thread` | `changes/ticket41458`, `src/core/mainloop/connection.c`, `src/feature/metrics/metrics.{c,h}`, `src/test/test_metrics.c` | +310 / −2 |
| | **Total** | 8 files | **+401 / −44** (of which 97 are tests and the changes file) |

1. **Policy lock.** `metrics_policy` is rebuilt on SIGHUP by `load_policy_from_option()`, which frees it and sets it to `NULL` first. A `NULL` policy means "accept" in `compare_tor_addr_to_addr_policy()`. The worker reads the policy, so it is now guarded by a mutex (created on first use, like `socket_accounting_lock()`), and the check fails closed when there is no policy.
2. **Accept past `max_sockets`.** `tor_accept_socket_with_extensions()` refuses once tor has `max_sockets - 1` sockets open, although `set_max_file_descriptors()` keeps `ULIMIT_BUFFER` (32) more descriptors. The new `tor_accept_socket_nonblocking_unlimited()` shares its code but skips that check. It is meant for callers that hold a small, fixed number of sockets, which the worker does: one client at a time. Because it skips the check, the worker also never reads `max_sockets`, which SIGHUP rewrites.
3. **Refactor, no behavior change.** `metrics_check_http_request()` and `metrics_get_http_response()` let the worker give the same answers as the main-thread path.
4. **Worker thread.** `connection_listener_new()` hands `CONN_TYPE_METRICS_LISTENER` to `metrics_configure_listener()`, the same way it hands DNSPort listeners to `dnsserv_configure_listener()`. A 1-second `periodic_timer_t` on the main thread rebuilds the HTTP response, and starts the worker on its first tick, after `sandbox_init()`, so the worker is under the seccomp filter. The worker:
   - accepts one client at a time and checks `MetricsPortPolicy`;
   - reads up to 1024 bytes of headers and sends a copy of the latest response, with a 10-second limit per client;
   - accepts with `tor_accept_socket_nonblocking_unlimited()`, so scrapes work at the socket limit;
   - sleeps after a failed `accept()` instead of spinning.

   `metrics_close_listener()` runs before a MetricsPort listener socket is closed and calls `shutdown()` on it. On Linux, a socket that another thread is polling stays bound after `close()`, which made re-binding the same port on SIGHUP fail. Windows, which has no `poll()`, keeps the main-loop path.

## Build and test

```bash
git clone --branch tor-0.4.9.14 https://gitlab.torproject.org/tpo/core/tor.git
cd tor && git am /path/to/metricsport-worker/patches/*.patch
./autogen.sh && ./configure --enable-fatal-warnings && make -j"$(nproc)"
./src/test/test metrics/.. policy/.. buffer/..   # includes the new metrics/worker test
make check-spaces && python3 scripts/maint/lintChanges.py changes/ticket41458
```

Results on Ubuntu 24.04 (gcc 13, glibc 2.39): builds with `--enable-fatal-warnings`; the full unit test suite passes (1596 ok, 31 skipped); `check-spaces`, `lintChanges.py`, and `practracker` report nothing new (`connection.c`, already over its size limit, grows by 5 lines).

## Lab scripts (`lab/`)

These scripts reproduce the results in the issue on one Linux machine. Each starts a throwaway relay that doesn't publish its descriptor, with `MetricsPort 127.0.0.1:<base+35>`. Working files go to `$LAB_DIR` (default `/tmp/metricsport-lab`). Usage is `<script> <tor-binary> [port-base]`.

| Script | What it shows |
|---|---|
| `latency.sh` | 20 scrapes while healthy, then 20 while tor's main thread is stopped with `ptrace` (`stall.py`) |
| `socket-cap.sh` | Scrapes with a 256 fd limit, after filling tor's sockets with idle SocksPort connections |
| `sandbox.sh` | Runs with `Sandbox 1`, and prints each thread's seccomp mode |
| `stress.sh <tor> [secs]` | Parallel scrapes while SIGHUP flips the MetricsPort port and policy, plus a stall. Counts `BUG()` warnings, and ThreadSanitizer reports for a `-fsanitize=thread` build |
| `accept-spin.sh` | Makes `accept()` fail with `EMFILE` and prints each thread's CPU time |

`stall.py` uses `PTRACE_SEIZE`, so it needs root or `kernel.yama.ptrace_scope=0`. `accept-spin.sh` needs `prlimit` (util-linux).

## Changes from the first prototype

An earlier version of this branch scraped the metrics directly on the worker thread. Review and lab testing found these problems, all fixed in the current series:

- `metrics_get_output()` on the worker read main-thread state: `node_get_by_id(...)->rs`, `get_options()`, the signing key certificate, and the hidden service map. Under SIGHUP stress it hit `BUG()` (`!in_option_validation` in `get_options_mutable()`). The main thread now builds the response.
- The worker was spawned while `tor_init()` opened listeners, before `sandbox_init()`, so it ran without the seccomp filter (`Seccomp: 0`).
- `MetricsPortPolicy` and `max_sockets` were read without locks while SIGHUP rewrote them. Commit 1 locks the policy, and the worker no longer reads `max_sockets`.
- To accept at the socket limit, it stopped counting the listener for the length of each `accept()`. Under a connection flood, the main thread took that slot first, so the trick did no better than stock tor: 2 of 5 scrapes got through for each, after 1.1–2.4 s. Commit 2 replaces the trick.
- Changing only the MetricsPort address on SIGHUP (`127.0.0.1:P` to `0.0.0.0:P`) made tor exit: the worker's `poll()` kept the old listener bound, so re-binding failed.
- Its unit test changed a `connection_t`'s type to a listener type, so `connection_free_minimal()` failed its magic-number assertion.
- `total_bytes_allocated_in_chunks` became an `atomic_counter_t` but was never initialized with `atomic_counter_init()`. That change, and the per-thread `metrics_format_label()` buffers, are no longer needed because the worker uses neither.
- `<poll.h>` was included unconditionally, which would break the Windows build.
- `changes/bug_metrics_policy_null` cited ticket 40063, which is the ticket that introduced MetricsPort, not a bug.
