### Summary

When a relay's main thread is saturated, its `MetricsPort` stops answering: every scrape waits behind the main `libevent` loop, so Prometheus times out exactly during the overload that operators most need to see. Separately, once tor has `max_sockets - 1` sockets open, `tor_accept_socket_with_extensions()` refuses the scrape connection itself.

We would like maintainers' feedback on serving `MetricsPort` from a dedicated thread before we open an MR. We have a working 4-commit series against `tor-0.4.9.14` (+401/−44 lines, including tests), but some of the design choices are yours to make. See **Questions for maintainers** below.

### Current behavior (production, `0.4.9.14`)

| Relay | Main thread CPU | `GET /metrics` | `GET /invalid` (404) | Result (60 s scrape timeout) |
|---|---|---|---|---|
| Relay A (healthy) | < 35% | 2.22 ms | < 2.5 ms | `200 OK` |
| Relay B (main loop saturated, 185 `perf` samples) | 99.95% | > 60,000 ms | > 60,000 ms | Timeout on every scrape |
| Relay C (main loop saturated, 187 `perf` samples) | 99.64% | > 60,000 ms | 32,125 ms | Timeout |

The 404 timings show the main loop only reaching the MetricsPort connection every 30 seconds or so. We are investigating the saturation itself (connection-list scanning shows up in `perf`) separately. This issue is only about keeping `MetricsPort` available while it happens.

The cause: `MetricsPort` connections are served entirely by the main thread. `connection_listener_new()` calls `connection_start_reading()` on the listener, and `metrics_connection_process_inbuf()` runs `metrics_get_output()` inline. Accepting, parsing, building the output and flushing all wait for the main loop.

### What is the expected behavior?

`MetricsPort` keeps answering while the main loop is stalled, with metrics at most a few seconds old and a way to tell their age, and it accepts a scrape when tor is at its soft socket limit. None of this should weaken `MetricsPortPolicy`, `Sandbox 1`, or SIGHUP and shutdown handling.

### Proposed approach

Follow the DNSPort pattern. In `connection_listener_new()`, hand the `MetricsPort` listener to a new `metrics_configure_listener()` instead of calling `connection_start_reading()`, much as DNSPort listeners go to `dnsserv_configure_listener()`.

- **Main thread:** a 1-second `periodic_timer_t` builds the complete HTTP response (headers and `metrics_get_output()`), and stores it for the worker.
- **Worker thread** (one, from `spawn_func()`): it `poll()`s the listener, accepts one client at a time, checks `MetricsPortPolicy`, and reads up to 1024 bytes of headers. It then sends a copy of the stored response, or the same 400, 404 or 405 the main thread would send. It never calls into the metrics subsystems; the only main-thread state it reads is `MetricsPortPolicy` and the socket accounting, both under locks. When the main loop stalls, scrapes get the last response, and its `Date:` header says when it was built.

The series:

1. `policies: Make metrics_policy_permits_address() thread-safe`
2. `net: Add tor_accept_socket_nonblocking_unlimited()`
3. `metrics: Split MetricsPort request checks and response into helpers` (no behavior change)
4. `metrics: Answer MetricsPort requests from a dedicated thread` (with a `metrics/worker` unit test and a changes file)

Patches, lab scripts and notes: [`1aeo/TorUtils`, branch `metricsport-worker`](https://github.com/1aeo/TorUtils/tree/metricsport-worker/metricsport-worker).

### Challenges, and what we ran into

1. **Scraping on the worker thread is not safe.** Our first prototype called `metrics_get_output()` on the worker. The `get_metrics` callbacks read main-thread state without locks:
   - `fill_relay_flags()` dereferences `node_get_by_id(router_get_my_id_digest())->rs`, which is replaced with every consensus;
   - `fill_signing_cert_expiry()` reads `get_options()` and `get_master_signing_key_cert()`;
   - `hs_metrics_get_stores()` walks `hs_service_map`;
   - relay metrics rebuild a shared store.

   Under a SIGHUP stress test, the prototype hit `BUG()`: `Non-fatal assertion ! in_option_validation failed in get_options_mutable`, with the stack `metrics_connection_process_inbuf → metrics_get_output → relay_metrics_get_stores → get_options` on the worker. ThreadSanitizer reported 22 data races in that run, 21 of them not seen on stock: in the policy code, `hs_service_ht`, `rephist.c` counters and `smartlist_del()`, among others. Making every callback thread-safe looked much larger than this feature, so the main thread builds the response instead.
2. **`Sandbox 1` only covers threads created after `sandbox_init()`.** The seccomp filter is loaded without TSYNC, and `MetricsPort` is opened in `tor_init()`, before `sandbox_init()`. A worker spawned when the listener opened ran with `Seccomp: 0`. We now start it on the timer's first tick in the main loop, just as `cpuworker_init()` runs after `sandbox_init()`.
3. **`MetricsPortPolicy` reload.** `load_policy_from_option()` frees `metrics_policy` and sets it to `NULL` before parsing the new one, and `compare_tor_addr_to_addr_policy()` treats a `NULL` policy as "accept". On one thread that is harmless. A worker checking the policy during SIGHUP could read freed memory or accept everyone. Commit 1 adds a mutex, created on first use like `socket_accounting_mutex`, and fails closed.
4. **Soft socket limit.** `tor_accept_socket_with_extensions()` refuses once `get_n_open_sockets() >= max_sockets - 1`, even though `set_max_file_descriptors()` keeps `ULIMIT_BUFFER` (32) descriptors beyond `max_sockets`. Our prototype stopped counting its listener for the length of each `accept()`. Under a connection flood the main thread took that slot first, so the prototype did no better than stock tor: in the lab, 2 of 5 scrapes got through for each, after 1.1–2.4 s. Commit 2 adds `tor_accept_socket_nonblocking_unlimited()`, which skips the check. The worker holds one client at a time, so it uses at most one extra descriptor. Skipping the check also means the worker no longer reads `max_sockets`, which SIGHUP rewrites; ThreadSanitizer had reported that race.
5. **Closing a listener that another thread is polling.** On Linux, a listening socket stays bound after `close()` while another thread is in `poll()` on it. Re-binding its port then fails with `EADDRINUSE`, and tor exits with "Restart failed (config error?)". Changing only the `MetricsPort` address, for example `127.0.0.1:9035` to `0.0.0.0:9035`, goes through the re-bind path in `retry_all_listeners()`, and our prototype exited on the first such SIGHUP. Moving the port away and back within a second fails the same way. We call `shutdown(SHUT_RD)` on the listener before `tor_close_socket()`, which unbinds it and wakes the worker.
6. **`accept()` failures.** If `accept()` keeps failing, for example with `EMFILE`, the listener stays readable, so a plain accept loop spins at 100% CPU and competes with the saturated main thread. We measured that with a draft of this series. The worker now sleeps for one second after a failed accept.
7. **Windows** has no `poll()`, so there `metrics_configure_listener()` keeps the main-loop behavior.
8. **Related, pre-existing: tpo/core/tor#41060.** With `Sandbox 1` and a recent glibc (we saw it with 2.39), `pthread_create()` calls `rt_sigprocmask(SIG_BLOCK, ...)`. `sb_rt_sigprocmask()` rejects that with `EPERM`, so glibc then restores an uninitialized mask with `SIG_SETMASK`. On stock 0.4.9.14, the main thread ended up blocking `SIGTERM` in 2 of 4 runs, and `kill` was ignored. This already happens when the cpuworkers start. Our worker is one more `pthread_create()` after `sandbox_init()`.

### Lab results

These come from one Ubuntu 24.04 host (glibc 2.39) with a local relay that doesn't publish its descriptor, using the scripts in the branch. The "main thread stopped" rows use `ptrace` to stop only tor's main thread. We still have to repeat the production measurements with this series.

| | Stock `0.4.9.14` | First prototype (scrape on worker) | This series |
|---|---|---|---|
| `GET /metrics`, healthy (20 scrapes) | 20/20, median 0.96 ms | | 20/20, median 0.40 ms |
| `GET /metrics`, main thread stopped (20 scrapes, 3 s timeout) | **0/20** | | **20/20**, median 0.40 ms, max 0.57 ms |
| `GET /metrics` at `max_sockets - 1`, during a SocksPort flood (5 scrapes) | 2/5, after 1.2–2.4 s | 2/5, after 1.1–2.2 s | **5/5**, 0.50 ms |
| Worker thread with `Sandbox 1` | | `Seccomp: 0` (unfiltered) | `Seccomp: 2` |
| 40 s of SIGHUPs flipping port and policy, 4 parallel scrapers, one 4 s stall | no `BUG()` | 4 `BUG()` (49 in the ThreadSanitizer build) | no `BUG()` |
| ThreadSanitizer reports in that run | 1–2 (threadpool lock order, log severity) | 22 data races, 21 of them not seen on stock | same 1–2 as stock |
| SIGHUP changing only the `MetricsPort` address, 6 times | survives | **exits on the first one** | survives |
| Main thread cost of each 1 s refresh (26 KB of relay metrics) | | | about 0.27 ms |

An empty cell means we didn't measure it, or it doesn't apply.

The series builds with `--enable-fatal-warnings` and passes the full unit test suite, `make check-spaces`, and `lintChanges.py`.

### Questions for maintainers

1. Is a dedicated `MetricsPort` thread acceptable in principle, or would you rather we only fix the main-loop stall?
2. How fresh should the snapshot be? The options we see:
   - refresh every second unconditionally, as now (about 0.27 ms per second here, more with many onion services);
   - refresh only after scrapes;
   - wake the main thread on each scrape (with an alert socket) and fall back to the last snapshot after a timeout.

   Should the snapshot's age also be a metric, rather than only the `Date:` header?
3. Is it acceptable for `MetricsPort` to ignore the `max_sockets` soft limit for its one connection, through the new `tor_accept_socket_nonblocking_unlimited()`? Or should it respect the limit?
4. The worker thread is detached and exits within a second after its listener closes; `metrics_cleanup()` doesn't wait for it. Do you want it joined at shutdown, like `threadpool_stop_threads()` does for cpuworkers?
5. On Windows, should we keep the main-loop path, or use `WSAPoll()`?
6. The worker serves one client at a time, with 10 seconds per client. Is that acceptable, given that `MetricsPortPolicy` limits who can connect?

<details>
<summary>Code references (<code>tor-0.4.9.14</code>)</summary>

- **Listener setup and close**
  - [`src/core/mainloop/connection.c#L1777-L1783`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/mainloop/connection.c#L1777-L1783): end of `connection_listener_new()`, which hands DNSPort listeners to `dnsserv_configure_listener()`
  - [`src/feature/client/dnsserv.c#L404-L416`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/feature/client/dnsserv.c#L404-L416): `dnsserv_configure_listener()`
  - [`src/core/mainloop/connection.c#L1054-L1089`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/mainloop/connection.c#L1054-L1089): `connection_close_immediate()`
  - [`src/core/mainloop/connection.c#L782-L960`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/mainloop/connection.c#L782-L960): `connection_free_minimal()`
  - [`src/core/mainloop/connection.c#L3290-L3337`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/mainloop/connection.c#L3290-L3337): the re-bind loop in `retry_all_listeners()`, which closes the old listener and binds the same port again right away
- **MetricsPort**
  - [`src/feature/metrics/metrics.c#L70-L169`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/feature/metrics/metrics.c#L70-L169): `metrics_get_output()`, `metrics_connection_process_inbuf()`
  - [`src/feature/metrics/metrics.c#L195`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/feature/metrics/metrics.c#L195): only the first `MetricsPort` line is used, so there is one listener
- **Main-thread state that `get_metrics` callbacks read**
  - [`src/feature/relay/relay_metrics.c#L303-L322`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/feature/relay/relay_metrics.c#L303-L322): `fill_relay_flags()`
  - [`src/feature/relay/relay_metrics.c#L1069-L1085`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/feature/relay/relay_metrics.c#L1069-L1085): `fill_signing_cert_expiry()`
  - [`src/feature/hs/hs_service.c#L4592-L4604`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/feature/hs/hs_service.c#L4592-L4604): `hs_service_get_metrics_stores()`
  - [`src/app/config/config.c#L939-L945`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/app/config/config.c#L939-L945): `get_options_mutable()` and its `in_option_validation` assertion
- **Policy**
  - [`src/core/or/policies.c#L1071-L1075`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/or/policies.c#L1071-L1075): `metrics_policy_permits_address()`
  - [`src/core/or/policies.c#L1214-L1263`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/or/policies.c#L1214-L1263): `load_policy_from_option()`, `parse_metrics_port_policy()`
  - [`src/core/or/policies.c#L1534-L1541`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/or/policies.c#L1534-L1541): `compare_tor_addr_to_addr_policy()`, "no policy? accept all"
- **Sockets and limits**
  - [`src/lib/net/socket.c#L377-L391`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/lib/net/socket.c#L377-L391): the `max_sockets - 1` check in `tor_accept_socket_with_extensions()`
  - [`src/lib/net/socket.c#L94-L108`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/lib/net/socket.c#L94-L108): `max_sockets`, which `set_max_sockets()` rewrites on SIGHUP
  - [`src/lib/process/restrict.c#L163-L240`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/lib/process/restrict.c#L163-L240): `ULIMIT_BUFFER` and `set_max_file_descriptors()`
- **Sandbox and threads**
  - [`src/app/main/main.c#L1400-L1425`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/app/main/main.c#L1400-L1425): `tor_init()`, then `sandbox_init()`
  - [`src/app/main/main.c#L1306`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/app/main/main.c#L1306): `cpuworker_init()`, run from the main loop after the sandbox
  - [`src/lib/sandbox/sandbox.c#L2065`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/lib/sandbox/sandbox.c#L2065): `seccomp_init(SCMP_ACT_ERRNO(EPERM))`
  - [`src/lib/sandbox/sandbox.c#L403-L424`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/lib/sandbox/sandbox.c#L403-L424): `sb_accept4()`
  - [`src/lib/sandbox/sandbox.c#L1358-L1383`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/lib/sandbox/sandbox.c#L1358-L1383): `sb_rt_sigprocmask()`, where `SIG_BLOCK` is only allowed with fragile hardening (tpo/core/tor#41060)
  - [`src/lib/evloop/compat_libevent.c#L147`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/lib/evloop/compat_libevent.c#L147): `EVENT_BASE_FLAG_NOLOCK`, so other threads can't touch the main event base
  - [`src/lib/evloop/workqueue.c#L659-L685`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/lib/evloop/workqueue.c#L659-L685): `threadpool_stop_threads()`

</details>

/label ~Feature
