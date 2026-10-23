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
counters posted to the thread measured, what `+tor41339.6` answered, and what
`+tor41339.7` adds to answer the rest. File and line references are to tor
0.4.9.14 unless marked v6 (this series).

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
  directory fetches: relays use BEGIN_DIR to directory caches too. A relay
  we know is one in our consensus or one whose descriptor we still hold,
  which includes relays that left the consensus in about the last two days
  (`connection_or.c:814`, `routerlist.c:1944`). On an authenticated channel
  with an identity we don't know, the cases are a relay newer than our
  consensus, or a host running an unpublished relay identity. The
  single-hop check only asks whether the channel authenticated
  (`directory.c:264`), so an unpublished identity, or a listed relay
  running modified software, can make one-hop onion service requests.
- So David's model is mostly right with two exceptions: authenticated does
  not mean multi-hop (relays fetch for themselves over one hop, and any
  relay identity, listed or not, can send one-hop onion service requests
  with modified software), and
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
  relay identities. (Tor files ntor_v3 drops under `type="ntor"`,
  `onion_queue.c:111`, so `{type="ntor_v3",action="dropped"}` is always 0.)
  One stock counter does see clients:
  `tor_relay_congestion_control_total{state="cc_circuits",action="circs_created"}`
  counts congestion-control circuits from every kind of previous hop
  (`cpuworker.c:446`), so it minus `onionskins{type="ntor_v3",action="processed"}`
  roughly approximates the circuits clients opened. It is only rough: it
  also counts the relay's own circuits, misses senders that don't negotiate
  congestion control, and can go negative when authenticated circuits
  don't negotiate it.

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
| Q3 | **partly** | stock onionskins give circuits from authenticated channels only, and congestion-control circuits minus those roughly give the circuits clients opened plus the relay's own; a ControlPort snapshot (`GETINFO orconn-status`, which the script reads) counts open connections by kind of peer and distinct client addresses, but not circuits or streams. Nothing counts addresses over time. |

## What `+tor41339.7` adds

Patches 0016 and 0017 were proposed under those numbers; three independent
designs, two judges and three adversarial verifiers shaped them. A first
version that classified a circuit at its first BEGIN_DIR was superseded.
`.7` adds six more (0018–0023, from `metrics-proposal.md`); the end of this
section lists them. `.7` also renames most of `.6`'s families
(`analysis/v7-review.md` maps them); the names below are `.7`'s.

- **The previous hop, set once per circuit.** When a CREATE cell arrives,
  `channel_get_prev_hop()` classifies its channel as `client` (never
  authenticated: a tor client or a bridge), `known_relay` (a relay in our
  consensus or descriptors) or `unknown_relay` (an identity we don't know).
  The circuit keeps the class in two bits and its directory connections
  copy it, so a request is attributed even after its circuit is gone. It is
  how the previous hop identified itself, not a hop count.
- **0016 counts, by that class:** every CREATE cell
  (`tor_relay_create_cell_total`, clients' included, unlike the stock
  onionskin counters); every BEGIN_DIR cell before stock tor or 0012 can
  refuse it, with its place on its circuit
  (`tor_relay_begindir_cell_total{nth}`, in the bands `1`, `2_10`,
  `11_100`, `101_1000` and `1001_plus` that the per-source counts use too,
  so `nth="1"` counts circuits); and each accepted stream's request once,
  by what it asked for (`tor_relay_begindir_request_total{type}`:
  `hs_get`, `hs_post`, `consensus`, `microdesc`, `descriptor`, `other`
  (which 0018 splits into `other_get` and `other_post`), `unparsed`,
  `no_request`). An onion service request that reaches a circuit already
  closing becomes `circuit_dead`, as stock tor names that case in its other
  onion service families, so `single_hop` means only a client channel.
  This is 0007's family, which in `.6` (as `tor_relay_dir_requests_total`)
  counted only the requests that aren't onion service requests, in two
  types that are sums of these; its sum by previous hop is the accepted
  streams, which stock `tor_relay_streams_total{type="BEGIN_DIR"}` counts in
  total.
- **0017 counts** client CREATE cells that find their address's
  `DoSCircuitCreationRate`/`Burst` bucket empty, whether or not the address
  is marked (`tor_relay_dos_total{type="circuit_over_rate"}`), and those
  from addresses tor no longer tracks
  (`tor_relay_dos_total{type="circuit_untracked"}`), which
  `DoSCircuitCreation` neither limits nor counts; both while
  `DoSCircuitCreationEnabled` is on. Within its bucket an address can send
  at most Rate × T + Burst CREATE cells in T seconds, so (client CREATE
  cells − both) ÷ (Rate × T + Burst) is a lower bound on how many tracked
  client addresses sent CREATE cells.

| | with 0016 and 0017 |
|---|---|
| Q1 | every accepted BEGIN_DIR stream by what it asked for, down to consensus, microdescriptors and relay descriptors, and streams that sent nothing |
| Q4 | every BEGIN_DIR cell and request by previous hop; refusals by class are cells minus requests |
| Q2 | BEGIN_DIR cells per circuit for each class, and the share past a circuit's 10th, 100th or 1000th |
| Q3 | CREATE cells by class, and for clients a lower bound on distinct addresses; nothing for the sources behind authenticated channels |

Cost: one known-relay lookup per CREATE cell from an authenticated channel
(a consensus binary search, about 1 µs warm and up to 9 µs cold; under
1.5% of a core at 1,500/s),
twelve bits per circuit and three per directory connection (neither struct
grows), and 44 more series. `hsdir_unknown_prev_hop` keeps its lookup per
request, so it still matches what `HSDirRefuseUnknownPrevHop` refuses.

Both build with `--enable-fatal-warnings`, with and without the relay
module, and pass the full unit suite (1618 tests), `check-spaces` and
`check-changes`; practracker shows no new problem kinds; the new tests kill
all 22 mutants tried; and the patches apply with `git am` to tor-0.4.9.14
after 0001–0015, to the exact tree tested.

In the private lab (one HSDir receiving, at once, descriptor fetches
multiplexed on shared circuits through relays, one-hop fetches from an
unpublished relay identity, one-hop fetches from a plain client, and
ordinary traffic), nothing was unaccounted and each class's requests added
up exactly to its accepted streams: client 70 BEGIN_DIR cells (the plain
client's one-hop fetches, all refused, all on one circuit), known relay 180
(176 fetches and 4 uploads on 6 circuits, one of them carrying the
multiplexed load), unknown relay 37 (the unpublished identity's 35 fetches
and 2 consensus fetches of its own). CREATE cells were client 1, known
relay 26 and unknown relay 2, and the stock onionskin counter showed exactly
the authenticated 28. The `.6` rough count of clients' circuits read 73 in
this quiet network, almost all of it the relay's own circuits; on a busy
relay they are a small share, but the exact count needs 0016
(`engineering/breakdown-lab/results/p2-0016-0017-lab24v6.txt`, run with the
proposed patches before they were renumbered). One-hop
directory circuits are shared by design, so many BEGIN_DIR cells on one
circuit are not abuse in themselves; many onion service requests on one
circuit are, since stock clients use a new circuit for each.

The six other additions in `.7`:

| Patch | Adds | Answers |
|---|---|---|
| 0018 | `other` split into `other_get` and `other_post`; response bytes read by their stream, by request type | Q1, and what each kind of request costs in bandwidth |
| 0019 | requests on streams over `DoSBeginDirMaxStreams`, by type | Q2: what `DoSBeginDirLimitEnabled` would refuse, while it is off |
| 0020 | CREATE and BEGIN_DIR cells by their place among their source's cells that minute (1st, 2–10, 11–100, 101–1000, 1001+). A source is a client address (a client channel, if tor doesn't track its address) or a relay's channel; bridges don't count these, and relays count them only with a MetricsPort | Q3: sources per minute, and what a limit per source would cut |
| 0021 | onion service fetches by their place among the same descriptor's fetches that minute, found and missing apart (a keyed hash per key, kept until the first fetch of a later minute; only with a MetricsPort) | whether fetches concentrate on a few descriptors, and whether misses repeat |
| 0022 | onion service requests whose previous hop is known only by descriptor | Q4: how much `HSDirRefuseUnknownPrevHop` lets through from relays that left the consensus |
| 0023 | BEGIN_DIR cells over their circuit's `DoSStreamCreationRate`/`Burst` (never refused; only with a MetricsPort) | Q2: what a per-circuit rate limit would cut |

Still not answered, by design:

- the hop count behind a previous hop: a known relay can be a client's
  middle, or an attacker's own relay sending one-hop requests;
- the clients behind a relay's channel;
- what a refused BEGIN_DIR would have asked for;
- peaks within a minute.
