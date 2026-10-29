# A smaller series, and its review (`+tor41339.9`)

`.9` is `.8` with less code: the same 20 patches on tor 0.4.9.15, the same
options and defaults, and the same MetricsPort series. It also has the fixes
from a three-lens adversarial review of the smaller series, listed below with
the five changes of behavior they make. This directory has the record.

## What got smaller

Lines changed per patch (added plus removed), `.8` → `.9` (`sizes.txt`):

| Patch | All | Production code | Tests |
|---|---|---|---|
| 0001 | 48 → 48 | 14 → 14 | 27 → 27 |
| 0002 | 53 → 53 | 9 → 7 | 39 → 40 |
| 0003 | 83 → 92 | 17 → 10 | 63 → 79 |
| 0004 | 63 → 50 | 44 → 31 | 14 → 14 |
| 0005 | 131 → 109 | 29 → 27 | 96 → 76 |
| 0006 | 293 → 281 | 161 → 162 | 126 → 113 |
| 0007 | 210 → 398 | 125 → 191 | 78 → 197 |
| 0008 | 110 → 103 | 47 → 46 | 60 → 54 |
| 0009 | 102 → 102 | 102 → 102 | 0 → 0 |
| 0010 | 130 → 122 | 49 → 49 | 76 → 66 |
| 0011 | 286 → 260 | 92 → 93 | 173 → 146 |
| 0012 | 186 → 173 | 66 → 63 | 101 → 91 |
| 0013 | 727 → 667 | 202 → 188 | 480 → 434 |
| 0014 | 54 → 37 | 9 → 7 | 40 → 25 |
| 0015 | 1001 → 586 | 349 → 205 | 639 → 374 |
| 0016 | 113 → 114 | 28 → 28 | 78 → 78 |
| 0017 | 272 → 127 | 107 → 50 | 159 → 74 |
| 0018 | 417 → 261 | 158 → 142 | 251 → 111 |
| 0019 | 372 → 287 | 108 → 107 | 256 → 172 |
| 0020 | 59 → 50 | 18 → 14 | 26 → 21 |
| **all** | **4710 → 3920** | **1734 → 1536** | **2782 → 2192** |

The rest of each count is the man page, the `changes/` files and
practracker's exceptions. 0007 grows because it now adds what `.8`'s 0015
and 0017 rewrote, and 0003 because of a review fix (below).

Where the lines went:

- **No more rewriting earlier patches.** `.8`'s 0007 counted requests as
  `non_hs` or `unparsed`. 0015 rewrote that into the request types, and 0017
  split `other` into `other_get` and `other_post`, each time redoing the URL
  table, the call sites, the enum and the close path. 0007 now adds the final
  request types once, with the four bits of state 0017 used; 0015 only adds
  the previous hop, and 0017 only the bytes. `fill_labeled_values()` takes
  its final arguments from 0006 on, so no later patch changes its callers.
- **Reusing tor 0.4.9.15.** The per-descriptor fetch bucket (0012) uses
  0.4.9.15's `dos_stream_bucket_consume()`, and 0013 reuses 0012's function
  instead of a copy of its own.
- **One lookup, one helper.** 0010's counter and 0011's refusal of unknown
  previous hops are one function, with one known-relay lookup per request
  instead of up to four, and one test at each call site.
- **Plainer patches.** 0004 moves the existing signature-length check
  instead of wrapping it in a new helper, and looks the signature up once.
  0002 sets the body limit in three lines. 0003, 0005 and 0014 keep the
  reasoning in their commit messages and a short comment in the code. 0006
  maps the upload result in one line. A response is counted by a function
  that takes the connection, so the response type enum is gone. The
  previous-hop enum has no value that only tests used, so the labeling
  helper doesn't skip one. 0017 counts the bytes of a request that has no
  type yet in a slot that isn't exported, instead of testing for it. 0018's
  three-field struct is in `or.h` instead of a header of its own. 0020 drops
  an include it made unnecessary.
- **Tests.** Each test forks, so it starts with every counter at zero; the
  tests now check absolute counts instead of reading each counter first.
  The one exception is the request type `other_get`: three stock
  `dir_handle_get` tests run unforked on tunneled connections and fetch
  `/tor/networkstatus-bridges`, so the URL-table test checks it by its
  deltas. Every test that needs a channel uses `test/fakechans.h`'s fake
  channel, so no test mocks the channel's address or description or clears
  each circuit's previous hop before freeing it. Nine tests are gone: eight
  folded into tests that set up the same state, and one whose checks
  another test already made. The tests share
  `hsdir_request_on_new_circ()` (which now returns the answer's status),
  `DOS_METRIC()`, `metric_has_type()`, stock tor's
  `helper_get_hsdir_query()`, and one helper for an HS POST of any declared
  and sent length. The URL-table test moves from 0015 and 0017 into 0007,
  with the request types. A test reviewer proposed these changes for `.8`'s
  tests and checked them against 44 mutants of the production code (every
  mutant the old tests killed, the new ones kill).

## The review

Three reviewers each read the smaller series with one lens:
- correctness and edge cases;
- regressions against stock tor with every default;
- metrics accounting and docs.

None built or ran it. None found a crash, use-after-free, NULL dereference,
out-of-bounds index, overflow or division by zero, or a change that breaks
any role with the defaults. They found the following, and every item has a
test or doc change in the commit named.

**Fixed in the code (the five changes of behavior from `.8`):**

1. **0007: a stream that closes before sending anything was counted as
   `circuit_dead`, not `no_request`** (two reviewers). When a client ends
   such a stream, its directory connection sees EOF and is processed once
   more, and `directory_handle_command()` counted any connection whose
   stream was gone as `circuit_dead` before looking at its input. So
   `no_request` counted only connections that timed out themselves. It is
   now `no_request` when nothing arrived, and `circuit_dead` only for a
   request or part of one.
2. **0013: while shedding, the ceiling of one and a half times the budget
   came before the fetches within their descriptor's rate.** Fetches that
   won the lottery early in the second could fill the ceiling, and the
   "answered first" fetches arriving later were then shed. Now those are
   answered first whenever they arrive, up to half the budget, and the
   others stop at the budget, so the total still stays within one and a half
   times the budget.
3. **0011: `HSDirRefuseUnknownPrevHop` refused with a 503** (two reviewers).
   A stock client then avoids that relay as a directory server for an hour
   (`DIR_503_TIMEOUT`) and skips its HS_DESC FAILED event; 0013 already
   avoided a 503 for that reason. It now closes the circuit without an
   answer, as tor's limit of one HSDir request per circuit does, and clients
   retry at another HSDir.
4. **0018: 8 more bytes per tracked client address, and per channel, paid
   with or without a MetricsPort.** The per-source state is now 32 bits (the
   minute modulo 4096 and two 10-bit counts) in what was padding, so no
   struct tor allocates per client, channel, circuit or connection grows
   (`struct-sizes.txt`). A source silent for a multiple of 4096 minutes
   (about 68 hours) carries its counts over.
5. **0003 discarded input on DirPort connections too.** There, each write a
   slowly reading client allows restarts the stall timeout, so such a client
   could keep sending forever, where stock tor closes it at 10 MB. Only
   tunneled (BEGIN_DIR) connections discard it now, and its test checks
   that a DirPort connection keeps the input.

**Fixed in the docs:**

- 0019's message said the key is decoded once, before the lookup; it is
  decoded right after, for misses too. Its `found` also counts the fetches
  that shedding then refuses, which its message now says.
- 0010's message, its `changes` entry and `dos.h` called the requests it
  counts ones "that tor accepts"; from 0011 on, some are refused.
- 0013's message said a flood over many descriptors, each within its rate,
  is shed by the lottery. Those fetches are within their rates, so they share
  the first half of the budget with the other fetches within theirs.
- `dos.h`: `hsdir_fetch_pressure` also counts the second after one over the
  budget, and `hsdir_descriptor_only_prev_hop` isn't a subset of
  `hsdir_unknown_prev_hop`.
- 0019: some keys find no slot in the 4096-slot table well before it is
  full, because a key may land at most 16 slots after its own: 0.04% of keys
  with 2,000 distinct keys in a minute, 1.1% with 3,000 and 8.6% with 4,096
  (`fetch-table-sim.txt`). A sweep, or fetches of random keys meant to fill
  the table, can make the later bands undercount repeats. Its `changes`
  entry also said the table is cleared "in a later minute": it is cleared
  by the first fetch counted in one.
- 0016: on a bridge, clients that connect over a pluggable transport have a
  geoip entry only under the transport's name, which `DoSCircuitCreation`
  doesn't look up, so their CREATE cells count as `circuit_untracked`.
- 0002: an oversized upload is closed without an answer, which its
  `changes` entry now says. 0007's entry says such a request counts as
  `unparsed`, since it never reaches `tor_relay_hsdir_upload_total`.
- 0013's man page: fetches refused before the budget is checked aren't
  counted towards it.
- 0008: the gauge's help text says streams, which is what it counts.

**Left as they are:**

- Relays that aren't public count `hsdir_unknown_prev_hop` and
  `hsdir_fetch_shed` but never refuse. Stock clients and services pick
  HSDirs from the consensus, so such relays see no onion service requests
  from them.
- Bridges export the aggregate families, as stock tor exports its own, but
  not the per-source and per-descriptor ones, which describe single users.
- Every heartbeat names the two new defenses (`[HSDirRefuseUnknownPrevHop
  disabled]`), and several new `tor_relay_dos_total` types count what a
  defense sees rather than what it refuses, as stock's
  `[DoSCircuitCreationEnabled disabled]` and `marked_address` do.
- `begindir_response_bytes_total{type="no_request"}` and
  `{type="circuit_dead"}` stay at 0: those requests get no answer, and the
  family keeps the request types' labels.
- 0001 and 0014 change which directory-client messages are warnings, as
  their messages say.
- The `dir_conn_is_closing()` checks in the HS handlers can't fire, because
  `directory_handle_command()` checks first. That is tor 0.4.9.15's code.

## Checks

- **`per-commit.txt`:** every commit, built with `--enable-fatal-warnings`:
  - no compiler warning;
  - `check-spaces` and `lintChanges.py` clean;
  - the full unit suite passes: 1605 to 1632 tests, 31 skipped.
- **`practracker.txt`:** after every commit, practracker reports the same 98
  problems as stock 0.4.9.15, and `checkSpace.pl` and `lintChanges.py` find
  nothing in the files the commit changes. Three exceptions change:
  - 0007 raises `directory_handle_command_post()`'s from 124 to 138 lines,
    and 0010 to 139;
  - 0013 raises `dos.c`'s dependency-violation count from 6 to 8.
- **Applying the patches:**
  - `git am` onto `tor-0.4.9.15` gives the branch's tree exactly;
  - `git am -3` onto tor `main` at a0062a3e3e (2026-10-28) applies all 20.
- **At the tip:**
  - `check-includes` and `check-changes` pass, and `check-logs` reports what
    it reports on stock;
  - `check-docs` finds every option the series adds in the man page, and
    lists only stock tor's undocumented options;
  - `check-best-practices` exits with practracker's 98 problems, as on stock;
  - with `--disable-module-relay`, the tip builds with no warning and passes
    the unit suite (1632 tests, 31 skipped).
- **`mutants.tsv`:** 31 mutants of the lines the minimization and the review's
  fixes changed, each killed by the unit tests. They cover:
  - the request types, the close path and DirPort connections (0007);
  - `HSDirRefuseUnknownPrevHop`, its counter and how it refuses (0011), and
    the descriptor-only split (0020);
  - the per-descriptor bucket (0012) and shedding (0013);
  - the response bytes (0017) and the previous-hop counts (0015);
  - the body limits, the input discard on tunneled connections only, the
    signature-length check and the upload results (0002 to 0006);
  - the per-source counts' last band and minute (0018).
- **`struct-sizes.txt`:** no struct that tor allocates per client, channel,
  circuit or connection is larger than in stock 0.4.9.15.
- **`fetch-table-sim.txt`:** how many keys of a minute find no slot in 0019's
  table, by the number of distinct keys (`fetch-table-sim.py`).
- **Packages** (`../../packages/`, `../deb/README.md`): `+tor41339.9` for
  Ubuntu 24.04 and 26.04 builds with no warning on a line the series adds,
  passes the unit suite (1639 tests, 24 skipped) and the install check, and
  runs the live controls, which switch each defense on and off; the
  breakdown lab checks the operator tool against the 24.04 package. Both
  `tor` binaries are byte-identical to the ones built before the last edit
  of the commit messages, and the install checks and labs ran on both
  builds.
