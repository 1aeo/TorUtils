# Can our metrics answer the network team's BEGIN_DIR questions?

On 22 October 2026, in the tor-relays thread "Shutting down my ~40 guards",
David Goulet (Tor network team) asked an operator under the BEGIN_DIR flood
four questions, because "in both cases, we will apply different fixes":

- **Q1.** Are the BEGIN_DIR streams onion service descriptor requests, or
  ordinary directory requests (consensus and the like)?
- **Q2.** Is a limit per circuit or relay-wide (and what does the
  per-circuit pattern look like)?
- **Q3.** Do the 1000 circuits/s come from 1000 addresses? Per-address
  circuit limits exist.
- **Q4.** Do the circuits arrive over **authenticated** channels (from
  relays: multi-hop, so onion service requests) or **unauthenticated** ones
  (tor clients: one hop to this relay, so ordinary directory requests)?

This note says what tor's channels and counters actually mean, what the
counters posted to the thread measured, what `+tor41339.6` answers, and the
metric change that would answer the rest. File and line references are to
tor 0.4.9.14 unless marked v6 (this series).

## How tor sees a previous hop

- **Who authenticates.** A tor that connects to a relay authenticates only
  if it is a public relay: `public_server_mode()`, which is an ORPort and
  neither `ClientOnly` nor `BridgeRelay` (`routermode.c:43`,
  `channeltls.c:2277`, `:2378`). Clients, onion services and bridges never
  do, so the relay marks their channels as client channels
  (`channeltls.c:1777`). An unpublished relay (ORPort set,
  `PublishServerDescriptor 0`) does authenticate, with an identity no
  consensus lists. Arti clients don't authenticate; Arti relays do.
- **What a BEGIN_DIR on each kind of channel means.** On a client channel,
  the circuit was built by that client and has one hop: stock clients
  fetch the consensus, descriptors and microdescriptors that way, from a
  directory guard (`dirclient.c:556`). Stock software never sends an onion
  service request over one hop; the relay answers one with a 503 (`dircache.c:1364`).
  On an authenticated channel from a relay we know, the cases are a
  client's multi-hop circuit to us (onion service requests, and a few
  anonymized directory fetches), **and** that relay's own one-hop
  directory fetches: relays use BEGIN_DIR to directory caches too. On an
  authenticated channel with an identity we don't know, the cases are a
  relay newer than our consensus, or a host running an unpublished relay
  identity, which passes the single-hop check (`directory.c:264`) and so
  can make one-hop onion service requests.
- So David's model is mostly right with two exceptions: authenticated does
  not mean multi-hop (relays fetch for themselves over one hop, and an
  unpublished relay identity can send one-hop onion service requests), and
  unauthenticated is not always a client's own circuit (a bridge relays its
  users' circuits as an unauthenticated peer, though stock software sends
  no BEGIN_DIR to a second hop).
- **Per-address limits.** The circuit creation limit looks only at client
  channels (`dos.c:720`), and marks an address only once its bucket is
  empty **and** it holds at least `DoSCircuitCreationMinConnections` open
  connections (`dos.c:500`); the consensus of 22 October 2026 sets that to
  2, with `DoSCircuitCreationRate=2`, `Burst=60`. Circuits over
  authenticated channels, and over client channels from addresses holding
  one connection each, are never limited per address. The connection
  limits (`DoSConnectionMaxConcurrentCount=50`) count connections, not
  circuits.
- **Stock circuit counters leave clients out.** `tor_relay_load_onionskins_total`
  and the heartbeat's "Circuit handshake stats" count only CREATE cells
  from authenticated channels (`command.c:349`, `cpuworker.c:622`). Their
  rate is the rate of circuits extended by relays or opened by unpublished
  relay identities; nothing counts circuits opened by clients.

## What the posted table measured

The table posted on 22 October came from the legacy `+tor41339.3` counters.
Those count an onion service request in `connection_dir_allow_hs_request()`,
which runs **after** stock tor's single-hop check (legacy 0001, the
`dircache.c` hunks at `-1366` and `-1611`). So:

| Column | What it is |
|---|---|
| All directory starts | `tor_relay_streams_total{type="BEGIN_DIR"}`: every BEGIN_DIR stream that got a directory connection |
| HS attempts | onion service GET and POST that passed the single-hop check: **authenticated channels only** |
| Other / unclassified | everything else: ordinary directory requests, onion service requests refused as single hop, streams that never sent a usable request. Not "non-HSDir". |
| HS recognized hop | authenticated, previous hop a relay we know |
| HS unrecognized hop | authenticated with a relay identity we don't know. Not "unauthenticated". |
| Repeat HS requests, circuits with repeat HS | onion service requests after the first on a circuit, and the circuits that made them |

On the relay under attack (44 hours): 212 BEGIN_DIR streams/s on average,
14.8/s of them counted onion service requests (7%), 197/s "other".
84% of the onion service requests came on a circuit that had already made
one, about 6.4 per such circuit, all over authenticated channels; stock C tor
gives every onion service directory request its own circuit. 1.8% came from
relay identities the HSDir didn't know (0.06% to 7.6% on the nine quiet
relays, 0.54% pooled). How many onion service requests came over
unauthenticated channels, and what the 197/s "other" were, these counters
cannot say.

## What `+tor41339.6` answers

`operator/begindir-breakdown.py` and `operator/BEGIN_DIR-BREAKDOWN.md` turn
the `.6` MetricsPort into these answers.

| | `.6` | how |
|---|---|---|
| Q1 | **yes** | every BEGIN_DIR stream ends in exactly one of `hsdir_get_total`, `hsdir_post_total`, `dir_requests_total{non_hs}`, `{unparsed}`, or is still `dir_server_conns{command_wait}`; GET and POST are separate. It does not say which ordinary document (consensus or other). |
| Q4 | **onion service requests only** | `single_hop` (unauthenticated, or the circuit was already closing), `hsdir_request_total` minus `hsdir_unknown_prev_hop` (relay we know), `hsdir_unknown_prev_hop` (identity we don't know). Ordinary requests and empty streams carry no previous hop. |
| Q2 | **onion service requests only** | `hsdir_req_reused`, `hsdir_circ_reused`; and `begindir_over_max` for circuits holding 64 or more open directory streams. No BEGIN_DIR count per circuit in general. |
| Q3 | **partly** | stock onionskins give circuits from authenticated channels only; a ControlPort snapshot (`GETINFO orconn-status`, which the script reads) counts open connections by kind of peer and distinct client addresses, but not circuits or streams. |

## The metric change that answers the rest

`patches/proposed/0016-relay_metrics-Count-BEGIN_DIR-traffic-by-kind-of-pre.patch`
(on top of 0001–0015; not in the `.6` packages):

- classifies a circuit's previous hop as `client` (never authenticated),
  `relay` (authenticated, in our consensus or descriptors) or
  `unknown_relay` (authenticated, an identity we don't know), once per
  circuit at its first BEGIN_DIR, and copies it to each directory stream,
  so a stream that closes before its request is still attributed;
- adds label `prev_hop` to `tor_relay_dir_requests_total`, and families
  `tor_relay_begindir_cells_total{prev_hop}`,
  `tor_relay_begindir_circuits_total{prev_hop}` and
  `tor_relay_create_cells_total{prev_hop}` (CREATE cells from every kind of
  channel, unlike the stock onionskin counters);
- counts an onion service request whose circuit was already closing as the
  new action `closing`, so `single_hop` means exactly "unauthenticated".

With it, Q4 is answered for every BEGIN_DIR stream, Q2 by BEGIN_DIR cells
per circuit for each kind of previous hop, and Q3 by circuits per kind.
Cost: one known-relay lookup per CREATE cell and per circuit's first
BEGIN_DIR, three bits per circuit and two per directory connection; no
address or identity is recorded.

It builds with `--enable-fatal-warnings`, passes the full unit suite (1615
tests; new tests kill all six mutants tried), `check-spaces` and
`check-changes`. In the private lab (one HSDir receiving multiplexed
fetches through relays, one-hop fetches from an unpublished relay identity,
one-hop fetches from a plain client, and ordinary traffic) it reported
BEGIN_DIR cells by previous hop as client 42, relay 182 and unknown relay
43, each equal to that kind's classified requests (client: the 35 refused
one-hop fetches and 7 ordinary requests; unknown relay: 35 fetches and 8
ordinary requests), and CREATE cells as client 68, relay 136 and unknown
relay 5, while the stock onionskin counter showed 140 handshakes and none of
the clients' 68
(`engineering/breakdown-lab/results/prevhop-prototype-lab24v6.txt`). In an
earlier run the one-hop client sent all 70 of its requests on one circuit:
one-hop clients reuse their directory circuit, so a high count per circuit
alone is not abuse.

Still not answered: which ordinary document a request was for, whether an
empty stream sent nothing or part of a request, and how many distinct
addresses send circuits (the ControlPort snapshot gives distinct client
addresses for open connections).
