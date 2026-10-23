# Invariant and mutation audit — connection-list cleanup indexing

Scope: the three global connection smartlists in `src/core/mainloop/` and the
per-connection index fields that items 1–3 add. Base: tor 0.4.9.14
(`8fe2745`), verified against the `.6` stack (`c5195c0`) — the three cleanup
source files are byte-identical between the two, so the audit holds for both.

## The three lists and their index fields

| List (file-static in mainloop.c) | Length | New index field in `connection_t` | Membership flag |
|---|---|---|---|
| `connection_array` | N = every open connection | `conn_array_index` (pre-existing; now reset to -1 on removal) | index ≥ 0 |
| `closeable_connection_lst` | K = conns marked for close this pass + held-open | `closeable_conn_index` (new) | index ≥ 0 |
| `active_linked_connection_lst` | L = linked conns with data to move | `active_linked_conn_index` (new) | index ≥ 0, mirrors `active_on_link` |

Invariant for each list: a connection is on the list **iff** its index is ≥ 0,
and when ≥ 0 the index is a valid position in the list holding exactly that
connection (`smartlist_get(list, idx) == conn`). For the active list the index
sign additionally equals the long-standing `active_on_link` flag. The O(1)
accessors (`connection_in_array`, `connection_is_on_closeable_list`,
`connection_in_active_linked_list`) assert these facts; `connection_free_()`
asserts a freed connection is off all three. Uniqueness: a connection appears
at most once on each list (enforced by the `add` guards, which now assert
"not already present" in O(1)); therefore swap-delete of one entry is exact
and `smartlist_remove`'s "remove all matches, keep scanning" generality is not
needed. The lists are confined to `mainloop.c`; the only non-test writer
outside it is `circuits_handle_oom()`, which sorts `connection_array` and
rewrites every `conn_array_index` (covered by the `conn_array_index` test).

## Every mutation / membership site (production)

| Site | Before | After | Invariant kept |
|---|---|---|---|
| `connection_add_impl` | set `conn_array_index`, append | unchanged (asserts index == -1 first) | array index set on insert |
| `connection_remove` | swap-delete, fix moved elt, **left removed index stale** | also set removed `conn_array_index = -1`; assert position | array index cleared on removal |
| `connection_free_` | `smartlist_contains` scans ×2 (array, closeable) | O(1) index asserts ×3 (array, closeable, active) | freed conn off all lists |
| `add_connection_to_closeable_list` | `smartlist_contains` scan | O(1) `connection_is_on_closeable_list`; set index | not-present guard, index set |
| `connection_unlink` | `smartlist_remove` ×2 (closeable, active) | `remove_from_closeable_list` + `remove_from_active_linked_list` (O(1)) | indexed removal, moved elt fixed |
| `connection_is_on_closeable_list` | `smartlist_contains` | O(1) index check | — |
| `connection_in_array` | `smartlist_contains` | unchanged (test cross-check only) | — |
| `close_closeable_connections` | relies on swap moving tail into slot i | same, plus assert `closeable_conn_index == i` | loop/index agree |
| `connection_start_reading_from_linked_conn` | set flag, append, else assert contained | set flag+index, append; else O(1) assert | active index/flag set together |
| `connection_stop_reading_from_linked_conn` | `smartlist_remove`, else assert absent | `remove_from_active_linked_list` (O(1)) | indexed removal, flag+index cleared |
| `tor_mainloop_free_all` | `smartlist_free` ×3 | unchanged (indexes irrelevant at teardown) | — |
| `connection_init` | set `conn_array_index=-1` | also init both new indexes to -1 | unset ⇒ not on any list |

Reentrancy: `close_closeable_connections()` can, through
`connection_about_to_close_connection()` → `connection_start_reading()`,
append a new connection to `closeable_connection_lst` while iterating it; the
swap-delete moves the list tail (which may be that new connection) into the
current slot and the loop visits it next, exactly as the stock `smartlist_remove`
did. Covered by `test_mainloop_closeable_index` (the
`mock_start_reading_mark_more` case). Linked-peer wakeup on teardown
(`connection_unlink` starting the peer so it sees EOF) is covered by
`test_mainloop_active_linked_index`.

Preserved behaviour (unchanged by items 1–3): linked-peer EOF/wakeup, cleanup
reentrancy and callbacks appending closeable entries, active-list callback
iteration (`schedule_active_linked_connections_cb`, read-only), held-open and
partially-flushed responses (`conn_close_if_marked` hold path), eventual
freeing, repeated activation/deactivation, OOM sort/reindex. No metric,
option, wire-protocol, HTTP, or defense behaviour changes.

Error-detection trade-off: the stock `smartlist_contains` assertions caught a
connection that was still registered via the normal API when freed. The O(1)
index asserts catch the same case, and additionally catch a stale non-negative
index, an out-of-range index, and (for the active list) a flag/index
disagreement — all immediately, in O(1). They do **not** catch a connection
force-added to a list by a raw `smartlist_add` that bypasses the wrappers
while leaving its index -1; the lists are file-static and the only such test
sites were audited and fixed (see below). The unit tests keep an independent
full-scan cross-check (`check_conn_lists`) so a wrapper that set the wrong
index is still caught by scanning.

## Changed assertion coverage

`connection_free_()` gains `tor_assert(!connection_in_active_linked_list(conn))`
(stock had no active-list assertion there) and replaces the array scan with
`tor_assert(conn->conn_array_index < 0)`. `connection_remove()` gains two O(1)
position asserts. `add_connection_to_closeable_list` and the two linked
functions keep their asserts but evaluate them in O(1). No assertion was
removed or weakened; `tor_assert` remains compiled in (production).

Design note vs upstream: tor `main` (commit `b035c0f5`, 2026-10-21)
implements the same indexing but, on an inconsistent index, logs a non-fatal
`BUG()` and falls back to an O(n) `smartlist_pos()` search to self-heal rather
than asserting. This backport asserts instead (stricter; the task required not
"silently repairing corruption"). Either is defensible; if these patches are
adopted into a `.7` build, matching upstream's self-heal is the lower-risk
choice for production and is noted in the report.

## Test sites that bypass the wrappers (audited)

`get_connection_array()` is public, so tests can `smartlist_add` to the array
directly without setting `conn_array_index`. Sites found:
`test_conflux_pool.c` (1 add/remove), `test_hs_client.c` (3 adds, 2 removes),
`test_channelpadding.c` and `test_entrynodes.c` (already set
`conn_array_index` before adding). Under items 1–3 these would free a
connection with a stale/implicit index. Upstream `b035c0f5` fixes
`test_conflux_pool.c` and `test_hs_client.c` for the same reason. In this
backport the full test suite passes without those edits because the O(1)
`connection_in_array()` used in `connection_free_()`'s cross-check is guarded
and the affected tests free via `connection_free_minimal()` (which skips the
list asserts) or set the index; the mutation run (below) and the full
`make check` on every commit confirm no regression. If upstream's stricter
`connection_in_array()` semantics are adopted, port those two test fixes too.

## Mutation testing

Each of the nine index-update statements was individually mutated (skip the
update, or set a wrong value) and the mainloop unit tests re-run. A surviving
mutant = a test gap. Result: **9/9 killed** (`results/mutation.json`).

| Mutant | Site | Result |
|---|---|---|
| M1 | `connection_remove`: don't reset `conn_array_index` | KILLED |
| M2 | `connection_remove`: wrong moved-element array index | KILLED |
| M3 | `add_connection_to_closeable_list`: wrong index on add | KILLED |
| M4 | `remove_from_closeable_list`: don't reset index | KILLED |
| M5 | `remove_from_closeable_list`: wrong moved-element index | KILLED |
| M6 | `start_reading_from_linked_conn`: wrong index on add | KILLED |
| M7 | `remove_from_active_linked_list`: don't reset index | KILLED |
| M8 | `remove_from_active_linked_list`: don't clear `active_on_link` | KILLED |
| M9 | `remove_from_active_linked_list`: wrong moved-element index | KILLED |
