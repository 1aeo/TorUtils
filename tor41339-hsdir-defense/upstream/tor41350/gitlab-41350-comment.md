<!-- Ready-to-paste comment for https://gitlab.torproject.org/tpo/core/tor/-/work_items/41350
     Line numbers are tor-0.4.9.14 (8fe2745); the cited code is identical on main and maint-0.4.9. -->

Root cause (0.4.9.14; same code on `main` / `maint-0.4.9`): the increment and the decrement aren't paired.

- **+1:** `listener_connection_new()` (`connection.c:654`), and `note_connection()` (`status.c:151`). The latter is called only after `connection_init_accepted_conn()` succeeds (`connection.c:2111`) or `connect()` returns 0 or EINPROGRESS (`connection.c:2317`).
- **−1:** every `connection_mark_for_close_internal_()` (`connection.c:1180`), clamped at 0 (`rephist.c:1727`).

These connections are marked for close but were never counted:

| Path | Bucket pulled down | Where |
|-|-|-|
| Accepted OR conn whose TLS handshake fails synchronously (FIN, RST or non-TLS bytes queued before `accept()`) | `OR/received` | `connection.c:2139-2141`; returns before `:2111` |
| TransPort conn rejected by `connection_ap_process_transparent()` | `Socks/received` | `connection_edge.c:2914-2918` |
| Linked EXIT + DIR pair of every `BEGIN_DIR` | `Exit/initiated`, `Directory/initiated` | `connection_edge.c:4284`, `:4701`, `:4714` |
| Linked AP + DIR pair of a tunneled dir request | `Directory/initiated` | `connection_edge.c:3629`; marked at `dirclient.c:2848` |
| Exit stream or RESOLVE dummy marked while resolving | `Exit/initiated` | `circuitlist.c:2431`, `relay.c:1429` |
| Direct DIR conn whose `connect()` fails immediately | `Directory/initiated` | `dirclient.c:1364-1367` |
| ExtOR conn: counted as `EXT_OR`, retyped, uncounted as `OR` | `OR/received` ↓, `Extended OR` ↑ | `ext_orport.c:91` |

Every accepted connection either reaches `note_connection()` or fails init (`connection.c:2105-2111`). So without an ExtORPort, the first row is the only path that can lower `OR/received`.

**Repro:** offline, one relay in a loopback-only netns. 7 inbound TLS connections, then `SIGSTOP`, then 10 connections that send `GET / HTTP/1.0` or only a FIN, then `SIGCONT`.

| | `OR/received` opened | ESTAB on ORPort |
|-|-|-|
| 0.4.9.14 | 7 → 0 | 7 |
| fixed | 7 → 7 | 7 |

**Fix:** +23/−6 lines of C, plus a changes file and tests. Same pattern as `tracked_for_dos_mitigation` (`dos.c:1119`, `:1136`).

- `connection_t.opened_in_rephist:1`, set next to `rep_hist_note_conn_opened()` in `note_connection()` and `listener_connection_new()`.
- `connection_mark_for_close_internal_()`: decrement only if the bit is set, then clear it.
- `connection_ext_or_transition()`: if the bit is set, move the count from `EXT_OR` to `OR`.

One bit is enough: once a connection is counted, its (`from_listener`, type, family) only change at `ext_orport.c:91`, which the transition hunk handles. The new `connection/opened_counter` test and three new assertions in the existing `extorport/handshake` test fail on 0.4.9.14 and pass with the fix.

Questions before the MR (target `maint-0.4.9`; also applies to `main`):

1. Move ExtOR connections to `OR` at the transition, which also bumps `OR` `created`? Or keep them under `Extended OR` until close, which needs a second bit?
2. Decrement at mark time (as today), or in `connection_free_minimal()` so the gauge follows the fd? Marked connections with `hold_open_until_flushed` keep their socket after the mark.
