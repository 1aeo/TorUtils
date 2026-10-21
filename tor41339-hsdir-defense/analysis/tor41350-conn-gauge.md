# `tor#41350` (`tor_relay_connections{state="opened"}` Drift) & HS Descriptor POST Outcome Accounting

Baseline source: C Tor `tor-0.4.9.14` (commit `8fe2745`, tag `tor-0.4.9.14`), cross-checked against upstream `main` (`8dbbbe6`). Across all files cited below (`src/core/mainloop/connection.c`, `src/core/or/status.c`, `src/core/or/connection_or.c`, `src/core/or/connection_edge.c`, `src/core/or/circuitlist.c`, `src/core/or/relay.c`, `src/feature/stats/rephist.c`, `src/feature/ext_orport/ext_orport.c`, `src/feature/dirclient/dirclient.c`, `src/feature/dircommon/directory.c`, `src/feature/dircache/dircache.c`, `src/feature/hs/hs_cache.c`, `src/feature/hs/hs_descriptor.c`, `src/feature/dns/dns.c`, `src/feature/dns/dnsserv.c`), line numbers in `tor-0.4.9.14` and `main` (`8dbbbe6`) are identical.

---

## Part A: `tor_relay_connections{state="opened"}` Gauge Drift (`tor#41350`)

### 1. Where the Gauge Moves

`fill_connections_values()` (`src/feature/relay/relay_metrics.c:411-452`) exports `tor_relay_connections{type=...,direction=...,state="opened",family=...}` by reading `rep_hist_get_conn_opened(from_listener, type, af)` (`src/feature/stats/rephist.c:1753-1771`).

#### Increments (`rep_hist_note_conn_opened()`, `src/feature/stats/rephist.c:1696-1715`)

There are only **three** call sites in the entire codebase:

1. **Listener creation:** `listener_connection_new()` at `src/core/mainloop/connection.c:654`:
   ```c
   rep_hist_note_conn_opened(false, type, socket_family);
   ```
2. **Inbound `accept()` completion:** `connection_handle_listener_read()` at `src/core/mainloop/connection.c:2111` calls `note_connection(true, newconn)` (`src/core/or/status.c:146-162`), which calls `rep_hist_note_conn_opened(inbound, conn->type, conn->socket_family)` at `status.c:151`.
   - This line is reached **only** after `connection_init_accepted_conn(newconn, listener->type)` (`connection.c:2105`) returns `>= 0`.
3. **Outbound OS socket `connect()`:** `connection_connect_sockaddr()` at `src/core/mainloop/connection.c:2317` calls `note_connection(false, conn)` (`status.c:151`), which calls `rep_hist_note_conn_opened(false, conn->type, conn->socket_family)` only after `tor_connect_socket()` (`connection.c:2284`) returns a valid socket descriptor `s >= 0`.

#### Decrement (`rep_hist_note_conn_closed()`, `src/feature/stats/rephist.c:1719-1740`)

There is a **single** call site, inside `connection_mark_for_close_internal_()` at `src/core/mainloop/connection.c:1180`:
```c
rep_hist_note_conn_closed(conn->from_listener, conn->type,
                          conn->socket_family);
```
This runs unconditionally for **every** `connection_t` marked for close, using whatever `(conn->from_listener, conn->type, conn->socket_family)` values the struct holds at close time. In `rephist.c:1727-1734`, the `uint64_t` counter is clamped at `0` (`if (*val > 0) (*val)--`), preventing unsigned underflow but masking extra decrements once a bucket hits `0`.

> **Pre-`connection_new()` rejections do not touch the gauge:** In `connection_handle_listener_read()`, `SocksPolicy` (`connection.c:2022-2031`), `DirPolicy` (`connection.c:2033-2042`), and `dos_conn_addr_get_defense_type()` (`connection.c:2043-2049`, which increments `tor_relay_connections{state="rejected"}` via `rep_hist_note_conn_rejected()` at `:2046`) all close `newsock` before `connection_new(new_type, socket_family)` is called at `connection.c:2059`. No `connection_t` exists, so `connection_mark_for_close_internal_()` never runs.

---

### 2. Complete Table of Unpaired Lifecycle Paths

| Path | Conn type (`type` label) | Direction (`from_listener` -> `direction` label) | Family (`socket_family` -> `family` label) | Rough frequency | Drift direction | Evidence (`tor-0.4.9.14` `8fe2745` & `main` `8dbbbe6`) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Path 1a:** Accepted `OR` conn fails `connection_init_accepted_conn()` (synchronous `SSL_accept()` error/EOF on `accept()`) | `CONN_TYPE_OR` (`"OR"`) | `from_listener=1` (`"received"`) | `AF_INET` (`"ipv4"`) or `AF_INET6` (`"ipv6"`) | **High** during port scans, client connection churn, or listen-backlog timeouts when main loop is busy | **Down** toward `0` (missing increment, unpaired decrement) | `connection.c:2079` sets `newconn->from_listener = 1`; `:2099` adds conn; `:2105` calls `connection_init_accepted_conn()` (`:2126-2185`), which at `:2139` calls `connection_tls_start_handshake(TO_OR_CONN(conn), 1)` (`connection_or.c:1706-1743`) -> `connection_tls_continue_handshake()` (`:1739`) -> `tor_tls_handshake()` (`:1758`). If client `FIN`/`RST` or non-TLS bytes are already buffered at `accept()` time, `tor_tls_handshake()` fails synchronously (`:1761`) and calls `connection_or_close_for_error()` -> `connection_mark_for_close()` (`connection_or.c:1687`) -> `connection.c:1180` decrement. `connection_init_accepted_conn()` returns `-1` (`connection.c:2106-2108`), returning before `note_connection()` at `connection.c:2111`. |
| **Path 1b:** Accepted transparent `AP` conn fails `connection_init_accepted_conn()` (`pf` / `netfilter` / `ipfw` destination lookup fails) | `CONN_TYPE_AP` (`"Socks"`) | `from_listener=1` (`"received"`) | `AF_INET` (`"ipv4"`) or `AF_INET6` (`"ipv6"`) | **Low–moderate** on relays/clients with `TransPort` when `ioctl`/`getsockopt` original-dst lookup fails | **Down** toward `0` (missing increment, unpaired decrement) | `connection.c:2105, 2166-2167` calls `connection_ap_process_transparent()` (`connection_edge.c:2899-2919`). When `connection_ap_get_original_destination()` fails (`:2914`), `:2916` calls `connection_mark_unattached_ap()` -> `connection_mark_for_close()` (`connection_edge.c:760`) -> `connection.c:1180` decrement, returning `-1` before `note_connection()` at `connection.c:2111`. *(Note: `connection_ext_or_start_auth()` at `ext_orport.c:643-660` unconditionally returns `0`—its cookie check is later in `handle_client_auth_nonce()` at `ext_orport.c:356` after `note_connection()`—and `CONN_TYPE_AP_NATD_LISTENER` at `connection.c:2168-2170` only sets state and returns `0`.)* |
| **Path 2a:** Server-side linked `EXIT` + `DIR` pair created for every incoming `BEGIN_DIR` cell | `CONN_TYPE_EXIT` (`"Exit"`) and `CONN_TYPE_DIR` (`"Directory"`) | `from_listener=0` (`"initiated"`) on both | `EXIT`: always `AF_INET` (`"ipv4"`); `DIR`: previous hop's family (`"ipv4"` or `"ipv6"`) | **Very high** on DirCaches/HSDirs (1 pair per `BEGIN_DIR`; thousands/sec during `tor#41339` floods, tens/min normal) | **Down** toward `0` on `Exit/initiated/ipv4` and `Directory/initiated/ipv4,ipv6` (missing increment on both halves, unpaired decrement on both) | `connection_exit_begin_conn()` creates `edge_connection_new(CONN_TYPE_EXIT, AF_INET)` (`connection_edge.c:4284`, hardcoded `AF_INET`, `from_listener=0`) and for `RELAY_COMMAND_BEGIN_DIR` calls `connection_exit_connect_dir()` (`connection_edge.c:4326-4333, 4689-4750`), which creates `dir_connection_new(tor_addr_family(&exitconn->base_.addr))` (`:4706`, `from_listener=0`) and links them via `connection_link_connections()` (`:4718`). Neither half has a socket (`s = TOR_INVALID_SOCKET`) or calls `note_connection()`. Closing the stream (`connection_edge.c:310, 1246`, `directory.c:577`) marks both for close (`connection.c:1180`), decrementing `(Exit, initiated, ipv4)` and `(Directory, initiated, ipv4/ipv6)`. |
| **Path 2b:** Client-side / relay self-fetch linked `AP` + `DIR` pair (`connection_ap_make_link()`) | `CONN_TYPE_AP` (`"Socks"`) and `CONN_TYPE_DIR` (`"Directory"`) | `from_listener=0` (`"initiated"`) on both | `AP`: `AF_INET` (`"ipv4"`); `DIR`: `AF_INET` (`"ipv4"`) or `AF_INET6` (`"ipv6"`) | **Moderate** on all relays and bridges (every consensus, microdescriptor, or authority cert self-fetch via `directory_initiate_request()`) | **Down** toward `0` on `Directory/initiated` and `Socks/initiated/ipv4` (missing increment on both halves, unpaired decrement on both) | `directory_send_command()` (`dirclient.c:1327, 1380-1435`) creates `dir_connection_new(socket_family)` and for tunneled requests calls `connection_ap_make_link()` (`connection_edge.c:3642-3701`), which allocates `entry_connection_new(CONN_TYPE_AP, AF_INET)` (`:3651`, `from_listener=0`) and links them (`:3666`). Neither calls `note_connection()`. Both call `connection_mark_for_close()` on completion (`connection.c:1180`). Because `Socks/initiated` is never incremented, it stays clamped at `0`; `Directory/initiated` pulls any real outbound DirPort socket gauge down. |
| **Path 3:** Extended ORPort `EXT_OR` -> `OR` connection retyping after `USERADDR`/`TRANSPORT`/`DONE` | Opened as `CONN_TYPE_EXT_OR` (`"Extended OR"`); closed as `CONN_TYPE_OR` (`"OR"`) | `from_listener=1` (`"received"`) | `AF_INET` (`"ipv4"`) or `AF_INET6` (`"ipv6"`) | **High on PT bridges** (every obfs4/conjure/snowflake client connection accepted on `ExtORPort`) | `Extended OR/received` drifts **up** without bound; `OR/received` drifts **down** toward `0` (type mutation between open and close) | Accepted on `CONN_TYPE_EXT_OR_LISTENER` (`connection.c:1994-1996`), so `note_connection(true, newconn)` (`connection.c:2111`) increments `(Extended OR, received, af)`. After ExtOR authentication and `DONE`, `connection_ext_or_transition()` (`ext_orport.c:83-102`) executes `conn->base_.type = CONN_TYPE_OR;` at `ext_orport.c:91` without updating rephist. When the connection later closes, `connection.c:1180` decrements `(OR, received, af)`. |
| **Path 4:** Outbound direct `DIR` connection fails `connection_connect()` | `CONN_TYPE_DIR` (`"Directory"`) | `from_listener=0` (`"initiated"`) | `AF_INET` (`"ipv4"`) or `AF_INET6` (`"ipv6"`) | **Low** (only when a direct non-tunneled `DirPort` connect fails immediately in `tor_connect_socket()`, e.g. `EADDRNOTAVAIL`/`ENETUNREACH`) | **Down** toward `0` (missing increment, unpaired decrement) | `directory_send_command()` (`dirclient.c:1327, 1353-1368`) allocates `dir_connection_new(socket_family)` and calls `connection_connect()` (`:1353`). If `connection_connect_sockaddr()` fails before `note_connection(false, conn)` (`connection.c:2317`), `dirclient.c:1367` calls `connection_mark_for_close(TO_CONN(conn))`, decrementing `(Directory, initiated, af)`. *(Contrast with `connection_or_connect()` at `connection_or.c:1375`, which correctly calls `connection_free_minimal()` instead of `connection_mark_for_close()`.)* |
| **Path 5:** Unconnected `EXIT` stream in `resolving_streams` (or failed DNS) closed before `connection_exit_connect()` | `CONN_TYPE_EXIT` (`"Exit"`) | `from_listener=0` (`"initiated"`) | Always `AF_INET` (`"ipv4"`), even for IPv6 targets | **Moderate–high** on Exit relays (every stream that fails DNS resolution, receives `RELAY_COMMAND_END` while resolving, or is on a circuit torn down during DNS resolution) | **Down** toward `0` on `Exit/initiated/ipv4` (missing increment, unpaired decrement) | `connection_exit_begin_conn()` (`connection_edge.c:4284`) allocates `edge_connection_new(CONN_TYPE_EXIT, AF_INET)` (`from_listener=0`, `socket_family=AF_INET`) and places it on `on_circuit->resolving_streams` via `dns_resolve()` (`connection_edge.c:4401`). No OS socket is opened (`note_connection()` only runs inside `connection_exit_connect()` -> `connection_connect()` at `connection_edge.c:4611`). If DNS fails (`dns.c:673-678`), the circuit closes (`circuit_about_to_free()` at `circuitlist.c:2431`), the client sends `END` (`relay.c:1429`), or a deliver-window violation occurs (`relay.c:1729, 2117`), `connection_mark_for_close()` decrements `(Exit, initiated, ipv4)`. *(Note: `n_stream->socket_family` is only updated to `AF_INET6` inside `connection_exit_connect()` at `connection_edge.c:4610`, so even IPv6 streams decrement `ipv4` here; similarly, exit-policy rejections at `connection_edge.c:4562, 4590` run before `:4610` and record IPv6 exit policy rejections under `ipv4`.)* |
| **Path 6:** `DNSPort` requests and controller `RESOLVE` commands (`dnsserv.c`) | `CONN_TYPE_AP` (`"Socks"`) | `from_listener=0` (`"initiated"`) | `AF_INET` (`"ipv4"`) | **Moderate** on instances running `DNSPort` or controller `RESOLVE` | **Down** toward `0` on `Socks/initiated/ipv4` (clamped at `0` in practice because `Socks/initiated` is never incremented) | `evdns_server_callback()` (`dnsserv.c:148`) and `dnsserv_launch_request()` (`dnsserv.c:228`) create a dummy socketless `entry_connection_new(CONN_TYPE_AP, AF_INET)` (`from_listener=0`) without calling `note_connection()`, and close it with `connection_mark_for_close()` (`dnsserv.c:167, 250, 294`). |
| **Path 7:** Counted connection freed directly via `connection_free_minimal()` without `connection_mark_for_close()` on error paths | ` Listener`, `OR`, `Exit`, `Directory` | `from_listener=0` (`"initiated"`) | `AF_INET`, `AF_INET6`, `AF_UNIX` | **Rare** (requires `connection_add()` failure at fd cap or `connected_cell_format_payload()` failure) | **Up** (incremented, missing decrement) | Three error branches call `rep_hist_note_conn_opened()` and then free the connection without `connection_mark_for_close()`: (7a) `connection_listener_new()` (`connection.c:654`, then `connection_add()` fails at `:1742, 1768, 1799` -> `connection_free_minimal()`); (7b) `connection_connect_sockaddr()` (`note_connection()` at `connection.c:2317`, then `connection_add_connecting()` fails at `:2324-2328` -> `goto err` -> `tor_close_socket()`); (7c) `connection_exit_connect()` (`connection_connect()` counts at `connection_edge.c:4611`, then `connected_cell_format_payload()` fails at `:4628, 4666-4670` -> `connection_free()`). |

---

### 3. Resolving the Open Question: Why Operators Saw `OR/received` Far Below Real OR Sockets

In `analysis/flood-cost-and-constrained-hosts.md:108-110`, a relay under the `tor#41339` `BEGIN_DIR` flood reported:
- `tor_relay_connections{type="OR",direction="received",state="opened"} = 598` during the flood, and **`33` after the flood**;
- while the relay actually held **~4,800 open OR TCP sockets** (verified via `ss` and host fd tables).

Paths 2 and 3 do not explain this on a standard relay (`Path 2` hits `Exit/initiated` and `Directory/initiated`, and `Path 3` only occurs when `ExtORPort` is configured). **Path 1a (`connection_init_accepted_conn()` failing synchronous `SSL_accept()` at `accept()` time) directly explains the `OR/received` collapse**, reinforced by one secondary family-accounting detail:

1. **Primary mechanism (Path 1a under main-loop stall or scanner/client churn):**
   - When `connection_handle_listener_read()` accepts a socket on `ORPort` (`CONN_TYPE_OR_LISTENER`), it sets `newconn->from_listener = 1` (`connection.c:2079`), registers the socket in the mainloop (`connection_add()`, `:2099`), and calls `connection_init_accepted_conn(newconn, listener->type)` (`connection.c:2105`).
   - For `CONN_TYPE_OR`, `connection_init_accepted_conn()` (`connection.c:2139`) immediately invokes `connection_tls_start_handshake(TO_OR_CONN(conn), 1)` (`connection_or.c:1706-1743`), which calls `connection_tls_continue_handshake(conn)` (`connection_or.c:1739`) -> `tor_tls_handshake(conn->tls)` (`connection_or.c:1758`).
   - On a fresh connection where the client has not yet delivered packets, `SSL_accept()` returns `SSL_ERROR_WANT_READ` (`TOR_TLS_WANTREAD`), so `connection_tls_continue_handshake()` returns `0`, `connection_init_accepted_conn()` returns `0`, and `note_connection(true, newconn)` at `connection.c:2111` increments `OR/received`.
   - **However**, when the relay's main thread is busy processing a flood (or when TCP port scanners / impatient clients connect and disconnect quickly), the kernel completes the TCP 3-way handshake in the listen backlog and buffers either the client's `FIN`/`RST` or non-TLS bytes *before* Tor calls `accept()`.
   - When `accept()` finally runs and `connection_tls_start_handshake()` calls `tor_tls_handshake()`, `SSL_accept()` immediately reads those buffered bytes/EOF and returns `TOR_TLS_CLOSE` or `TOR_TLS_ERROR_*` **synchronously inside `connection_init_accepted_conn()`**.
   - `connection_tls_continue_handshake()` (`connection_or.c:1761-1765`) immediately calls `connection_or_close_for_error(conn, 0)` -> `connection_mark_for_close(TO_CONN(conn))` (`connection_or.c:1687`) -> `connection_mark_for_close_internal_()` (`connection.c:1180`), which **decrements `OR/received`** (`from_listener=1, type=CONN_TYPE_OR`).
   - `connection_init_accepted_conn()` then returns `-1` to `connection_handle_listener_read()` (`connection.c:2105-2108`), which returns early **without calling `note_connection(true, newconn)` at `connection.c:2111`**.
   - Every such aborted inbound connection subtracts `1` from the `OR/received` gauge while the ~4,800 established relay-to-relay OR sockets remain open. Then, when the flood ends and several hundred idle OR connections close normally, their legitimate decrements subtract further from the already-understated gauge, leaving it at `33` (and `0` shortly thereafter) while thousands of OR sockets remain `ESTAB`.

2. **Secondary comparison pitfall (`direction` and `family` labels vs. `ss`):**
   - `tor_relay_connections` splits connections across four time series per type: `direction="received"|"initiated"` × `family="ipv4"|"ipv6"`, whereas `ss -s` or an unfiltered `ss -tnp` counts all OR sockets together (`received + initiated`, `ipv4 + ipv6`).
   - On dual-stack Linux hosts where `ORPort` uses a dual-stack socket (`IPV6_V6ONLY=0`), `ss` displays IPv4-mapped peers (`::ffff:a.b.c.d`) under the `tcp6` (`AF_INET6`) listener, whereas `tor_accept_socket_nonblocking()` inspects the peer address and `connection_handle_listener_read()` sets `socket_family = tor_addr_family(&addr)` (`connection.c:2058`), recording IPv4 peers under `family="ipv4"`. Even summing all four `{type="OR", direction=*, family=*}` series on the affected relay, however, could not recover the ~4,800 sockets once Path 1a drained `OR/received/ipv4` to `33`.

---

### 4. Private Loopback Lab Reproduction & Transcript Summary

#### Lab Environment
- **Isolation:** `docker run --rm --network none` (loopback `127.0.0.1` only; no external interfaces or routes).
- **Topology:** 4-node Chutney network (`3` private DirAuths/relays `test000a`–`test002a` + `1` target Exit/HSDir relay `test003r` with `ORPort 127.0.0.1:9003`, `DirPort 127.0.0.1:9033`, `ControlPort 127.0.0.1:8003`, `MetricsPort 127.0.0.1:9103`, `ExitRelay 1`, `ExitPolicy accept 127.0.0.1:*`).
- **Per-path temporary instrumentation:** In the stock binary, `rep_hist_note_conn_opened()` and `rep_hist_note_conn_closed()` were instrumented to track `in_rephist_opened` as a shadow check only (preserving stock `tor-0.4.9.14` gauge behavior) and classify every unpaired close into `path1a_or_accept_init_fail`, `path1b_ap_trans_accept_init_fail`, `path2a_begindir_linked_exit`, `path2a_begindir_linked_dir`, `path2b_client_linked_ap_or_dir`, `path3_ext_or_retyped_close`, `path4_unconnected_dir_close`, `path5_unconnected_exit_close`, and `path6_unconnected_ap_close`, recording both `(effective)` decrements (`gauge > 0`) and `(clamped)` decrements (`gauge == 0`).

#### Summary of Lab Results (`Stock 0.4.9.14` vs. `Patched 0.4.9.14`)

| Condition | Metric / Ground Truth | Stock `0.4.9.14` (Instrumented) | Patched `0.4.9.14` (`0001` Applied) |
| :--- | :--- | :--- | :--- |
| **Condition 1: Idle** (after bootstrap) | `OR/received/ipv4` gauge | `7` | `8` |
| | `OR/initiated/ipv4` gauge | `4` | `3` |
| | `GETINFO orconn-status` | `11` CONNECTED (`7` inbound, `4` outbound) | `11` CONNECTED (`8` inbound, `3` outbound) |
| | `ss -tnp` (`OR_inbound` / `OR_outbound`) | `7` / `4` | `8` / `3` |
| | Unpaired decrements so far | `path2a_begindir_linked_dir=3`, `path2a_begindir_linked_exit=3`, `path2b_client_linked_dir=2`, `path2b_client_linked_ap=2` (all clamped at `0`) | `0` |
| **Condition 2A: 4 normal OR TLS handshakes + close** | `OR/received/ipv4` gauge after close | `7` (`== ss -tnp`) | `8` (`== ss -tnp`) |
| | `path1a_or_accept_init_fail` | `0` | `0` |
| **Condition 2B: 10 handshake-incomplete connections** (5 non-TLS + 5 immediate EOF buffered at `accept()`) | `OR/received/ipv4` gauge | **`0` (drifted from `7` -> `0`)** | **`8` (unchanged, `== ss -tnp`)** |
| | `GETINFO orconn-status` | `11` CONNECTED (`7` inbound, `4` outbound) | `11` CONNECTED (`8` inbound, `3` outbound) |
| | `ss -tnp` (`OR_inbound_ESTAB`) | **`7`** (7 real sockets missing from gauge) | **`8`** (exact match) |
| | `path1a_or_accept_init_fail` | **`10`** (`7` effective + `3` clamped) | `0` |
| **Condition 3A: Open 5 real outbound Exit streams** | `Exit/initiated/ipv4` gauge | `5` | `5` |
| | `ss -tnp` (`Exit_outbound_ESTAB`) | `5` | `5` |
| **Condition 3B: Send 25 `BEGIN_DIR` streams** over an OR circuit | `Exit/initiated/ipv4` gauge | **`0` (drifted from `5` -> `0`)** | **`5` (unchanged, `== ss -tnp`)** |
| | `ss -tnp` (`Exit_outbound_ESTAB`) | **`5`** (5 real Exit sockets missing from gauge) | **`5`** (exact match) |
| | `path2a_begindir_linked_exit` (cumulative) | **`28`** (`5` effective + `23` clamped) | `0` |
| | `path2a_begindir_linked_dir` (cumulative) | **`28`** (`0` effective + `28` clamped) | `0` |
| **Condition 3C: Close the 5 real outbound Exit streams** | `Exit/initiated/ipv4` gauge | `0` (`5` legitimate closes hit the `0` clamp!) | `0` (`5` legitimate closes decrement `5 -> 0`) |
| | `ss -tnp` (`Exit_outbound_ESTAB`) | `0` | `0` |

#### Verbatim Excerpts from the Lab Transcript

Stock `tor-0.4.9.14` (`Condition 2B`, `Condition 3B`, and `Condition 3C`):
```text
======================================================================
SNAPSHOT: CONDITION 2B — AFTER 10 HANDSHAKE-INCOMPLETE CONNECTIONS (Path 1a -> OR/received drifts to 0!)
======================================================================
[2] Kernel sockets via `ss -tnp` for relay 003r:
  Summary: OR_inbound_ESTAB=7, OR_outbound_ESTAB=4 (total OR ESTAB=11), Exit_outbound_ESTAB=0, Dir_inbound=0, Dir_outbound=0

[3] MetricsPort `tor_relay_connections` (AF_INET) vs Ground Truth:
  Type             Direction   created  opened(gauge)  ground_truth  paired_close(eff/clamp)
  OR listener      initiated         1              1             1                      0/0
  OR               received         14              0             7                      7/0
  OR               initiated         4              4             4                      0/0
  Directory        initiated        43              0             0                     43/0
  Exit             initiated         0              0             0                      0/0

[4] Per-path Unpaired Decrement Attribution (from instrumentation):
  path=path2a_begindir_linked_dir     type=Directory  direction=initiated  family=ipv4     total=   3 (effective_drift=  0, clamped_at_0=   3)
  path=path2b_client_linked_dir       type=Directory  direction=initiated  family=ipv4     total=   2 (effective_drift=  0, clamped_at_0=   2)
  path=path2a_begindir_linked_exit    type=Exit       direction=initiated  family=ipv4     total=   3 (effective_drift=  0, clamped_at_0=   3)
  path=path1a_or_accept_init_fail     type=OR         direction=received   family=ipv4     total=  10 (effective_drift=  7, clamped_at_0=   3)
  path=path2b_client_linked_ap        type=Socks      direction=initiated  family=ipv4     total=   2 (effective_drift=  0, clamped_at_0=   2)

[6] `CONN_AUDIT` notice.log entries (total logged=20, showing last 6):
  CONN_AUDIT unpaired_decrement path=path1a_or_accept_init_fail type=OR direction=received family=AF_INET linked=0 purpose=0 gauge_before=3 gauge_after=2 mark_site=src/core/or/connection_or.c:1687
  CONN_AUDIT unpaired_decrement path=path1a_or_accept_init_fail type=OR direction=received family=AF_INET linked=0 purpose=0 gauge_before=2 gauge_after=1 mark_site=src/core/or/connection_or.c:1687
  CONN_AUDIT unpaired_decrement path=path1a_or_accept_init_fail type=OR direction=received family=AF_INET linked=0 purpose=0 gauge_before=1 gauge_after=0 mark_site=src/core/or/connection_or.c:1687
  CONN_AUDIT unpaired_decrement path=path1a_or_accept_init_fail type=OR direction=received family=AF_INET linked=0 purpose=0 gauge_before=0 gauge_after=0 mark_site=src/core/or/connection_or.c:1687

======================================================================
SNAPSHOT: CONDITION 3B — AFTER 25 BEGIN_DIR STREAMS (Path 2a -> Exit/initiated drifts from 5 to 0 while 5 Exit sockets remain ESTAB!)
======================================================================
[2] Kernel sockets via `ss -tnp` for relay 003r:
  Summary: OR_inbound_ESTAB=7, OR_outbound_ESTAB=4 (total OR ESTAB=11), Exit_outbound_ESTAB=5, Dir_inbound=0, Dir_outbound=0

[3] MetricsPort `tor_relay_connections` (AF_INET) vs Ground Truth:
  Type             Direction   created  opened(gauge)  ground_truth  paired_close(eff/clamp)
  OR               received         14              0             7                      7/0
  OR               initiated         4              4             4                      0/0
  Directory        initiated        47              0             0                     47/0
  Exit             initiated         5              0             5                      0/0

[4] Per-path Unpaired Decrement Attribution (from instrumentation):
  path=path2a_begindir_linked_dir     type=Directory  direction=initiated  family=ipv4     total=  28 (effective_drift=  0, clamped_at_0=  28)
  path=path2b_client_linked_dir       type=Directory  direction=initiated  family=ipv4     total=   2 (effective_drift=  0, clamped_at_0=   2)
  path=path2a_begindir_linked_exit    type=Exit       direction=initiated  family=ipv4     total=  28 (effective_drift=  5, clamped_at_0=  23)
  path=path1a_or_accept_init_fail     type=OR         direction=received   family=ipv4     total=  10 (effective_drift=  7, clamped_at_0=   3)
  path=path2b_client_linked_ap        type=Socks      direction=initiated  family=ipv4     total=   2 (effective_drift=  0, clamped_at_0=   2)

======================================================================
SNAPSHOT: CONDITION 3C — AFTER CLOSING THE 5 REAL EXIT SOCKETS (paired closes hit the 0 clamp!)
======================================================================
  Type             Direction   created  opened(gauge)  ground_truth  paired_close(eff/clamp)
  Exit             initiated         5              0             0                      0/5
```

Patched `tor-0.4.9.14` (`0001` applied, `Condition 2B`, `Condition 3B`, and `Condition 3C`):
```text
======================================================================
SNAPSHOT: CONDITION 2B — AFTER 10 HANDSHAKE-INCOMPLETE CONNECTIONS
======================================================================
[2] Kernel sockets via `ss -tnp` for relay 003r:
  Summary: OR_inbound_ESTAB=8, OR_outbound_ESTAB=3 (total OR ESTAB=11), Exit_outbound_ESTAB=0, Dir_inbound=0, Dir_outbound=0

[3] MetricsPort `tor_relay_connections` (AF_INET):
  Type             Direction   created  opened(gauge)
  OR listener      initiated         1              1
  OR               received         15              8
  OR               initiated         3              3
[4] Per-path Unpaired Decrement Attribution:
  (none)

======================================================================
SNAPSHOT: CONDITION 3B — AFTER 25 BEGIN_DIR STREAMS
======================================================================
[2] Kernel sockets via `ss -tnp` for relay 003r:
  Summary: OR_inbound_ESTAB=8, OR_outbound_ESTAB=3 (total OR ESTAB=11), Exit_outbound_ESTAB=5, Dir_inbound=0, Dir_outbound=0

[3] MetricsPort `tor_relay_connections` (AF_INET):
  Type             Direction   created  opened(gauge)
  OR               received         15              8
  OR               initiated         3              3
  Exit             initiated         5              5
[4] Per-path Unpaired Decrement Attribution:
  (none)

======================================================================
SNAPSHOT: CONDITION 3C — AFTER CLOSING THE 5 REAL EXIT SOCKETS
======================================================================
[2] Kernel sockets via `ss -tnp` for relay 003r:
  Summary: OR_inbound_ESTAB=8, OR_outbound_ESTAB=3 (total OR ESTAB=11), Exit_outbound_ESTAB=0, Dir_inbound=0, Dir_outbound=0

[3] MetricsPort `tor_relay_connections` (AF_INET):
  Type             Direction   created  opened(gauge)
  Exit             initiated         5              0
```

---

### 5. Fix Rationale & Comparison Against Alternatives

#### Implemented Fix (`0001-rephist-Pair-opened-connection-gauge-decrements-with.patch`)

We add four fields to `struct connection_t` (`src/core/mainloop/connection_st.h`):
- `unsigned int in_rephist_opened:1;`
- `unsigned int rephist_from_listener:1;`
- `unsigned int rephist_type:5;`
- `int rephist_socket_family;`

And two helper functions in `src/core/mainloop/connection.c`:
1. `connection_note_opened_in_rephist(connection_t *conn, bool from_listener)`:
   - Called at the three open-accounting sites (`listener_connection_new()` at `connection.c:654`, `connection_handle_listener_read()` at `connection.c:2111` via `note_connection()`, and `connection_connect_sockaddr()` at `connection.c:2317` via `note_connection()`).
   - Guards against double-counting (`if (BUG(conn->in_rephist_opened)) return;`), snapshots `(from_listener, conn->type, conn->socket_family)` on `conn`, sets `conn->in_rephist_opened = 1`, and calls `rep_hist_note_conn_opened()`.
2. `connection_note_closed_in_rephist(connection_t *conn)`:
   - Called from `connection_mark_for_close_internal_()` (`connection.c:1203`) **and** as a safety net from `connection_free_minimal()` (`connection.c:723`).
   - Does nothing unless `conn->in_rephist_opened` is set; when set, clears `conn->in_rephist_opened = 0` and calls `rep_hist_note_conn_closed(conn->rephist_from_listener, conn->rephist_type, conn->rephist_socket_family)`.

This single invariant guarantees a strict 1-to-1 bijection between increments and decrements across **all** paths (Paths 1a, 1b, 2a, 2b, 3, 4, 5, 6, and 7).

#### Comparison Against Alternatives

| Approach | Path 1a/1b (init fail at accept) | Path 2a/2b (linked conns) | Path 3 (`EXT_OR` -> `OR` retype) | Path 4/5/6 (unconnected `DIR`/`EXIT`/`AP`) | Path 7 (counted conn freed without mark) | Assessment |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. `in_rephist_opened` bit + stored `(from_listener, type, family)` (Selected)** | **Fixed** | **Fixed** | **Fixed** | **Fixed** | **Fixed** (via `connection_free_minimal()` safety net) | Enforces the exact accounting invariant at the data-structure level; immune to future connection types or retyping. |
| **2. Skip `if (!conn->linked)` in `connection_mark_for_close_internal_()`** | Broken | Fixed | Broken | Broken (`resolving_streams` `EXIT` conns, failed direct `DIR` connects, and `dnsserv` `AP` conns have `linked == 0`) | Broken | Fixes only `BEGIN_DIR` / tunneled dir pairs; leaves `OR/received` drift (Path 1a) and unconnected `EXIT` DNS failures (Path 5) completely unfixed. |
| **3. Count in `connection_add()` instead of `note_connection()`** | Partially broken (`connection_add_nonlinked()` at `connection.c:2099` runs *before* `connection_init_accepted_conn()`, which works for open/close pairing, **but** counts rejected/failed TLS handshakes in `total` created connections `status.c:150` or splits `opened` from `created`) | Requires `if (SOCKET_OK(conn->s))` guard (`connection_add_linked()` also goes through `connection_add_impl()`) | Still broken unless original `type` is stored on `conn` | Fixed if guarded by `SOCKET_OK(conn->s)` | Still broken if `connection_add()` itself fails after `listener_connection_new()` | Couples rephist socket metrics to mainloop event registration rather than `note_connection()`, and still requires per-connection state to handle `EXT_OR` -> `OR` retyping. |

*(Optional follow-up on Path 3: storing `rephist_type` ensures an `ExtORPort` connection increments and decrements `Extended OR/received`. If operators instead want a connection to move from the `Extended OR` gauge to the `OR` gauge at the moment `connection_ext_or_transition()` retypes it at `ext_orport.c:91`, a 4-line helper can decrement `Extended OR`, update `conn->rephist_type = CONN_TYPE_OR`, and increment `OR`.)*

#### Should Linked Connections Get Their Own Series?

- **`tor_relay_connections` should remain strictly OS-socket-backed.** Every other label in `tor_relay_connections` (`Listener`, `OR`, `Control`, `Metrics`, etc.) represents a kernel socket consuming an fd. Mixing socketless in-process `linked` streams into `tor_relay_connections` would conflate TCP sockets with circuit-level streams and make `type="Exit",direction="initiated"` unusable for monitoring outbound socket pressure on relays that are both Exit and HSDir/DirCache.
- **A separate gauge for server-side linked directory streams is well-motivated.** As proposed in our HSDir defense metrics draft, exporting a dedicated gauge for active server-side directory streams (or splitting by `DIR_CONN_STATE_SERVER_COMMAND_WAIT` vs. `DIR_CONN_STATE_SERVER_WRITING`) gives operators direct visibility into queued in-memory directory streams during a `BEGIN_DIR` flood without polluting socket gauges.

---

## Part B: HS Descriptor POST Outcomes (`tor_relay_hsdir_post_total`)

### 1. Complete Outcome Table (Stock `0.4.9.14` and With `patches/0001`–`0007` Applied)

All paths below trace an incoming stream or connection targeting an HSDir upload (`POST /tor/hs/3/publish`) from `BEGIN_DIR` arrival (`connection_exit_begin_conn()`, `connection_edge.c:4326`) through `connection_dir_process_inbuf()` (`directory.c:2243`), `directory_handle_command()` (`directory.c:2168`), `directory_handle_command_post()` (`dircache.c:1586-1635`), `handle_post_hs_descriptor()` (`dircache.c:1545-1579`), `hs_cache_store_as_dir()` (`hs_cache.c:295-336`), `hs_desc_decode_descriptor()` (`hs_descriptor.c:2678-2726`), and `cache_store_v3_as_dir()` (`hs_cache.c:192-265`).

| Stage / Patch | HTTP Status | Reason Phrase | `function:line` (`tor-0.4.9.14` & `main`) | Condition | Can a Legitimate Service Hit This? (Stock C Tor / Arti / Onionbalance) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Pre-HTTP / Stream (`Stock`)** | None (stream closed before HTTP parse) | — | `connection_dir_process_inbuf()` (`directory.c:2261-2269`) -> `fetch_from_buf_http()` (`proto_http.c:142-254`) | Client closes stream (`END` / circuit tear-down) before sending `\r\n\r\n` or full `Content-Length`, headers exceed `MAX_HEADERS_SIZE` (`24576`), body exceeds `MAX_DIR_UL_SIZE` (`20971520` in stock), or `Content-Length` is unparseable (`proto_http.c:196-226`). | **Rarely (network transient only):** Only if an upload circuit dies mid-stream before the HTTP request finishes arriving. |
| **Pre-HTTP / Stream (`Patch 0004`)** | None (stream closed in `proto_http.c`) | — | `connection_dir_process_inbuf()` (`directory.c:2264`) + `fetch_from_buf_http()` (`proto_http.c:218`) + `dir_max_upload_body_size()` (`directory.c:2227`) | `Content-Length` or buffered body exceeds `MIN(HSV3MaxDescriptorSize, 16 MB)` (default `50 KB`). | **No** (unless an operator configures a non-standard `HSV3MaxDescriptorSize` above the HSDir's limit). |
| **Pre-HTTP / Stream (`Patch 0003`)** | None (stream closed) | — | `fetch_from_buf_http()` (`proto_http.c:199, 211, 224`) | Same as stock malformed HTTP, with `LOG_WARN` rate-limited / downgraded so floods cannot spam logs. | **No.** |
| **Pre-HTTP / Stream (`Patch 0005`)** | Status already queued (`200`/`400`/`503`) | — | `connection_dir_process_inbuf()` (`directory.c:2257-2260`) | Trailing bytes sent after `DIR_CONN_STATE_SERVER_COMMAND_WAIT` exited are drained via `buf_clear(conn->base_.inbuf)`. | **No.** |
| **Command Dispatch (`Stock`)** | `503` | `"Directory unavailable"` | `directory_handle_command_post()` (`dircache.c:1591-1594`) | `!public_server_mode(get_options())` (checked *before* `parse_http_url()`). | **Yes (transient consensus race):** If a relay was recently listed in a consensus and subsequently toggled `BridgeRelay` / non-public mode before its descriptor aged out. |
| **Command Dispatch (`Stock`)** | `400` | `"Bad request"` | `directory_handle_command_post()` (`dircache.c:1599-1603`) -> `parse_http_url()` (`directory.c:1804-1845`) | First line does not match `HTTP/1.x`, URL is missing or doesn't start with `/`, or exceeds `MAX_DIR_URL_LEN`. | **No.** |
| **Command Dispatch (`Stock`)** | `503` | `"Service unavailable"` | `directory_handle_command_post()` (`dircache.c:1609-1613`) -> `connection_dir_is_anonymous()` (`directory.c:235-265`) | URL starts with `/tor/hs/` on a non-`linked` connection (direct `DirPort`), or circuit has `on_circuit->purpose != CIRCUIT_PURPOSE_OR` (i.e. single-hop `CIRCUIT_PURPOSE_C_GENERAL` or missing `p_chan`). | **No** for standard services. *(Only a deliberate `HiddenServiceSingleHopMode 1` + `HiddenServiceNonAnonymousMode 1` test instance would send single-hop.)* |
| **Command Dispatch (`Patch 0001`)** | `503` | `"Service unavailable"` | `directory_handle_command_post()` (`dircache.c:1614` w/ `0001`) -> `hsdir_reject_if_unknown_prev_hop()` (`dircache.c:1244-1269`) | When `DoSHSDirRefuseUnknownPrevHop 1` (or `auto` with consensus param `1`): previous hop `p_chan->identity_digest` is not in the live consensus routerlist (`nodelist_Get_node_by_id() == NULL`). | **Yes (transient consensus skew):** A legitimate service whose middle relay just dropped out of the latest consensus (or joined a newer consensus the HSDir hasn't fetched yet) can hit this on a single circuit and will retry over a new circuit. |
| **Command Dispatch (`Patch 0002`)** | None (circuit closed with `END_CIRC_REASON_TORPROTOCOL`) | — | `directory_handle_command_post()` (`dircache.c:1618` w/ `0002`) -> `hsdir_reject_if_circ_already_used()` (`dircache.c:1273-1305`) | `or_circ->hsdir_req_seen` is already `1` and `DoSHSDirOneReqPerCircuit` is enforcing. | **No:** Stock C Tor, Arti (`tor-hsservice`), and Onionbalance always build a fresh 4-hop `HS_SERVICE_HSDIR` circuit per descriptor upload/fetch and never reuse a single HSDir circuit for two `/tor/hs/` requests. |
| **Command Dispatch (`Stock`)** | `400` | `"Invalid/unrecognizedalv post request"` (`"Invalid/unrecognized post request"` at `dircache.c:1632`) | `directory_handle_command_post()` (`dircache.c:1625-1632`) | URL does not start with `/tor/hs/` and is not `/tor/post/vote` or `/tor/post/consensus-signature` on an authority. | **No.** |
| **HS POST URL (`Stock`)** | `400` | `"Invalid hs descriptor"` | `handle_post_hs_descriptor()` (`dircache.c:1556-1565`) -> `parse_hs_version_from_post()` (`dircache.c:1519-1540`) | URL after `/tor/hs/` does not parse as integer version `3` (`HS_VERSION_THREE`) with exact subpath `"/publish"` (e.g., `/tor/hs/2/publish`, `/tor/hs/bad/publish`, `/tor/hs/3/other`). | **No** for v3 services (only obsolete v2 clients/services attempting `/tor/hs/2/publish`). |
| **HS Cache Decode (`Stock`)** | `400` | `"Invalid hs descriptor"` | `handle_post_hs_descriptor()` (`dircache.c:1570-1575`) -> `hs_cache_store_as_dir()` (`hs_cache.c:302-312`) -> `hs_desc_decode_descriptor()` (`hs_descriptor.c:2678-2726`) -> `hs_desc_decode_plaintext()` (`hs_descriptor.c:2249-2437`) | Fails any plaintext validation check:<br>1. `strlen(encoded) >= hs_cache_get_max_descriptor_size()` (`HSV3MaxDescriptorSize`, default `51200`, `hs_descriptor.c:2261-2271`);<br>2. Tokenization or `"hs-descriptor 3"` header fails (`:2279-2315`);<br>3. `descriptor-lifetime` missing, `< 30` min, or `> 720` min (`:2318-2342`);<br>4. `descriptor-signing-key-cert` missing, unparseable, wrong `cert_type` (`!= ED25519_V_SIGNING`), wrong `key_type`, **expired or not-yet-valid** vs. `approx_time()`, or bad cert signature (`cert_parse_and_validate()`, `hs_descriptor.c:2079-2142`, `:2345-2356`);<br>5. `revision-counter` missing or non-integer (`:2359-2369`);<br>6. `superencrypted` blob missing or fails base64 / length (`:2371-2399`);<br>7. `signature` token missing, wrong length (`Patch 0006` checks `strlen(sig_b64) != ED25519_SIG_BASE64_LEN` *before* `cert_parse_and_validate()` at `hs_descriptor.c:2345`), or `ed25519_checksig_prefixed()` fails (`:2402-2429`). | **Yes (clock skew only):** If a legitimate service host (C Tor, Arti, or Onionbalance) or the HSDir itself has significant clock skew (`cert->exp_field * 3600 < approx_time()` in `tor_cert_checksig()`), step 4 rejects the signing cert (`HS_DESC_DECODE_PLAINTEXT_ERROR`). Otherwise **No**. |
| **HS Cache Decode (`Stock`)** | `400` | `"Invalid hs descriptor"` | `hs_cache_store_as_dir()` (`hs_cache.c:305`) -> `hs_desc_decode_descriptor()` (`hs_descriptor.c:2704`) -> `hs_desc_decode_superencrypted()` (`hs_descriptor.c:2182-2236`) | Superencrypted layer fails message header, MAC, or length check (`HS_DESC_DECODE_SUPERENC_ERROR`). | **No.** |
| **HS Cache Revision Check (`Stock`)** | `400` | `"Invalid hs descriptor"` | `handle_post_hs_descriptor()` (`dircache.c:1570-1575`) -> `hs_cache_store_as_dir()` (`hs_cache.c:320`) -> `cache_store_v3_as_dir()` (`hs_cache.c:222-233`) | Descriptor is **cryptographically valid**, but an entry for the same `blinded_pubkey` already exists in `hs_cache_v3_dir` with `cache_entry->desc->plaintext_data.revision_counter >= desc->plaintext_data.revision_counter`. Logs `LOG_INFO`: `"Descriptor revision counter in our cache is %llu. Which is >= to the one we just received (%llu). Rejecting!"` and returns `0` (`handle_post_hs_descriptor` returns `200` only if `hs_cache_store_as_dir(body) > 0` at `dircache.c:1570`). | **YES — Frequently hit by legitimate services:**<br>• **Onionbalance:** Multiple Onionbalance frontend instances (or a frontend retrying/reloading state whose OPE/timestamp-derived revision counter matches or trails another frontend's recent upload) routinely publish descriptors with `revision_counter <= cached` to overlapping HSDirs.<br>• **Active-active / failover C Tor or Arti instances:** Two instances sharing an identity key without shared state (or after a VM snapshot/container restart with a slightly older clock/OPE counter) produce `revision_counter <= cached`.<br>• **Stock C Tor / Arti:** Within a single uninterrupted process, C Tor enforces `service->state.obfuscated_last_revision_counter + 1` (`hs_service.c:1726`) and Arti enforces monotonic revision counters, so a single instance normally increments on rebuild; however, process restarts within the same OPE cipher step or duplicate instances hit `<=`. |
| **HS Cache Store (`Stock`)** | `200` | `"Service descriptor (v3) stored"` | `handle_post_hs_descriptor()` (`dircache.c:1570-1571`) -> `directory_handle_command_post()` (`dircache.c:1620-1622`) | `hs_cache_store_as_dir(body) > 0` (new `blinded_pubkey` or strictly higher `revision_counter`). | **Yes** (normal descriptor publish). |

---

### 2. Metric Proposal, Hook Points, and Reconciliation Identity Check

#### Why `400` Must Be Split by Reason

In stock `0.4.9.14`, `handle_post_hs_descriptor()` (`src/feature/dircache/dircache.c:1570`) treats both `hs_cache_store_as_dir(body) < 0` (corrupt/forged descriptor) and `hs_cache_store_as_dir(body) == 0` (cryptographically valid descriptor whose `revision_counter` is `<=` the cached one) identically, returning `400 "Invalid hs descriptor"`.
However, `hs_cache_store_as_dir()` (`src/feature/hs/hs_cache.c:295-336`) **already returns a tri-state `int`**:
- `1`: stored (`200 OK`);
- `0`: valid descriptor rejected solely by the `revision_counter <= cached` check in `cache_store_v3_as_dir()` (`hs_cache.c:222-233`);
- `-1`: failed decoding, size, cert, or signature validation (`hs_cache.c:305`).

#### Proposed Metric & Labels (`0002-relay_metrics-Export-HS-descriptor-POST-outcome-coun.patch`)

We add `tor_relay_hsdir_post_total` (`RELAY_METRICS_NUM_HSDIR_POST`) to `src/feature/relay/relay_metrics.c`:
```prometheus
# HELP tor_relay_hsdir_post_total Total number of HS descriptor POST requests by HTTP status and reason
# TYPE tor_relay_hsdir_post_total counter
tor_relay_hsdir_post_total{status="200",reason="ok"} ...
tor_relay_hsdir_post_total{status="400",reason="rev_counter"} ...
tor_relay_hsdir_post_total{status="400",reason="bad_url"} ...
tor_relay_hsdir_post_total{status="400",reason="invalid_desc"} ...
```

Exact hook points:
1. `handle_post_hs_descriptor()` (`src/feature/dircache/dircache.c:1556-1565`): when `parse_hs_version_from_post()` fails or `version != HS_VERSION_THREE`, call `rep_hist_note_hsdir_post(HSDIR_POST_REJECTED_BAD_URL)`.
2. `hs_cache_store_as_dir()` (`src/feature/hs/hs_cache.c:305-333`):
   - `hs_desc_decode_descriptor() < 0` (`hs_cache.c:305`): call `rep_hist_note_hsdir_post(HSDIR_POST_REJECTED_INVALID_DESC)`.
   - `cache_store_v3_as_dir() == 0` (`hs_cache.c:320`): call `rep_hist_note_hsdir_post(HSDIR_POST_REJECTED_REV_COUNTER)`.
   - Stored (`hs_cache.c:331`): call `rep_hist_note_hsdir_post(HSDIR_POST_OK)`.

#### Verification Against the Reconciliation Identity

Our metrics draft proposes the reconciliation identity:
$$\text{BEGIN\_DIR streams} \approx \text{unparsed} + \text{non\_hs} + \text{hs} + \text{single\_hop\_rejected} + \text{command\_wait}$$

Auditing `tor-0.4.9.14` (and `patches/0001`–`0007`) against every path a `BEGIN_DIR` stream can take reveals **four exact boundary details** that must be accounted for so the identity closes without a gap:

1. **`single_hop_rejected` is NOT counted by `tor_relay_dos_total{type="single_hop_refused"}` in stock `0.4.9.14`:**
   - `dos_note_refuse_single_hop_client()` (`src/core/or/dos.c:273`) is called **only** in `rend_mid_establish_intro_legacy()` at `src/feature/rend/rendmid.c:53`.
   - It is **never** called in `connection_dir_is_anonymous()` (`src/feature/dircommon/directory.c:235-265`) or in `dircache.c:1319-1323` (`GET /tor/hs/`) or `dircache.c:1609-1613` (`POST /tor/hs/`).
   - Therefore, for `/tor/hs/` requests rejected by `!connection_dir_is_anonymous(conn)` (`503 "Service unavailable"` at `dircache.c:1319, 1609`), either `dircache.c:1319, 1609` must explicitly increment `single_hop_rejected`, or those `503` responses will be missing from the right-hand side.
2. **Pre-URL `503` (`!public_server_mode`) and `400` (`parse_http_url() < 0`) in `directory_handle_command_get()` / `directory_handle_command_post()`:**
   - At `dircache.c:1591-1603` (and `dircache.c:1278-1282` for `GET`), `!public_server_mode()` (`503`) and `parse_http_url() < 0` (`400`) return **before** the URL prefix `/tor/hs/` is inspected.
   - To keep the identity exact, `parse_http_url() < 0` (`dircache.c:1278, 1599`) should be counted in `unparsed` (alongside streams closed in `DIR_CONN_STATE_SERVER_COMMAND_WAIT` before a full HTTP request is parsed, including `Patch 0004` oversized body rejections), and `!public_server_mode` (`dircache.c:1591`) in `non_hs` (or `unparsed`).
3. **With `patches/0001` and `0002` applied:**
   - `Patch 0001` (`hsdir_reject_if_unknown_prev_hop()` at `dircache.c:1324, 1614`) increments `tor_relay_dos_total{type="hsdir_unknown_prev_hop"}` (`dos_note_hsdir_unknown_prev_hop()`).
   - `Patch 0002` (`hsdir_reject_if_circ_already_used()` at `dircache.c:1328, 1618`) increments `tor_relay_dos_total{type="hsdir_circ_reuse"}` (`dos_note_hsdir_circ_reuse()`). Note that in `0002`, the first request on the circuit already transitioned its `dir_connection_t` out of `COMMAND_WAIT`, and the second request arrives on a **second** `BEGIN_DIR` stream on the same circuit, which is closed before `handle_get_hs_descriptor_v3()` or `handle_post_hs_descriptor()` runs.
   - Thus with `0001`–`0007` applied, the exact partition of `BEGIN_DIR` streams is:
     $$\text{BEGIN\_DIR streams} = \underbrace{\text{command\_wait}}_{\text{active in-flight}} + \underbrace{\text{unparsed}}_{\text{EOF/oversize/bad HTTP line}} + \underbrace{\text{non\_hs}}_{\text{non-/tor/hs/ GET+POST}} + \underbrace{\text{single\_hop\_rejected}}_{\text{dircache.c:1319,1609}} + \underbrace{\text{hsdir\_unknown\_prev\_hop}}_{\text{Patch 0001}} + \underbrace{\text{hsdir\_circ\_reuse}}_{\text{Patch 0002}} + \underbrace{\text{hs\_get} + \text{hs\_post}}_{\text{200 + 400 + 404}}$$
     where $\text{hs\_post} = \sum \text{tor\_relay\_hsdir\_post\_total}\{\text{status},\text{reason}\}$.

---

## Draft GitLab Comment for `tor#41350`

```markdown
Hi! We audited the `rep_hist_note_conn_opened()` / `rep_hist_note_conn_closed()` call sites in `tor-0.4.9.14` (`8fe2745`, unchanged on `main` `8dbbbe6`) and reproduced the drift in a private Chutney network.

### Root Cause: Unpaired Closes and Type Mutation

`connection_mark_for_close_internal_()` (`src/core/mainloop/connection.c:1180`) unconditionally calls:
```c
rep_hist_note_conn_closed(conn->from_listener, conn->type, conn->socket_family);
```
for every `connection_t`, whereas `rep_hist_note_conn_opened()` is only called in three places:
1. `listener_connection_new()` (`connection.c:654`);
2. `connection_handle_listener_read()` -> `note_connection(true, newconn)` (`connection.c:2111`), which only runs after `connection_init_accepted_conn()` (`:2105`) succeeds;
3. `connection_connect_sockaddr()` -> `note_connection(false, conn)` (`connection.c:2317`), when an outbound OS socket connects.

Because `rep_hist_note_conn_closed()` clamps each bucket at `0` (`src/feature/stats/rephist.c:1727-1734`), any lifecycle path that closes without calling `note_connection()`—or changes `conn->type` between open and close—drains the gauge toward `0`:

1. **Accepted `OR` / transparent `AP` connections that fail `connection_init_accepted_conn()` (`connection.c:2105-2108`) -> pulls `OR/received` and `Socks/received` down:**
   - For `CONN_TYPE_OR`, `connection_init_accepted_conn()` (`connection.c:2139`) calls `connection_tls_start_handshake()` -> `connection_tls_continue_handshake()` -> `tor_tls_handshake()` (`src/core/or/connection_or.c:1739, 1758`), which performs an immediate `SSL_accept()`.
   - When a peer's `FIN`/`RST` or non-TLS bytes are already in the kernel socket buffer at `accept()` time (common during scanner traffic or when clients time out in the listen backlog while the main loop is busy), `tor_tls_handshake()` fails synchronously (`connection_or.c:1761`) and calls `connection_or_close_for_error()` -> `connection_mark_for_close()`. `connection_init_accepted_conn()` returns `-1` before `note_connection()` (`connection.c:2111`), decrementing `(OR, received, ipv4/ipv6)` without a matching increment.
   - Similarly, `connection_ap_process_transparent()` (`connection.c:2167`, `src/core/or/connection_edge.c:2914-2916`) marks the connection for close if original-destination lookup fails before `note_connection()`.
   - *(Note: `SocksPolicy`, `DirPolicy`, and `dos_conn_addr_get_defense_type()` rejections at `connection.c:2022-2049` close `newsock` before `connection_new()` at `:2059`, so they do not decrement the gauge.)*
2. **In-process `linked` connection pairs (no OS socket, never call `note_connection()`) -> pulls `Exit/initiated` and `Directory/initiated` down:**
   - Every incoming `BEGIN_DIR` cell creates an `EXIT` connection (`edge_connection_new(CONN_TYPE_EXIT, AF_INET)` at `connection_edge.c:4284`, `from_listener=0`) linked to a `DIR` connection (`connection_exit_connect_dir()` at `connection_edge.c:4706`, `from_listener=0`). Neither calls `note_connection()`, but closing them decrements `(Exit, initiated, ipv4)` and `(Directory, initiated, ipv4/ipv6)`. On relays that are both Exit and DirCache/HSDir, `BEGIN_DIR` traffic rapidly pulls `Exit/initiated/ipv4` to `0`.
   - Client/relay self-fetches via `connection_ap_make_link()` (`connection_edge.c:3651`, `src/feature/dirclient/dirclient.c:1388`) similarly create and close socketless `AP` + `DIR` pairs with `from_listener=0`.
3. **Unconnected `EXIT`, `DIR`, and `AP` connections marked for close before `connection_connect()`:**
   - `EXIT` streams in `resolving_streams` that fail DNS (`src/feature/dns/dns.c:678`), receive `END` (`src/core/or/relay.c:1429`), or belong to a circuit closed during DNS resolution (`src/core/or/circuitlist.c:2431`) call `connection_mark_for_close()` without ever calling `connection_exit_connect()`, pulling `(Exit, initiated, ipv4)` down.
   - Direct outbound `DIR` connections whose `connection_connect()` fails (`dirclient.c:1367`) and socketless `DNSPort` / controller `RESOLVE` `AP` connections (`src/feature/dns/dnsserv.c:148, 228`) also call `connection_mark_for_close()` without `note_connection()`.
4. **`EXT_OR` -> `OR` retyping on bridges (`src/feature/ext_orport/ext_orport.c:91`):**
   - `ExtORPort` connections are counted at `accept()` as `(Extended OR, received, af)`, then retyped via `conn->base_.type = CONN_TYPE_OR` in `connection_ext_or_transition()`. Closing them decrements `(OR, received, af)`, so `Extended OR/received` drifts up without bound while `OR/received` drifts down toward `0`.
5. **Rare leak paths (counted open, freed via `connection_free_minimal()` without `connection_mark_for_close()`):**
   - `connection_listener_new()` (`connection.c:1742, 1768, 1799`), `connection_connect_sockaddr()` (`connection.c:2324-2328`), and `connection_exit_connect()` (`connection_edge.c:4666-4670`) if adding/formatting fails after `rep_hist_note_conn_opened()`.

### Lab Reproduction

In a 4-node Chutney network (`test003r` with `7` inbound OR connections and `5` active outbound Exit connections):
- Sending 10 handshake-incomplete connections to `ORPort` (non-TLS bytes or immediate EOF buffered at `accept()`) triggered 10 `connection_init_accepted_conn()` failures (`7` effective decrements + `3` clamped), pulling `tor_relay_connections{type="OR",direction="received",state="opened",family="ipv4"}` from `7` to `0` while `GETINFO orconn-status` and `ss -tnp` still showed `7` established inbound OR sockets.
- Sending 25 `BEGIN_DIR` streams over an established circuit triggered 25 unpaired `Exit/initiated` decrements (`5` effective + `20` clamped), pulling `tor_relay_connections{type="Exit",direction="initiated",state="opened",family="ipv4"}` from `5` to `0` while all `5` outbound Exit TCP sockets remained `ESTAB`.

### Proposed Fix

Record on `connection_t` whether `rep_hist_note_conn_opened()` counted the connection (`in_rephist_opened`) along with the counted `(rephist_from_listener, rephist_type, rephist_socket_family)` tuple, and call `rep_hist_note_conn_closed()` in `connection_mark_for_close_internal_()` (and `connection_free_minimal()` as a safety net) only when `in_rephist_opened` is set, using the stored tuple and clearing the bit.

We have a patch with unit tests (`stats/rephist_conn_opened`) covering failed `connection_init_accepted_conn()`, linked `EXIT`+`DIR` closes, `EXT_OR`->`OR` retyping, normal accept/close, and listener close/free. Happy to open an MR if this approach looks good!
```

---

## Review Summary: Verification Status & Open Questions

All code references and line numbers above were verified directly against `tor-0.4.9.14` (`8fe2745`) and `main` (`8dbbbe6`), and all Part A and Part B patches were built and tested (`make check`, `make check-spaces`, `make check-changes`, `practracker`). Only the following points involve design choices or external assumptions:

1. **Behavior of `EXT_OR` -> `OR` retyping (`ext_orport.c:91`):**
   - With `0001-rephist-Pair-opened-connection-gauge-decrements-with.patch`, an `ExtORPort` connection is opened as `Extended OR` and decremented from `Extended OR` when it closes, eliminating drift in both `Extended OR` and `OR`.
   - *Design choice for upstream review:* If maintainers prefer post-handshake `ExtORPort` connections to be reflected in the `OR` gauge while open, `connection_ext_or_transition()` (`ext_orport.c:91`) can call a helper that decrements `Extended OR`, updates `conn->rephist_type = CONN_TYPE_OR`, and increments `OR`.
2. **Pre-existing family mismatch on IPv6 Exit policy rejections (`connection_edge.c:4562, 4590` vs. `:4610`):**
   - While auditing `connection_exit_connect()` (`src/core/or/connection_edge.c:4552-4615`), we verified that `conn->socket_family = tor_addr_family(&conn->base_.addr)` is assigned at line `4610`, **after** the two exit-policy rejection checks at lines `4562` and `4590` call `rep_hist_note_conn_rejected(conn->type, conn->socket_family)`. Because `edge_connection_new(CONN_TYPE_EXIT, AF_INET)` (`connection_edge.c:4284`) initializes `socket_family = AF_INET`, IPv6 exit-policy rejections are currently counted under `family="ipv4"` in `tor_relay_connections{state="rejected"}`. We left `state="rejected"` untouched in `0001` to keep the `tor#41350` patch minimal, but noted it here in case a separate one-line move of `conn->socket_family = tor_addr_family(&conn->base_.addr)` to the top of `connection_exit_connect()` is desired.
3. **Arti and Onionbalance `revision_counter` behavior:**
   - Verified from C Tor's `hs_service.c:1673-1735` and the Tor specification (`rend-spec-v3.txt` §2.2.1.1 / Onionbalance v3 design) that multiple active frontends or restarted instances without shared state produce overlapping OPE-derived revision counters. We did not run live Onionbalance or Arti binaries in the lab, as `hs_cache/hsdir_post_outcomes` tests the HSDir cache directly with constructed v3 descriptors.
