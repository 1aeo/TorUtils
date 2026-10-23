# Adversarial review of the `+tor41339.7` series

The `.7` series went through two review rounds on 23 October 2026.

- **Round 1** reviewed the nine commits that the first `.7` added on top of
  `.6`. Five reviewers took part: a first full-series pass, then four in
  parallel, each with its own lens (bugs and edge cases; upstream readiness;
  mutation testing; docs and tools).
- **Round 2** began by closing round 1's open items across the whole series.
  That meant metric names, gating the per-cell work on a MetricsPort,
  merging the `changes` files, and three 0014 items from an earlier round.
  Three reviewers then went over all 23 commits again: bugs and edge cases,
  upstream readiness, and mutation testing.

Every finding was checked against the code. Every accepted fix is folded
into the commit it belongs to, so `../patches/0001`–`0023` are the reviewed
series. The packages carry one more, Debian-only patch (0024, below).

Patch numbers here are the final ones. Round 2 folded round 1's 0016 (a
heartbeat wording fix) into 0014. Round 1's 0017–0024 are therefore now
0016–0023.

## Round 2: what was asked, and what changed

### Metric names

**Recommendation, now applied:**
- counters are `tor_relay_<subsystem>_<singular noun>[_<unit>]_total`;
- gauges have no `_total`;
- each subsystem has one prefix:
  - `begindir_` for everything about tunneled directory streams;
  - `hsdir_` for onion service descriptor requests;
  - `<cell>_cell_` for cells;
- dimensions are labels, never parts of the name.

**Why:**
- **Stock tor's own families.** The newer families in `relay_metrics.c` are
  singular:
  - `tor_relay_destroy_cell_total`, `drop_cell_total` and
    `circ_proto_violation_total` (2024, 5a5ca444c8);
  - `tor_relay_exit_dns_query_total` (2021);
  - `tor_relay_est_intro_total` and `intro1_total` (2023).

  The plural ones are older: `streams_total`, `connections_total`,
  `circuits_total` (2022). Stock pairs the counter
  `tor_relay_connections_total` with the gauge `tor_relay_connections`.
  Stock isn't uniform: its gauges `tor_relay_circuits_total` and
  `tor_relay_load_socket_total` carry `_total`, and the counter
  `tor_relay_traffic_bytes` lacks it. The series follows the newer, consistent
  pattern and doesn't copy those exceptions.
- **The Prometheus naming guide** (`docs/practices/naming.md` in
  prometheus/docs), which tor's MetricsPort format follows:
  - a single-word application prefix (`tor_`);
  - `_total` on accumulating counters only;
  - plural base units (`_bytes`), but no rule about pluralising the counted
    thing;
  - name parts ordered so related families sort together, for example
    `begindir_request_total` next to `begindir_request_over_max_total`;
  - `sum()` or `avg()` over a family's labels should mean something, so
    label names don't belong in metric names.

**What was renamed.** Each rename was made in the commit that introduced the
name (`git filter-branch`), so no commit ever exports an old name.

| Before | Now |
|---|---|
| `tor_relay_hsdir_get_total` | `tor_relay_hsdir_fetch_total` |
| `tor_relay_hsdir_post_total` | `tor_relay_hsdir_upload_total` |
| `tor_relay_dir_requests_total` (`.6`), `tor_relay_begindir_requests_total` (first `.7`) | `tor_relay_begindir_request_total` |
| `tor_relay_dir_responses_total` | `tor_relay_begindir_response_total` |
| `tor_relay_dir_server_conns` (gauge) | `tor_relay_begindir_connections` |
| `tor_relay_begindir_over_max_requests_total` | `tor_relay_begindir_request_over_max_total` |
| `tor_relay_hsdir_fetch_target_total` | `tor_relay_hsdir_fetch_descriptor_total` |
| `hsdir_fetch_descriptor_total{lookup="missing"}` | `{lookup="not_found"}`, as in `hsdir_fetch_total{action="not_found"}` |
| `tor_relay_dos_total{type="hsdir_request_total"}` | dropped (see the upstream review below) |

- **C identifiers:** the C identifiers new in the series now follow the
  metric names. For example, `RELAY_METRICS_NUM_BEGINDIR_REQUESTS`,
  `fill_begindir_conns_values`, `RELAY_METRICS_NUM_HSDIR_FETCH_DESCRIPTORS`
  and `DOS_DIR_STAT_COUNT`.
- **Kept on purpose:** `HSDIR_GET_*`, `HSDIR_POST_*` and
  `relay_increment_hsdir_{get,post}_action()`. They mirror the HTTP handlers
  that call them, and the `hs_get`/`hs_post` request types.
- **0016's change to the requests family:** it extends 0007's family in
  place. The family keeps its key and its place in the scrape; only its help
  text and fill function change.

Breaking `.6`'s names was accepted, since every relay moves to `.7`.
`operator/begindir-breakdown.py` reads `.6`, first-`.7` and final-`.7` dumps
alike.

### Skipping per-cell work without a MetricsPort

**"It's not used anywhere, yes?" Yes.**
- The relay metrics store is filled only by `metrics_get_output()`, which only
  the MetricsPort connection handler calls (`metrics.c`).
- The heartbeat reads only four of the counters: `begindir_over_max`,
  `hsdir_circ_reused`, `hsdir_unknown_prev_hop` and `hsdir_fetch_shed`.
  Those four are plain increments.
- No control-port command reads any of them.

**Now gated on `get_options()->MetricsPort_set`:**
- **0020:** per-source counting, which costs a geoip lookup and a minute
  window per client CREATE or BEGIN_DIR cell.
- **0021:** the per-descriptor table, which costs a siphash and a probe of a
  4096-slot table per descriptor fetch.
- **0023:** the BEGIN_DIR stream-rate shadow bucket, which costs a refill per
  BEGIN_DIR cell.

**Deliberately not gated:**
- **Plain counter increments.** An array increment costs no more than the
  check would.
- **The previous-hop class.** It is set once per circuit, at its CREATE cell,
  with one known-relay lookup for a CREATE cell from a relay. Gating it would
  leave circuits unclassified if a MetricsPort is added later by SIGHUP. The
  `single_hop`/`circuit_dead` split depends on it.

**What the tests check.** New tests confirm that without a MetricsPort the
gated paths count nothing and keep no per-source or per-key state.

**The gate follows the option, not the listener.** The bugs review found a
stock tor bug where these can differ: after a SETCONF that fails to bind,
tor can reopen a MetricsPort from a stale port list while `MetricsPort_set`
is 0. The three gated families then stop counting while being scraped. The
trigger is narrow; see "Stock tor bugs" below.

### `changes` files

The 22 per-patch files are now five. Each commit adds or edits its own entries,
so every commit's tree describes what that commit has.

| File | Patches | Kind |
|---|---|---|
| `changes/ticket41339_http_log` | 0001 | bugfix ("on all supported versions"), can be backported alone |
| `changes/ticket41339_download_credit` | 0005 | bugfix ("on 0.4.8.14"), can be backported alone |
| `changes/ticket41339_hardening` | 0002–0004, 0015 | minor features |
| `changes/ticket41339_metrics` | 0006–0010, 0016–0023 | minor features |
| `changes/ticket41339_dos` | 0011–0014 | minor features |

Round 2 first merged them into three files. The upstream reviewer pointed out
that the hardening file tied the two backportable bugfixes to four features,
so 0001 and 0005 got their own files.
- **Headings** say "denial-of-service" throughout.
- **Feature entries** end "Part of ticket 41339."
- **Bugfix entries** end "Bugfix on …; related to ticket 41339."

All five pass `lintChanges.py`.

### The three 0014 items from an earlier review

- **The option is renamed:** `HSDirDescriptorFetchLimit` (torrc option and
  consensus parameter) is now `HSDirFetchShedding`.
  - *Why:* it doesn't limit anything per descriptor. It sheds fetches while
    the HSDir is asked for more descriptor bytes than `HSDirFetchBudget`.
  - *The Debian packages* add one Debian-only patch,
    `engineering/deb/build-reordered/debian-patches/0024-…`. It is one line in
    `option_abbrevs_[]`, so a torrc that still says
    `HSDirDescriptorFetchLimit` keeps working, with tor's usual deprecation
    warning.
  - *Not for upstream:* the option was never released there.
- **Wording:** the budget is described as descriptor bytes *asked for*, not
  sent. This is the case in the man page, the option comments, `changes` and
  the commit message.
- **The lottery test gap:**
  - A new test changes `HSDirFetchBudget` in the middle of a second. The
    shedding decision, the lottery odds and the share answered first must
    all come from the previous second's budget.
  - Byte-exact boundary tests cover asked = budget + 1, the 1.5× ceiling
    and the half-budget share. Before, every test fetch was a multiple of
    100 bytes, so an off-by-one at these boundaries passed.
  - A test where the bytes within their rate exceed half the budget pins
    the odds' answered-first term. Another sheds fetches within their rate
    at the ceiling: their bytes count towards the odds because they were
    asked for, whether or not they were answered.

## Round 2 review: findings and what was done

### Bugs and edge cases

The bugs reviewer found nothing high or medium, and four low or nit findings,
each with a reproducer:
1. **Low, stock tor:** a MetricsPort can serve while `MetricsPort_set` is 0.
   See "Stock tor bugs". Nothing to change in the series.
2. **Low, stock tor:** `GETCONF HSDirDescriptorFetchLimit` always reads as
   unset. Every stock abbreviation behaves the same; see "Stock tor bugs".
   With the Debian packages, query the new name. Everything else about the
   alias works: the torrc with its deprecation warning, the command line,
   SETCONF, RESETCONF and `--verify-config`.
3. **Low, tests:** the `tor_relay_dos_total` labels were read by no test,
   and six tests passed while reading a series that no longer existed.
   - *Why the labels:* tests read `hsdir_req_reused`,
     `hsdir_unknown_prev_hop`, `begindir_over_max` and the then
     `hsdir_request` only through `dos_get_dir_stat()`.
   - *Why the six tests:* the read helper returned −1 on both sides of a
     comparison.
   - *The fix:* `get_metric()`, `get_metric2()` and `get_dos_metric()` now fail
     on a missing series, and the tests read those labels by name. This went
     into 0006, 0010, 0016 and 0017, where each helper and read starts.
4. **Nit:** 0014's budget-change test didn't pin the answered-first share to
   the old budget. Fixed by the test described above.

**Checked and found correct:**
- *The MetricsPort flag* equals "a MetricsPort is configured" for startup,
  SIGHUP, SETCONF, RESETCONF and a reload that fails validation.
- *The renames* leave no old name anywhere: code, strings, consensus
  parameters, log and heartbeat text, the man page, `changes`, tests and
  commit messages.
- *0014's logic* holds:
  - in second 0 and in idle seconds;
  - with the budget captured once per second;
  - for the odds (bounded, no overflow) and the 1.5× ceiling;
  - with counting-only mode mirroring enforcement.
- *Every commit's `changes` and man page* name only families, labels and
  options that exist in that commit.
- *The counting invariants:*
  - every BEGIN_DIR request is typed exactly once, and DirPort connections
    are excluded;
  - the prev_hop class set at CREATE equals `channel_is_client()` at
    request time;
  - no bit-field or count can overflow;
  - bridges skip the per-source and per-descriptor counts.

### Upstream readiness

The verdict was "not mergeable as is, though the code is close". The code
passed check-spaces, check-includes, check-changes and check-docs, with the
same practracker problem locations as stock.

| Item | Done |
|---|---|
| Drop the dos type `hsdir_request`. Every stock `dos_total` type is a defense event, and this one was a request total that other families give exactly (`hsdir_fetch_total` + `hsdir_upload_total` − `single_hop` − `circuit_dead`). | yes, in 0010 (−9 lines) |
| `lookup="missing"` → `"not_found"` | yes, in 0021 |
| 0016 should change 0007's family in place: final key and fill-function names in 0007, so that 0016 changes only the help text and the fill body. | yes |
| Rename the C identifiers new in the series to match the metric names. | yes (see above) |
| Remove 0021's `relay_note_hsdir_fetch_target()` stub from `relay_stub.c`. It is called only from `dircache.c`, which is built only with the relay module. Checked with `--disable-module-relay --enable-fatal-warnings`. | yes |
| Restore the stock blank line that 0016 deleted. | yes |
| Remove 0017's redundant `circuit_over_rate` assert. `dos/cc_over_rate` checks the export. | yes |
| Saturate the per-descriptor count at `NTH_BAND_MAX` like every other band count. Rename `DOS_DIR_STAT_MAX` to `_COUNT`. | yes |
| Give the backportable bugfixes their own `changes` files. Use one heading style and one attribution style. | yes |
| Name one counter per defense in the man page, or none. Fix 0019's ragged wrap. | yes: HSDirOneRequestPerCircuit → `hsdir_circ_reused`; HSDirRefuseUnknownPrevHop → `hsdir_unknown_prev_hop`; DoSBeginDirLimitEnabled → `begindir_over_max` |
| Doc comments on the six new functions in `relay_metrics.c` that had none, as stock's `fill_est_intro_cells()` has none, and on their tables. | yes |
| The test hard-coded the per-descriptor table's 4096 slots. | yes: `FETCH_TARGET_SLOTS` and `FETCH_TARGET_PROBES` are in `relay_metrics.h` under `RELAY_METRICS_PRIVATE` |
| 0002's commit message had a 73-column line. | yes |

**Declined, with reasons:**
- **Make `begindir_response_total`'s `type` the request type**, as in the
  other `begindir_*` families.
  - The family counts responses fully handed to their stream. Its
    `hs_descriptor` value pairs with `hsdir_fetch_total{action="success"}`,
    which counts responses queued. The difference is the descriptors
    abandoned before they were handed off, which is the case 0005 is about.
  - Keying by request type would fold 404s into `hs_get` and lose that
    identity.
- **Rename `hsdir_req_reused` and `hsdir_circ_reused` to spell out "request"
  and "circuit", and `begindir_connections` to `begindir_streams`.**
  - The reviewer marked these optional.
  - Stock abbreviates too (`conn_rejected`, `circ_proto_violation_total`).
  - `begindir_connections` mirrors stock's `tor_relay_connections` gauge.
  - The two dos types are deployed with `.5` and `.6`.
- **Put the final request classification in 0007**, so that 0016 adds only
  `prev_hop` and 0018 only the byte hook.
  - Reviewers would read the classification once instead of three times.
  - But it rewrites 0007, 0016 and 0018 wholesale, for an identical tip. It
    is best done when the series is cut into merge requests (below).
- **Drop 0023's gate.**
  - Skipping per-cell work without a MetricsPort is what the gates are for.
  - 0023's refill runs per BEGIN_DIR cell, unlike the plain counters the
    reviewer compared it with.
- **Fold `note_hs_dir_request()` into `allow_hs_dir_request()`** (−12 lines).
  - 0010 is count-only, and 0011 adds the refusals.
  - Folding the two would put 0011's enforcement into 0010.
- **Route 0018's byte hook through `rephist.c`** to save one practracker
  include and a stub.
  - The bytes belong to the request-type family that `relay_metrics.c` owns.
  - Stock's `connection.c` already includes three `feature/relay` headers.
- **Split 0016 and move 0018's split of `other`.** Both are part of cutting
  merge requests (below).
- **Smaller items, left as they are:**
  - *Declaring two locals after the early-return gate:* they sit before the
    gate, as in the surrounding code.
  - *Sharing `get_metric()` and `get_dos_metric()`:* they are a few lines
    each, in two test files. Sharing them would need a new test-helper
    API.
  - *Moving the relay-metrics tests out of `test_hs_cache.c`:* the reviewer
    wouldn't block on it.
  - *Decoding the key once in `handle_get_hs_descriptor_v3()`:* it saves no
    lines and would need a new `hs_cache` helper.
  - *Trimming HSDirDescriptorFetchRate's man-page sentence that points to
    HSDirFetchShedding:* the reader of that option needs it.
- **Checked and kept:** 0016's message says "42 more series". That is the
  net count:
  - `create_cell` adds 3, `begindir_cell` adds 15 and the requests family
    adds 24;
  - 0007's 2 request series go;
  - `circuit_dead` adds 1 to each of the two HSDir families.

### Mutation testing

- **Coverage.** 343 mutants cover every production line that round 2 added or
  changed, concentrated in 0014 (96), 0021 (63), 0020 (53), 0016 (36) and
  0023 (26).
- **Results.**

  | Result | Mutants |
  |---|---|
  | Killed by the series' tests | 274 |
  | Survived, now killed by a new test | 25 |
  | Equivalent, each with a stated reason | 36 |
  | Doesn't build (killed under `-Werror`) | 8 |
- **The 25 gaps:**
  - The MetricsPort gates of 0020 and 0021 had no test without a
    MetricsPort.
  - 0020's NULL-channel check had none either.
  - The four families renamed from `.6` had no test of their counter or
    gauge type.
  - The dos labels were read by no test (finding 3 above).
  - 0014 had the byte boundaries, the budget changes, and the bytes asked
    within their rate but shed, described above.
  - 0021's probe window had to wrap at the end of its table. A mutant that
    didn't wrap was caught only by chance, through out-of-bounds writes under
    some siphash keys. The probing test now starts its keys at the table's
    last slot.
- **Every gap test is in the series.** Mutants R2-DT-01 and -02 were on the
  dropped `hsdir_request` label, so 23 of the 25 still apply. Those 23 were
  re-targeted to the final code. Five more were added: three of round 2's
  killed mutants on the same lines, and two on the `not_found` label. All 28
  are killed at the final tip.
- **One dead store, removed.** Two equivalent mutants (R2-NS-12, R2-FA-10)
  showed that 0014 set the lottery odds to one in a second that doesn't shed,
  where nothing reads them. The store is gone. R2-FA-10, which drops the
  early answer in such a second, is now killed by three tests, at the final
  tip like the 28 above.
- **No vacuous reads, whatever the siphash key.**
  - A check added to the test helpers found no lookup that matched zero or
    several series.
  - The hs_cache and dos groups passed 20 runs, each with a new random
    siphash key.
- **One round-1 verdict changed.** Round 1 called swapping two
  `channel_prev_hop_t` values equivalent. Since `CHANNEL_PREV_HOP_COUNT`
  became `CHANNEL_PREV_HOP_UNKNOWN_RELAY + 1`, that mutant is killed.

## Stock tor bugs found (not changed by the series)

Both are in stock 0.4.9.14 code that the series doesn't touch. They were
reproduced with a loopback-only tor and a unit test. The proposed fixes are
in `../engineering/v7-review/round2/stock-bugs/`.

1. **A failed options change leaves the listener list stale.**
   - *Cause:* `options_start_listener_transaction()` replaces
     `configured_ports` with the new options' ports. The rollback in
     `set_options()` restores the old options, but not that list.
     `retry_listeners_callback()` then reopens listeners from the stale list
     every 60 seconds.
   - *Trigger:* SETCONF, RESETCONF or LOADCONF that validates but then fails
     to bind (a failed SIGHUP makes tor exit instead).
   - *Effect:* a MetricsPort the operator didn't get can open about a minute
     later, while `GETCONF MetricsPort` says it is unset. It can be read only
     if the old config already had a MetricsPortPolicy.
   - *Fix:* re-parse the old options' ports on rollback. With it, the same
     scenario leaves the port closed, and config/, options/ and control/
     pass.
2. **GETCONF of an abbreviation reads as unset.**
   - *Cause:* `handle_control_getconf()` accepts the key through
     `option_is_recognized()`, which expands abbreviations. It then reads the
     value through `config_get_assigned_option()`, which doesn't.
   - *Effect:* the answer has no value, and tor logs "Unknown option".
     Example: `GETCONF SocksSocketsGroupWritable` answers
     `250 UnixSocksGroupWritable` while it is 1.
   - *Fix:* one line, `config_expand_abbrev()` before the lookup. With it,
     config/, control/ and options/ pass.

## Round 1 findings and fixes, by severity

**Medium. 0021 counted URL spellings, not descriptors.**
- *The problem.* `base64_decode()` stops at the first `=`, so
  `GET /tor/hs/3/<key>=0`, `=1`, … fetch the same descriptor. The counter
  hashed the raw URL text, so each spelling counted as a new descriptor.
- *Why it mattered.* A flood that adds a nonce would look like a sweep of many
  descriptors instead of one descriptor hammered. That is the very question
  0021 exists to answer.
- *The fix.*
  - `handle_get_hs_descriptor_v3()` decodes the key once, reusing the decode
    its found path already did, and the counter hashes the 32-byte key.
  - A key that doesn't decode counts as a first fetch, without touching the
    table.
  - A regression test fetches the found descriptor as `<key>=x`.

**Medium. 0017's lower bound on client addresses was wrong, twice.**
- *First,* it ignored the burst. Within its bucket an address can send
  `Burst + Rate·T` cells in T seconds, not `Rate·T`.
- *Second,* `dos_cc_new_create_cell()` returns before the bucket for a client
  address the geoip cache no longer tracks. Tor drops an entry a day or two
  after the address's last new connection, even while older connections from
  it stay open. Cells from such addresses were neither limited nor counted.
- *The fix.*
  - A count-only `circuit_untracked`.
  - The bound is now (client CREATE − `circuit_over_rate` −
    `circuit_untracked`) ÷ (Rate·T + Burst) over T seconds, on tracked
    addresses.
  - It holds only while `DoSCircuitCreationEnabled` is on, because neither
    counter counts otherwise.
- *What the review found about stock tor.* DoSCircuitCreation does not apply
  to these untracked addresses at all. A circuit flood over connections older
  than their geoip entry escapes it. `circuit_untracked` shows how much does.
  That is worth raising upstream.

**Low. 0020 treats an untracked address's channels separately.** Once an
address's geoip entry is dropped, each of its channels counts as its own
source until it opens a new connection. This is documented in the code
comment, the commit message and `changes`.

**Low. 0018 misses bytes still queued at close.** When a directory connection
closes with bytes still queued, `conn_close_if_marked()` moves them to the
stream without counting them. Stock tor's directory byte history has the same
gap. The family is described as bytes "read by their stream".

**Low, wording.**
- *0014's heartbeat* says "fetches selected for shedding". Fetches shed by
  the lottery pass no threshold, so "over the shed threshold" was wrong.
- *0021:* the table keeps hashes "until the first fetch of a later minute",
  not "for the current minute".
- *0022:* "for up to two days", not "about two days".

**Hygiene.**
- `CTASSERT`s check that the narrow bit-fields hold their values:
  `prev_hop:2`, `request_type:4`, and the `n_begindir:10` count, which stops
  at `NTH_BAND_MAX`.
- The commit messages match the code.

**Upstream-readiness changes, all accepted.**
- **Dropped families.** Two families were dropped, since the others give the
  same numbers:
  - `tor_relay_dir_requests_total`: each of its types was a sum of the
    requests family's types;
  - `tor_relay_begindir_streams_total`: stock
    `tor_relay_streams_total{type="BEGIN_DIR"}` has the total.
- **One set of bands.** One `nth_band_t` / `nth_band_of()` /
  `nth_band_names[]` replaces two sets of cut points and a ten-line if-chain.
  - *Before:* per circuit `1, 2_9, 10_49, 50_plus`; per source and per
    descriptor `1, 2_10, 11_100, 101_1000, 1001_plus`.
  - *Now:* the second set everywhere.
  - The per-circuit count moved into free bits, so `or_circuit_t` does not
    grow.
- **Header layering.**
  - `channel_prev_hop_t` is in `or.h`, and `source_minute_t` has its own
    `source_minute_st.h`.
  - `channel.h` doesn't include `dos.h`, and `rephist.h` doesn't include
    `channel.h`.
  - No practracker exception was raised.
- **Smaller changes.**
  - *Test-only code* moved out of `rep_hist_note_begindir_cell()`.
  - *One hook per CREATE cell* counts the per-source band too.
  - *One `fill_labeled_values()`* fills every two-label family.
  - *The tests* use the stock fake channels and helpers.
  - *Memory:* each tracked client address and channel costs 8 bytes, not 16.

**Docs and tools.**
- *The breakdown tool:*
  - prints the corrected bound (`--cc-burst`) and `circuit_untracked`;
  - divides by the real time between scrapes;
  - exits if a counter went backwards, which means the relay restarted;
  - reads every version's names.
- *PromQL:* the Q2 ratio needed `ignoring(type)`.
- *The install check* tests every new series' exact labels, and that the
  replaced families are gone.

**Considered and kept: bridges.** They export the aggregate counters
`create_cell_total{prev_hop="client"}`, `circuit_over_rate` and
`circuit_untracked`. On a bridge these describe its own users, which its
operator can already see. Bridges skip only the per-source and per-descriptor
bands.

## The series in numbers

| | First `.7` | After round 1 | After round 2 |
|---|---|---|---|
| New series against stock (install check) | 134 | 133 | 132 |
| New `tor_relay_dos_total` types | — | 12 | 11 |
| `.7`'s additions over 0015, production lines (net) | +772 | +675 | +680 |
| `.7`'s additions over 0015, test lines (net) | +817 | +1240 | +1353 |
| Whole series over stock 0.4.9.14, production / tests (net) | — | — | +1463 / +2974 |

Round 2 added 21 production lines and 198 test lines net across the whole
series.

## Verification of the final series

- **Per commit.** Each of the 23 commits builds in-tree with
  `--enable-fatal-warnings` and no warning. Each passes the whole unit suite
  (1596 to 1636 tests, 31 skipped) and `make check-spaces`
  (`../engineering/v7-review/round2/per-commit.txt`).
- **Repo checks at the tip.**
  - `check-includes`, `check-docs` and `lintChanges.py` pass.
  - The man page renders with asciidoc without a warning, metric selectors
    and all.
  - practracker reports the same problem locations as stock 0.4.9.14.
- **Without the relay module.** At the tip, the tree builds with
  `--disable-module-relay --enable-fatal-warnings` and passes the whole unit
  suite.
- **`git am`.** The series applies onto `tor-0.4.9.14`, giving the identical
  tree, and onto `main` (`8dbbbe6e86`). So does the Debian alias.
- **Mutants.** The 29 re-targeted mutants above are killed at the tip
  (`../engineering/v7-review/round2/gap-mutants-final.tsv`).
- **Packages, install check and labs:** see
  `../engineering/deb/README.md` and `../packages/BUILD-INFO.txt`.

## Still open (for upstream submission)

- **Cut the merge requests from `main`.**
  - Split into hardening (0001–0005, with 0015), the metrics, and the
    defenses (0011–0014).
  - In the same pass:
    - move the final request classification into 0007;
    - split 0016's `single_hop` → `circuit_dead` change into its own commit,
      since it changes an exported value;
    - move 0018's split of `other` next to the request types.
- **Ticket numbers.**
  - Open tickets for the two bugfixes (0001, 0005), so that their `changes`
    entries can say "Fixes bug N".
  - File the two stock bugs above.
- **Metrics documentation.** tor#40762 asks for metrics documentation to land
  with the metrics. The family descriptions in `changes`, the `.help` strings
  and `../operator/BEGIN_DIR-BREAKDOWN.md` are the material.
- **The cleanup-indexing work.** It moves `dos_should_refuse_begindir()` ahead
  of the stream allocation, and must keep 0019's stream mark and 0023's
  shadow bucket (`cleanup-indexing-interaction.md`).
- **DoSCircuitCreation and untracked addresses.** Raise upstream that
  DoSCircuitCreation doesn't apply to client addresses tor no longer tracks
  (round 1).
