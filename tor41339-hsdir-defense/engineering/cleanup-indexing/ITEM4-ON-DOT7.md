# Rebasing item 4 (refuse-BEGIN_DIR-before-alloc) onto .7 — do not lose the
# new BEGIN_DIR counts

Flagged by the Directory-flood metrics agent, and confirmed here against the
BEGIN_DIR instrumentation it is adding. **This does not affect the delivered
item 4, which is a fixup of 0012 on the `.6` series.** It applies only to the
eventual rebase of item 4 onto a `.7` that instruments the directory-request
path.

## Why .6 is already safe

On `.6`, the only count on the over-limit path lives *inside*
`dos_should_refuse_begindir()` itself: it calls
`dos_note_dir_stat(DOS_DIR_BEGINDIR_OVER_MAX)` before returning. Item 4 moves
the **call**, so that count moves with it automatically. `test_dos_begindir_refused`
asserts `DOS_DIR_BEGINDIR_OVER_MAX == 1` after an over-limit BEGIN_DIR is
refused through `connection_exit_begin_conn()` — i.e. the count is verified to
survive the move. Nothing to do for `.6`.

## Why .7 is not safe to rebase mechanically

`.7` adds per-outcome counters at the **call sites** in
`connection_exit_begin_conn()`, *outside* `dos_should_refuse_begindir()`. In
the metrics draft reviewed here (confirm the exact names against the actual
`.7` — a parallel metrics branch uses different names), the relevant lines are:

- a per-hop class computed once near the top of the function
  (`count_begindir` / `begindir_peer` = `relay_metrics_circ_peer_class(circ)`);
- on the `dos_should_refuse_begindir(or_circ)` branch, immediately before the
  END cell:
  `relay_increment_begindir(begindir_peer, BEGINDIR_REFUSED_LIMIT);`
- on the admitted path, the peer class is threaded through:
  `return connection_exit_connect_dir(n_stream, begindir_peer);`
  and `connection_exit_connect_dir()` does
  `relay_increment_begindir(peer, BEGINDIR_ADMITTED);`

Item 4, as a diff, (a) inserts a refuse-check at the top of the BEGIN_DIR
branch (before `edge_connection_new`) and (b) **deletes** the post-allocation
`if (dos_should_refuse_begindir(...)) { ... }` block. A mechanical rebase onto
`.7` would delete that block *including* its
`relay_increment_begindir(begindir_peer, BEGINDIR_REFUSED_LIMIT)` line, and the
newly inserted top check (taken from the `.6` item 4, which has no such line)
would not re-add it. Result: **over-limit refusals stop being counted**
(`BEGINDIR_REFUSED_LIMIT` lost), and the modified
`connection_exit_connect_dir(n_stream, begindir_peer)` call can be dropped in
the same merge, losing the **`BEGINDIR_ADMITTED`** peer attribution. Those are
the two "new counts" a naive move loses — silently, because the build still
compiles and the metric still exists, it just never increments on that path.

## The safe move on .7

1. When relocating the `dos_should_refuse_begindir()` check to its new
   pre-allocation site (top of the BEGIN_DIR branch, after the
   NOTDIRECTORY/permits check), **carry its counter with it**:
   ```c
   if (dos_should_refuse_begindir(or_circ)) {
     if (count_begindir)
       relay_increment_begindir(begindir_peer, BEGINDIR_REFUSED_LIMIT);
     relay_send_end_cell_from_edge(msg->stream_id, circ,
                                   END_STREAM_REASON_MISC, layer_hint);
     return 0;                 /* no connection allocated */
   }
   ```
   `begindir_peer`/`count_begindir` are set at the top of the function in `.7`,
   before the BEGIN_DIR branch, so they are valid at the new site; guard with
   `if (count_begindir)` exactly as the other call sites do.
2. In the (now count-free) post-allocation BEGIN_DIR block, **keep** the
   admitted-path call unchanged: `return connection_exit_connect_dir(n_stream,
   begindir_peer);` so `BEGINDIR_ADMITTED` is still attributed.
3. Placing the refuse-check ahead of `we_are_hibernating()` (item 4's whole
   point) also means an over-limit **and** hibernating BEGIN_DIR is now counted
   as `BEGINDIR_REFUSED_LIMIT` rather than `BEGINDIR_REFUSED_NOT_SERVING`. This
   is a deliberate reattribution in that rare both-apply case (the rate/limit
   defense is the more specific reason, and upstream main orders rate-limit
   first for the same reason). Note it in the `.7` metrics docs.

## How to verify on .7 (regression guard)

Extend `test_dos_begindir_refused` (or add a metrics test) to read the
`.7` BEGIN_DIR metric after driving an over-limit refusal through
`connection_exit_begin_conn()`, and assert the `BEGINDIR_REFUSED_LIMIT`
(or its `.7` name) count is 1 and no connection was allocated. That test
fails on a mechanical rebase and passes on the safe move above. Also assert
the admitted path increments `BEGINDIR_ADMITTED` once per accepted stream.

If upstream `main`'s `dos_begindir_new_request()` / `dos_begindir_should_refuse()`
split is adopted instead of the `.6` 0012 `dos_should_refuse_begindir()`, the
same rule applies to each of those call sites' counters.
