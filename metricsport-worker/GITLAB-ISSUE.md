### Summary

When a relay's main thread is saturated, its `MetricsPort` stops answering. Scrapes wait behind the main `libevent` loop, so Prometheus times out during the overload that operators most need to see. Separately, once tor has `max_sockets - 1` sockets open, `tor_accept_socket_with_extensions()` refuses the scrape connection itself.

We would like feedback on a proof of concept that serves `MetricsPort` from a dedicated thread, before we open an MR.

### Current behavior (production, `0.4.9.14`)

| Relay | Main thread CPU | `/metrics` | `/invalid` (404) | Result (60 s timeout) |
|---|---|---|---|---|
| Relay A (healthy) | < 35% | 2.22 ms | < 2.5 ms | `200 OK` |
| Relay B (saturated) | 99.95% | > 60,000 ms | > 60,000 ms | Timeout on every scrape |
| Relay C (saturated) | 99.64% | > 60,000 ms | 32,125 ms | Timeout |

The 404 timings show the main loop reaching the MetricsPort connection only every 30 seconds or so. We are investigating the saturation itself separately.

The cause: `connection_listener_new()` calls `connection_start_reading()` on the listener, and `metrics_connection_process_inbuf()` runs `metrics_get_output()` inline, all on the main thread.

### What is the expected behavior?

`MetricsPort` keeps answering while the main loop is stalled, with metrics a few seconds old at most and a way to tell their age, and at tor's soft socket limit. This must not weaken `MetricsPortPolicy`, `Sandbox 1`, or SIGHUP and shutdown handling.

### Proof of concept

The main thread rebuilds a snapshot of the HTTP response every second. A worker thread, handed the listener the way `dnsserv_configure_listener()` is, serves that snapshot and checks the policy, but runs no metrics code. What the PoC had to handle:

- Metrics code isn't thread-safe (scraping on the worker hit `BUG()`), so only the main thread builds the snapshot.
- `Sandbox 1`: the worker starts after `sandbox_init()`.
- `MetricsPortPolicy` reloads: the policy is locked and fails closed.
- Socket limit: a new `tor_accept_socket_nonblocking_unlimited()`.
- SIGHUP re-binds: the listener gets a `shutdown()` before it is closed.

Lab results on one host:

| | 0.4.9.14 | PoC |
|---|---|---|
| Scrapes with the main thread stopped | 0 of 20 | 20 of 20, ~0.4 ms |
| Scrapes at the socket limit during a flood | 2 of 5 | 5 of 5 |
| Worker thread under `Sandbox 1` | — | filtered |
| 40 s reload stress | no assertions | no assertions |
| Race-detector reports | 1–2 | the same 1–2 as 0.4.9.14 |

### Questions for maintainers

1. Is a dedicated `MetricsPort` thread acceptable in principle, or should we only fix the main-loop stall?
2. Snapshot freshness: refresh every second (about 0.27 ms each here, more with many onion services), only after scrapes, or wake the main thread on each scrape and fall back to the last snapshot? Should its age be a metric, beyond the `Date:` header?
3. May `MetricsPort` ignore the `max_sockets` soft limit for its one connection?
4. Should shutdown join the worker, like `threadpool_stop_threads()` does? It is detached now, and exits within a second of its listener closing.
5. Windows: keep the main-loop path, or use `WSAPoll()`?
6. Is one client at a time, with 10 seconds each, acceptable, given that `MetricsPortPolicy` limits who can connect?

### Sources

- [PoC branch](https://github.com/1aeo/TorUtils/tree/metricsport-worker/metricsport-worker)
- tor-0.4.9.14: [connection.c](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/mainloop/connection.c#L1777-L1783), [metrics.c](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/feature/metrics/metrics.c#L70-L169), [socket.c](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/lib/net/socket.c#L377-L391)
