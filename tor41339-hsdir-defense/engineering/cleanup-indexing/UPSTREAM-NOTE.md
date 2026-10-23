# Draft note to the Tor network team (not sent)

Subject: connection-list cleanup scaling under BEGIN_DIR churn — already
covered by b035c0f5?

Hi,

While profiling a directory cache under the ongoing BEGIN_DIR / onion-service
descriptor churn (tor#41339), we found the relay's main thread spending almost
all of its userspace time in two list scans during connection teardown, rather
than in the directory work itself:

- `smartlist_remove(active_linked_connection_lst, conn)` on every linked
  connection as it is deactivated/torn down, and
- the `connection_array` absence scan inside `connection_free_()`
  (`smartlist_contains`), run once per freed connection.

Each BEGIN_DIR stream is two connections (the exit conn and its linked dir
conn), both added and freed, so a high rate of short-lived BEGIN_DIR streams
turns these O(n) scans into the dominant main-thread cost: in one sustained
low-output-flood capture the two scans were ~90% of that thread's userspace
samples, and in a synthetic scaling benchmark draining a pass of closures cost
up to hundreds of millions of pointer comparisons.

We prepared the obvious fix — track each connection's position in the
closeable and active-linked lists (as `conn_array_index` already does for the
main array), clear the array index on removal, and make the membership checks
and removals O(1) — and then found that `main` already has it:
`b035c0f5 "mainloop: Index global connection lists and membership checks"`
(thank you). We also independently reached the same refuse-BEGIN_DIR-before-
allocating change that `142b3d44 "dos: Rate limit BEGIN_DIR per circuit"` /
`cc22fd44` implement, including placing it ahead of the hibernation check and
keeping `END_STREAM_REASON_MISC`.

So this is confirmation rather than a patch: two independent analyses of the
same flood converged on the same change, and it is already merged. Two small
notes from our backport to 0.4.9.14, in case they are useful:

1. Our version `tor_assert()`s on an inconsistent index; `b035c0f5` logs a
   non-fatal `BUG()` and self-heals with an `smartlist_pos()` search. The
   self-heal is the safer production choice and we are adopting it; just
   flagging that the assertion variant did catch a couple of test-only call
   sites that add to `get_connection_array()` without setting the index
   (`test_conflux_pool.c`, `test_hs_client.c`), which `b035c0f5` also fixes.
2. `sizeof(connection_t)` is unchanged on 64-bit (the two new ints fill
   existing padding), which may be worth noting in the commit's "two
   additional integer fields" tradeoff line.

Happy to share the scaling benchmark (real-lifecycle, counts the full-list
comparisons `smartlist_remove` actually does) if it is useful for a regression
guard.

— (operator)
