# Metrics for the next build: more data for little code

This note merges every metrics request so far into one proposal:

- the network team's four questions (`begindir-questions.md`);
- the first ten-question review (`metrics-coverage.md`);
- a second ten-question review, written against live `.6` data, whose
  numbering §5 follows;
- the operator critique of `flood-cost-and-constrained-hosts.md`;
- the design judges' and verifiers' notes on 0016;
- a stock profile that put 90.5% of sampled main-thread user CPU in global
  connection-cleanup scans.

None of the additions below is built. 0016 and 0017 themselves are built
and tested, but in no package (`patches/proposed/`). The `.6` rollout adds
no telemetry; whether the next build carries any of this is a separate
decision (§7).

The approach: 0016 already hooks five places (a CREATE cell, a BEGIN_DIR
cell, an accepted BEGIN_DIR stream, a parsed request, and a closing
directory connection). Record more at those five, and add only two new
kinds of hook:

- the point where stock tor already counts directory response bytes;
- a once-a-second tick.

0016 and 0017 are in no package yet, so their names and labels can still
change without breaking anyone's dashboards. After a release, changing
them would break dashboards.

## 1. Onion service requests vs the rest, and empty streams

- **`.6`** splits every BEGIN_DIR stream three ways:
  - onion service requests (`hsdir_get_total`, `hsdir_post_total`);
  - parsed ordinary requests (`dir_requests_total{type="non_hs"}`);
  - everything else (`{type="unparsed"}`): malformed requests and streams
    that sent nothing, counted together.

  It does not split the ordinary requests further, and only onion service
  requests have a previous hop. In the latest `.6` interval, onion service
  and parsed ordinary requests were about equal in number, so "other" is
  about half the requests.
- **0016** counts every request once, by what it asked for and by previous
  hop. It has eight types (`hs_get`, `hs_post`, `consensus`, `microdesc`,
  `descriptor`, `other`, `unparsed`, `no_request`) and three classes
  (`client`, `known_relay`, `unknown_relay`).
- **An empty stream cannot be classed as onion service or other.** It
  never says what it wants. What can be measured is its context:
  - the previous-hop class (0016);
  - whether it was its circuit's first BEGIN_DIR (item 6);
  - whether 0012 would have refused it (item 6);
  - how long it stayed open (item 4): opened and dropped at once, or held
    until the five-minute stall timeout.

  An empty stream could be tied to an onion service request on the same
  circuit. That needs hooks at both stream close and circuit close, and
  they can run in either order. It is left out until a flood shows many
  empty streams on circuits that also carry onion service requests.

## 2. How many kinds of "other": eight

| Type | Requests (GET unless noted) | What answering costs | Who normally sends it |
|---|---|---|---|
| `consensus` | `/tor/status-vote/current/consensus…` without diff hashes | the largest response, a whole consensus, usually precompressed in the consensus cache | anyone without a recent consensus (a bootstrap), or a tool |
| `consensus_diff` | the same with diff hashes (`X-Or-Diff-From-Consensus`, or a `/diff/` URL) | a diff; a 304 if the requester is already current; a whole consensus if no diff exists | C tor, whenever its latest consensus is under 72 hours old (`try-diff-for-consensus-newer-than`) |
| `microdesc` | `/tor/micro/d/` | batches of microdescriptors, compressed as they are sent | clients, after each new consensus |
| `descriptor` | `/tor/server/`, `/tor/extra/` | relay descriptors, compressed as they are sent | relays that cache directory information; bridge users asking their bridge for its descriptor |
| `keys` | `/tor/keys/` | authority certificates, small | bootstrapping clients, and everyone after an authority key rotation |
| `other_get` | `/tor/`, `/tor/robots.txt`, the other `/tor/status-vote/` documents, the bandwidth file, `/tor/networkstatus-bridges` | short, and mostly a 404 except on an authority | rarely anyone, on a relay |
| `unknown_get` | any other URL (404) | one short response | probing, or broken software |
| `other_post` | POSTs other than onion service descriptors | one short refusal, except on an authority | rarely anyone, on a relay |

`hs_get`, `hs_post`, `unparsed` and `no_request` stay as they are, so there
are twelve types in all. `.6` has two buckets (`non_hs` and `unparsed`) for
everything that is not an onion service request.

**Why not fewer.** The eight differ in cost or in sender, and a flood made
of one of them calls for its own fix:

- whole consensuses call for a byte limit;
- junk 404s call for a per-circuit limit;
- diffs need no fix at all.

**Why not more:**

- The consensus flavor mostly repeats the previous-hop class: relays that
  cache directory information fetch both flavors, clients one.
- Whether a request got a 304, a 404 or a full answer shows in bytes per
  request (item 4).
- The remaining rare documents are cheap.

**Code.** 0016 already added a type column to the GET table (`url_table`);
the split changes values in that column. The rest is four new enum values
and their names, and one line in the consensus handler once it has parsed
the request. The dispatcher's count moves after the handler call, so the
handler's more specific type wins. 0016's once-only bit already guarantees
one count per request.

Bytes by type are the only way to see what these requests cost: stock
tor's "directory busy" 503 never applies to tunneled requests
(`flood-cost-and-constrained-hosts.md` §4), so a relay answers them however
short of bandwidth it is.

## 3. The proposal

"Answers" uses the second review's question numbers (§5). Line counts are C
without tests; tests have run to about the same length again. Series are
new MetricsPort series.

### A. Ship what is built

0016 and 0017 as they are: 45 series, one known-relay lookup per CREATE cell
from an authenticated channel.

### B. Recommended additions (about 300 lines, about 115 series)

Items 1–3 change 0016 before it ships.

| # | Addition | Answers | How |
|---|---|---|---|
| 1 | the eight kinds of "other" (§2) | 1 | as in §2 |
| 2 | split `known_relay` into `consensus_relay` and `descriptor_relay` | 5, 6 | see below the table |
| 3 | keep the request type on its directory connection (4 bits, replacing `request_counted`) | enables 4, 6 | the once-only rule becomes "type already set" |
| 4 | per request type: response bytes handed to the stream; responses abandoned (closed with data still queued); seconds open, summed | 1, 2, 9 | see below the table |
| 5 | CREATE cells by class, by outcome: accepted, completed, dropped (queue full), expired (waited too long); gauges for the onion queue's length and oldest wait, and the jobs at the CPU workers | 7, 9 | see below the table |
| 6 | per request type: requests on a stream that was not its circuit's first BEGIN_DIR; requests on a stream over 0012's limit, which in count-only mode is what 0012 would refuse | 4, 10 | one bit each on the directory connection, set when the stream is accepted |
| 7 | the busiest second for CREATE cells and for BEGIN_DIR cells in the last full minute | 4, 7 | the one-second tick takes per-second differences of 0016's counters |
| 8 | main-loop delay: the most the one-second tick ran late in the last full minute | 9 | the tick's own timing, on the monotonic clock |

How items 2, 4 and 5 work:

- **Item 2.** `connection_or_digest_is_known_relay()` already makes two
  lookups: is the relay in the consensus, and do we hold its descriptor.
  `channel_get_prev_hop()` would make them one at a time, so the split
  costs nothing. A relay the authorities drop stays `descriptor_relay` for
  up to about two days, then becomes `unknown_relay`.
- **Item 4.**
  - Bytes are counted where stock tor already counts directory bytes,
    `record_num_bytes_transferred_impl()`.
  - Abandoned responses and seconds open are counted in
    `connection_dir_about_to_close()`, where 0016 already counts.
  - Seconds have one-second resolution. Summed over many streams, they give
    an average.
  - An onion service miss is one short 404, so `hs_get` bytes are almost
    all hits.
- **Item 5.**
  - Accepted is counted in `command.c` after `or_circuit_new()`.
  - Dropped and expired are counted on `onion_pending_add()`'s two drop
    paths. Stock tor counts drops only from authenticated channels, and
    expiries not at all.
  - Completed is counted in `onionskin_answer()`, which both CREATE_FAST
    and CPU-worker replies reach.

Items 7 and 8 describe the last full minute whenever they are scraped, so
slow scrapes under load (tor#41458) don't hide them.

### C. Cheap extras (about 160 lines, about 45 series)

| # | Addition | Answers | How |
|---|---|---|---|
| 9 | circuits reaching 2, 10, 50 and 100 BEGIN_DIR cells, by class; circuits reaching 10 and 50 onion service requests | 4 | at 0016's BEGIN_DIR hook. Its per-circuit count widens from 6 to 7 bits, and 0010's from 2 to 6 |
| 10 | accepted BEGIN_DIR streams, by how many were already open on their circuit (0, 1–3, 4–15, 16–63, 64+) | 4 | 0012 already makes this count for every stream. It stops at the limit, 64 by default |
| 11 | bytes waiting: directory responses queued, by state; the totals that MaxMemInQueues is compared with, by subsystem (cell queues, buffers, compression, onion service cache, client address cache, DNS cache, half-closed streams), with the limit | 9 | 0008's scrape-time walk, and the OOM handler's existing O(1) totals. Stock exports only what the OOM handler freed |
| 12 | our consensus's valid-after, fresh-until and valid-until times; the process start time | 3, 6 | gauges of values the ControlPort already gives |
| 13 | each 0011–0014 option's value in effect, once "auto" is resolved from the consensus | 10 | gauges |

### D. Opt-in, after a privacy review (about 220 lines)

These describe individual peers or descriptors without naming them. On a
bridge or a quiet relay, one peer can be most of a number. They would sit
behind one torrc option, off by default, for the pilot only, and never in
extra-info.

| # | Addition | Answers | How |
|---|---|---|---|
| 14 | per class, for the last minute: how many channels sent a CREATE or a BEGIN_DIR, and the busiest channel's and busiest ten's share | 7 | two per-minute counters on each channel (8 bytes); a walk of the channel list once a minute |
| 15 | for the last minute: how many distinct descriptors were fetched (found and missing apart) and uploaded, and the largest one's and largest ten's share | 2, 8 | a distinct-count sketch and a top-ten table over a keyed hash of the blinded key. The key is random at each start, and only counts are exported; about 2 KB |

### E. Performance, not metrics (about 20 lines, plus a lab run)

Each connection tor closes costs five list scans (stock tor 0.4.9.14,
`mainloop.c:346-347`, `:419`; `connection.c:969-970`):

- three of the closeable list (connections closing in this loop
  iteration);
- one of the list of active linked connections;
- one of the whole connection array.

Each BEGIN_DIR stream adds two connections to that array: its exit
connection and its directory connection. When 0012 refuses a stream, it
frees an exit connection that was never in the array, and the free still
scans the whole array to confirm that.

| # | Change | Answers | How |
|---|---|---|---|
| 16 | cleanup indexing | 9, 10 | (a) `connection_remove()` resets `conn_array_index` to −1, and `connection_free_()` asserts on that instead of scanning the array: O(N) to O(1); (b) a bit for "on the closeable list" makes both of its assertions O(1); (c) only remove a connection from the active linked list when `active_on_link` is set |
| 17 | refuse an over-limit BEGIN_DIR (0012) before allocating its stream | 10 | move the check into the BEGIN_DIR branch of `connection_exit_begin_conn()` |

The test is to reproduce the profile's connection counts in the private
lab and compare main-thread CPU per BEGIN_DIR stream with `perf`, before
and after. 16 changes stock code that every relay runs, so it would go
upstream on its own, separately from the metrics.

### F. Not tor code

- Per-thread CPU (the main thread against the CPU workers), in
  `begindir-breakdown.py`. It would read `/proc/<pid>/task/`, with the pid
  from `GETINFO process/pid`.
- `perf` call graphs, taken alongside metric scrapes and shared as text.
- Brackets around each HSDir-flag removal, and equal-length windows for
  before-and-after comparisons.
- A known-normal workload. For now that is the private lab's C tor and
  Arti clients; the live probe in `../operator/probe-helper-acceptance.md`
  is specified but not built.

### G. Not proposed

- **The previous hop's flags, HSDir included.** A client's middle relay
  needs no particular flag. Consensus membership is item 2, and flags
  would add a lookup.
- **The consensus flavor** (§2), **and a DirPort label.** Onion service
  requests on the DirPort are refused.
- **What a refused BEGIN_DIR would have asked for.** It is refused before
  it asks.
- **The hops behind a previous hop, the sources behind a relay's channel,
  and distinct client addresses.** All are invisible to a relay by design.
  0017 gives a lower bound on client addresses.

## 4. Cost

- **Per event.** Item 2 splits an existing lookup, so there are no new
  lookups. Counter updates are O(1). Each move of a tunneled directory
  response to its stream adds one O(1) addition.
- **Per scrape.** The gauges are O(1). 0008's existing walk does one more
  addition per directory connection.
- **Memory.** The new per-circuit and per-connection bits fit the existing
  bitfield words, so no struct grows. The exception is item 14, which adds
  8 bytes to each channel.
- **Code.** B and C together are about 460 lines of C, about half of it
  MetricsPort boilerplate. With tests, that is about the size of 0016
  again. Items 1–3 alone are about 35 lines.
- **Series.** 45 for 0016 and 0017, plus about 160 for B and C. For
  upstream, the per-type response families could collapse into fewer kinds.

## 5. The ten questions after the proposal

| # | Question | `.6` and stock | With 0016, 0017, B and C | Still open |
|---|---|---|---|---|
| 1 | onion service or ordinary? (David) | three-way split | twelve types × four classes; bytes, abandonment and time by type | what refused streams would have asked |
| 2 | what drives the remaining onion service traffic? | hits, misses, uploads; would-act counters | bytes, abandonment, time and repeats for `hs_get` and `hs_post` | target concentration (item 15) |
| 3 | does traffic fall when the HSDir flag goes? | `tor_relay_flag{type="HSDir"}`; all counters | consensus times, to align a change with when clients could have seen it; start time | clients' consensus choices |
| 4 | one onion service request per circuit, or reuse? | onion service repeats, up to "2 or more" | BEGIN_DIR cells per circuit, by class; circuits reaching 2–100; repeats by type; streams open at once; busiest second | nothing more needed |
| 5 | relay or client channels? (David) | onion service requests only | every CREATE, BEGIN_DIR cell, stream and request by class | the hops behind a relay |
| 6 | consensus relay, descriptor only, or unknown? | combined, onion service requests only | split; consensus times | flags (not proposed) |
| 7 | is circuit creation concentrated? (David) | onionskins from relays; per-address refusals | CREATE outcomes by class; onion queue; busiest second; lower bound on client addresses | per-channel shares (item 14) |
| 8 | one descriptor or many? | hits and misses; 0013's over-rate count | nothing new | item 15 |
| 9 | what uses the CPU and bandwidth? | traffic, rate-limit and OOM counters | bytes by type; queued bytes; memory by subsystem; loop delay; onion queue | per-thread CPU and profiles (F); item 16 |
| 10 | which limiter scope and action? (David) | would-act and did-act counters | settings in effect; what 0012 would refuse, by type; churn; bytes | normal clients' latency outside the lab |

## 6. Mapping to `metrics-coverage.md`

That note numbers the questions from the first review. Its ranked "missing"
list is replaced by this proposal. Its questions map to this note's (§5)
as follows: its Q1 → 1, Q2 → 5, Q3 → 4, Q4 → 7, Q5 → 6, Q6 → 8 and 2,
Q7 → 3, Q8 → 9, Q9 → 2 and 9, Q10 → 10.

## 7. Decisions

1. **Whether the next build carries 0016 and 0017 as built, or with items
   1–3.** Items 1–3 cost about 35 lines. Renaming after a release breaks
   dashboards.
2. **How much of B and C to include.** The recommendation is all of B.
   From C, items 9 and 11 come first.
3. **Whether to build D at all, and if so with what default.** That is a
   privacy decision.
4. **When to run E's lab test.** It does not depend on any metric change.
