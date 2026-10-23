# What is this BEGIN_DIR flood? A breakdown from the MetricsPort

`begindir-breakdown.py` reads the MetricsPort of a relay running the
tor#41339 series (`+tor41339.6`), optionally twice to get rates, and says
what the relay's BEGIN_DIR streams were. With access to the ControlPort it
also counts the relay's open OR connections by kind of peer. It only reads,
and prints counts: never an address, a fingerprint or a nickname.

```
python3 -I begindir-breakdown.py --metrics http://127.0.0.1:9035/metrics \
    --interval 60 \
    --control 127.0.0.1:9051 --cookie /var/lib/tor/control_auth_cookie
```

`--interval 0` prints totals since the relay started. `--control-socket`
takes a ControlSocket path instead of `--control`, and `--password` a
HashedControlPassword password instead of `--cookie`. Without `--control`
the connection snapshot is skipped. Run it during a flood and again on a
quiet day for comparison.

## What it answers

The questions are the ones the Tor network team asked an operator under
this flood (tor-relays, "Shutting down my ~40 guards", 22 Oct 2026).

**Q1. Are the BEGIN_DIR streams onion service descriptor requests, or other
directory requests (consensus and the like)?** Answered. Every BEGIN_DIR
stream the relay opens (`tor_relay_streams_total{type="BEGIN_DIR"}`) ends in
exactly one bucket:

| line | metric | what it is |
|---|---|---|
| descriptor fetches | `tor_relay_hsdir_get_total` (all actions) | GET `/tor/hs/3/...` |
| descriptor uploads | `tor_relay_hsdir_post_total` (all actions) | POST `/tor/hs/3/publish` |
| other directory requests | `tor_relay_dir_requests_total{type="non_hs"}` | consensus, descriptors, microdescriptors, anything else |
| no request, or unparsable | `tor_relay_dir_requests_total{type="unparsed"}` | the stream closed before a request arrived, or the request didn't parse |
| still waiting | `tor_relay_dir_server_conns{state="command_wait"}` (gauge) | open, no request yet |

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
| `single_hop` | `hsdir_get_total` + `hsdir_post_total`, `action="single_hop"` | answered 503: the request came over an unauthenticated channel (a one-hop circuit from a client or bridge), or its circuit was already closing |
| relay we know | `dos_total{type="hsdir_request_total"}` minus the next line | authenticated, and the previous hop is a relay in our consensus or descriptors: normally a client's multi-hop circuit |
| relay identity we do not know | `dos_total{type="hsdir_unknown_prev_hop"}` | authenticated with a relay identity that is in neither our consensus nor our descriptors: a relay newer than our consensus, or a host running an unpublished relay identity, which passes the single-hop check |

Stock tor answers 503 to an onion service request on an unauthenticated
channel before anything else, so "unknown relay identity" is **not**
"unauthenticated": those requests did authenticate. The `single_hop` line is
the unauthenticated one; it also counts requests whose circuit was already
closing (for example after a client or a defense closed it with requests
still queued).

**Not answered by these metrics:** the previous hop of the *other*
directory requests and of the empty streams. If those are the bulk of a
flood, the metrics can say *what* they are, not *who* sends them.

**Q2. Per circuit or relay-wide?** Partly. For onion service requests:
`hsdir_req_reused` (requests on a circuit that already made one) and
`hsdir_circ_reused` (circuits that made more than one); the script prints
the mean requests per such circuit. For all BEGIN_DIR streams:
`begindir_over_max` counts BEGIN_DIR cells arriving on a circuit that
already holds `DoSBeginDirMaxStreams` (default 64) open directory streams,
whether or not that limit is enabled. There is no count of BEGIN_DIR
streams per circuit in general.

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
don't negotiate congestion control, and can go negative. The per-address circuit limit
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

## With the proposed 0016 and 0017

`patches/proposed/0016` and `0017` (not in the `.6` packages) classify every
circuit's previous hop when its CREATE cell arrives: `client` (the channel
never authenticated: a tor client or a bridge), `known_relay` (a relay in our
consensus or descriptors) or `unknown_relay` (an identity we don't know). It
is how the previous hop identified itself, not a hop count. With them the
script also prints a table of every BEGIN_DIR cell, accepted stream and
request by previous hop, which answers Q1 and Q4 together:

| metric | what it is |
|---|---|
| `tor_relay_begindir_cell_total{prev_hop,nth}` | every BEGIN_DIR cell, before stock tor or `DoSBeginDirLimitEnabled` refuses it; `nth` is its place among its circuit's BEGIN_DIR cells (`1`, `2_9`, `10_49`, `50_plus`), so `nth="1"` counts circuits |
| `tor_relay_begindir_streams_total{prev_hop}` | BEGIN_DIR streams accepted; cells minus streams were refused |
| `tor_relay_begindir_requests_total{type,prev_hop}` | each request once, by what it asked for: `hs_get`, `hs_post`, `consensus`, `microdesc`, `descriptor`, `other` (404s included), `unparsed`, or `no_request` (the stream closed without sending anything) |
| `tor_relay_create_cell_total{prev_hop}` | every CREATE cell, clients' included |
| `tor_relay_dos_total{type="circuit_over_rate"}` | (0017) client CREATE cells that find their address over `DoSCircuitCreationRate`, whether or not the address is marked |

The `single_hop` action then means only a client channel; a request that
reached a circuit already closing is `circuit_dead`. `tor_relay_dir_requests_total`
keeps its `.6` meaning.

Reading them: one-hop directory circuits are shared by design (a
bootstrapping client sends a consensus, certificate and microdescriptor
requests over one; relays share theirs), so `2_9` and even `10_49` have a
legitimate baseline for `client` and `known_relay`. Onion service requests
are different: stock clients use a new circuit for each. With `--cc-rate R`
(the consensus `DoSCircuitCreationRate`, 2 as of October 2026) the script
also prints (client CREATE cells − over-rate cells) ÷ R: each address
sends at most R cells a second within its rate, so at least that many
client addresses sent CREATE cells. Nothing counts the sources behind
authenticated channels.

## Prometheus

The same with PromQL, over 5 minutes:

```
# Q1
sum(rate(tor_relay_hsdir_get_total[5m]))
sum(rate(tor_relay_hsdir_post_total[5m]))
rate(tor_relay_dir_requests_total{type="non_hs"}[5m])
rate(tor_relay_dir_requests_total{type="unparsed"}[5m])
rate(tor_relay_streams_total{type="BEGIN_DIR"}[5m])
# Q4 (onion service requests)
sum(rate(tor_relay_hsdir_get_total{action="single_hop"}[5m]))
  + sum(rate(tor_relay_hsdir_post_total{action="single_hop"}[5m]))
rate(tor_relay_dos_total{type="hsdir_request_total"}[5m])
rate(tor_relay_dos_total{type="hsdir_unknown_prev_hop"}[5m])
# Q2
rate(tor_relay_dos_total{type="hsdir_req_reused"}[5m])
  / rate(tor_relay_dos_total{type="hsdir_request_total"}[5m])
rate(tor_relay_dos_total{type="begindir_over_max"}[5m])
# Q3 (onionskins: authenticated previous hops only)
sum(rate(tor_relay_load_onionskins_total{action="processed"}[5m]))
# roughly the circuits clients opened
sum(rate(tor_relay_congestion_control_total{state="cc_circuits",action="circs_created"}[5m]))
  - sum(rate(tor_relay_load_onionskins_total{type="ntor_v3",action="processed"}[5m]))
rate(tor_relay_dos_total{type="circuit_rejected"}[5m])
# With 0016 and 0017: Q1 x Q4, BEGIN_DIR per circuit, and at least how many
# client addresses (with DoSCircuitCreationRate = 2)
sum by (type, prev_hop) (rate(tor_relay_begindir_requests_total[5m]))
sum by (prev_hop) (rate(tor_relay_begindir_cell_total[5m]))
  / sum by (prev_hop) (rate(tor_relay_begindir_cell_total{nth="1"}[5m]))
(sum(rate(tor_relay_create_cell_total{prev_hop="client"}[5m]))
  - sum(rate(tor_relay_dos_total{type="circuit_over_rate"}[5m]))) / 2
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
(`engineering/breakdown-lab/results/v6-lab24v6.txt`). With the proposed 0016 and 0017 bound over the
package's tor, the same lab showed every class's requests adding up exactly
to its accepted streams (client 70, known relay 180, unknown relay 37,
including the unpublished identity's 2 consensus fetches of its own), and
CREATE cells by class next to the stock onionskin count of the
authenticated ones (`engineering/breakdown-lab/results/p2-0016-0017-lab24v6.txt`).
