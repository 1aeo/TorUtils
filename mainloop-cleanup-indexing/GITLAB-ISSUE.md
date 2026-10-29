### Summary

`Tor 0.4.9.15` resolved the two $O(N)$ global connection-list cleanup scans (`b035c0f582`, *"mainloop: Index global connection lists and membership checks"*) that accounted for **`90.47%` of sampled main-thread userspace CPU** (`1,775 / 1,962` samples) during `5,585.4 BEGIN_DIR/s` floods on `Tor 0.4.9.14`, and also added `BEGIN_DIR` DoS rate limiting plus a one-HSDir-request-per-circuit limit (`4c0ce0febb`, `7d9b3b11ef`).

However, stock `Tor 0.4.9.15` still lacks `MetricsPort` observability to:
1. Verify post-`0.4.9.15` mainloop connection-list occupancies (`connection_array`, `closeable_connection_lst`, `active_linked_connection_lst`), `close_closeable_connections()` work/backlog/wall-time, and Libevent main-loop tick stalls in production without attaching `perf`.
2. Distinguish ordinary directory traffic (`consensus`, `microdesc`, `server_desc`, `extra_info`, `authority_certs`) from hidden-service v3 directory requests (`hs_v3_fetch`, `hs_v3_publish`), aborted/churned `BEGIN_DIR` streams (`aborted_pre_http`, `aborted_mid_http`, `aborted_writing`), per-circuit `BEGIN_DIR` stream reuse (`reused_circuit`), and server-side directory application bytes (`read` vs `written`) independently of whole-process OR traffic.

We propose a single minimized commit on `tor-0.4.9.15` (`4d8efff53a`) — available in [`1aeo/torutils` branch `mainloop-cleanup-indexing`](https://github.com/1aeo/torutils/tree/mainloop-cleanup-indexing/mainloop-cleanup-indexing) (`patches/0001-relay-metrics-mainloop-and-directory-observability.patch`, `+541` net production C/H lines across 12 files + `changes/mainloop_and_dir_metrics` + unit tests):
- Adds 9 fixed-cardinality Prometheus metric families (`112` time series total, zero high-cardinality labels, zero hot-path scans, $O(1)$ counter/gauge updates).
- Includes `--disable-module-relay` stubs in `src/feature/relay/relay_stub.c`, passes `checkSpace.pl`, `lintChanges.py`, `includes.py`, and `practracker.py` with zero new warnings, and passes all `1,612 / 1,612` unit tests.

---

### Motivation & Production `perf` Context (`Tor 0.4.9.14` $\to$ `Tor 0.4.9.15`)

On `Tor 0.4.9.14` relays experiencing `RELAY_BEGIN_DIR` floods, hardware `perf` captures across four host-paired event/control relays revealed two distinct CPU regimes:

| Relay / Role (`Tor 0.4.9.14`, Build ID `8b225673...`) | `BEGIN_DIR` Rate | Outbound Traffic | Main-Thread CPU | `connection_stop_reading_from_linked_conn` (`smartlist_remove`) | `connection_free_` (`!connection_in_array` / `smartlist_contains`) | Combined Cleanup Scan Share (Userspace Main-Thread) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **`sarkodie`** (Flooded, low output, `38.65s` capture) | **`5,585.4 / s`** | `45.84 Mbit/s` | **`99.86%`** | **`50.58%`** (`992 / 1,962`) | **`39.89%`** (`783 / 1,962`) | **`90.47%`** (`1,775 / 1,962`) |
| **`goodiemob`** (Co-hosted control, `34.18s` capture) | `7.1 / s` | `390.61 Mbit/s` | `67.14%` | `0.10%` (`1 / 1,004`) | `0.00%` (`0 / 1,004`) | **`0.10%`** (`1 / 1,004`) |
| **`antglizzy`** (Flooded + high output, `35.24s` capture) | `1,303.7 / s` | `317.85 Mbit/s` | `99.78%` | `9.69%` (`152 / 1,568`) | `4.91%` (`77 / 1,568`) | **`14.60%`** (`229 / 1,568`) |
| **`joji`** (Ending flood + high output, `31.11s` capture) | `742.6 / s` $\to$ `2.8 / s` | `369.92 Mbit/s` | `97.92%` | `10.17%` (`166 / 1,632`) | `4.17%` (`68 / 1,632`) | **`14.34%`** (`234 / 1,632`) |

While `tor-0.4.9.15` commit `b035c0f582` eliminates the $O(N)$ global list scans in `sarkodie`'s teardown bottleneck and `4c0ce0febb` rejects multiple HSDir requests on a single circuit (`tor_relay_dos_total{type="begindir_hsdir_rejected"}`), three operational visibility gaps remain on `tor-0.4.9.15`:
1. **Mainloop list occupancy, cleanup wall-time, and tick-stall visibility**: Without `MetricsPort` counters for list lengths, `close_closeable_connections()` duration/deferrals, and `run_main_loop_once()` tick stalls (`>10 ms`, `>100 ms`, `>1000 ms`), operators cannot distinguish residual cleanup backlog from compression/crypto/cell-packaging saturation (`antglizzy`/`joji` high-output regime).
2. **`BEGIN_DIR` stream churn vs. full HTTP request/response completion**: `tor_relay_dos_total` counts rejected cells/requests, but cannot distinguish streams that open `BEGIN_DIR` and abort before sending HTTP headers (`aborted_pre_http`), abort mid-header or upon early refusal (`aborted_mid_http`), abort mid-response (`aborted_writing`), or complete cleanly (`completed`).
3. **Ordinary vs. HSDir HTTP request class and application byte attribution**: Whole-process OR bandwidth counters mix relay forwarding traffic with directory responses, and `BEGIN_DIR` cell counts do not reveal whether unthrottled directory load targets `consensus`, `microdesc`, `server_desc`, `extra_info`, `authority_certs`, `hs_v3_fetch`, `hs_v3_publish`, or malformed URLs/verbs (`invalid`).

---

### Proposed Patch (`tor-0.4.9.15`): `relay_metrics: Add mainloop cleanup, tick stall, and BEGIN_DIR metrics`

The patch adds 9 fixed-cardinality metrics (`112` series total, no per-circuit/per-IP/per-onion identifiers, zero new `#include`s in `core/mainloop/*` or `core/or/*`, $O(1)$ hot-path updates):

| Metric Name | Type | Labels (Cardinality) | Purpose |
| :--- | :---: | :--- | :--- |
| `tor_relay_mainloop_connection_list_size` | Gauge | `list` (`connection_array`, `closeable`, `active_linked`) (3) | Exposes runtime global connection-list occupancies ($N_{\text{conn}}, N_{\text{closeable}}, N_{\text{active}}$) |
| `tor_relay_mainloop_connection_list_ops_total` | Counter | `list` (`closeable`, `active_linked`), `op="add"` (2) | Measures connection closure queueing and active-linked read wakeup rates |
| `tor_relay_mainloop_close_pass_total` | Counter | `field` (`runs`, `visited`, `closed`, `deferred`, `duration_usec`) (5) | Quantifies `close_closeable_connections()` work, `hold_open_until_flushed` deferrals, and cumulative wall time |
| `tor_relay_mainloop_ticks_total` | Counter | `threshold` (`over_10ms`, `over_100ms`, `over_1000ms`) (3) | Counts `run_main_loop_once()` event-loop stalls exceeding `10 ms`, `100 ms`, and `1 s` |
| `tor_relay_mainloop_tick_max_duration_usec` | Gauge | none (1) | High-water-mark single event-loop tick duration in microseconds |
| `tor_relay_dir_streams_total` | Counter | `phase` (`opened`, `writing`, `completed`, `aborted_pre_http`, `aborted_mid_http`, `aborted_writing`, `reused_circuit`) (7) | Tracks server-side `BEGIN_DIR` stream lifecycle conservation (`opened == completed + aborted_* + active`) and circuit stream reuse |
| `tor_relay_dir_streams_active` | Gauge | `state` (`opened_wait`, `writing`) (2) | Current server-side `BEGIN_DIR` streams waiting for HTTP headers vs. flushing responses |
| `tor_relay_dir_http_requests_total` | Counter | `class` (10) $\times$ `status` (`200`, `304`, `400`, `404`, `503`, `other`, `rejected_early`) (70) | Classifies directory requests across `consensus`, `microdesc`, `server_desc`, `extra_info`, `authority_certs`, `hs_v3_fetch`, `hs_v3_publish`, `other_valid`, `invalid`, `unclassified` |
| `tor_relay_dir_bytes_total` | Counter | `class` (10) $\times$ `dir` (`read`, `written`) (20) | Separates server-side directory application bytes by request class and direction from whole-process OR traffic |

#### Key Edge Cases & `tor-0.4.9.15` Integration Details
- **Closing-circuit suppression (`7d9b3b11ef`)**: Queued requests on circuits already marked for close exit early via `dir_conn_is_closing(conn)` in `directory_handle_command()` before parsing, emitting zero spurious `tor_relay_dir_http_requests_total` counts while still attributing unconsumed `inbuf` bytes on teardown.
- **Per-circuit HSDir limit (`4c0ce0febb`) & silent refusals**: Second HSDir requests rejected by `hsdir_request_allowed_on_circuit()` (as well as silent non-HTTP refusals in `handle_get_descriptor()` on bridges and `handle_get_networkstatus_bridges()` on non-bridge authorities) explicitly record `status="rejected_early"` under their classified endpoint.
- **Exact $O(1)$ wire read-byte attribution**: `directory_handle_command()` records `inbuf_before - buf_datalen(inbuf)` *after* `directory_handle_command_get()` / `directory_handle_command_post()` classifies `dir_req_class`, avoiding `strlen()` scans and attributing request header/body bytes to the matched endpoint class.
- **Dying-peer flush protection**: When `conn_close_if_marked()` drains `dir_conn->outbuf` into `conn->linked_conn->inbuf`, bytes are counted as `written` (and `connection_dir_about_to_close()` transitions `WRITING -> COMPLETED`) only when the linked edge connection is open and not `marked_for_close` (or `SOCKET_OK(conn->s)` for unlinked `DirPort` connections) and `!dir_conn->spool`.

---

### Code References (`tor-0.4.9.15`, `4d8efff53a`)

- [`src/core/mainloop/mainloop.c#L463-L468`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.15/src/core/mainloop/mainloop.c#L463-L468), [`#L878-L885`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.15/src/core/mainloop/mainloop.c#L878-L885), [`#L911-L925`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.15/src/core/mainloop/mainloop.c#L911-L925), [`#L1081-L1088`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.15/src/core/mainloop/mainloop.c#L1081-L1088), [`#L2543-L2552`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.15/src/core/mainloop/mainloop.c#L2543-L2552) (`add_connection_to_closeable_list()`, `connection_start_reading_from_linked_conn()`, `close_closeable_connections()`, `conn_close_if_marked()`, `run_main_loop_once()`)
- [`src/core/mainloop/connection.c#L3662-L3669`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.15/src/core/mainloop/connection.c#L3662-L3669) (`record_num_bytes_transferred_impl()`)
- [`src/core/or/connection_edge.c#L4761-L4768`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.15/src/core/or/connection_edge.c#L4761-L4768) (`connection_exit_connect_dir()`)
- [`src/feature/dircache/dircache.c#L348-L390`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.15/src/feature/dircache/dircache.c#L348-L390), [`#L1412-L1433`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.15/src/feature/dircache/dircache.c#L1412-L1433), [`#L1670-L1734`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.15/src/feature/dircache/dircache.c#L1670-L1734), [`#L1836-L1880`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.15/src/feature/dircache/dircache.c#L1836-L1880) (`url_table[]`, `hsdir_request_allowed_on_circuit()`, `directory_handle_command_post()`, `directory_handle_command()`)
- [`src/feature/dircommon/directory.c#L518-L585`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.15/src/feature/dircommon/directory.c#L518-L585) (`connection_dir_about_to_close()`, `connection_dir_finished_flushing()`)
- [`src/feature/relay/relay_metrics.c`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.15/src/feature/relay/relay_metrics.c) & [`src/feature/relay/relay_stub.c`](https://gitlab.torproject.org/tpo/core/tor/-/blob/tor-0.4.9.15/src/feature/relay/relay_stub.c)

/label ~Performance ~"Denial of Service" ~Metrics
