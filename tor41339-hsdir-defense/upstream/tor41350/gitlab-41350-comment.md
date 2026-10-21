<!-- Ready-to-paste comment for https://gitlab.torproject.org/tpo/core/tor/-/work_items/41350
     Line numbers are tor-0.4.9.14 (8fe2745); the cited code is identical on main and maint-0.4.9. -->

Following up on the report quoted above: I went through every `rep_hist_note_conn_opened()` / `rep_hist_note_conn_closed()` site in 0.4.9.14 (the code is the same on `main` and `maint-0.4.9`) and reproduced the drift offline.

### Root cause

The gauge is incremented in three places: `listener_connection_new()` (`src/core/mainloop/connection.c:654`), and `note_connection()` (`src/core/or/status.c:151`) once an accepted connection has passed `connection_init_accepted_conn()` (`connection.c:2111`) or an outbound `connect()` has returned 0 or EINPROGRESS (`connection.c:2317`). But it is decremented for **every** connection marked for close (`connection.c:1180`), and the decrement is clamped at 0 (`src/feature/stats/rephist.c:1727`). So each close of a connection that was never counted silently cancels out a real one:

1. **Accepted OR connections whose TLS handshake fails right away** (`OR/received`). `connection_init_accepted_conn()` starts the handshake immediately (`connection.c:2139`). If the peer had already sent a FIN, an RST, or a few bytes of non-TLS data before we called `accept()`, the first `SSL_accept()` fails, `connection_or_close_for_error()` marks the connection (`connection.c:2141`), and `connection_handle_listener_read()` returns before `note_connection()` (`connection.c:2105-2111`). TCP-connect probes do this, and so do clients that give up while waiting in the accept queue of a busy relay (we accept one connection per listener read event, `connection.c:1954`). TransPort connections rejected synchronously in `connection_ap_process_transparent()` do the same to `Socks/received`. On a relay without an ExtORPort, this is the only code path that can push `OR/received` below the real count.
2. **Connections without a socket** (`Exit/initiated`, `Directory/initiated`). These are never counted, but they are marked for close: the linked EXIT and DIR connections created for every `BEGIN_DIR` (`src/core/or/connection_edge.c:4284`, `:4701`, `:4714`), the linked AP and DIR connections of tunneled directory requests (`connection_ap_make_link()`, `connection_edge.c:3629`), exit streams (and RESOLVE dummies) marked while still resolving (`src/core/or/circuitlist.c:2431`, `src/core/or/relay.c:1429`), and DNSPort requests (`src/feature/client/dnsserv.c:148`, `:228`). On an exit that is also a directory cache, `BEGIN_DIR` traffic alone keeps `Exit/initiated` at 0.
3. **Direct directory connections whose `connect()` fails right away** (`src/feature/dirclient/dirclient.c:1364-1367`).
4. **Extended ORPort connections** (bridges). They are counted as `Extended OR` when accepted, retyped to OR at `src/feature/relay/ext_orport.c:91`, then uncounted as `OR`, so `Extended OR` only grows and `OR` drains.

The other direction (a counted connection freed without being marked) can't happen today: `connection_add_impl()` never fails.

### Reproduction

Offline, in a loopback-only network namespace with a single relay: 7 real inbound TLS connections, then the relay is stopped (`SIGSTOP`) while 10 short connections that send `GET / HTTP/1.0` or only a FIN queue up in the accept backlog, then resumed.

| | `OR/received` opened, before → after | established ORPort sockets after |
|-|-|-|
| 0.4.9.14 | 7 → **0** | 7 |
| with the fix below | 7 → 7 | 7 |

In an earlier Chutney run, 25 `BEGIN_DIR` streams to an exit that is also a directory cache, with 5 exit sockets open, took `Exit/initiated` from 5 to 0 (5 real decrements plus 20 clamped). With the fix it stays at 5.

This fits what we saw on a relay during the tor#41339 flood: `OR/received` read 598 while about 4,800 sockets (roughly 2,300 clients and 2,500 relays) were open on its ORPort, and 33 after the flood. We haven't confirmed on that relay that this mechanism is the cause, though. The gap also includes connections still waiting in the accept queue, which the gauge correctly doesn't count.

### Proposed fix (about 25 lines plus tests)

- Add one bit to `connection_t`, set where `rep_hist_note_conn_opened()` is called (`note_connection()` and `listener_connection_new()`).
- In `connection_mark_for_close_internal_()`, call `rep_hist_note_conn_closed()` only if the bit is set, and clear it.
- In `connection_ext_or_transition()`, move a counted connection from the `Extended OR` counters to the `OR` ones when it is retyped. Clearing the bit on close matters here: the transition can run on a connection that has already been marked.

This is the same pattern `or_connection_t.tracked_for_dos_mitigation` already uses for the DoS concurrent-connection count (`src/core/or/dos.c:1119`, `:1136`), which is why that count stays correct when the gauge doesn't. There's no need to remember the (direction, type, family) seen at open time. `from_listener` and `socket_family` never change once a connection is counted, and `ext_orport.c:91` is the only place where a counted connection changes type. Tests: a new `connection/opened_counter` case covering a failed accepted handshake, an uncounted exit connection, and mark-then-free, plus gauge checks in `extorport/handshake`. Both fail on 0.4.9.14.

Before I open the MR (against `maint-0.4.9` given the milestone; it applies cleanly to `main` too), two questions:

1. **ExtOR connections:** is it OK to move them to the `OR` gauge when they become OR connections? This also counts them in `tor_relay_connections_total{type="OR",state="created"}`, which keeps opened ≤ created in each bucket. The alternative is to keep them under `Extended OR` until they close, which needs a second bit.
2. **When to uncount:** I kept it at mark time, as today. Would you rather do it in `connection_free_minimal()`, so the gauge follows the socket until it is actually closed? Held-open connections can linger about 15 s after being marked.
