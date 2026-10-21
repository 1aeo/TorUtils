# `tor#41350`: `tor_relay_connections{state="opened"}` drift

Revision 2. This replaces revision 1 of this file. An adversarial review
(`analysis/tor41350-review.md`) re-checked every claim against the source and
found many wrong line numbers, two falsified mechanisms, and a patch design
that was larger than it needed to be. The patch in `upstream/tor41350/` was
rewritten; the errata are listed at the end of this file. Revision 1 also
proposed HS descriptor POST metrics; that work is handled elsewhere and is out
of scope here.

**Baseline.** C Tor `tor-0.4.9.14` (`8fe2745`). All `path:line` references are
to that tag. Upstream `main` (`8dbbbe6`) and `maint-0.4.9` (`ccd9eb8`) have
identical code at every cited location. The only differences in the cited
files are comment typo fixes.

**How this was checked.** Source reading on all three trees, unit tests, and
an offline single-relay lab run in a loopback-only network namespace
(`unshare -n`; see `upstream/tor41350/lab/`). Revision 1's Chutney numbers
couldn't be re-run for this revision, so they were removed.

---

## `tor_relay_connections{state="opened"}` drift

### A.1 Where the gauge moves

The gauge is exported by `fill_conn_gauge_values()`
(`src/feature/relay/relay_metrics.c:815-843`), and the `state="created"`
counter by `fill_conn_counter_values()` (`:771-811`). Both read the
file-static arrays in `src/feature/stats/rephist.c:1685-1692`.

**Increments.** `rep_hist_note_conn_opened()` (`rephist.c:1696-1715`) bumps
both `created` and `opened`. It is reached from exactly three places (called directly at `connection.c:654`, and through `note_connection()` at `status.c:151`, which has two callers):

| Site | When |
|-|-|
| `listener_connection_new()`, `src/core/mainloop/connection.c:654` | every listener, when created |
| `note_connection(true, …)`, `connection.c:2111` → `src/core/or/status.c:151` | an accepted connection, only after `connection_init_accepted_conn()` (`connection.c:2105`) returned ≥ 0 |
| `note_connection(false, …)`, `connection.c:2317` | an outbound socket, only after `connect()` returned 0 or EINPROGRESS (`connection.c:2299-2315`) |

**Decrement.** `rep_hist_note_conn_closed()` (`rephist.c:1719-1740`) has a
single caller, `connection_mark_for_close_internal_()`
(`connection.c:1180-1181`). It runs for **every** connection marked for
close, with the connection's current `(from_listener, type, socket_family)`.
The decrement is clamped at 0 (`rephist.c:1727-1735`), so an extra decrement
is invisible once a bucket is empty: it cancels a real connection only while
the bucket is above 0.

Both functions ignore families other than `AF_INET`/`AF_INET6`, so
`AF_UNIX` connections are never counted or uncounted. Duplicate marks return
before the decrement (`connection.c:1142-1148`), and no production code ever
un-marks a connection, so a connection is uncounted at most once.

**Semantics.** The gauge counts "counted and not yet marked", not kernel
sockets in ESTABLISHED. Outbound connections are counted at EINPROGRESS. A
marked connection with `hold_open_until_flushed` keeps its socket for up to
about 15 s (`connection.c:1189-1222`). Short-lived differences against `ss`
are therefore expected and are not drift.

### A.2 Unpaired paths (stock 0.4.9.14)

Except for Path 3 (counted as one type, uncounted as another), none of these
connections is ever passed to `rep_hist_note_conn_opened()`, but each is
marked for close, so each mark subtracts 1 from a bucket that
holds real connections.

| # | Path | Bucket pulled down | Evidence |
|-|-|-|-|
| 1a | Accepted OR connection whose TLS handshake fails synchronously | `OR / received` | `connection_init_accepted_conn()` starts the handshake at `connection.c:2139`. `connection_tls_start_handshake()` returns −1 (TLS error or close from `tor_tls_handshake()`, `src/core/or/connection_or.c:1739`, `:1762-1766`, `:1793-1796`; or `tor_tls_new()` failure, `:1727-1731`). The caller then runs `connection_or_close_for_error()` (`connection.c:2141`) → `connection_mark_for_close_internal()` (`connection_or.c:1687`) → decrement. `connection_handle_listener_read()` returns at `connection.c:2105-2108`, before `note_connection()` at `:2111`. There is exactly one mark and no duplicate-mark warning. |
| 1b | Accepted TransPort connection rejected synchronously | `Socks / received` | `connection.c:2162-2167` → `connection_ap_process_transparent()` (`src/core/or/connection_edge.c:2898-2925`): original-destination lookup failure (`:2914-2918`) or any synchronous rewrite, policy or attach rejection through `:2924`. The mark is `connection_mark_unattached_ap_()` → `connection_mark_and_flush_()` (`connection_edge.c:284`). |
| 2a | Linked EXIT + DIR pair of every incoming `BEGIN_DIR` | `Exit / initiated` (always `ipv4`) and `Directory / initiated` (previous hop's family) | `edge_connection_new(CONN_TYPE_EXIT, AF_INET)` at `connection_edge.c:4284`; `connection_exit_connect_dir()` (`:4689-4750`) creates the DIR connection at `:4701` and links it at `:4714`. Neither has a socket. Close sites: `connection_edge.c:310`, `:4745-4749`, `src/feature/dircommon/directory.c:577`, `src/core/or/circuitlist.c:2417-2418`. If the previous hop's address is unknown, the DIR connection is `AF_UNSPEC` and rephist ignores it. |
| 2b | Linked AP + DIR pair of a tunneled directory request | `Directory / initiated`; `Socks / initiated` (always clamped at 0) | `directory_initiate_request()` creates the DIR connection at `src/feature/dirclient/dirclient.c:1327` and calls `connection_ap_make_link()` at `:1410-1415` (`connection_edge.c:3629-3690`, AP created at `:3642` with the partner's family, linked at `:3675`). Always the case on clients, bridges and onion services; on public relays only when the target has no DirPort (`src/feature/dirclient/dirclient_modes.c:30-35`). |
| 3 | Extended ORPort connection retyped to OR | `OR / received` pulled down; `Extended OR / received` only grows | Counted as `CONN_TYPE_EXT_OR` at `connection.c:2111` (dispatch at `:4027-4028`; `connection_ext_or_start_auth()` always returns 0, `src/feature/relay/ext_orport.c:642-660`). `connection_ext_or_transition()` (`ext_orport.c:86-95`) retypes it at `:91`. It is then uncounted as `OR`. ExtOR connections that fail authentication before the transition are paired correctly. |
| 4 | Direct DIR connection whose `connect()` fails at once | `Directory / initiated` | `dirclient.c:1364-1367`: `connection_connect()` returns −1, which happens before `note_connection()`, and the connection is marked. OR and EXIT connections in the same situation are freed without being marked, which is neutral. |
| 5 | Exit stream marked while still resolving (`BEGIN` or `RESOLVE`) | `Exit / initiated` (always `ipv4`) | Both kinds sit on `resolving_streams` with no socket: `connection_edge.c:4284`, and the `RESOLVE` dummy at `:4401`. They are marked on circuit teardown (`circuitlist.c:2431`), on END while resolving (`src/core/or/relay.c:1429`), or on a deliver-window violation (`relay.c:1729`, `:2117`). DNS failures free the stream without marking it (`src/feature/relay/dns.c:472`, `:698`, `:1110`, `:1239`), so they do **not** drift. |
| 6 | DNSPort requests | `Socks / initiated` (always clamped at 0, so invisible) | Socketless `entry_connection_new(CONN_TYPE_AP, AF_INET)` at `src/feature/client/dnsserv.c:148` and `:228`, marked from `connection_edge.c`, for example `:2391-2394`. |

**Checked and neutral:** SocksPolicy, DirPolicy and DoS connection rejections
(`connection.c:2021-2050`) close the socket before `connection_new()`
(`:2052`). The OOS handler (disabled by default) only closes counted OR
connections. `connection_or_clear_identity()` only clears a digest.
`channel_close_for_error()` never calls back into the connection. Tor uses
neither `SO_LINGER` nor `TCP_DEFER_ACCEPT`.

**Apart from Path 3's `Extended OR` bucket, upward drift (counted, never uncounted) is not reachable.** Revision 1
listed three "Path 7" leaks. All of them are dead code:
`connection_add_impl()` (`src/core/mainloop/mainloop.c:245-271`) has a single
`return 0;`, so the `connection_add()` / `connection_add_connecting()`
failure branches at `connection.c:1768`, `:2100` and `:2324` cannot run.
`connection_free_()` asserts `!connection_in_array(conn)`
(`connection.c:970`), so the `connection_edge.c:4670` case would crash rather
than leak. The only counted-but-unmarked free is `connection_free_all()` at
shutdown (`connection.c:5973-5974`).

**Labelling quirks, not drift.** Proxied OR and DIR connections are labelled
with the target's family, not the proxy socket's. IPv6 exit-policy and
re-entry rejections are recorded under `ipv4` in `state="rejected"`
(`connection_edge.c:4562`, `:4590` run before `:4609-4610`). The rejected
counter is exported only with `direction="received"`
(`relay_metrics.c:802-807`). None of this is in scope for the fix.

### A.3 The operator observation and Path 1a

`analysis/flood-cost-and-constrained-hosts.md` §1.5 reports, for one relay
under the `tor#41339` flood: `OR in` (the opened gauge) read **598** while "a
socket count on the ORPort at the same time showed about 2,300 direct clients
and 2,500 relays"; it read **33** after the flood. Revision 1 misquoted this
(it said "~4,800 relay-to-relay sockets verified via fd tables" and "0 shortly
thereafter"). The source says neither.

What the code establishes:

- By elimination, on a relay **without an ExtORPort**, Path 1a is the only
  code path in 0.4.9.14 that can push `OR/received` below the real count. Paths
  1b, 2, 4, 5 and 6 hit other types or directions, `from_listener` is written
  only at `connection.c:2098`, and nothing inflates `OR/received`.
- Path 1a is triggered by a peer whose FIN, RST, or at least 5 bytes of
  non-TLS data are already queued when Tor calls `accept()`, with or without a
  ClientHello before them. A peer that only sent a ClientHello is counted.
  TCP-connect probes do this at any load. Under a saturated main loop it gets
  much more likely: Tor accepts one connection per listener read event
  (`connection.c:1954`), so connections wait in the kernel accept queue and
  peers give up before they are accepted.
- The deficit `D = real − gauge` builds up from process start, not just
  during the flood. A paired close leaves `D` unchanged. So the 598 → 33 drop
  is consistent with flood-era clients closing normally. Revision 1 said
  post-flood closes "subtract further", which is wrong.
- Part of the during-flood gap is a measurement artifact: an `ss` count by
  local ORPort also sees accept-queue sockets that Tor hasn't accepted yet
  and marked sockets still flushing, and the gauge is split by family.

**Falsified secondary mechanism.** Revision 1 blamed dual-stack
`IPV6_V6ONLY=0` sockets for a family mismatch. Tor sets `IPV6_V6ONLY` on every
IPv6 listener (`connection.c:1571-1584`), rejects accepted sockets whose
family differs from the listener's (`:2002-2005`), and an accepted connection
always inherits the listener's family (`:2052`).

**Status:** Path 1a is consistent with the observation and is the only
in-code explanation, but it is a hypothesis for that relay. Confirming it
would need the retained Prometheus series around the flood onset (a step down
during the stall), the relay's uptime, and a post-flood `ss` count filtered to
`sport = :ORPort`, owned by the tor process, summed over both families, taken
at scrape time. Once the fix lands, synchronous accept-time handshake failures
leave no trace on the MetricsPort; counting them separately would be a
possible follow-up.

### A.4 Reproduction

**Offline single relay** (`upstream/tor41350/lab/path1a_offline_repro.py`,
re-run for this revision). The relay runs in a loopback-only network
namespace. 7 real inbound TLS connections are opened, then the relay is
stopped with `SIGSTOP` while 5 connections that send `GET / HTTP/1.0` and 5
that only send FIN queue up in its accept backlog, then it is resumed with
`SIGCONT`.

| Step | 0.4.9.14 gauge | Fixed gauge | Established ORPort sockets |
|-|-|-|-|
| 7 real TLS connections open | 7 | 7 | 7 |
| +10 queued while stalled, then resumed | **0** | 7 | 7 |
| real connections closed | 0 | 0 | 0 |

`created` stays at 7 in both builds: the failed connections are never counted
as created either.

Paths 2a and 3 are exercised only by the unit tests in A.5. For 2a, the
test marks an uncounted socketless EXIT connection; for 3, it drives the real
ExtOR transition. There is no lab run for either in this revision.

### A.5 Fix (`upstream/tor41350/0001-conn-Only-uncount-connections-that-were-counted-as-o.patch`)

+23/−6 lines of C (excluding tests and the changes file), in 5 files:

- **`connection_st.h`.** One new bit, `unsigned int opened_in_rephist:1;`,
  next to `from_listener`. It fits in existing bitfield padding. The file
  comment "Connections never change their type" gets the Extended ORPort
  exception.
- **`status.c` / `status.h`.** `note_connection()` takes a non-const
  connection and sets the bit next to its `rep_hist_note_conn_opened()` call.
- **`connection.c`.** `listener_connection_new()` sets the bit.
  `connection_mark_for_close_internal_()` calls `rep_hist_note_conn_closed()`
  only if the bit is set, and clears it.
- **`ext_orport.c`.** `connection_ext_or_transition()` moves a counted
  connection from the `EXT_OR` counters to the `OR` ones before retyping it.

This is the pattern `or_connection_t.tracked_for_dos_mitigation` already uses
for the DoS concurrent-connection count (`src/core/or/dos.c:1119`, `:1136`),
which is why the DoS count stays correct for Path 1a connections while the
gauge doesn't.

**Why one bit is enough.** Every write to `from_listener` and `socket_family`
either happens before the connection is counted or rewrites the value it was
counted with:

- `from_listener` is set at `connection.c:2098`.
- `socket_family` is set in `connection_init()` (`:737`), at `:1744` (the
  same value already passed at `:1742`), at `connection_edge.c:4609-4610`
  (before `connect()`), and at `src/feature/hs/hs_common.c:84` (`AF_UNIX`,
  before `connect()`, and never counted).

The type changes after counting only at `ext_orport.c:91`.
`connection_edge.c:4706` writes the same value to a socketless connection.
So revision 1's snapshot of `(from_listener, type, socket_family)` (three
extra fields, including an `int`) bought nothing beyond what the transition
hunk does.

**Clearing the bit is defensive.** In 0.4.9.14 the transition can't run on
a marked connection. `connection_handle_write_impl()` returns at once for a
marked connection (`connection.c:4448`), and for `EXT_OR`,
`connection_flushed_some()` has no branch and returns 0, so the mark at
`:4661` can't precede `connection_finished_flushing()`. Clearing the bit on
close, together with the guard at the transition, keeps this correct if that
ever changes.

**What changed from revision 1's patch.**

- Four fields, a helper and a `BUG()` guard became one bit and two
  conditionals. `note_connection()` has exactly two callers, each reached once
  per connection, so the `BUG()` guard and the added `tor_assert(conn)` were
  noise.
- No `connection_free_minimal()` hook. A counted connection is never freed without a mark, except by `connection_free_all()` at shutdown (A.2),
  and keeping the decrement at mark time preserves its current semantics.
  Moving it to free time instead would make the gauge follow the socket until
  it is closed. That is offered upstream as an option.
- ExtOR connections now move to the `OR` gauge when they become OR
  connections, instead of staying in `Extended OR` until they close. This
  also counts them in `OR`'s `created`, which keeps opened ≤ created in every
  bucket. A "move only the gauge" helper would break that invariant on a
  bridge with only PT clients. Keeping them under `Extended OR` would need a
  second bit. This is offered upstream as a question.
- The tests moved to where the code under test lives. The lifecycle cases
  are in `test_connection.c` instead of `test_stats.c`, which had needed 12
  new includes and a `CONNECTION_PRIVATE` define. The ExtOR case is three assertions in the existing
  `extorport/handshake` test.
- "Bugfix on 0.4.7.11", not "0.4.7.1-alpha". The gauge came in with
  `5603baf257`, first released in 0.4.7.11.

**Tests.** `connection/opened_counter` uses canaries so that the 0 clamp
cannot hide stray decrements. It checks:

1. A listener is counted, then uncounted when marked.
2. An accepted OR connection whose mocked handshake fails inside
   `connection_init_accepted_conn()` does not decrement `OR/received`.
3. A counted connection that is marked and then freed is decremented exactly
   once.
4. An uncounted socketless EXIT connection does not decrement
   `Exit/initiated`.
5. `created` is unchanged.

`extorport/handshake` checks that the counted connection moves from `EXT_OR`
to `OR` at the transition. Both tests fail on 0.4.9.14, at the Path 1a and
ExtOR assertions, and pass with the fix. They rely on `TT_FORK`, like the
other connection tests, because the rephist arrays are process-static. The
synchronous `SSL_accept()` failure itself is only exercised by the lab
script.

### A.6 Should socketless connections be counted somewhere?

Not in `tor_relay_connections`. Every other series there is backed by a
kernel socket, so mixing in linked streams would make `type="Exit"` useless
for outbound socket pressure. A separate gauge of active server-side directory
streams would be useful during a `BEGIN_DIR` flood, but it is a separate
feature.

---

## Upstream plan

1. Post `upstream/tor41350/gitlab-41350-comment.md` on `tor#41350`.
2. Open `0001` as a standalone bugfix MR against `maint-0.4.9` (milestone
   `0.4.9.x-post-stable`). It applies with `git am` to `maint-0.4.9`, `main`
   and `tor-0.4.9.14`, and on top of `patches/0001-0007` (the HSDir series),
   and depends on neither.

See `upstream/tor41350/TEST-RESULTS.txt` for build and test results.

---

## Errata for revision 1 (summary)

- **Wrong paths.** `src/feature/ext_orport/` is `src/feature/relay/`,
  `src/feature/dns/` is `src/feature/relay/` (`dns.c`) and
  `src/feature/client/` (`dnsserv.c`), and `src/core/mainloop/connection_st.h`
  is `src/core/or/`. `fill_connections_values()` does not exist (the
  functions are `fill_conn_gauge_values()` and `fill_conn_counter_values()`),
  and neither does `connection_add_nonlinked()`.
- **Wrong line numbers**, including `connection.c:2079` / `:2099` / `:2059` /
  `:2058` / `:2284`, `connection_or.c:1761` as the closer,
  `connection_edge.c:3651` / `:3666` / `:4706` / `:4718` / `:760`,
  `relay_metrics.c:411-452`, `rephist.c:1753-1771` and `status.c:146-162`.
- **Falsified mechanisms.**
  - The `IPV6_V6ONLY=0` family mismatch doesn't exist.
  - DNS failures don't drift.
  - "Path 7" leaks are unreachable.
  - Post-flood paired closes don't "subtract further".
- **The field observation was misquoted** (A.3).
- **The patch descriptions didn't match the patches.** The analysis named
  helpers that didn't exist and fields called `rephist_*`, while the patch
  used `opened_*`. `TEST-RESULTS.txt` claimed transparent-AP, AP+DIR and
  outbound-close coverage that the test didn't have, and practracker
  "exit 0", which stock 0.4.9.14 itself doesn't achieve here.
- **Wrong "bugfix on" version.** Revision 1 said 0.4.7.1-alpha; the counters
  first shipped in 0.4.7.11 (`5603baf257`).

The full list with evidence is in `analysis/tor41350-review.md`.
