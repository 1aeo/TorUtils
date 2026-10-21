### Summary

When a relay's main `libevent` loop is saturated (or when open sockets reach `max_sockets - 1` during a connection/circuit flood), `MetricsPort` HTTP scrapes stall behind main-thread events and time out (`60s`), blinding operator monitoring during the exact overload events `MetricsPort` is meant to observe.

We propose a 3-commit C99 series (`+161 / -15` lines, including `changes/` files and unit tests) that moves `CONN_TYPE_METRICS_LISTENER` accept/read/write off the main `libevent` loop onto a dedicated worker thread in `src/feature/metrics/metrics.c`—following the existing `dnsserv_configure_listener()` handoff pattern in `connection_listener_new()`.

---

### Problem & Production Telemetry (`0.4.9.14`)

Because `CONN_TYPE_METRICS_LISTENER` and `CONN_TYPE_METRICS` run entirely on the main thread's `libevent` base (`connection_listener_new()` -> `connection_start_reading()`), `MetricsPort` has two failure modes under load:

1. **Event-loop head-of-line blocking**: Any multi-second main-thread stall (e.g., large connection-list teardown or directory/HS bursts) blocks `accept()`, `metrics_connection_process_inbuf()`, and socket flushes.
2. **Soft socket-cap (`max_sockets - 1`) rejection**: When `get_n_open_sockets() >= max_sockets - 1`, `tor_accept_socket_with_extensions()` rejects new `MetricsPort` scrapes with `EMFILE` even though Tor reserves `ULIMIT_BUFFER` (`32`) extra OS file descriptors above `max_sockets`.

| Relay / Condition (`Tor 0.4.9.14`) | Main Thread CPU | `GET /metrics` Latency | `GET /invalid` (`404`) Latency | Outcome (60s Scrape Timeout) |
| :--- | :---: | :---: | :---: | :--- |
| **Relay A** (Healthy control) | `< 35%` | **`2.22 ms`** | `< 2.5 ms` | `200 OK` |
| **Relay B** (Mainloop saturated, 185 `perf` samples) | **`99.95%`** | **`> 60,000 ms`** | **`> 60,000 ms`** | **Timeout (100% loss)** |
| **Relay C** (Mainloop saturated, 187 `perf` samples) | **`99.64%`** | **`> 60,000 ms`** | **`32,125 ms`** | **Timeout** |

*(Note: The underlying mainloop connection-list scan cost observed in `perf` is being tracked/patched separately; this issue addresses decoupling `MetricsPort` liveness from main-thread saturation.)*

---

### Proposed 3-Commit Series & Measured Results

| Metric | Stock `0.4.9.14` (Main Thread Stalled / At `max_sockets - 1`) | Proposed 3-Commit Series |
| :--- | :---: | :---: |
| **`GET /metrics` latency under 100% main-thread stall** | `> 60,000 ms` (Timeout) | **`2.1 – 4.3 ms` (`200 OK`)** |
| **`GET /metrics` when `n_sockets_open == max_sockets - 1`** | `EMFILE` / Timeout | **`200 OK`** (uses 1 of 32 `ULIMIT_BUFFER` fds) |
| **Linux `Sandbox 1` (`seccomp`) compatibility** | `accept4()` via `sb_accept4()` | Preserved (`tor_accept_socket_nonblocking()`) |
| **Diff footprint (including `changes/` & `test_metrics.c`)** | — | **3 commits, `+161 / -15` (`146` net lines; `130` net C lines)** |

#### Commit 1: `metrics: Reject MetricsPort connections when metrics_policy is NULL`
In `options_act_reversible()`, `options_start_listener_transaction()` opens `MetricsPort` before `options_act()` calls `policies_parse_from_options()`. Because `compare_tor_addr_to_addr_policy()` returns `ADDR_POLICY_ACCEPTED` (`1`) when `policy == NULL`, `metrics_policy_permits_address()` previously defaulted to `accept *:*` whenever `metrics_policy == NULL` (bugfix on `0.4.5.1-alpha`, ticket `40063`):

```c
/* src/core/or/policies.c */
int
metrics_policy_permits_address(const tor_addr_t *addr)
{
  return metrics_policy ? addr_policy_permits_tor_addr(addr, 1, metrics_policy)
                        : 0;
}
```

#### Commit 2: `buf, metrics: Make chunk allocation counter and label formatter thread-safe`
Uses Tor's C99 threading primitives (`src/lib/thread/threads.h`) so `buf_t` allocation and metric label formatting are race-free across the main thread and the `MetricsPort` worker thread:
1. **`src/lib/buf/buffers.c`**: Converts `static size_t total_bytes_allocated_in_chunks` to `static atomic_counter_t total_bytes_allocated_in_chunks;` (matching `src/lib/compress/compress.c`), preventing `tor_assert()` races in `buf_chunk_free_unchecked()` and `buf_get_total_allocation()`.
2. **`src/lib/metrics/metrics_common.c`**: Indexes a two-slot static buffer by `in_main_thread()` in `metrics_format_label()` so main-thread hidden service metric updates (`hs_metrics_update_by_service()`) cannot clobber worker-thread label formatting:
   ```c
   const char *
   metrics_format_label(const char *key, const char *value)
   {
     static char buf[2][128];
     char *b = buf[in_main_thread() ? 1 : 0];
     tor_snprintf(b, sizeof(buf[0]), "%s=\"%s\"", key, value);
     return b;
   }
   ```

#### Commit 3: `metrics: Service MetricsPort connections on a dedicated worker thread`
1. **Listener handoff in `src/core/mainloop/connection.c` (`+6` net lines)**:
   Skip `connection_start_reading()` for `CONN_TYPE_METRICS_LISTENER` so `libevent` never touches the listener fd on the main thread, and call `metrics_close_listener(conn)` before `tor_close_socket()` on `SIGHUP`/`SETCONF`/shutdown:
   ```c
   int is_stream = (type != CONN_TYPE_AP_DNS_LISTENER);
   if (is_stream && type != CONN_TYPE_METRICS_LISTENER)
     start_reading = 1;
   ...
   if (start_reading) {
     connection_start_reading(conn);
   } else if (type == CONN_TYPE_METRICS_LISTENER) {
     metrics_configure_listener(conn);
   } else {
     tor_assert(type == CONN_TYPE_AP_DNS_LISTENER);
     dnsserv_configure_listener(conn);
   }
   ```
2. **Dedicated worker loop in `src/feature/metrics/metrics.c` (`metrics_worker_threadfn`)**:
   Spawns a single worker thread via `spawn_func()` on first `MetricsPort` configuration that polls `the_listener_sock` and services one HTTP request at a time using stack-local `connection_t` + `buf_t` buffers:
   ```c
   /* Temporarily release the listener's slot in n_sockets_open under metrics_mutex
    * so MetricsPort can still accept 1 connection via ULIMIT_BUFFER (32 reserved fds)
    * when the main thread is pegged at max_sockets - 1, while still calling
    * tor_accept_socket_nonblocking() for Linux seccomp (sb_accept4) compatibility. */
   tor_release_socket_ownership(the_listener_sock);
   sock = tor_accept_socket_nonblocking(
       the_listener_sock, (struct sockaddr *)&sa, &salen);
   tor_take_socket_ownership(the_listener_sock);
   ```

---

### Open Design Question for Maintainers Before MR

Currently, the worker thread calls `metrics_get_output(the_format)` under `metrics_mutex`. While `metrics_store_entry_get_value()` counters are simple integer reads, some fill callbacks (e.g., `hs_metrics.c` iterating `hs_service_list`) read main-thread structures.

Would you prefer:
1. **Direct scrape on the worker thread** (minimal code: 3-commit series in [`1aeo/torutils` branch `metricsport-worker`](https://github.com/1aeo/torutils/tree/metricsport-worker/metricsport-worker)), or
2. **Double-buffered `buf_t` snapshot** (main thread refreshes a cached `buf_t` payload on a periodic timer when active, and the worker thread serves the latest snapshot with zero cross-thread subsystem reads)?

---

### Code References (`tor-0.4.9.14`)

- **Listener setup & close paths**:
  - [`src/core/mainloop/connection.c#L1488-L1784`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/mainloop/connection.c#L1488-L1784) (`connection_listener_new()`, `dnsserv_configure_listener()`)
  - [`src/core/mainloop/connection.c#L783-L948`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/mainloop/connection.c#L783-L948) (`connection_free_minimal()`)
  - [`src/core/mainloop/connection.c#L1055-L1089`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/mainloop/connection.c#L1055-L1089) (`connection_close_immediate()`)
- **MetricsPort HTTP processing & label formatting**:
  - [`src/feature/metrics/metrics.c#L71-L169`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/feature/metrics/metrics.c#L71-L169) (`metrics_get_output()`, `metrics_connection_process_inbuf()`)
  - [`src/lib/metrics/metrics_common.c#L38-L44`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/lib/metrics/metrics_common.c#L38-L44) (`metrics_format_label()`)
- **Policy check (`NULL` `metrics_policy` default-accept bug)**:
  - [`src/core/or/policies.c#L1072-L1075`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/or/policies.c#L1072-L1075) (`metrics_policy_permits_address()`)
  - [`src/core/or/policies.c#L1531-L1545`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/core/or/policies.c#L1531-L1545) (`compare_tor_addr_to_addr_policy()`)
- **Buffer chunk accounting, atomic counters & socket limits / sandbox**:
  - [`src/lib/buf/buffers.c#L126-L140`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/lib/buf/buffers.c#L126-L140) (`total_bytes_allocated_in_chunks`, `buf_chunk_free_unchecked()`)
  - [`src/lib/thread/threads.h#L100-L171`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/lib/thread/threads.h#L100-L171) (`atomic_counter_t`, `in_main_thread()`)
  - [`src/lib/net/socket.c#L377-L391`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/lib/net/socket.c#L377-L391) (`tor_accept_socket_with_extensions()` `max_sockets - 1` check)
  - [`src/lib/process/restrict.c#L163-L282`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/lib/process/restrict.c#L163-L282) (`ULIMIT_BUFFER` 32-fd reservation)
  - [`src/lib/sandbox/sandbox.c#L404-L424`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.14/src/lib/sandbox/sandbox.c#L404-L424) (`sb_accept4()` seccomp rule)

/label ~Feature ~"Sponsor 15"
