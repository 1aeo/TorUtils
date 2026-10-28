# What is this BEGIN_DIR flood? A breakdown from the MetricsPort

`begindir-breakdown.py` reads the MetricsPort of a relay running the
tor#41339 series (`+tor41339.7`; it also reads `.6`, with fewer answers),
optionally twice to get rates, and says what the relay's BEGIN_DIR streams
were. With access to the ControlPort it
also counts the relay's open OR connections by kind of peer. It only reads,
and prints counts: never an address, a fingerprint or a nickname.

```
python3 -I begindir-breakdown.py --metrics http://127.0.0.1:9035/metrics \
    --interval 60 \
    --control 127.0.0.1:9051 --cookie /var/lib/tor/control_auth_cookie
```

Names below are `.7`'s. `.6` called some of the families differently
(`tor_relay_hsdir_get_total` and `_post_total`, `tor_relay_dir_requests_total`,
`tor_relay_dir_responses_total`, `tor_relay_dir_server_conns`), and exported
the dos type `hsdir_request_total`, which `.7` drops because the request
families give it; `analysis/v7-review.md` maps them, and the script reads
both.

`--interval 0` prints totals since the relay started. `--control-socket`
takes a ControlSocket path instead of `--control`, and `--password` a
HashedControlPassword password instead of `--cookie`. Without `--control`
the connection snapshot is skipped. Run it during a flood and again on a
quiet day for comparison.

## What it concludes

The output ends with "What this says": the numbers above as numbered
sentences, each built from named counters, for `.7` or later:

1. **What the BEGIN_DIR streams were.** The tool names the kind that is most
   (over 50%) or nearly all (over 95%) of them, or else lists every kind
   by its share.
2. **Who sent that kind**, by previous hop. Through a relay we know means
   other senders' multi-hop circuits, which no previous-hop rule refuses.
3. **How deep their circuits went:** the shares of BEGIN_DIR cells past
   their circuit's 10th, 100th and 1000th. For comparison, stock tor and
   Arti send one cell per onion service circuit, and about 30 or fewer on a
   directory circuit.
4. **How many onion service requests reused a circuit.** Stock clients
   never do.
5. **What each rule refuses, or would refuse while off,** largest share
   first. These are upper bounds on what a rule saves, because a refused
   client can retry.
6. **What the responses cost:**
   - their bytes, and the bytes per descriptor served, in cells;
   - the CONNECTED cell (514 bytes) that every accepted stream costs;
   - about what share of the relay's written bytes that is.
7. **The empty streams:**
   - their rate;
   - what their CONNECTED cells cost;
   - an upper bound on their mean life, from the waiting-stream gauge
     (Little's law). Below 10 s, it also gives the share that must have
     closed within 10 s, before the stall timeout could close them
     (Markov's inequality).
8. **What these metrics can't say**, pointing to
   `analysis/v8-metrics-proposal.md`.

Where a relay exports the proposed families of that note (a prototype
build, `engineering/v8-prototype/`), the tool prints them too:
- requests by their BEGIN_DIR cell's place on the circuit;
- circuits by the number of BEGIN_DIR cells they reached;
- empty streams by how they ended, their circuit and their age;
- response bytes by the rule that would refuse them;
- descriptor bytes apart from not-found;
- bytes dropped at close, and bytes waiting.

The conclusions then use them as well: which kinds sit deep, how empty
streams end, and the bytes each rule would avoid.

## What it answers

The questions are the ones the Tor network team asked an operator under
this flood (tor-relays, "Shutting down my ~40 guards", 22 Oct 2026).

**Q1. Are the BEGIN_DIR streams onion service descriptor requests, or other
directory requests (consensus and the like)?** Answered. Every BEGIN_DIR
stream the relay opens (`tor_relay_streams_total{type="BEGIN_DIR"}`) ends in
exactly one bucket:

| line | metric | what it is |
|---|---|---|
| descriptor fetches | `tor_relay_hsdir_fetch_total` (all actions) | GET `/tor/hs/3/...` |
| descriptor uploads | `tor_relay_hsdir_upload_total` (all actions) | POST `/tor/hs/3/publish` |
| other directory requests | `tor_relay_begindir_request_total`, types `consensus`, `microdesc`, `descriptor`, `other_get` and `other_post` (`.6`: `tor_relay_dir_requests_total{type="non_hs"}`) | consensus, descriptors, microdescriptors, anything else |
| no request, or unparsable | `tor_relay_begindir_request_total`, types `unparsed` and `no_request` (`.6`: `tor_relay_dir_requests_total{type="unparsed"}`) | the stream closed before a request arrived, or the request didn't parse |
| still waiting | `tor_relay_begindir_connections{state="command_wait"}` (gauge) | open, no request yet |

The script prints the share of each and checks that nothing is
unaccounted. GET and POST are separate: a flood of descriptor fetches makes
the relay send much more than it receives, a flood of uploads or of empty
streams does not.

**Q4. Do the requests come over authenticated channels (from relays: the
circuit has more than one hop) or unauthenticated ones (from tor clients or
bridges: a one-hop circuit to this relay)?** Answered for onion service
requests only:

| line | metric | what it is |
|---|---|---|
| `single_hop` | `hsdir_fetch_total` + `hsdir_upload_total`, `action="single_hop"` | answered 503: the request came over an unauthenticated channel (a one-hop circuit from a client or bridge). On `.6`, also a request whose circuit was already closing |
| `circuit_dead` (`.7`) | the same, `action="circuit_dead"` | answered 503: the request came over an authenticated channel, but its stream or circuit was already closing |
| relay we know | the anonymous requests (fetches and uploads less `single_hop` and `circuit_dead`) minus the next line | authenticated, and the previous hop is a relay in our consensus or descriptors: normally a client's multi-hop circuit |
| relay identity we do not know | `dos_total{type="hsdir_unknown_prev_hop"}` | authenticated with a relay identity that is in neither our consensus nor our descriptors: a relay newer than our consensus, or a host running an unpublished relay identity, which passes the single-hop check |

Stock tor answers 503 to an onion service request on an unauthenticated
channel before anything else, so "unknown relay identity" is **not**
"unauthenticated": those requests did authenticate. The `single_hop` line is
the unauthenticated one. A request whose circuit was already closing (for
example after a client or a defense closed it with requests still queued)
is `circuit_dead` on `.7`; `.6` counts it as `single_hop` too.

**Not answered by the `.6` metrics** (`.7` answers it; see below): the
previous hop of the *other* directory requests and of the empty streams. If those are the bulk of a
flood, the metrics can say *what* they are, not *who* sends them.

**Q2. Per circuit or relay-wide?** Partly. For onion service requests:
`hsdir_req_reused` (requests on a circuit that already made one) and
`hsdir_circ_reused` (circuits that made more than one); the script prints
the mean requests per such circuit. For all BEGIN_DIR streams:
`begindir_over_max` counts BEGIN_DIR cells arriving on a circuit that
already holds `DoSBeginDirMaxStreams` (default 64) open directory streams,
whether or not that limit is enabled. `.6` has no count of BEGIN_DIR
streams per circuit in general; `.7` counts every BEGIN_DIR cell by its
place on its circuit (below).

**Q3. How many circuits, and from how many addresses?** Partly. Stock
`tor_relay_load_onionskins_total` (and the heartbeat's "Circuit handshake
stats") count only CREATE cells from **authenticated** previous hops: tor
leaves clients out of those statistics on purpose (`command.c`,
`cpuworker.c`). So their rate is the rate of circuits extended by relays,
or opened by unpublished relay identities. (Tor files ntor_v3 drops under
`type="ntor"`, so the script sums the drops over all types.) One stock
counter does see clients: congestion-control circuits
(`tor_relay_congestion_control_total{state="cc_circuits",action="circs_created"}`)
are counted from every kind of previous hop, so the script prints them
minus the authenticated ntor_v3 handshakes as a rough count of the circuits
clients opened. It is only rough: it includes the relay's own circuits
(in our quiet lab it read 73 while clients opened 1), misses senders that
don't negotiate congestion control, and can go negative. (`.7` counts
every CREATE cell, clients' included, by previous hop: below.) The
per-address circuit limit
(`tor_relay_dos_total{type="circuit_rejected"}`) applies only to
unauthenticated channels, and only marks an address that holds at least
`DoSCircuitCreationMinConnections` open connections (2 in the consensus as
of October 2026): circuits from relays or unpublished relay identities, and
from addresses with a single connection, never hit it. The ControlPort snapshot (`GETINFO
orconn-status`) splits the open connections by how tor names the peer:
`$FP~nick` when our node list has a name for it, `$FP` when it authenticated
with an identity our node list doesn't name, and `address:port` when it
never authenticated (a tor client or a bridge). The node list is close to,
but not the same test as, the HSDir check's "relay we know" (in our consensus
or a descriptor we have), so the script checks each unnamed identity against
those (`GETINFO ns/id/…` and `desc/id/…`) in memory and prints only the
count. It also prints how many distinct client addresses there are and the
most connections from one address. It is a snapshot of connections, not a
count of circuits or streams, and it needs ControlPort access.

## What `+tor41339.7` adds

`.7` (patches 0016–0023) classifies every
circuit's previous hop when its CREATE cell arrives:

- `client`: the channel never authenticated (a tor client or a bridge);
- `known_relay`: a relay in our consensus or descriptors;
- `unknown_relay`: an identity we don't know.

This is how the previous hop identified itself, not a hop count. The
script then prints a table of every BEGIN_DIR cell, accepted stream and
request by previous hop, which answers Q1 and Q4 together, and the sections
below.

| metric | what it is |
|---|---|
| `tor_relay_begindir_cell_total{prev_hop,nth}` | every well-formed BEGIN_DIR cell for a new stream, before stock tor or `DoSBeginDirLimitEnabled` refuses it. `nth` is its place among its circuit's BEGIN_DIR cells, in the bands below, so `nth="1"` counts circuits |
| `tor_relay_begindir_request_total{type,prev_hop}` | each accepted stream's request once, by what it asked for (see below). Summed over `type`, the accepted streams by previous hop, once each has a request or has closed; cells minus these were refused |
| `tor_relay_begindir_response_bytes_total{type}` | response bytes their stream read, by request type: work done, not proof of delivery |
| `tor_relay_begindir_request_over_max_total{type}` | requests on streams over `DoSBeginDirMaxStreams`: what `DoSBeginDirLimitEnabled` would refuse while it is off |
| `tor_relay_create_cell_total{prev_hop}` | every CREATE cell, clients' included |
| `tor_relay_create_cell_source_total{prev_hop,nth}`, `tor_relay_begindir_cell_source_total{prev_hop,nth}` | CREATE and BEGIN_DIR cells by their place among the cells of the same kind their source sent in the same minute (see below) |
| `tor_relay_hsdir_fetch_descriptor_total{lookup,nth}` | onion service descriptor fetches that reached the cache, `found` or `not_found`, by their place among the fetches of the same descriptor in the same minute |
| `tor_relay_dos_total{type="circuit_over_rate"}` | client CREATE cells that find their address's `DoSCircuitCreationRate`/`Burst` bucket empty, whether or not the address is marked. Counted only while `DoSCircuitCreationEnabled` is on |
| `tor_relay_dos_total{type="circuit_untracked"}` | client CREATE cells from addresses tor no longer tracks (a day or two after their last new connection), which `DoSCircuitCreation` neither limits nor counts. Counted only while `DoSCircuitCreationEnabled` is on |
| `tor_relay_dos_total{type="hsdir_descriptor_only_prev_hop"}` | anonymous onion service requests whose previous hop is a relay known only by its descriptor (it left the consensus in about the last two days). `HSDirRefuseUnknownPrevHop` treats these as known |
| `tor_relay_dos_total{type="begindir_over_stream_rate"}` | BEGIN_DIR cells that `DoSStreamCreationRate`/`Burst` would refuse on their circuit if it applied to them as it does to BEGIN. Never refused |

**Request types:**

- onion service requests: `hs_get` and `hs_post`;
- ordinary requests: `consensus`, `microdesc`, `descriptor` (relay
  descriptors), `other_get` (any other GET, 404s included) and
  `other_post`;
- no usable request: `unparsed` (malformed or incomplete) and `no_request`
  (the stream closed without sending anything).

**Sources and bands.** A source is what tor would limit:

- every client channel from one address, as the per-address DoS limits
  do. If tor isn't tracking that address, the channel is its own source;
- each channel from a relay.

The bands are `1` (the first cell from that source that minute), `2_10`,
`11_100`, `101_1000` and `1001_plus`.

- The first band counts the sources active in each clock minute: its rate
  × 60 is sources per minute, over an interval that is a multiple of 60 s.
- The share of cells in the last two bands is what a limit of 100 a minute
  per source would cut.

The same goes for descriptors in `hsdir_fetch_descriptor_total`: only a
keyed hash of each blinded key is kept, until the first fetch of a later
minute clears the table, and nothing per key is exported. Bridges count
none of the per-source or per-descriptor numbers. Tor counts these, and the
BEGIN_DIR stream-rate shadow, only while it has a MetricsPort, the only
place they show: a MetricsPort added by a reload starts them from zero.

The `single_hop` action means only a client channel; a request that
reached a circuit already closing is `circuit_dead`.
`tor_relay_begindir_request_total` counts onion service requests too:
`.6`'s `tor_relay_dir_requests_total` types are sums of its types (`non_hs`
is the five ordinary request types, `unparsed` is `unparsed` and
`no_request`). On a bridge, the `client` class is the bridge's own users.

**Reading them:**

- **One-hop circuits share directory traffic by design.** A bootstrapping
  client sends a consensus, certificate and microdescriptor requests over
  one circuit, and relays share theirs. So `2_10` and even `11_100` have a
  legitimate baseline for `client` and `known_relay`.
- **Onion service requests are different.** Stock clients use a new
  circuit for each one.
- **The client address count.** With `--cc-rate R --cc-burst B` (the
  consensus `DoSCircuitCreationRate` and `DoSCircuitCreationBurst`, 2 and 60
  as of October 2026) the script also prints (client CREATE cells −
  over-rate cells − untracked cells) ÷ (R × T + B) over its interval of T
  seconds. Within its bucket an address sends at most R cells a second
  plus its burst, so at least that many tracked client addresses sent
  CREATE cells. This holds only while `DoSCircuitCreationEnabled` is on:
  otherwise nothing counts over-rate or untracked cells.
- **Untracked addresses.** Tor forgets a client address a day or two after
  its last new connection, even while older connections from it stay open,
  and `DoSCircuitCreation` then neither limits nor counts it. A large
  `circuit_untracked` share means the stock per-address limit misses that
  much of a circuit flood.
- **Time per stream.** With an interval, the script also prints:
  - the mean time a stream waits for its request, from Little's law on the
    state gauge;
  - the mean time a descriptor takes to write;
  - how many descriptors were abandoned before their stream took them.
- **Relays behind a channel.** Nothing counts the sources behind a relay's
  channel.

## Prometheus

The same with PromQL, over 5 minutes:

```
# Q1
sum(rate(tor_relay_hsdir_fetch_total[5m]))
sum(rate(tor_relay_hsdir_upload_total[5m]))
sum(rate(tor_relay_begindir_request_total{type=~"consensus|microdesc|descriptor|other_get|other_post"}[5m]))
sum(rate(tor_relay_begindir_request_total{type=~"unparsed|no_request"}[5m]))
rate(tor_relay_streams_total{type="BEGIN_DIR"}[5m])
# Q4 (onion service requests)
sum(rate(tor_relay_hsdir_fetch_total{action="single_hop"}[5m]))
  + sum(rate(tor_relay_hsdir_upload_total{action="single_hop"}[5m]))
# the anonymous onion service requests
sum(rate(tor_relay_hsdir_fetch_total{action!~"single_hop|circuit_dead"}[5m]))
  + sum(rate(tor_relay_hsdir_upload_total{action!~"single_hop|circuit_dead"}[5m]))
rate(tor_relay_dos_total{type="hsdir_unknown_prev_hop"}[5m])
# Q2
sum(rate(tor_relay_dos_total{type="hsdir_req_reused"}[5m]))
  / (sum(rate(tor_relay_hsdir_fetch_total{action!~"single_hop|circuit_dead"}[5m]))
     + sum(rate(tor_relay_hsdir_upload_total{action!~"single_hop|circuit_dead"}[5m])))
rate(tor_relay_dos_total{type="begindir_over_max"}[5m])
# Q3 (onionskins: authenticated previous hops only)
sum(rate(tor_relay_load_onionskins_total{action="processed"}[5m]))
# roughly the circuits clients opened
sum(rate(tor_relay_congestion_control_total{state="cc_circuits",action="circs_created"}[5m]))
  - sum(rate(tor_relay_load_onionskins_total{type="ntor_v3",action="processed"}[5m]))
rate(tor_relay_dos_total{type="circuit_rejected"}[5m])
# .7: Q1 x Q4, BEGIN_DIR per circuit, and at least how many tracked client
# addresses per relay (with DoSCircuitCreationRate = 2 and Burst = 60, over
# 300 s, while DoSCircuitCreationEnabled is on)
sum by (type, prev_hop) (rate(tor_relay_begindir_request_total[5m]))
sum by (prev_hop) (rate(tor_relay_begindir_cell_total[5m]))
  / sum by (prev_hop) (rate(tor_relay_begindir_cell_total{nth="1"}[5m]))
(sum by (instance) (increase(tor_relay_create_cell_total{prev_hop="client"}[5m]))
  - sum by (instance) (increase(tor_relay_dos_total{type=~"circuit_over_rate|circuit_untracked"}[5m])))
  / (2 * 300 + 60)
# .7: client CREATE cells that DoSCircuitCreation can't see (untracked)
rate(tor_relay_dos_total{type="circuit_untracked"}[5m])
# .7: bytes by request type, and bytes per request
rate(tor_relay_begindir_response_bytes_total[5m])
sum by (type) (rate(tor_relay_begindir_response_bytes_total[5m]))
  / sum by (type) (rate(tor_relay_begindir_request_total[5m]))
# .7: what DoSBeginDirLimitEnabled would refuse, by type
rate(tor_relay_begindir_request_over_max_total[5m])
# .7: sources a minute, and the share past 100 cells a minute per source
60 * rate(tor_relay_create_cell_source_total{nth="1"}[5m])
sum by (prev_hop) (rate(tor_relay_create_cell_source_total{nth=~"101_1000|1001_plus"}[5m]))
  / sum by (prev_hop) (rate(tor_relay_create_cell_source_total[5m]))
sum by (prev_hop) (rate(tor_relay_begindir_cell_source_total{nth=~"101_1000|1001_plus"}[5m]))
  / sum by (prev_hop) (rate(tor_relay_begindir_cell_source_total[5m]))
# .7: descriptors fetched a minute, and the share of fetches past 10 a minute
60 * rate(tor_relay_hsdir_fetch_descriptor_total{nth="1"}[5m])
sum by (lookup) (rate(tor_relay_hsdir_fetch_descriptor_total{nth!~"1|2_10"}[5m]))
  / sum by (lookup) (rate(tor_relay_hsdir_fetch_descriptor_total[5m]))
# .7: descriptor-only previous hops, and BEGIN_DIR over the stream rate
rate(tor_relay_dos_total{type="hsdir_descriptor_only_prev_hop"}[5m])
rate(tor_relay_dos_total{type="begindir_over_stream_rate"}[5m])
```

## Checked in a private lab

In a loopback-only chutney network (`--network none`, `+tor41339.6` on
Ubuntu 24.04), one HSDir received, at once: descriptor fetches multiplexed on
shared circuits through relays, one-hop fetches from an unpublished relay
identity, one-hop fetches from a plain client (answered 503), and the
network's ordinary directory traffic. Over 45 seconds the script reported
99.4% descriptor fetches and 0.6% other requests, with nothing unaccounted;
1.00/s `single_hop` (the one-hop client), 2.44/s from relays we know and
0.49/s from the unpublished identity. Over the whole run, the unpublished
identity's 35 fetches matched `hsdir_unknown_prev_hop` exactly; the one-hop
client's 35 fetches showed as 70 `single_hop` requests (counts are requests,
not clients: it sent two per fetch); 2 circuits carried 105 descriptor
requests on average; and the ControlPort showed 10 connections to named
relays, 2 from one unnamed identity, which the script found in neither our
consensus nor our descriptors, and 1 client connection
(`engineering/breakdown-lab/results/v6-lab24v6.txt`). With the proposed
patches that became 0016 and 0017 bound over the package's tor, the same
lab showed every class's requests adding up exactly to its accepted streams (client 70, known relay 180, unknown relay 37,
including the unpublished identity's 2 consensus fetches of its own), and
CREATE cells by class next to the stock onionskin count of the
authenticated ones (`engineering/breakdown-lab/results/p2-0016-0017-lab24v6.txt`).

The same lab with the final `+tor41339.7` package
(`engineering/breakdown-lab/results/v7-lab24v7.txt`) ran every section:
- **Cells, requests and sources agree.** Every class's BEGIN_DIR cells
  equal its requests (client 71, known relay 181, unknown relay 36), and
  equal the sum of its per-source bands. The same holds for CREATE cells
  (15, 48, 2).
- **Descriptors.** The 211 fetches that reached the cache are all in the
  per-descriptor bands (`found`), as three descriptor-minutes, with 38%
  past a descriptor's 100th fetch in a minute.
- **Response bytes.** They came through the real read path: 10.7 KB per
  descriptor fetch.
- **Per circuit.** BEGIN_DIR cells per circuit were 35.5 (client), 25.9
  (known relay) and 18.0 (unknown relay), and 41% of the known-relay
  class's cells were past their circuit's 100th: the multiplexed fetches.
- **Nothing else counted.** `circuit_over_rate`, `circuit_untracked`, the
  over-max requests and the stream-rate shadow stayed 0, as this load
  never reaches them.

The conclusions, and the sections for the proposed families, ran in the same
lab with two more load clients, which open BEGIN_DIR streams that never send
a request. Two results files show them:
- `engineering/v8-prototype/lab/results/v8-prototype-lab24v7.txt`: every
  node runs the v8 prototype;
- `engineering/v8-prototype/lab/results/v7-control-lab24v7.txt`: the same
  load on `.7`.

On `.7`, the conclusions name the fetches through relays we know, their
reuse (95.6% of onion service requests on a circuit that had already made
one), what each rule would refuse, and the empty streams' cost. They end
with what `.7` can't say. On the prototype, they add how the empty streams
ended and on which circuits, and the response bytes each rule would avoid.
