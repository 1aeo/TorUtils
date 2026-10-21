# Adversarial review: `tor#41350` gauge fix and HS POST outcome metric (revision 1)

This is the review that led to revision 2 of `analysis/tor41350-conn-gauge.md`
and of the patches in `upstream/tor41350/`.

**Method.** Every claim was re-checked against `tor-0.4.9.14` (`8fe2745`),
`main` (`8dbbbe6`) and `maint-0.4.9` (`ccd9eb8`), and against the tree with
`patches/0001-0007` applied. Two independent passes did this:

- **Audit pass.** Seven read-only auditors, one per dimension (lifecycle,
  tests and design, mechanism, outcome table, metric idioms, docs and
  sanitization, upstream conventions). Each was followed by an adversarial
  verifier and then a completeness critic.
- **Deliverables pass.** Reviewers checked the citations in the new
  documents and code-reviewed the new patches.

The most consequential findings were re-checked by hand. The fixes were
validated with unit tests (shown to fail on stock), the full `make check`, the
linters, a `--disable-module-relay` build, and an offline single-relay lab.

Verdicts: **F** = falsified, **P** = partly correct, **N** = new issue,
**I** = improvement, **C** = confirmed. All line numbers are `tor-0.4.9.14`.

## Part A: opened-connection gauge (`0001`)

1. **I, high: four new fields were three too many.** Revision 1 added
   `in_rephist_opened:1`, `opened_from_listener:1`, `opened_type:5` and
   `int opened_socket_family`, plus a helper.
   - `from_listener` is written only at `connection.c:2098`, before
     `note_connection()` (`:2111`).
   - Every `socket_family` write (`connection.c:737`, `:1744`,
     `connection_edge.c:4609-4610`, `hs_common.c:84`) happens before the
     connection is counted.
   - The only type change after counting is `ext_orport.c:91`.

   So one bit plus a transition hunk is equivalent. Done in revision 2: +23/−6
   lines outside tests, versus about +44/−6.
2. **F, high: "Path 7" leaks are unreachable.** `connection_add_impl()` has a
   single `return 0;` (`mainloop.c:245-271`), so the failure branches at
   `connection.c:1768`, `:2100` and `:2324` are dead. The
   `connection_edge.c:4670` free would hit
   `tor_assert(!connection_in_array(conn))` (`connection.c:970`) first.
   Revision 1's `connection_free_minimal()` "safety net" fixed nothing
   reachable, so it was dropped. Moving the decrement to free time is offered
   upstream as an option.
3. **I, low: clear the bit on close, and guard the transition.** Both are
   defensive. One audit claimed the ExtOR transition could run on a marked
   connection. A later review refuted that: `connection_handle_write_impl()`
   returns early for marked connections (`connection.c:4448`), and
   `connection_flushed_some()` can't fail for `EXT_OR`, so the mark at
   `:4661` can't come first. Revision 2 keeps both because they cost two
   lines and make the transition safe if that ever changes.
4. **I, medium: choosing an ExtOR bucket.** Revision 1 kept ExtOR connections
   in the `Extended OR` bucket for their whole life, which needed the type
   snapshot. Revision 2 moves them to `OR` at the transition. This also bumps
   `OR` `created`, which keeps opened ≤ created per bucket. A gauge-only
   "retype" helper would break that on a bridge with only PT clients. Keeping
   revision 1's semantics would need a second bit. The choice is put to
   maintainers.
5. **I, low: the `BUG()` guard and `tor_assert(conn)` can go.**
   `note_connection()` has two callers (`connection.c:2111`, `:2317`), each
   reached once per connection, and its first statement already dereferences
   `conn`.
6. **P, medium: Path 1a call chain.** `connection_tls_continue_handshake()`
   only returns −1 (`connection_or.c:1762-1766`, `:1793-1796`). The close
   happens in the caller, `connection.c:2141`, through
   `connection_or_close_for_error()` → `connection_mark_for_close_internal()`
   (`connection_or.c:1687`). There is exactly one mark and no duplicate-mark
   warning. `tor_tls_new()` failure (`:1727-1731`) also leads here.
7. **P, medium: Path 1a triggers.**
   - Path 1a needs a FIN, an RST, or at least 5 bytes of non-TLS data
     already queued at `accept()` time.
   - A peer that only sent a ClientHello is counted.
   - SYN scans never reach `accept()`, so "port scans" should read
     "TCP-connect probes".
   - The amplifier under load is that Tor accepts one connection per listener
     read event (`connection.c:1954`).
8. **F, medium: the dual-stack `IPV6_V6ONLY=0` mechanism.**
   - Tor sets `IPV6_V6ONLY` on every IPv6 listener (`connection.c:1571-1584`).
   - It rejects accepted sockets whose family differs from the listener's
     (`:2002-2005`).
   - Accepted connections inherit the listener's family (`:2052`).
   - `connection.c:2058` is unrelated code.
9. **F, medium: the field observation was misquoted.** The source
   (`flood-cost-and-constrained-hosts.md` §1.5) says ~2,300 client and ~2,500
   relay sockets on the ORPort, with the gauge at 598 during the flood and 33
   after. It says nothing about fd tables, "relay-to-relay", "0 shortly
   thereafter", or a post-flood socket count.
10. **P, medium: Path 1a was stated as established.**
    - On a relay without an ExtORPort, Path 1a is the only code path that can
      push `OR/received` below the real count.
    - The deficit builds up from process start.
    - Paired closes after the flood leave the deficit unchanged; they do not
      "subtract further".
    - An `ss` count by local port also includes accept-queue and flushing
      sockets.

    So this is a hypothesis for that relay, and revision 2 says which
    measurements would confirm it.
11. **F, medium: Path 5 and DNS failures.** DNS failures free the stream
    without marking it (`dns.c:472`, `:698`, `:1110`, `:1239`), so they don't
    drift. Drift only comes from marking a resolving stream: circuit teardown
    (`circuitlist.c:2431`), END (`relay.c:1429`), or a deliver-window
    violation. `RESOLVE` dummy connections (`connection_edge.c:4401`) behave
    the same way. The file is `src/feature/relay/dns.c`.
12. **P, low: Path 1b is broader than an original-destination failure.** Any
    synchronous rewrite, policy or attach rejection through
    `connection_edge.c:2924` triggers it. The mark is at
    `connection_edge.c:284`.
13. **P, low: Path 2b details.** The AP connection's family follows its
    partner (`connection_edge.c:3642`). The function is
    `directory_initiate_request()` (`dirclient.c:1327`, `:1410-1415`). Public
    relays use a direct DirPort when the target has one.
14. **P, low: Path 6.** The file is `src/feature/client/dnsserv.c`, and it has
    no mark calls. The drift exists but is invisible, because `Socks/initiated`
    is never incremented.
15. **F, low: wrong paths and lines throughout Part A.** For example
    `src/feature/ext_orport/` and `src/feature/dns/` don't exist, and neither
    do `connection_st.h` under `mainloop/`, `fill_connections_values()` or
    `connection_add_nonlinked()`. Wrong lines include `connection.c:2079` /
    `:2099` / `:2059` / `:2058` / `:2284`, `connection_edge.c:3651` / `:3666` /
    `:4706` / `:4718` / `:760` / `:1246`, `status.c:146-162`,
    `rephist.c:1753-1771` and `relay_metrics.c:411-452`. The analysis's
    section 5 also described helpers (`connection_note_opened_in_rephist()`)
    and fields (`rephist_*`) that weren't in the patch.
16. **F, medium: `TEST-RESULTS.txt` overclaimed coverage.** It listed
    transparent-AP and AP+DIR cases, outbound closes, and a listener freed on
    `connection_add()` failure. None of these is in the test, and the last
    can't happen. It also used field names the patch doesn't have.
17. **N, medium: the double decrement went untested.** No assertion checked
    that mark-then-free decrements exactly once while a canary keeps the bucket
    above 0. Removing the bit-clear wouldn't have failed the test. Revision 2's
    test checks this.
18. **I, low: test placement.** `test_stats.c` needed `CONNECTION_PRIVATE` and
    12 new includes and a define. Revision 2 uses `test_connection.c`, which already has the
    setup, and adds three assertions to the existing `extorport/handshake`
    test.
19. **F, low: the "bugfix on" version.** The gauge came in with `5603baf257`,
    first released in 0.4.7.11, not 0.4.7.1-alpha.
20. **N, low: gauge semantics.** Closes are counted at mark time and outbound
    opens at EINPROGRESS, and held-open sockets can live about 15 s after the
    mark. The gauge is therefore not "sockets in ESTABLISHED", and the docs now
    say so.
21. **I, info: upstream precedent.** `or_connection_t.tracked_for_dos_mitigation`
    (`dos.c:1119`, `:1136`) is the same set-on-count, check-on-close pattern.
    That is also why the DoS concurrent count stays correct for Path 1a
    connections. It is cited in the commit message and the comment.
22. **F, info: "line numbers on main are identical".** False for
    `hs_descriptor.c` past `:1468`, which is −1 on `main` because of a
    comment-only change.
23. **N, info, pre-existing.** `rephist.h:42-43` names the parameter
    `initiated` where the definition calls it `from_listener`, meaning the
    opposite. The `tor_assert(type <= CONN_TYPE_MAX_)` checks in rephist are
    off by one (unreachable). This is a follow-up cleanup, kept out of the fix.
24. **C, info.** IPv6 exit-policy and re-entry rejections are recorded under
    `ipv4` in `state="rejected"`, and that counter is exported only as
    `direction="received"` (`relay_metrics.c:802-807`). Out of scope.
25. **I, info, follow-up.** After the fix, synchronous accept-time handshake
    failures leave no trace on the MetricsPort. A dedicated counter would let
    operators test the Path 1a hypothesis directly.

## Part B: HS descriptor POST outcomes (`0002`)

26. **F, high: `hs_cache_store_as_dir()` is not tri-state.** It returns 0 on
    store and −1 for both decode failure and revision-counter rejection
    (`hs_cache.c:378-411`). Its only caller checks `< 0`
    (`dircache.c:1556`, not `> 0` at `:1570`). So the idea of counting
    everything in `handle_post_hs_descriptor()` without touching `hs_cache.c`
    can't work: some change to `hs_cache.c` is unavoidable. Revision 2 makes
    it return −2 for "not newer"; two test assertions change.
27. **F, high: reason phrases.** Every phrase in revision 1's table except
    `Bad request` was invented. The real ones are:
    - `Not acting as a public relay`
    - `Rejecting single hop HS descriptor post`
    - `Invalid HS descriptor. Rejected.`, for the URL, decode and revision
      cases alike
    - `HS descriptor stored successfully.`
    - `Nonauthoritative directory does not accept posted server descriptors`
    - `Not found`, for an unknown URL on an authority
28. **F, high: the superencrypted layer.** The HSDir only runs
    `hs_desc_decode_plaintext()` (`hs_cache.c:122`). It never decrypts or
    MAC-checks the superencrypted layer, because it has no subcredential.
    Revision 1's row and its `0002` commit message were wrong about this.
29. **F, medium: constants.**
    - `MAX_HEADERS_SIZE` is 50000 (`or.h:122`).
    - `MAX_DIR_UL_SIZE` is 16 MB − 1 (`dircache.c:48`).
    - `HSV3MaxDescriptorSize` defaults to 50000 (`hs_descriptor.h:50`).
    - `MAX_DIR_URL_LEN` doesn't exist.
    - The size limits reject at ≥, not >.
30. **F, medium: legitimate revision-counter rejections.**
    `hs_service.c:1726` and `obfuscated_last_revision_counter` don't exist. A
    single C Tor instance always uploads increasing counters: an
    order-preserving encryption, under a fixed key, of the seconds since the
    start of the time period, recomputed before every upload
    (`hs_service.c:3248-3274`, `:3550`). `not_newer` comes from several
    instances sharing a key, or from a clock step. Onionbalance and Arti are
    unverified. My own first draft also said "a retry after a lost response",
    which is wrong because C Tor doesn't retry for 60-120 min and then
    recomputes. Corrected.
31. **P, medium: the certificate check.** There is no "not yet valid" check.
    Services mint a fresh 54 h certificate per upload
    (`hs_service.c:1793-1796`), so expiry needs the HSDir's clock to be about
    54 h or more ahead. There is also no 30-minute minimum lifetime, only a
    12 h maximum (`hs_descriptor.c:2221`).
32. **F, medium: single-hop conditions.** `connection_dir_is_anonymous()`
    (`directory.c:201-265`) has no circuit-purpose test. It fails for
    non-tunneled requests, a closing edge or circuit, an origin circuit, no
    `p_chan`, or a client previous hop. C Tor services, single onion services
    included, always upload over anonymous circuits (`hs_service.c:4051`).
    The GET-side check is `dircache.c:1364`, not `:1319`.
33. **F, medium: the series rows.**
    - Both rules are in `connection_dir_allow_hs_request()`
      (`directory.c:293`).
    - The reuse close uses `END_CIRC_REASON_RESOURCELIMIT`, not `TORPROTOCOL`.
    - The 503 phrase is `Rejecting HS request: previous hop is not a known
      relay`.
    - The counters fire whether or not enforcement is on, so with the
      count-only default, counted requests are still served.
34. **F, medium: the reconciliation identity.** It used terms no metric
    exports (`unparsed`, `non_hs`, `single_hop_rejected`, `command_wait`). Its
    "exact partition" double-counted with enforcement off, and it named
    `hsdir_circ_reuse`, which doesn't exist (the counter is
    `hsdir_circ_reused`, and it counts circuits). Revision 2 restates it with
    what is observable.
35. **I, medium: where the counters live.** Upstream review explicitly moved
    the HS relay counters out of `rephist.c` into `relay_metrics.c`
    (`1899b6230d`, "Removed getter abstraction and moved from rephist to
    relay_metrics"), as `relay_increment_<x>_action()` with an `action`
    label. Revision 1 put new counters and getters in `rephist.c`. Revision 2
    follows the `intro1` / `est_rend` pattern.
36. **N, medium: `--disable-module-relay`.** `relay_metrics.c` is only
    compiled with the relay module (`src/feature/relay/include.am:44-47`), and
    upstream CI has a `debian-disable-relay` job. `hs_cache.c` is always
    compiled, so hooks there would need a `relay_stub.c` stub. `dircache.c`
    is compiled only with the relay module (`configure.ac:394-400`), so
    revision 2 does all the counting there. Verified with a
    `--disable-module-relay` build.
37. **I, low: labels.** A `status` + `reason` pair is redundant, since each
    reason maps to one status. The precedent is a single `action` label. Put
    to maintainers.
38. **I, low: `single_hop` was missing.** Revision 1 didn't count the
    single-hop 503, which is the outcome its own identity needed. Revision 2
    adds it with one line, following the `INTRO1_SINGLE_HOP` /
    `EST_REND_SINGLE_HOP` naming.
39. **P, low: non-HS POSTs.** On a non-authority, every non-HS POST gets 400
    `Nonauthoritative directory does not accept posted server descriptors`
    (`dircache.c:1625-1631`). On an authority, an unknown URL gets 404.
40. **P, low: `400 Bad request`.** It fires only when `parse_http_command()`
    fails (`directory.c:304-351`). A URL without the `/tor/` prefix is
    rewritten (`dircache.c:76-84`), not rejected.
41. **N, low: missing stage-0 outcomes.** BEGIN_DIR is refused with
    `EXITPOLICY`, `NOTDIRECTORY` or `HIBERNATING`, or silently dropped,
    before the stream counter at `connection_edge.c:4697`.
42. **P, low: the `/publish` match.** It is a prefix match, so `/publishXYZ`
    passes, and `tor_parse_long()` accepts `03` and `+3`.
43. **F, low: the revision-counter log message** was paraphrased wrongly. The
    real one is at `hs_cache.c:187-191`, uses `%d` with `(int)` casts, and runs
    after the OOM prune (`:158-177`).
44. **N, info: what the service sees.** A service logs a 400 as "Malformed
    hidden service descriptor?" (`dirclient.c:2809-2817`), including for
    `not_newer`, and doesn't retry that HSDir until its next upload, 60-120 min
    later. Mentioned in the new issue.
45. **N, medium, series follow-up outside these patches.** Patch 0003
    throttles only HTTP-framing warnings. Each junk descriptor POST still logs
    one unthrottled `log_warn` from `hs_desc_decode_plaintext()` (stock
    `hs_descriptor.c:2682`, `:2692`, `:2703`, `:2708`), which matters given
    that `tor#41339` is literally about log flooding.
46. **F, low: the series patch 0001 row.** Revision 1 said a refused service
    "will retry over a new circuit". It doesn't: it logs a warning and waits
    for its next upload cycle, 60-120 min later.

## Process, tests and upstream readiness

47. **F, medium: practracker.** "practracker exit code 0" isn't reproducible:
    `practracker.py` exits 98 on stock 0.4.9.14 here, with 167 problems.
    What matters is that the patches add none. Separately,
    `test_practracker.sh` fails identically on stock under Python 3.13 (a
    fixture ordering difference), so `make check` shows 1 FAIL on stock too.
48. **I, medium: commit structure.**
    - `0001` is a standalone bugfix MR against `maint-0.4.9`, the milestone
      branch. It applies cleanly to `main` too.
    - `0002` is a separate feature MR against `main`, after a new issue gets
      naming feedback.
    - Neither depends on the other.
    - `upstream/tor41350/hsdir-series/` has the `0002` variant that stacks on
      `patches/0001-0007`; it only differs in two test includes.
49. **I, low: changes files.** `bugNNNNN` naming is the upstream majority.
    The bugfix-on version is 0.4.7.11. The feature entry says "Part of ticket
    41339" until the new ticket exists, then becomes `ticketNNNNN` with "Closes
    ticket NNNNN".
