# Adversarial review: `tor#41350` opened-connection gauge fix (revision 1)

This is the review that led to revision 2 of `analysis/tor41350-conn-gauge.md`
and of `upstream/tor41350/0001-*.patch`. Revision 1 also proposed HS
descriptor POST metrics; that work is handled elsewhere, and its findings are
not listed here.

**Method.** Every claim was re-checked against `tor-0.4.9.14` (`8fe2745`),
`main` (`8dbbbe6`) and `maint-0.4.9` (`ccd9eb8`), and against the tree with
`patches/0001-0007` applied. Two passes did this:

- **Audit pass.** Read-only auditors, one per dimension: lifecycle, tests and
  design, mechanism, docs and sanitization, and upstream conventions. An
  adversarial verifier re-checked the lifecycle findings. The other findings
  were re-checked by hand and by the deliverables pass. The audit was stopped
  before its completeness critic ran.
- **Deliverables pass.** Reviewers checked every citation in the new
  documents, checked the test claims, and independently code-reviewed the
  new patch. That review found no code issues and one commit-message
  overclaim, since fixed.

The fix was validated with unit tests (shown to fail on stock), the full
`make check`, the linters, and an offline single-relay lab.

Verdicts: **F** = falsified, **P** = partly correct, **N** = new issue,
**I** = improvement, **C** = confirmed. All line numbers are `tor-0.4.9.14`.

## Findings: opened-connection gauge (`0001`)

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

## Process, tests and upstream readiness

26. **F, medium: practracker.** "practracker exit code 0" isn't reproducible:
    `practracker.py` exits 98 on stock 0.4.9.14 here (98 problems and 67
    warnings). What matters is that the patch adds none. Separately,
    `test_practracker.sh` fails identically on stock under Python 3.13 (a
    fixture ordering difference), so `make check` shows 1 FAIL on stock too.
27. **I, medium: commit structure.** `0001` is a standalone bugfix MR against
    `maint-0.4.9`, the milestone branch. It applies cleanly to `main`,
    `tor-0.4.9.14` and on top of `patches/0001-0007`.
28. **I, low: the changes file.** `bugNNNNN` naming is the upstream majority,
    and the bugfix-on version is 0.4.7.11.
