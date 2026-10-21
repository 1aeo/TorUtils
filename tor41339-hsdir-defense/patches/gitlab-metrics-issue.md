# Upstream GitLab Issue Draft: Directory and HSDir MetricsPort Visibility (`0006`–`0008`)

**Title:** `relay_metrics`: Export server directory and HSDir request, outcome, and connection state metrics on MetricsPort

## Summary

During `BEGIN_DIR` and onion service directory (`HSDir`) floods (see #41339), relays see large spikes in `tor_relay_streams_total{type="BEGIN_DIR"}` and main-thread CPU saturation while `tor_hs_rdv_stats` and outbound bandwidth remain flat. Existing `MetricsPort` counters cannot distinguish what `BEGIN_DIR` streams are requesting, whether responses complete locally or abort mid-stream, or how many internal `BEGIN_DIR` connections are accumulating in `connection_array`.

We propose exporting three small groups of `tor_relay_dos_total{type="..."}` metrics on the `MetricsPort`:

## 1. Directory & HSDir Request and Topology Counters (`0006`)
Currently, `tor_relay_streams_total{type="BEGIN_DIR"}` increments before HTTP parsing, and `tor_hs_rdv_stats` only counts completed descriptor fetches/uploads. Operators cannot tell whether `BEGIN_DIR` streams are anonymous HS requests, single-hop HS requests rejected with `503`, ordinary directory requests, or streams closing before sending valid HTTP headers, nor whether attackers reuse circuits across requests.

* `hsdir_request_total`: Total anonymous `/tor/hs/...` requests (GET + POST).
* `hsdir_req_reused`: Repeat anonymous `/tor/hs/...` requests on a circuit that already made one.
* `hsdir_circ_reused`: Circuits that made more than one anonymous `/tor/hs/...` request (counted once per circuit; also logged in the DoS heartbeat).
* `hsdir_single_hop`: Non-anonymous (single-hop) `/tor/hs/...` requests rejected with `503`.
* `hsdir_unknown_prev_hop`: Anonymous `/tor/hs/...` requests whose previous hop is not in the consensus/routerlist (also logged in the DoS heartbeat).
* `dir_non_hs_request`: Valid non-HS server directory requests (consensus, microdescriptors, server descriptors, keys).
* `dir_req_unparsed`: Server directory streams that failed HTTP parsing or closed in `DIR_CONN_STATE_SERVER_COMMAND_WAIT` before sending a complete request.

## 2. Directory & HSDir Outcome and Completion Counters (`0007`)
Currently, `hs_cache_lookup_as_dir()` and `connection_dir_finished_flushing()` do not expose whether requests hit or miss the cache, or whether queued responses finish flushing to the linked edge stream versus aborting mid-stream.

* `hsdir_get_found` / `hsdir_get_not_found`: Anonymous HSv3 descriptor GET cache hits (`200`) vs. cache misses (`404`).
* `hsdir_get_completed`: Anonymous HSv3 descriptor GET responses (`200`) that finished flushing from `dir_conn->outbuf` to the linked edge stream (`hsdir_get_found - hsdir_get_completed - hsdir_writing_conns` gives mid-stream aborts).
* `hsdir_post_ok` / `hsdir_post_rejected`: Anonymous HSv3 descriptor POST uploads accepted (`200`) vs. rejected (`400`).
* `dir_resp_completed`: Server directory HTTP responses (all classes) that finished flushing from `dir_conn->outbuf` (`dir_resp_completed - hsdir_get_completed` gives completed non-HS-descriptor responses).

## 3. Server Directory Connection State Gauges (`0008`)
Internal `BEGIN_DIR` linked connections (`CONN_TYPE_DIR` + `CONN_TYPE_EXIT`) have `s = TOR_INVALID_SOCKET (-1)` and never call `rep_hist_note_conn_opened()`, making them invisible to `tor_relay_connections` even when thousands accumulate in `connection_array` and `active_linked_connection_lst`.

* `dir_server_wait_conns`: Live server `dir_connection_t` objects in `DIR_CONN_STATE_SERVER_COMMAND_WAIT`.
* `dir_server_write_conns`: Live server `dir_connection_t` objects in `DIR_CONN_STATE_SERVER_WRITING`.
* `hsdir_writing_conns`: Subset of `dir_server_write_conns` serving an onion service descriptor (`hs_ident != NULL`).
* `dir_server_edge_conns`: Live linked `BEGIN_DIR` `CONN_TYPE_EXIT` streams (`conn->linked == 1`), where `dir_server_edge_conns - (dir_server_wait_conns + dir_server_write_conns)` measures edge streams still draining onto circuits after `dir_conn` has closed.
