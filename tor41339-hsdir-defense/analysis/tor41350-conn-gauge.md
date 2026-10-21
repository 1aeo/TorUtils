# `tor#41350` (`tor_relay_connections{state="opened"}` drift) and HS descriptor POST outcomes

Revision 2. This replaces revision 1 of this file. An adversarial review
(`analysis/tor41350-review.md`) re-checked every claim against the source and
found many wrong line numbers, two falsified mechanisms, and a patch design
that was larger than it needed to be. Both patches in `upstream/tor41350/`
were rewritten; the errata are listed at the end of this file.

**Baseline.** C Tor `tor-0.4.9.14` (`8fe2745`). All `path:line` references are
to that tag. Upstream `main` (`8dbbbe6`) and `maint-0.4.9` (`ccd9eb8`) have
identical code at every cited location. The only differences in the cited
files are comment typo fixes, and the one in `hs_descriptor.c` shifts lines
after `:1468` by −1 on `main`.

**How this was checked.** Source reading on all three trees, unit tests, and
an offline single-relay lab run in a loopback-only network namespace
(`unshare -n`; see `upstream/tor41350/lab/`). Revision 1's Chutney numbers
couldn't be re-run for this revision, so they were removed.

---

## Part A: `tor_relay_connections{state="opened"}` drift (`tor#41350`)

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

## Part B: HS descriptor POST outcomes

### B.1 Outcome table (stock 0.4.9.14)

These are all the outcomes of a `POST /tor/hs/3/publish` that reaches a
directory cache over a `BEGIN_DIR` stream. A DirPort POST starts at the
`directory_handle_command()` rows.

| # | Stage | Result | `path:line` | Condition | Legitimate service? |
|-|-|-|-|-|-|
| 1 | `BEGIN_DIR` gate | `END` (`EXITPOLICY`, `NOTDIRECTORY`, `HIBERNATING`) or silent drop, no HTTP | `connection_edge.c:4191-4198`, `:4239-4247`, `:4317-4321`; drops in `relay.c:1670-1687`, `:2091-2101` | Not in server mode, `!directory_permits_begindir_requests()`, conflux circuit, purpose ≠ OR, or hibernating. All before the `BEGIN_DIR` stream counter (`:4697`). | A hibernating HSDir, or one that left directory mode while still listed |
| 2 | HTTP framing | Stream closed, no response | `dircache.c:1748-1754` → `directory.c:489-492` | Headers > `MAX_HEADERS_SIZE` (50000, `or.h:122`), body > `MAX_DIR_UL_SIZE` (16 MB − 1, `dircache.c:48`), or a malformed `Content-Length` (`proto_http.c:92-96`). A stream that ends before the request is complete is also closed without a response. | Only if the circuit dies mid-upload |
| 3 | Method | Stream closed, no response | `dircache.c:1772-1777` | Neither `GET` nor `POST` | No |
| 4 | Public relay check | `503 Not acting as a public relay` | `dircache.c:1591-1597` | `!public_server_mode()`, checked before the URL is parsed | Briefly, after a relay leaves public mode |
| 5 | URL | `400 Bad request` | `dircache.c:1599-1602` | `parse_http_command()` fails (`directory.c:304-351`): a missing token, or a version that isn't `HTTP/1.<n>\r`. A URL without the `/tor/` prefix is rewritten (`dircache.c:76-84`), not rejected. | No |
| 6 | Anonymity | `503 Rejecting single hop HS descriptor post` | `dircache.c:1609-1612`; `connection_dir_is_anonymous()` at `directory.c:201-265` | Not linked (DirPort), linked edge closed, origin or closing circuit, no `p_chan`, or the previous hop is a client (`channel_is_client()`) | No |
| 7 | HS URL | `400 Invalid HS descriptor. Rejected.` | `dircache.c:1543-1552`, `:1562-1564` | Version doesn't parse, command doesn't start with `/publish` (`strcmpstart()`, so `/publishX` passes), or version ≠ 3 | Only obsolete v2 software |
| 8 | Decode | `400 Invalid HS descriptor. Rejected.` | `hs_cache.c:390-393` → `cache_dir_desc_new()` (`:110-135`) → `hs_desc_decode_plaintext()` (`hs_descriptor.c:2666`) | Plaintext layer only: size (≥ `HSV3MaxDescriptorSize`, a consensus parameter defaulting to `HS_DESC_MAX_LEN` = 50000), tokens and version, lifetime (maximum 12 h, no minimum), signing-key certificate (type, signing key, signature and expiry), revision counter field, superencrypted object type and minimum length, signature. The HSDir never decrypts the superencrypted layer; it can't, because it doesn't have the subcredential. | Only if the HSDir's clock is ≥ ~54 h ahead: services mint a fresh `HS_DESC_CERT_LIFETIME` (54 h) certificate per upload (`hs_service.c:1793-1796`) |
| 9 | Revision counter | `400 Invalid HS descriptor. Rejected.` | `hs_cache.c:182-193` (`cache_store_v3_as_dir()`), after the OOM prune at `:158-177` | Valid descriptor, cached one has a revision counter ≥ this one. Logged at info level only, with the counters cast to `int`. | **Yes**, for several instances publishing for the same address, or after a clock step back. A single C Tor instance always uploads increasing counters: they are an order-preserving encryption, under a fixed key, of the seconds since the start of the shared-random protocol run that the descriptor uses, recomputed before each upload (`hs_service.c:3235-3274`, `:3550`). Onionbalance and Arti were not checked. |
| 10 | Stored | `200 HS descriptor stored successfully.` | `dircache.c:1614-1621`, `hs_cache.c:210-221` | New key, or a strictly higher revision counter | Yes |

Rows 7-9 send the same status and phrase. The service logs any 400 as
"Malformed hidden service descriptor?" (`dirclient.c:2809-2817`), and C Tor
doesn't retry that HSDir until its next upload, 60-120 min later
(`hs_service.h:34-36`). `hs_cache_store_as_dir()` returns 0
on success and −1 for **both** rows 8 and 9 (`hs_cache.c:378-411`), and its
only non-test caller checks `< 0` (`dircache.c:1556`). Revision 1 claimed it
already returned a tri-state 1/0/−1; that is false. So the split cannot be
done in `dircache.c` alone without changing that return value.

**With `patches/0001`-`0007`.** `connection_dir_allow_hs_request()`
(`directory.c:293-337` in that tree) runs right after row 6. It **counts**
every HS request in `tor_relay_dos_total{type="hsdir_request_total"}`,
repeats in `type="hsdir_req_reused"` (and circuits in
`type="hsdir_circ_reused"`), and unknown previous hops in
`type="hsdir_unknown_prev_hop"`, whether or not enforcement is on. When
enforcing, which is off by default, it closes a reused circuit
(`END_CIRC_REASON_RESOURCELIMIT`, checked first) or answers `503 Rejecting HS
request: previous hop is not a known relay`. Refused requests never reach rows
7-10; with enforcement off, they are counted there as usual. Note for the
series (not for these patches): patch 0003 only throttles HTTP-framing
warnings. Row 8 still logs one unthrottled `log_warn` per junk descriptor
(for example "Service descriptor is not parseable", stock
`hs_descriptor.c:2692`, `:2703`, `:2708`), so a POST flood of junk descriptors
can still flood the log. With patch 0004, the `:2682` size warning is no
longer reachable on non-authorities. Patch 0004 lowers the row 2
body limit for non-authorities to the HS descriptor maximum. Patch 0006 moves
the signature-length check ahead of the certificate check in row 8. Patches
0003, 0005 and 0007 don't change POST outcomes.

`dos_note_refuse_single_hop_client()` is only called from
`src/feature/rend/rendmid.c:53` (the single-hop `ESTABLISH_RENDEZVOUS` refusal in `rend_mid_establish_rendezvous()`), so
`tor_relay_dos_total{type="single_hop_refused"}` never counts row 6 (nor the
GET-side check at `dircache.c:1364`).

### B.2 Metric (`upstream/tor41350/0002-metrics-Count-onion-service-descriptor-uploads-by-ou.patch`)

```
tor_relay_hsdir_post_total{action="success"}     row 10 (200)
tor_relay_hsdir_post_total{action="bad_url"}     row 7  (400)
tor_relay_hsdir_post_total{action="invalid"}     row 8  (400)
tor_relay_hsdir_post_total{action="not_newer"}   row 9  (400)
tor_relay_hsdir_post_total{action="single_hop"}  row 6  (503)
```

Design choices and why:

- **Modelled on `tor_relay_intro1_total` / `tor_relay_est_rend_total`.** An
  enum and `relay_increment_hsdir_post_action()` in `relay_metrics.h`, a
  `static uint64_t hsdir_post_actions[]` and an `action` label in
  `relay_metrics.c`. Upstream moved exactly these counters out of `rephist.c`
  into `relay_metrics.c` during review (`1899b6230d`, "Removed getter
  abstraction and moved from rephist to relay_metrics"), so revision 1's
  `rephist.c` counters and getters went against that review.
- **One `action` label, not `status` + `reason`.** Each action maps to one
  HTTP status, so a `status` label would be redundant, and the precedent uses
  `action`. This is asked upstream.
- **All counting in `dircache.c`.** Revision 1 put three of its four hooks in
  `hs_cache.c`. `hs_cache.c` is always compiled, but `relay_metrics.c` is
  only compiled with the relay module (`src/feature/relay/include.am:44-47`),
  and upstream CI has a `debian-disable-relay` job. Calling relay metrics from
  `hs_cache.c` would have needed a `relay_stub.c` stub. `dircache.c` is
  compiled only with the relay module (`configure.ac:394-400`). The price is
  that `hs_cache_store_as_dir()` returns −2 for row 9. Its only caller checks
  `< 0`, and two existing assertions (`test_hs_cache.c:83`,
  `test_stats.c:576`) change from −1 to −2.
- **`single_hop` included.** It is one line, in the same function, and it is
  the only way to see row 6. `INTRO1_SINGLE_HOP` and `EST_REND_SINGLE_HOP`
  are the naming precedent. It also counts DirPort uploads, which aren't
  tunneled.
- **Rows 1-5 not counted.** Rows 1-3 happen before the request is known to be
  an HS upload, and rows 4-5 before the URL is parsed.

**Test.** `hs_cache/hsdir_post_metrics` drives every action through
`handle_post_hs_descriptor()` and `directory_handle_command_post()`, and reads
the values from the real store (`relay_metrics_get_stores()`), so it also
checks the exported name and label.

### B.3 How this fits with `BEGIN_DIR`

`tor_relay_streams_total{type="BEGIN_DIR"}` is incremented in
`connection_exit_connect_dir()` (`connection_edge.c:4697`), after the row 1
gate. A directory server answers one request per stream and then closes it,
so:

```
BEGIN_DIR streams = streams still waiting for their request   (COMMAND_WAIT)
                  + closed without a response                 (rows 2-3)
                  + answered GET (HS descriptor and other)
                  + answered POST: rows 4-5, non-HS POSTs,
                                   series refusals (with 0001/0002),
                                   and Σ tor_relay_hsdir_post_total minus DirPort single_hop
```

Revision 1's identity (`unparsed + non_hs + hs + single_hop_rejected +
command_wait`) used terms that no metric exports. With `0002`, the HS POST
term becomes observable. The GET side, which is where the `tor#41339` flood
was, still needs a counterpart (asked in the new issue).

---

## Part C: commit structure and upstream plan

1. **`0001` is a standalone bugfix MR for `tor#41350`** against `maint-0.4.9`
   (milestone `0.4.9.x-post-stable`). It applies with `git am` to
   `maint-0.4.9`, `main` and `tor-0.4.9.14`, and does not depend on `0002` or
   on the HSDir series. Post the comment in
   `upstream/tor41350/gitlab-41350-comment.md` first.
2. **`0002` is a separate feature MR against `main`.** File the issue in
   `upstream/tor41350/gitlab-new-issue-hsdir-post-metrics.md` first, wait for
   naming feedback, then rename `changes/hsdir_post_metrics` to
   `changes/ticketNNNNN` with "Closes ticket NNNNN." (it says "Part of ticket
   41339" for now). It does not depend on `0001`.
3. **Stacking on the HSDir series.** `0002` comes after `patches/0007`.
   `patches/0002` already adds two of its test includes (`relay_metrics.h`,
   `metrics_store.h`). `upstream/tor41350/hsdir-series/` has the
   variant with those includes deduplicated, tested on
   `tor-0.4.9.14 + patches/0001-0007 + 0001`. `single_hop` requests never
   reach the series' guard, and requests the guard refuses never get an
   `action`. With enforcement off (the default), the guard only counts and
   the request still gets its `action`, so the two metrics answer different
   questions and don't need to add up.

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
  `dircache.c:1319` / `:1545-1579`, `hs_cache.c:295-336`,
  `hs_descriptor.c:2249-2437`, `relay_metrics.c:411-452`,
  `rephist.c:1753-1771`, `status.c:146-162`, and
  `directory.c:2168` / `:2243`.
- **Falsified mechanisms.**
  - The `IPV6_V6ONLY=0` family mismatch doesn't exist.
  - DNS failures don't drift.
  - "Path 7" leaks are unreachable.
  - `hs_cache_store_as_dir()` is not tri-state.
  - The HSDir doesn't decode the superencrypted layer.
  - The Part B reason phrases were not the strings Tor sends.
  - `MAX_HEADERS_SIZE` is 50000, not 24576, and `MAX_DIR_UL_SIZE` is 16 MB −
    1, not 20 MB.
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
