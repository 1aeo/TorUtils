# Rebasing item 4 (refuse-BEGIN_DIR-before-alloc) onto .7 — keep the two new
# BEGIN_DIR counts

Flagged by the Directory-flood metrics agent (note verbatim in
`NOTE-FROM-METRICS-AGENT.md`) and verified here against the actual `+tor41339.7`
patches 0020 and 0024 on `tor41339-hsdir-defense-clean`. **The delivered item 4
is a fixup of 0012 on the `.6` series and is unaffected.** This is the rebase
onto `.7`, done and tested; the patch is
`patches/item4-on-dot7/0001-tor41339-item-4-on-.7-*.patch`.

> An earlier draft of this file guessed the `.7` mechanism from a parallel
> metrics branch and named it wrong (`relay_increment_begindir`,
> `BEGINDIR_REFUSED_LIMIT`, `BEGINDIR_ADMITTED`). Those names are **not** in
> `.7`. The real mechanism, from the actual patches, is below.

## Why .6 is already safe

On `.6`, `dos_should_refuse_begindir(const or_circuit_t *circ)` takes no stream
and the only over-limit count is inside it (`dos_note_dir_stat(DOS_DIR_BEGINDIR_OVER_MAX)`),
so item 4 moving the **call** moves that count with it;
`test_dos_begindir_refused` asserts `DOS_DIR_BEGINDIR_OVER_MAX == 1`. Nothing
to do for `.6`.

## What .7 added to the function item 4 moves

`.7` changes the signature to
`dos_should_refuse_begindir(or_circuit_t *circ, edge_connection_t *stream)` and
adds two counts:

1. **0020 "dos: Count what BEGIN_DIR streams over DoSBeginDirMaxStreams ask
   for".** When over `DoSBeginDirMaxStreams` (enforced or not) the function does
   `if (stream) stream->begindir_over_max = 1;`, and
   `connection_exit_connect_dir()` copies that onto the directory connection so
   the request is counted by type in the over-max requests family (served
   streams only — refused ones are freed before `connection_exit_connect_dir()`).
   * Moved before allocation there is **no `stream`** to mark; the `if (stream)`
     guard turns that into a silent no-op.
2. **0024 "dos: Count BEGIN_DIR cells over the stream creation rate".** The
   function first calls `dos_note_begindir_stream_rate(circ)`, a second
   per-circuit token bucket counting `tor_relay_dos_total{type="begindir_over_stream_rate"}`.
   * Its commit promises it runs **after the directory and hibernation checks**.
     Moved before `we_are_hibernating()` it would also count cells refused for
     hibernation.

A mechanical rebase (insert an early refuse, delete the post-alloc block) loses
both: the over-max mark (no stream yet) and the correct placement of the rate
count.

## The safe move (implemented and tested)

Per the metrics agent's suggested shape:

1. `dos_should_refuse_begindir(or_circuit_t *circ, bool *over_max_out)` — return
   the over-max result through the out-parameter instead of marking a stream,
   and drop the internal `dos_note_begindir_stream_rate()` call.
2. `connection_exit_begin_conn()` BEGIN_DIR branch, before `edge_connection_new()`:
   ```c
   tor_assert(or_circ);
   if (!we_are_hibernating() &&
       dos_should_refuse_begindir(or_circ, &begindir_over_max)) {
     relay_send_end_cell_from_edge(msg->stream_id, circ,
                                   END_STREAM_REASON_MISC, layer_hint);
     return 0;                       /* no connection allocated */
   }
   ```
3. Post-allocation BEGIN_DIR block (after the hibernation check), apply the mark
   and do the rate count there:
   ```c
   n_stream->begindir_over_max = begindir_over_max;
   dos_note_begindir_stream_rate(or_circ);     /* now exported from dos.c */
   ...
   return connection_exit_connect_dir(n_stream);
   ```
4. `dos_note_begindir_stream_rate()` becomes non-static (declared in `dos.h`).

### Why the `!we_are_hibernating()` guard

`.7`'s `test_dos_begindir_refused` asserts that an over-limit **and** hibernating
BEGIN_DIR is refused with `END_STREAM_REASON_HIBERNATING`, i.e. hibernation
takes precedence. Item 4 refusing before allocation also puts it before the
hibernation check, which would flip that to `MISC`. The guard restores the
precedence: while hibernating we skip the early refuse (the hibernation block
below refuses and frees, as before), and `dos_should_refuse_begindir()` is not
called at all — so the counts in the hibernating case are byte-for-byte `.7`.
A hibernating relay is not the flood this optimization targets.

## Counting: identical in production, one dormant divergence

Enforcement (`DoSBeginDirLimitEnabled`) is off in the deployment, so
`dos_should_refuse_begindir()` never returns true and nothing is refused: every
BEGIN_DIR is allocated and reaches the post-alloc block, so `begindir_over_max`
marking and the rate count happen exactly as in `.7`. The only difference is in
the enforced + over-limit + refused case (not deployed): `.7` rate-counts that
refused cell before refusing it; this rework refuses it before the rate count,
so it is not counted toward `begindir_over_stream_rate`. That is arguably more
correct (the cell was refused for the over-limit reason, not the rate reason)
and is dormant while the limit is off. `DOS_DIR_BEGINDIR_OVER_MAX`, the per-hop
`rep_hist` BEGIN_DIR cell count (0021, counted at the top of the branch), and
the over-max requests family are unchanged in all cases.

## Verification

`+tor41339.7` (patches 0001-0024) + cleanup-indexing items 1-3 + this rework,
built in the Noble container with `--enable-fatal-warnings`:
`make check` 33 PASS / 1 SKIP / 0 FAIL; `--disable-module-relay` tip green;
`check-spaces` clean. `./src/test/test dos/.. mainloop/..` = 25/25 OK, including
`dos/begindir_refused`, `dos/begindir_max_streams` and
`dos/begindir_over_stream_rate` (the 0020/0024 tests, updated for the new
signature and the standalone rate-count call). The full-suite / module-relay
results are in `results/dot7-*`.

If upstream `main`'s `dos_begindir_new_request()` / `dos_begindir_should_refuse()`
split is adopted instead of 0012's `dos_should_refuse_begindir()`, apply the
same rule to each of those call sites' counters.
