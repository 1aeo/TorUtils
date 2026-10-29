# Tor `MetricsPort` worker thread (`tor-0.4.9.15`)

A 4-commit patch series rebased onto Tor `0.4.9.15` that answers `MetricsPort` scrapes from a dedicated thread, so they keep working when the relay's main event loop is saturated or at its socket limit. The main thread builds the metrics HTTP response once per second. The worker thread performs only socket I/O and never runs metrics code; the only shared state it touches is `MetricsPortPolicy` and socket accounting, both under locks.

Upstream issue: [tpo/core/tor#41458](https://gitlab.torproject.org/tpo/core/tor/-/work_items/41458), "MetricsPort stops answering when the main loop is saturated. Dedicated thread?" Its text (updated for `tor-0.4.9.15`) is in [`GITLAB-ISSUE.md`](./GITLAB-ISSUE.md).

## Patch series (`patches/`)

| # | Commit | Files | Lines |
|---|---|---|---|
| 1 | `policies: Make metrics_policy_permits_address() thread-safe` | `src/core/or/policies.c`, `src/test/test_metrics.c` | +43 / −5 |
| 2 | `net: Add tor_accept_socket_nonblocking_unlimited()` | `src/lib/net/socket.{c,h}` | +27 / −5 |
| 3 | `metrics: Split MetricsPort request checks and response into helpers` | `src/feature/metrics/metrics.c` | +36 / −31 |
| 4 | `metrics: Answer MetricsPort requests from a dedicated thread` | `changes/ticket41458`, `src/lib/sandbox/sandbox.c`, `src/core/mainloop/connection.c`, `src/feature/metrics/metrics.{c,h}`, `src/test/test_metrics.c` | +343 / −3 |
| | **Total** | 9 files | **+449 / −44** (of which 123 are tests and `changes/ticket41458`) |

1. **Policy validation, atomic swap, and lock.** `validate_addr_policies()` now validates `options->MetricsPortPolicy` upfront, and `parse_metrics_port_policy()` stages parsed rules (plus trailing `"reject *:*"`) into a temporary list before swapping `metrics_policy` under `metrics_policy_mutex`, so failed reloads preserve the active policy and concurrent readers never observe a `NULL` or half-built policy. `metrics_policy_permits_address()` fails closed when `metrics_policy` is `NULL`, and `policies_free_all()` frees `metrics_policy` under the lock.
2. **Accept past `max_sockets`.** `tor_accept_socket_with_extensions()` refuses once tor has `max_sockets - 1` sockets open, although `set_max_file_descriptors()` keeps `ULIMIT_BUFFER` (32) more descriptors. `tor_accept_socket_nonblocking_unlimited()` shares its implementation while skipping the `max_sockets` check (and avoiding unlocked reads of `max_sockets` during `SIGHUP`).
3. **HTTP request/response helpers.** `metrics_check_http_request()` (using exact `"GET"` and `"/metrics"` matching) and `metrics_get_http_response()` let the worker serve identical HTTP responses without a `connection_t` or cross-thread `buf_t`.
4. **Worker thread.** `connection_listener_new()` hands `CONN_TYPE_METRICS_LISTENER` to `metrics_configure_listener()`, matching `dnsserv_configure_listener()`. A `mainloop_event_t` on the main thread activates immediately on the first main-loop tick (after `options_switch_id()` privilege drop and `sandbox_init()` seccomp load, with 0 ms startup delay) and reschedules every 1 second to refresh `worker_response`, falling back to `connection_start_reading()` if `spawn_func()` fails. The worker:
   - supports POSIX `poll()` (including `ppoll`/`ppoll_time64` under Linux `Sandbox 1` on `aarch64`/`riscv64`/`time64`) and Windows `WSAPoll()`;
   - accepts one client at a time via `tor_accept_socket_nonblocking_unlimited()` and checks `MetricsPortPolicy`;
   - sleeps 1s only on `ERRNO_IS_RESOURCE_LIMIT` (`EMFILE`/`ENFILE`/`ENOBUFS`) so `SYN+RST` (`ECONNABORTED`) from unauthorized peers cannot stall scrapes;
   - retries cleanly on `EINTR`/`EAGAIN`, returns `400 Bad Request` on `>= 1024`-byte headers (draining up to 4 KB of unread request bytes before close to avoid TCP `RST`), and aborts promptly if the listener is closed or rebound;
   - calls `shutdown(s, TOR_SHUT_RD)` in `metrics_close_listener()` before `tor_close_socket()` so Linux `poll()` unbinds immediately on `SIGHUP` rebinds and frees `worker_response` when `MetricsPort` is disabled.

## Build and test

```bash
git clone --branch tor-0.4.9.15 https://gitlab.torproject.org/tpo/core/tor.git
cd tor && git am /path/to/metricsport-worker/patches/*.patch
./autogen.sh && ./configure --enable-gcc-warnings && make -j"$(nproc)"
./src/test/test metrics/.. policy/.. buffer/..   # includes metrics/worker
make check-spaces && make check-includes && python3 scripts/maint/lintChanges.py changes/ticket41458
```

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
