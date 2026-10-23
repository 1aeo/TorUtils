# The smallest set of new metrics for the BEGIN_DIR flood

> **Status: built into `+tor41339.7`.** The proposed 0016 and 0017 below are
> patches 0016 and 0017. Items 1 and 2 are 0018, items 3–6 are 0019–0022,
> and 0023 is the shadow count that §7's question 4 asks about. As built,
> they add 63 series to 0016 and 0017's 44 (107 more than `.6`, net of the
> two `.6` request types that 0016 replaces): item 2 counts all nine types,
> item 4 has five bands and counts BEGIN_DIR too (30 series), and item 5 has
> ten. Memory: 8 bytes per channel and per tracked client address, one 64 KB
> table, and one more token bucket per OR circuit (0023). Items 4 and 5 and
> the shadow count are kept only while a MetricsPort is configured. The
> names below are those of the proposal and of `.6`; `.7` renamed most
> families (`analysis/v7-review.md` maps them).
>
> The answers to the questions in §7:
>
> - client sources are counted per address, which is what tor limits by,
>   when tor tracks the address (a DoS defense or `EntryStatistics` is
>   on), else per channel; relay sources per channel;
> - bridges count none of the per-source or per-descriptor numbers;
> - BEGIN_DIR is counted per source too;
> - BEGIN_DIR cells over the stream creation rate get a shadow counter
>   (0023);
> - the bands gain an edge at 1000, so that a limit per source between 100
>   and 1000 a minute can be judged;
> - no shadow thresholds have been chosen yet.

This replaces the larger proposal of the same day (commit `a5edba4`, 17
items, about 460 lines of C and 160 series). It merges every metrics request
made on 23 October 2026:

- David Goulet's four questions on tor-relays (`begindir-questions.md`).
  They come first: he maintains the network code and designs the fixes, so
  whatever he needs is in;
- the first ten-question review (`metrics-coverage.md`);
- the second ten-question review, written against live `.6` data;
- the operator critique of `flood-cost-and-constrained-hosts.md`;
- the design judges' and verifiers' notes on 0016;
- a stock profile that put 90.5% of sampled main-thread user CPU in global
  connection-cleanup scans.

**The result:** six additions on top of the proposed 0016 and 0017
(`patches/proposed/`): about 150 lines of C and 38 MetricsPort series.
Alongside them come one performance change, some tool work and a lab
procedure. None of it is built yet.

Three rules kept the list short:

- **Shadow counters before histograms.** Every defense in the series counts
  what it would do while it is off. Its threshold can be changed in
  count-only mode, which measures a candidate limit with no new code.
- **Derive before adding.** Refusals, abandoned responses and time spent in
  each state follow from counters and gauges that already exist (§2).
- **Count on objects tor already has.** A per-minute count kept on the
  channel, or in one small table of hashed keys, replaces periodic walks
  and sketches.

## 1. The questions, without duplicates

| # | Question | Asked by |
|---|---|---|
| Q1 | Are the BEGIN_DIR streams onion service requests, ordinary directory requests (which), malformed, or empty? | David (1); review 1 (Q1); review 2 (1, 2) |
| Q2 | Do they come over client channels (one hop) or relay channels? Are those relays in the consensus, known only by descriptor, or unknown? | David (4); review 1 (Q2, Q5); review 2 (5, 6) |
| Q3 | How do requests spread over circuits: how many per circuit, how many at once? Would a per-circuit or a relay-wide limit work? | David (2); review 1 (Q3); review 2 (4) |
| Q4 | How many circuits are created, over which channels, and from how many sources? | David (3); review 1 (Q4); review 2 (7) |
| Q5 | Are fetches concentrated on a few descriptors? Are misses repeats or a sweep? | review 1 (Q6); review 2 (2, 8) |
| Q6 | What does the flood cost? CPU (where), bandwidth (for what), memory; how much work is completed or abandoned, and how long it takes | review 1 (Q8, Q9); review 2 (9); operator critique; profile |
| Q7 | How does the flood change with the HSDir flag, restarts and our consensus? | review 1 (Q7); review 2 (3) |
| Q8 | Which defense, at what scope and threshold, with what collateral and churn? Should it refuse a stream or close the circuit? | David (2); review 1 (Q10); review 2 (10) |

## 2. What already answers them

Sources: `.6` is the rollout build. 0016 and 0017 are built and tested but
not packaged. "Tool" means `begindir-breakdown.py`, which also reads the
ControlPort.

| # | `.6` and stock | 0016, 0017 | Tool, procedure or derivation |
|---|---|---|---|
| Q1 | HS GET and POST, parsed non-HS, unparsed | every request by type (8) and previous-hop class | |
| Q2 | HS requests only: single hop; unknown previous hop | CREATE, BEGIN_DIR cells, accepted streams and requests, by class | our consensus's age (`GETINFO consensus/valid-after`) |
| Q3 | HS reuse ("2 or more"); `begindir_over_max` at `DoSBeginDirMaxStreams`; directory streams by state | BEGIN_DIR cells by place on their circuit (1, 2–9, 10–49, 50+), by class | share of cells that are a circuit's 50th or later = what a cap of 49 per circuit would cut; move 0012's threshold in count-only mode |
| Q4 | onionskins, from relay channels only; per-address refusals | CREATE by class; 0017: client CREATE over the per-address rate | client addresses: a lower bound of (client CREATE − over-rate) ÷ `DoSCircuitCreationRate`, set against the distinct client addresses connected at the moment (tool) |
| Q5 | hits, misses; 0013's fetches over a descriptor's own rate | | move 0013's rate in count-only mode |
| Q6 | traffic, rate-limit and OOM counters; responses handed off (HS, other) | requests by type | see below the table |
| Q7 | HSDir flag gauge; counter resets | | uptime and consensus times (tool); brackets around flag changes |
| Q8 | would-act counters for every rule; refusals when enforcing | refusals by class = BEGIN_DIR cells − streams; churn = CREATE by class | candidate thresholds in count-only mode; known-normal clients in the lab |

For Q6, the tool and some arithmetic give:

- per-thread CPU and `perf` profiles (§4);
- main-loop stalls, from Prometheus scrape durations and ControlPort round
  trips;
- HS responses abandoned = HS successes − HS responses handed off − HS
  responses still writing;
- mean time in each state = mean `dir_server_conns{state}` ÷ the rate of
  entering it (Little's law). This also bounds how long empty streams stay
  open.

What is still missing:

- what the ordinary "other" requests are, by method;
- the bandwidth each kind of request uses;
- what 0012 would refuse;
- how concentrated circuit creation is across sources (David's question 3);
- how concentrated fetches are across descriptors;
- the descriptor-only share of onion service previous hops.

## 3. Six additions

| # | Addition | Answers | Why nothing cheaper works | Cost |
|---|---|---|---|---|
| 1 | keep the request type on the directory connection, and split 0016's `other` into `other_get` and `other_post` | Q1; enables 2 and 3 | items 2 and 3 need the type on the connection; the split is review 2's explicit ask | ~8 lines; +3 series |
| 2 | response bytes handed to the stream, by request type | Q6, Q8 | see the notes | ~30 lines; 8 series |
| 3 | requests by type on streams over 0012's limit | Q3, Q8 | `begindir_over_max` counts these streams but not what they carry, which is 0012's collateral; 0012 is the one rule that covers every type | ~25 lines; 9 series |
| 4 | CREATE cells by their place among the same channel's CREATE cells this minute: 1st, 2nd–10th, 11th–100th, 101st+ | Q4, Q8 | see the notes | ~15 lines; +9 series; 8 bytes per channel |
| 5 | onion service fetches by their place among fetches of the same descriptor this minute (same bands), found and missing apart | Q5, Q8 | the same bands for targets. 0013 covers only cached descriptors, and only at its own rate | ~60 lines; 8 series; one 64 KB table |
| 6 | onion service requests whose previous hop is known only by descriptor | Q2, Q8 | splits a lookup `.6` already makes per request; shows whether `HSDirRefuseUnknownPrevHop` misses relays dropped from the consensus | ~8 lines; 1 series |

**Total:** about 150 lines of C, half of it MetricsPort boilerplate, plus
tests, and 38 series on top of 0016 and 0017's 45.

- **Per event:** O(1) updates and no new lookups. Item 5 adds one keyed hash
  per onion service fetch.
- **Memory:** 8 bytes per channel and one 64 KB table. No other struct
  grows.

Notes:

- **Item 1.** The type replaces 0016's once-only bit (4 bits instead of 1).
  On a bridge, the 503 answer to a POST was only counted when the
  connection closed. It is now typed before it is written, so its bytes
  count too.
- **Item 2.**
  - **Why it's needed.** Stock tor counts directory bytes only in total,
    daily, and not on the MetricsPort. The traffic counters can't separate
    them (operator critique). Sizing `HSDirFetchBudget` needs onion service
    bytes, and there is no other way to tell what ordinary requests cost.
  - **Where.** Counted where stock tor already counts directory bytes
    (`record_num_bytes_transferred_impl()`), as a response moves to its
    stream.
  - **What it means.** This is work done, not proof of delivery.
  - **What it shows.** A missed onion service fetch is one short 404, so
    `hs_get` bytes are almost all hits. Bytes per request also show whether
    `consensus` requests are full downloads, or diffs and 304s.
- **Item 3.** 0012 already counts each circuit's open streams for every
  BEGIN_DIR. It would mark the stream with one bit. This only means
  something while 0012 is in count-only mode.
- **Item 4.**
  - **What it answers.** David's question 3 without a list walk. The 1st
    band counts distinct sources per minute. The 101st+ band is what a
    per-peer limit of 100 a minute would cut.
  - **How.** Two counters on each channel.
  - **Bands.** On the relays in `flood-cost-and-constrained-hosts.md` §1.2,
    all previous hops together opened 8–45 circuits a second. Spread over a
    relay's many peers, normal per-peer rates should be far below 100 a
    minute; the bands will show whether they are.
  - **Clients.** For a client, a source is one connection, and one address
    can hold several (up to 50 under the consensus's
    `DoSConnectionMaxConcurrentCount`). So per-address concentration is at
    least what this shows. 0017 gives the per-address view against stock
    tor's rate.
- **Item 5.**
  - **Hashing.** Keys are hashed with tor's own per-run random hash key.
    Nothing per key is exported.
  - **Overflow.** If more keys arrive in a minute than the table holds, the
    extra ones count as first fetches. Concentration is then a lower bound,
    and that only happens when the fetches are a sweep.
  - **What it measures.** The 101st+ band for missing keys is what a
    per-key miss limit would cut.
- **Item 6.** It doesn't change what `HSDirRefuseUnknownPrevHop` refuses.

## 4. Needed to defend, but not metrics

**Cleanup indexing.** This is a stock tor performance change. A separate
agent prompt covers the change and its lab test.

- **The scans.** These are stock tor-0.4.9.14 sites, and `tor_assert()` is
  always compiled in.
  - **Each connection that closes** costs one scan of the connection array
    (`connection.c:970`), three of the closeable list (`mainloop.c:346`,
    `:419`; `connection.c:969`) and one of the active linked list
    (`mainloop.c:347`).
  - **Each read or write toggle** of a linked connection costs one more
    scan of the active linked list (`mainloop.c:833`, `:851`, `:853`).
  - **Under this flood.** Each BEGIN_DIR stream is two connections. Each
    0012 refusal frees a stream that was never in the array, and still
    scans all of it.
- **The fix.**
  - Reset `conn_array_index` to −1 in `connection_remove()`. Tor already
    reads −1 as "not in the array" in `connection_is_moribund()`.
  - Keep the same kind of index for the other two lists. The code's own
    "FFFF We could keep an index here" note at `mainloop.c:848` asks for
    this.
  - Have 0012 refuse before it allocates the stream.
- **The test.** Measure main-thread CPU per BEGIN_DIR stream with `perf`,
  before and after, in the private lab at the profile's connection counts.
- **Why it's worth it.** It helps every relay under any connection churn,
  and it makes enforcing 0012 cheap.

**Shadow thresholds on the pilot.** In count-only mode, run each candidate
for a while:

- `DoSBeginDirMaxStreams`, with item 3 showing what it would cut;
- `HSDirDescriptorFetchRate` and `Burst`;
- `HSDirFetchBudget`, sized from item 2.

These are configuration changes only; nothing is enforced.

**Lab A/B tests.**

- Run known-normal C tor and Arti clients under each candidate defense.
- For 0012, compare refusing streams with closing circuits, using CREATE
  churn (0016). An operator reported that closing cut his traffic far more.

**Tool.** Add:

- per-thread CPU from `/proc/<pid>/task/` (pid from `GETINFO process/pid`);
- the ControlPort round-trip time;
- uptime and consensus times;
- the derived figures in §2.

## 5. Critique: what was cut, and what would bring it back

| Cut from the larger proposal | Why it isn't needed now | Add it if |
|---|---|---|
| `consensus_diff`, `keys` and `unknown_get` as their own types | bytes per request (item 2) shows whether consensus requests are full downloads; no decision depends on the rest | `consensus` or `other_get` dominate the ordinary half |
| a fourth previous-hop class everywhere | the one decision it informs, `HSDirRefuseUnknownPrevHop`, concerns onion service requests: item 6 | a consensus-only rule for all circuits is considered |
| abandoned responses and seconds open, by type | the `.6` response identity, Little's law on `dir_server_conns`, bytes per request | the derived figures are too noisy or disagree |
| CREATE outcomes; onion queue gauges | the profile puts the main thread at the limit, not the CPU workers; stock counts drops on relay channels | per-thread CPU shows the workers saturated |
| repeats by type; circuits reaching N; streams open at once | 0016's place-on-circuit bands, `.6`'s HS reuse, and 0012's threshold moved in count-only mode | a cumulative per-circuit cap is designed |
| busiest second; main-loop delay | scrape durations and ControlPort round trips show stalls; no candidate defense is rate-based yet | a rate-based limit is designed |
| queued bytes; memory by subsystem | RSS and the stock OOM counters show memory trouble | constrained hosts approach `MaxMemInQueues` |
| consensus, start-time and settings gauges | the tool reads them from the ControlPort | — |
| a once-a-minute walk of all channels, with top-1 and top-10 shares | item 4's bands answer the same question with no walk | David wants top shares themselves |
| distinct-key sketches with top shares | item 5's bands | — |
| 0012's refusal before allocation, as a separate item | folded into cleanup indexing (§4) | — |

**Weak spots kept on purpose:**

- **Per-address counts.** For clients, item 4 counts per connection, not
  per address.
- **Single-threshold shadows.** Item 3 shows only the threshold 0012 is
  currently set to, and only while it doesn't enforce.
- **Delivery.** Item 2 is bytes handed to the stream, not delivered.
- **Windows.** The minute windows are tumbling and aligned to the clock, so
  a burst can be split across two of them.
- **Bursts.** Nothing measures bursts within a scrape interval.
- **Little's law.** The derived figures assume steady state over the
  window: fine for floods lasting hours, noisy for short bursts.

## 6. From readings to a defense

| If the metrics show | Test first | Read first |
|---|---|---|
| HS fetches over relay channels, several per circuit | 0011 `HSDirOneRequestPerCircuit` | `hsdir_req_reused`, `hsdir_circ_reused` |
| HS requests from unknown or descriptor-only previous hops | `HSDirRefuseUnknownPrevHop` (a consensus-only rule if item 6 is large) | `hsdir_unknown_prev_hop`; item 6 |
| many BEGIN_DIR at once on few circuits, mostly empty or HS | 0012, at a threshold from shadow runs | `begindir_over_max`; item 3 |
| a few descriptors fetched far over their rate | 0013 | `hsdir_fetch_over_rate`; item 5 |
| misses repeating on a few keys | a per-key miss limit (not built) | item 5 |
| HS bytes beyond what the relay can spare | 0014 `HSDirFetchBudget` | item 2; `hsdir_fetch_pressure`, `hsdir_fetch_shed` |
| CREATE concentrated on a few relay peers | a per-peer limit (not built) | item 4 |
| client CREATE concentrated on a few addresses | stock `DoSCircuitCreation*` (consensus parameters) | 0017; `circuit_rejected` |
| the main thread in cleanup scans | cleanup indexing | `perf` |
| none: many sources, few requests each, many keys | a relay-wide limit (0014) | items 2, 4 and 5 |

## 7. Open questions and decisions

**Unknowable at a relay, by design:**

- the hops behind the previous hop;
- the clients behind a relay's channel;
- what a refused stream would have asked for;
- clients' consensus choices;
- exact client address counts without a per-address variant of item 4.

**For David:**

1. **Client sources.** Should these be counted per channel (item 4 as
   designed) or per address? Per address would be exact, using the
   circuit-creation entry tor already looks up for each client address, at
   8 bytes per entry.
2. **Bridges.** Should item 4 count client channels on bridges, whose
   clients are their users?
3. **BEGIN_DIR per channel.** Does he want this too? It is the same
   mechanism, and adds 12 series.
4. **Rate limit or concurrency limit.** Would he rather extend stock tor's
   per-circuit stream rate limit (`DoSStreamCreation*`) to BEGIN_DIR than
   use 0012's concurrency limit? If so, the measurement to add is a shadow
   count of BEGIN_DIR cells over that rate, per circuit: one series.
5. **Thresholds.** Are the band edges (1, 10, 100) and the one-minute
   window what he would use?

**For us:**

1. Build items 1–6 on top of 0016 and 0017 now, so that the labels are
   final before any release, or after the other agent's review of 0016 and
   0017.
2. Run the cleanup-indexing lab test now. It doesn't depend on any metric.
3. Choose which shadow thresholds to run on the pilot.
4. Send David the questions above.
