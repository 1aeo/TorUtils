### Summary

When a relay's main thread is saturated, its `MetricsPort` stops answering. Scrapes wait behind the main `libevent` loop, so Prometheus times out during the overload that operators most need to see. Separately, once tor has `max_sockets - 1` sockets open, `tor_accept_socket_with_extensions()` refuses the scrape connection itself.

While `0.4.9.15` fixed quadratic connection-list removal (`tor#41339`), `MetricsPort` listeners and connections still execute on the single-threaded main loop. We would like feedback on a proof of concept (rebased onto `tor-0.4.9.15`) that serves `MetricsPort` from a dedicated thread, before we open an MR.

### Current behavior (production)

| Relay | Main thread CPU | `/metrics` | `/invalid` (404) | Result (60 s timeout) |
|---|---|---|---|---|
| Relay A (healthy) | < 35% | 2.22 ms | < 2.5 ms | `200 OK` |
| Relay B (saturated) | 99.95% | > 60,000 ms | > 60,000 ms | Timeout on every scrape |
| Relay C (saturated) | 99.64% | > 60,000 ms | 32,125 ms | Timeout |

The 404 timings show the main loop reaching the MetricsPort connection only every 30 seconds or so.

The cause: `connection_listener_new()` calls `connection_start_reading()` on the listener, and `metrics_connection_process_inbuf()` runs `metrics_get_output()` inline, all on the main thread.

### What is the expected behavior?

`MetricsPort` keeps answering while the main loop is stalled, with metrics a few seconds old at most and a way to tell their age, and at tor's soft socket limit. This must not weaken `MetricsPortPolicy`, `Sandbox 1`, or SIGHUP and shutdown handling.

### Proof of concept (`tor-0.4.9.15`)

The main thread rebuilds a snapshot of the HTTP response every second via `mainloop_event_t`. A worker thread, handed the listener the way `dnsserv_configure_listener()` is, serves that snapshot and checks the policy, but runs no metrics code. What the PoC handles:

- Metrics code isn't thread-safe (scraping on the worker hit `BUG()`), so only the main thread builds the snapshot.
- `Sandbox 1` & privilege drop: the worker starts on the first main-loop tick after `options_switch_id()` and `sandbox_init()`, with `ppoll`/`ppoll_time64` allowed alongside `poll` in `sandbox.c`.
- `MetricsPortPolicy` reloads: validated in `validate_addr_policies()`, staged into a temporary list before swapping under a mutex, and fails closed.
- Socket limit: `tor_accept_socket_nonblocking_unlimited()` uses 1 of the 32 `ULIMIT_BUFFER` descriptors, sleeping only on `ERRNO_IS_RESOURCE_LIMIT`.
- SIGHUP re-binds & cross-platform polling: the listener gets a `shutdown()` before close on POSIX, and Windows uses `WSAPoll()`.

Lab results on one host:

| | Stock Tor | PoC (`tor-0.4.9.15`) |
|---|---|---|
| Scrapes with the main thread stopped | 0 of 20 | 20 of 20, ~0.4 ms |
| Scrapes at the socket limit during a flood | 2 of 5 | 5 of 5 |
| Worker thread under `Sandbox 1` | — | filtered |
| 40 s reload stress | no assertions | no assertions |
| Race-detector reports | 1–2 | the same 1–2 as stock |

### Questions for maintainers

1. Is a dedicated `MetricsPort` thread acceptable in principle, or should we only fix main-loop stalls individually?
2. Snapshot freshness: refresh every second (~0.27 ms each here, more with many onion services), only after scrapes, or wake the main thread on each scrape and fall back to the last snapshot? Should its age be a metric, beyond the `Date:` header?
3. May `MetricsPort` ignore the `max_sockets` soft limit for its one connection?
4. Should shutdown join the worker, like `threadpool_stop_threads()` does? It is detached now, and exits promptly once its listener closes.
5. Windows: use `WSAPoll()` on the worker thread (as in the current PoC), or keep the main-loop path?
6. Is one client at a time, with 10 seconds each, acceptable, given that `MetricsPortPolicy` limits who can connect?

### Sources

- [PoC branch (`tor-0.4.9.15`)](https://github.com/1aeo/TorUtils/tree/metricsport-worker/metricsport-worker)
- tor-0.4.9.15: [connection.c](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.15/src/core/mainloop/connection.c#L1783-L1789), [metrics.c](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.15/src/feature/metrics/metrics.c#L70-L169), [policies.c](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.15/src/core/or/policies.c#L1072-L1263), [socket.c](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.15/src/lib/net/socket.c#L377-L391)
