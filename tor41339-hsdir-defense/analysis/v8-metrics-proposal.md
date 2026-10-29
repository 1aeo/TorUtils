# What `+tor41339.7` shows in production, and what to add

In late October 2026, four BEGIN_DIR floods hit relays running
`+tor41339.7`. Two were mostly onion service descriptor fetches. The other
two were mostly BEGIN_DIR streams that never sent a request ("empty
streams"). The `.7` metrics showed what each flood asked for, who sent it
and how deep its circuits went. They could not show what the empty streams
were, which requests sat deep in their circuits, or how many response bytes
each defense would save.

This note:
- lists what `.7` already shows, which `../operator/begindir-breakdown.py`
  now prints as plain conclusions;
- answers the questions about splitting the traffic;
- proposes seven additions and one fix, prototyped on `.7` in
  `../engineering/v8-prototype/`, with their cost and a private-lab run;
- checks the BEGIN_DIR position bands against the four floods.

## On tor 0.4.9.15 (`+tor41339.8`)

The series is now rebased onto tor 0.4.9.15, which has BEGIN_DIR defenses
of its own (`../README.md`, "The gap"). They change parts of this note:

- **What `.7` shows, items 3 and 4.** `.8` drops `hsdir_req_reused`,
  `hsdir_circ_reused`, `HSDirOneRequestPerCircuit` and
  `begindir_over_stream_rate`:
  - tor refuses a circuit's second onion service request and closes the
    circuit, counted as `begindir_hsdir_rejected`;
  - tor rate-limits BEGIN_DIR per circuit, on by default, counted as
    `begindir_rate_rejected`;
  - the requests queued on a closing circuit are dropped unread, counted by
    `.8` as `begindir_request_total{type="circuit_dead"}`.

  Tor's counts are of refusals, while their rule is on, not of what a rule
  would refuse while off.
- **`.8` drops the limit on open streams per circuit** (`.7`'s 0012, with
  `begindir_over_max`) and its per-type count (`.7`'s 0019). In every flood
  saved from `.7` relays, `begindir_over_max` stayed at 0: no circuit ever
  held 64 open directory streams, even with no BEGIN_DIR rate limit. The
  earlier case for keeping it was wrong: it took the streams' lifetime
  across a relay for the streams one circuit holds at once. Many requests
  over a circuit's life, or long-lived streams on many circuits, don't put
  64 streams on one circuit at the same time. Nor would a rise on `.7` have
  shown that the limit adds anything: tor 0.4.9.15's rate limit would also
  have refused some of those streams. If a later flood holds many streams
  open on each circuit, the limit can come back from `.7`'s history; placed
  after tor's rate limit, its count would be the streams over the limit that
  the rate limit lets through.
- **`hsdir_unknown_prev_hop`** now counts only the requests that tor's limit
  of one per circuit accepts, so it is what `HSDirRefuseUnknownPrevHop`
  refuses or would refuse. And `.8` drops the HSDir action `circuit_dead`:
  tor 0.4.9.15 drops those requests before reading them.
- **Addition 7** keeps its family for the series' rules:
  `hsdir_unknown_prev_hop` and `hsdir_fetch_shed`.
  Tor's rules answer nothing they refuse, so they have no response bytes to
  count.
- **The trial** has one rule fewer to choose from: reuse is refused in
  every phase.
- **The prototype** is built on `.7`. Ported to `.8`, its reuse rule would
  be tor's.

## Answers

- **Can `.7` split ordinary directory requests and empty streams by
  previous hop? Yes.** `tor_relay_begindir_request_total` counts every
  accepted stream once by `type` and `prev_hop`, empty streams included
  (`type="no_request"`). The breakdown tool prints the table ("Q1 x Q4"):

  ```
  sum by (type, prev_hop) (rate(tor_relay_begindir_request_total[5m]))
  ```

  The claim that it can't was true of `.6`, not `.7`.
- **Onion service directory traffic or not?** For requests, the type
  already says so: `hs_get` and `hs_post` against the seven other types.
  An empty stream asked for nothing, so only its circuit can say. Addition 2
  labels each empty stream by whether its circuit made an onion service
  request, before or after the stream opened.
- **How many categories for "other"?** None beyond `.7`'s. For charts,
  group `.7`'s nine types into four:
  - descriptor fetches;
  - descriptor uploads;
  - other directory requests: `consensus`, `microdesc`, `descriptor`,
    `other_get`, `other_post` and `unparsed`. With the uploads, these were
    under 0.5% of every flood's streams;
  - empty streams.

  The empty streams are what need splitting: by how they ended (3), how old
  they were (4) and what their circuit did (2), 24 categories (addition 2).
- **The position bands** (1, 2–10, 11–100, 101–1000, 1001+): keep them. Add
  per-circuit thresholds at 4, 31 and 301 as well as the band edges
  (addition 8). Reasons in "The position bands" below.
- **Cost of all eight:**
  - +441/−24 production lines, 281 of the additions in `relay_metrics.c`;
  - no larger structs;
  - 103 more series;
  - every new production line killed by a test under mutation.

## The four floods

The relays' charts, by share of each flood's own total (`~`: read from an
unlabeled segment of the chart). In the charts' table, unparsable requests
were at most 0.011% of a flood's streams, and consensus and microdescriptor
requests far less:

| | A | B | C | D |
|---|---|---|---|---|
| descriptor fetches (`hs_get`) | 91.3% | 97.8% | 10.2% | 21.3% |
| empty streams (`no_request`) | 8.3% | ~2% | 89.8% | 78.7% |
| uploads and every other type | ~0.4% | ~0.3% | ~0% | ~0% |
| BEGIN_DIR cells at position 1 | 17.2% | 21.3% | ~1% | ~3% |
| 2–10 | 66.3% | 74.3% | 6.5% | 16.8% |
| 11–100 | 10.0% | ~3% | 18.7% | 20.0% |
| 101–1000 | 6.1% | ~1% | 71.3% | 59.5% |
| 1001+ | ~0.4% | ~0.4% | ~2.5% | ~1% |

- **A and B are fetch floods on circuits reused a few times.** Their
  circuits carried about 5 or 6 BEGIN_DIR cells on average. That is all
  cells divided by cells at position 1, since each circuit has exactly one
  first cell. Stock tor and Arti make one onion service request per
  circuit.
- **C and D are empty-stream floods on deep circuits.** Their circuits
  carried about 35 to 100 BEGIN_DIR cells each.
- **Few circuits pass 1000 cells in any of the four.** At most 2.5% of
  cells are at position 1001 or later.
- **Empty streams cost cells even though they get no response.** Each
  accepted BEGIN_DIR stream costs a CONNECTED cell (514 bytes on the wire),
  and an END cell if we close it. At 5,000 empty streams a second that is
  2.6 MB/s of cells.
- **How long the empty streams lived: a tentative reading.**
  - In each chart, classified streams exceed cells. The excess equals the
    streams waiting at the window's start, less those waiting at its end
    and the cells refused (see "Other gaps found"). So at least that many
    were waiting at the start.
  - Assume the flood was steady when the window began, and that the waiting
    streams were the empty ones (requests wait milliseconds). Then Little's
    law gives a lower bound on their mean life: the excess over their rate.
  - That bound is two to three minutes in the fetch floods (A, B): their
    empty streams were held open for minutes. In the empty-stream floods
    (C, D) it is six to nine seconds, which says only that theirs lived at
    least that long.
  - The waiting gauge at each window's start gives the mean itself, and
    addition 2 measures it directly.
- **The chart's open question.** Across these four floods, the more cells
  past position 10, the more empty streams. But one fetch flood's last five
  minutes had nearly every stream a fetch and most cells past position 10.
  So the two don't always go together, and `.7` can't show which requests
  sit where (addition 1).

## What `.7` already shows

The breakdown tool now ends with these, in sentences, each from a named
family:

1. **What a flood asks for:** the shares of `begindir_request_total` by
   type.
2. **Who sends it:** the same family by `prev_hop`. A flood through relays
   we know comes over multi-hop circuits, so no rule on previous hops
   refuses it.
3. **How deep its circuits go:**
   - `begindir_cell_total{nth}`: the shares past each circuit's 10th, 100th
     and 1000th BEGIN_DIR cell;
   - `hsdir_req_reused` / the anonymous onion service requests: the share
     that came on a circuit that had already made one.
4. **Which rule would bind:** each rule counts what it would refuse while
   it is off:
   - `hsdir_req_reused` (`HSDirOneRequestPerCircuit`);
   - `hsdir_unknown_prev_hop` (`HSDirRefuseUnknownPrevHop`);
   - `hsdir_fetch_shed` (`HSDirFetchShedding`);
   - `begindir_over_max` (`DoSBeginDirLimitEnabled`);
   - `begindir_over_stream_rate` (a BEGIN_DIR stream rate, which no option
     enforces yet).
5. **What responses cost:**
   - `begindir_response_bytes_total` by type;
   - the bytes per descriptor served, in cells;
   - streams × 514 bytes for their CONNECTED cells;
   - the share of the relay's written bytes (`tor_relay_traffic_bytes`).
6. **How long empty streams live, at most:** the mean of
   `begindir_connections{state="command_wait"}` divided by the rate of
   `no_request` (Little's law). The gauge also holds streams about to send
   a request, so this is an upper bound.
7. **What `.7` can't say.** The tool names it, and points here.

## The additions

| # | family | labels | series | answers |
|---|---|---|---|---|
| 1 | `tor_relay_begindir_request_position_total` | `type`, `nth` | 45 | which kinds of request sit deep in their circuits |
| 2 | `tor_relay_begindir_empty_stream_total` | `ended`, `age`, `circuit` | 24 | what the empty streams are |
| 3 | `tor_relay_begindir_response_bytes_total` (fix) | `type` | 0 | the bytes moved when a directory connection closes, now counted |
| 4 | `tor_relay_begindir_discarded_bytes_total` | `where` | 2 | response bytes produced but never sent |
| 5 | `tor_relay_begindir_pending_bytes` (gauge) | `where` | 2 | response bytes waiting now |
| 6 | `tor_relay_hsdir_descriptor_bytes_total` | none | 1 | descriptors served, apart from not found |
| 7 | `tor_relay_dos_response_bytes_total` | `type` | 5 | the response bytes each rule would avoid |
| 8 | `tor_relay_begindir_circuit_total` | `prev_hop`, `reached` | 24 | how many circuits reach each depth |

### 1. Which kinds of request sit deep in their circuits

- **The gap:** `.7` counts cells by their place on the circuit, and
  requests by type, but never the two together.
- **The family:** `tor_relay_begindir_request_position_total{type,nth}`
  counts each request once, by its type and by the band of its stream's
  BEGIN_DIR cell on the circuit (`.7`'s bands).
- **Code:** `connection_exit_connect_dir()` stores the band in 3 bits of
  the directory connection, and `relay_note_dir_request()` counts it.
- **Naming:** by `.7`'s naming rules (`v7-review.md`), `nth` belongs as a
  label on `begindir_request_total`. That would replace every `.7` series of
  that family, which dashboards use, so this adds a second family instead.
  One family `{type, prev_hop, nth}` would have 135 series.

### 2. What the empty streams are

- **The gap:** `.7` counts empty streams (`no_request`), and a gauge shows
  how many wait. It can't say who ends them, how long they live, or whether
  their circuits also make onion service requests.
- **The family:** `tor_relay_begindir_empty_stream_total{ended,age,circuit}`:
  - `ended`:
    - `client`: the client sent an END;
    - `circuit`: its circuit closed;
    - `relay`: we closed it, mostly on the stall timeout
      (`TestingDirConnectionMaxStall`: 5 minutes, or 30 s in a test
      network).
  - `age`: from the stream's opening to its directory connection's close,
    in seconds: `0`, `1_9`, `10_59`, `60_plus`.
  - `circuit`: `hsdir` if the circuit made an onion service directory
    request, before or after this stream opened; `other` otherwise.
- **What each case means for the defenses:**
  - **Held open until we close them** (`relay`, `60_plus`): the streams
    hold slots. `DoSBeginDirMaxStreams` binds where one circuit holds more
    than its limit (64 by default) at once, which `.7`'s
    `begindir_over_max` shows.
  - **Opened and closed at once** (`client` or `circuit`, `0` to `1_9`):
    the streams cost CPU and a CONNECTED cell each. A limit on open streams
    can't bind; a BEGIN_DIR stream rate would.
  - **On onion service circuits** (`hsdir`): the same circuits fetch
    descriptors. A rule that closes such circuits, like
    `HSDirOneRequestPerCircuit`, closes their empty streams too.
- **Code:**
  - `connection_exit_about_to_close()` writes how the stream ended into its
    directory connection (`FLAG_REMOTE`: client; `DESTROY`: circuit);
  - a circuit's first onion service request marks its open directory
    streams;
  - `connection_exit_connect_dir()` marks those opened after it.

### 3–5. Where response bytes go

- **What `.7` counts:** response bytes when the stream takes them from the
  directory connection, by request type.
- **Fix 3:** `conn_close_if_marked()` moves what is left in a closing
  directory connection to its stream without counting it. The fix counts
  it, in 3 lines.
- **Addition 4:** `tor_relay_begindir_discarded_bytes_total{where}`:
  - `directory`: bytes left in a directory connection when it closes, which
    nothing will take;
  - `stream`: bytes a stream took but had not sent as cells when it closed.
- **Addition 5:** the gauge `tor_relay_begindir_pending_bytes{where}` holds
  the bytes waiting in each place now.
- **The accounting then closes:**
  - produced = taken + discarded{directory} + pending{directory};
  - taken = sent as cells + discarded{stream} + pending{stream}.
- **Not proposed:** counting by request type after the stream (in the
  circuit queue, or at TLS). Those cells share the busiest path in tor with
  all other traffic. The numbers above, and the relay's own written bytes,
  bound them. If a trial shows a gap, a few lines in
  `circuit_about_to_free()` could count the cells dropped with a closing
  circuit's queue.

### 6. Descriptors served, apart from not found

- **The gap:** `.7` counts fetches by outcome (`hsdir_fetch_total{action}`)
  and descriptor responses handed off, but bytes only by request type.
- **The family:** `tor_relay_hsdir_descriptor_bytes_total` counts the bytes
  of responses that carried a descriptor. The rest of
  `begindir_response_bytes_total{type="hs_get"}` is not-found and refusal
  responses.

### 7. What each rule would avoid

- **The gap:** `.7` counts the requests each rule would refuse while it is
  off, not their bytes.
- **The family:** `tor_relay_dos_response_bytes_total{type}` counts the
  response bytes of those requests. Its `type` labels are those of
  `tor_relay_dos_total`:
  - `hsdir_req_reused`;
  - `hsdir_unknown_prev_hop`;
  - `hsdir_fetch_shed`;
  - `begindir_over_max`;
  - `begindir_over_stream_rate`.

  So `dos_response_bytes_total / dos_total` is the bytes per counted
  request. A response counts under each rule that would refuse it.
- **What it doesn't measure:** these are upper bounds on what turning a
  rule on saves:
  - a refused client can retry on a new circuit;
  - the refusal itself costs an END cell, a 503 or a DESTROY.

  Only a trial measures the rest (below).

### 8. How many circuits reach each depth

- **The gap:** the bands count cells, but a limit acts on circuits.
- **The family:** `tor_relay_begindir_circuit_total{prev_hop,reached}`
  counts each circuit once when its BEGIN_DIR cells reach each of 1, 2, 4,
  11, 31, 101, 301 and 1001. `reached="1"` equals
  `begindir_cell_total{nth="1"}`.
- **Code:** the count is kept where `.7` already counts the circuit's
  cells, and stops at 1001 like it.

## The position bands

The bands answer the first question at a glance: fetch floods sit at 2–10,
empty-stream floods at 101–1000. Three things in the data argue for more
detail:
- **Two bands are crowded.** 2–10 holds 66–74% of the fetch floods' cells,
  and 101–1000 holds 60–71% of the empty floods'. Inside them, the bands
  can't tell 2 requests a circuit from 10, or 120 from 900.
- **The stock ceiling has no edge.** Stock clients send about 30 or fewer
  BEGIN_DIR cells on a directory circuit, and one per onion service circuit.
  The 30 falls inside 11–100, which held 10–20% of the cells in three of
  the floods.
- **The top band is nearly empty.** At most 2.5% of cells are at 1001 or
  later, so the cap at 1001 loses little. A higher band isn't worth it.

Changing the bands would replace `.7`'s deployed series. So keep the five,
and add per-circuit thresholds (addition 8) at:
- the band edges (1, 2, 11, 101, 1001), so the two families line up;
- one split inside each crowded band (4 and 301);
- the stock ceiling (31).

A limit of N BEGIN_DIR cells a circuit would act on the `reached` count just
above N. The cell bands bound how many cells it would cut.

If the bands were new, these eight edges would be the bands. As an
addition, they cost 24 series and no change to `.7`'s.

## The "best approach" proposal, point by point

| proposal | here |
|---|---|
| response bytes by request type and outcome | type: `.7`; outcome: addition 6; by rule: addition 7 |
| response cells queued, passed to TLS, discarded and pending | discarded and pending at the directory connection and the stream (3–5). Not after the stream: that path is shared with all traffic, and those numbers bound it |
| bytes of requests the limiter would reject | addition 7, for all five rules |
| rejection traffic, CPU and circuit creation | **Rejection traffic** comes from counts already exported: each refused stream costs an END cell (514 bytes), each closed circuit a DESTROY, and 503s are in the response bytes. **CPU:** tor exports none, so use the host's. **Circuit creation:** `.7`'s `create_cell_total` and `create_cell_source_total`. No new code |
| close the gaps first: transfers during connection closure, success and not found | fix 3 and addition 6 |
| a shadow-mode limiter, then an enforcement trial against a comparable control relay | yes: every rule counts while off (shadow mode). The trial is below |
| retries and adaptation mean predicted savings ≠ the bandwidth reduction | yes: addition 7 gives upper bounds; the trial measures the rest |

## Other gaps found

None of these needs new code:
- **Classified streams outnumbered cells by 0.04–0.34% in the charts.** This
  is not a counting error:
  - a stream is classified when it sends its request or closes, so
    classified − cells = streams waiting at the window's start − those
    waiting at its end − cells refused;
  - a chart of both should also show the waiting gauge,
    `begindir_connections{state="command_wait"}`, at each end.
- **With several rules on, refusals lump together.** `hsdir_fetch_total`
  counts every refusal as `action="refused"`, whichever rule made it. Each
  rule's own `dos_total` count tells them apart, on or off.
- **CPU.** Tor exports no CPU time: use the host's process metrics.
- **Per-circuit counts over a short window.** A circuit is counted when it
  reaches each number of BEGIN_DIR cells, so some counted in a window began
  before it. The tool says so.
- **A test network's stall timeout is 30 s, not 5 minutes**
  (`TestingDirConnectionMaxStall`). Lab lifetimes of empty streams are not
  production's.

## A trial of one rule

1. **Shadow.** Run with every rule off through a flood. For each rule,
   record its share of requests and its response bytes (addition 7).
2. **Choose.** Take the rule that avoids the most bytes per stock client it
   would touch. For the stock behaviour, see `prev_hop` and the depth
   above; stock clients never reuse onion service circuits.
3. **Enforce and compare.** Enable that rule on one relay. Keep a control
   relay that gets the same flood, with the rule off. Compare:
   - written bytes (`tor_relay_traffic_bytes`);
   - CPU, from the host;
   - circuit creation, for retries: `create_cell_total` and
     `create_cell_source_total`;
   - refusals (`hsdir_fetch_total{action="refused"}`, and the rule's own
     count).

   The bytes saved, minus what retries add, is the measured effect.

## The prototype

- **What it is:** `../engineering/v8-prototype/prototype.diff`, applied to
  the `.7` tree, with its tests.
- **Production code:**
  - +441/−24 lines in 14 files, 281 of the additions in `relay_metrics.c`
    (entries, counters and fill functions);
  - tests: +488/−15.
- **Memory:**
  - no struct grows: the 11 new bits fit the existing bitfield words of
    `dir_connection_t` (still 240 bytes) and `edge_connection_t`;
  - `or_circuit_t` gains nothing;
  - the new static counters take under 1 KB.
- **CPU:**
  - per BEGIN_DIR cell: one compare per threshold, until the circuit's
    count stops at 1001;
  - per request: a few increments;
  - per scrape: one more pass over the connection array.
- **Series:** +103 (45 + 24 + 5 + 1 + 24 + 2 + 2).
- **Checks:**
  - it builds with `--enable-fatal-warnings`;
  - the unit suite passes (1640 tests), and so does `make check-spaces`;
  - practracker, compared with `.7`'s tree: one more include and one
    dependency-violation warning in `mainloop.c` (core now includes
    `relay_metrics.h` for fix 3), and larger `connection_edge.c` and
    `rephist.c`;
  - 47 mutants over every new production line, all killed by a test (two
    after rerunning build failures with the value kept):
    `../engineering/v8-prototype/mutants.tsv`.
- **Lab:** a private chutney network with no network interface, with
  every node running the prototype
  (`../engineering/v8-prototype/README.md`). One HSDir received
  multiplexed fetches, one-hop fetches and two kinds of empty stream. Every
  new family counted what the load sent:
  - the 31 empty streams, by how they ended: 26 with the client's END, and
    5 with the circuit that was closed;
  - the response bytes of the reused fetches and of the unpublished
    identity's, to the byte: 217 and 35 responses of 14,260 bytes;
  - the descriptor bytes of the 221 fetches served.

  The same load on `.7` gave the same answers for everything `.7` counts.

## If fewer

In order of data per line:
1. **Fix 3** (3 lines): it corrects `.7`'s own family.
2. **Addition 2, empty streams:** the two largest floods were mostly empty
   streams, and `.7` can't say what they are.
3. **Addition 1, position by type:** the chart's open question.
4. **Addition 8, circuit reach:** what a per-circuit limit would touch.
5. **Additions 6 and 7, bytes by outcome and by rule:** what a rule would
   save.
6. **Additions 4 and 5, discarded and pending bytes:** they close the byte
   accounting.
