# Ten questions about the BEGIN_DIR flood, and the metrics each one needs

The central question is: **which observable behaviour creates the expensive
work, and which defense reduces that work while keeping normal directory
service working?** A review proposed ten questions to organize the reports
and the instrumentation around; David Goulet (Tor network team) asked four of
them on tor-relays on 22 October 2026 (Q1, Q2, Q4 and Q10 below). This note
checks each metric they need against what exists, and lists what is missing.

Where each metric comes from:

| Mark | Source |
|---|---|
| **S** | stock tor 0.4.9.14, MetricsPort |
| **S·ctl** | stock, ControlPort `GETINFO` |
| **S·log** | stock, logs only: the heartbeat, or `SIGUSR1` at info level |
| **S·xi** | stock, the relay's statistics files and published extra-info (24-hour periods) |
| **.6** | `+tor41339.6` (0006–0015), being rolled out |
| **P** | proposed 0016 and 0017, built and tested but not in a package |
| **T** | `../operator/begindir-breakdown.py` (read-only) |
| **X** | outside tor: the OS, `perf`, the private lab, controlled probes |
| **Gap** | nothing yet; proposals are in the last section |

The "What we have" column of the review predates 0016 and 0017. The main
corrections are in each question's notes.

## Q1. Onion service descriptors, or ordinary directory information? (David)

| Metric | Where |
|---|---|
| BEGIN_DIR starts accepted | **S** `tor_relay_streams_total{type="BEGIN_DIR"}` |
| BEGIN_DIR cells received, refused ones included | **P** `tor_relay_begindir_cell_total` |
| HS GET and POST, by outcome | **.6** `tor_relay_hsdir_get_total{action}`, `tor_relay_hsdir_post_total{action}` |
| consensus, microdescriptors, relay descriptors, other | **P** `tor_relay_begindir_requests_total{type}`; **.6** has them only as one `non_hs` |
| consensus diffs apart from full consensuses | **Gap** (counted together under `consensus`) |
| malformed or unparsed, and streams that sent nothing | **.6** `dir_requests_total{type="unparsed"}` (both together); **P** `unparsed` and `no_request` apart |
| tunneled vs direct (DirPort) | **.6**, **P** count tunneled requests only, by design. **S·xi** `dirreq-v3-direct-dl` and `-tunneled-dl` cover consensus downloads only. DirPort requests otherwise: **Gap**, low priority (onion service requests on the DirPort are refused with 503) |

With 0016, Q1 is answered except for consensus diffs, which matter for
bytes (a diff is small) rather than for "HS or not".

## Q2. Authenticated relay channels, or client channels? (David)

| Metric | Where |
|---|---|
| received BEGIN_DIR by channel class | **P** `tor_relay_begindir_cell_total{prev_hop}`: `client`, `known_relay`, `unknown_relay`, set at CREATE |
| accepted, and so refused, by class | **P** `tor_relay_begindir_streams_total{prev_hop}`; refused = cells − streams |
| parsed requests by class × request class | **P** `tor_relay_begindir_requests_total{type,prev_hop}` |
| HS requests only | **.6** `single_hop` (client channel or closing circuit), `hsdir_request_total` − `hsdir_unknown_prev_hop`, `hsdir_unknown_prev_hop` |

The review is right that the legacy recognized/unrecognized counter does not
answer this (it only sees authenticated channels). 0016 answers it for every
start, refused ones included. A refused cell's *request* class is unknowable,
since it is refused before any request arrives.

## Q3. One request per circuit, or many on fewer circuits?

| Metric | Where |
|---|---|
| HS requests per circuit (first vs repeat) | **.6** `hsdir_req_reused`, `hsdir_circ_reused` (a 2-bit counter: "2 or more") |
| all BEGIN_DIR by place on the circuit | **P** `begindir_cell_total{prev_hop,nth="1|2_9|10_49|50_plus"}`: cells per circuit and the share past the 50th |
| circuits reaching 2, 10, 100 requests | **Gap**. `nth="1"` counts circuits, but the bands count cells, not circuits reaching each step |
| HS and non-HS reuse apart | partly: **.6** for HS (up to 2), **P** by class. Per-circuit HS counts beyond 2: **Gap** |
| burst rates | **Gap**. Rates between scrapes are invisible (scrapes also stall under load, tor#41458) |
| simultaneous directory streams | **.6** relay-wide: `tor_relay_dir_server_conns{state}`; per circuit only the ≥64 tail: `dos_total{type="begindir_over_max"}`. Distribution: **Gap** |
| circuit lifetime | **Gap** |

## Q4. Do high circuit-creation rates come from a few sources or many? (David)

| Metric | Where |
|---|---|
| CREATE cells received/s, every kind of channel | **P** `tor_relay_create_cell_total{prev_hop}` (counted before any drop) |
| handshakes processed and dropped | **S** `tor_relay_load_onionskins_total{action}`: authenticated channels only, by design; ntor_v3 drops are filed under `type="ntor"` |
| refused per address (clients only) | **S** `dos_total{type="circuit_rejected"}`, `marked_address` |
| completed handshakes, and drops, by class | **Gap** |
| distinct client addresses | **P** 0017: (client CREATE − `circuit_over_rate`) ÷ `DoSCircuitCreationRate` is a lower bound |
| distinct upstream relays / channels | **Gap**. **S·log**: `SIGUSR1` logs each channel's open circuits with its relay identity digest (and its address, unless `SafeLogging` scrubs it); **T** counts open connections by kind, not their circuits |
| largest-source and top-ten-source shares, by class | **Gap** |

Open circuits (`tor_relay_circuits_total`) are a gauge and cannot stand in for
creations; 0016's CREATE counter replaces that use. For authenticated channels
a "source" is the previous-hop relay, not whoever is behind it; the HSDir
cannot see further, by design.

## Q5. Are the previous-hop relays in the consensus, descriptor-only or unknown, with which flags?

| Metric | Where |
|---|---|
| known (consensus **or** descriptor) vs unknown, by class | **P** `known_relay` / `unknown_relay`; **.6** for HS only (`hsdir_unknown_prev_hop`) |
| consensus vs descriptor-only apart | **Gap**: "known" includes relays whose descriptor we still hold up to about two days after they left the consensus |
| their flags (Running, Valid, Guard…) | **Gap**, low value: a relay in the consensus is Running and Valid |
| our consensus's time and freshness | **S·ctl** `GETINFO consensus/valid-after`, `consensus/fresh-until`, `consensus/valid-until`; not on the MetricsPort |

This matters before anyone enables `HSDirRefuseUnknownPrevHop`: quiet relays
showed 0.06%–7.6% unknown previous hops. Comparing the unknown share of CREATE
cells with its share of HS requests (both in **P**) separates consensus lag
from unlisted identities aimed at HSDirs; splitting descriptor-only out would
show how much "known" leans on stale descriptors.

## Q6. Are requests concentrated on a few descriptors, or spread out?

| Metric | Where |
|---|---|
| hits vs misses, and upload outcomes | **.6** `hsdir_get_total{action="success"|"not_found"}`, `hsdir_post_total{action}` |
| fetches over a descriptor's own rate | **.6** `dos_total{type="hsdir_fetch_over_rate"}` (0013, count-only; cached descriptors only) |
| distinct descriptors stored per day | **S·xi** `hidserv-dir-v3-onions-seen`: uploads, not fetches, with added noise |
| distinct keys fetched per window, hit and miss apart | **Gap** |
| top-one and top-ten target shares; repeated-target share | **Gap**. Tor already keeps a per-descriptor download count (`n_downloaded` in the HSDir cache), unexported |

The review is right that this is missing, and it separates three different
workloads: one hot descriptor fetched again and again (expensive bytes), a
sweep of many descriptors, and random keys that miss (cheap 404s). Today
`success` vs `not_found` and `hsdir_fetch_over_rate` give a first cut.

## Q7. When does each pattern start, change and end, relative to restarts and the HSDir flag?

| Metric | Where |
|---|---|
| request rates and outcomes over time | **S**, **.6**, **P** counters in a time-series database |
| the HSDir flag over time | **S** `tor_relay_flag{type="HSDir"}` (our own flags in our consensus) |
| restarts | counter resets in the time series; **S·ctl** `GETINFO uptime`; not on the MetricsPort |
| our consensus's validity | **S·ctl** `consensus/*`, as in Q5 |
| flood duration, time above thresholds, recovery | analysis of the above, not new metrics |

This is mostly available. What it needs is consistent windows and coverage
through a flag loss, its return and the next flood (process, not
instrumentation).

## Q8. Which work actually uses the CPU, and does it change across phases?

| Metric | Where |
|---|---|
| main thread vs other threads, user vs kernel | **X** `/proc/<pid>/task/<tid>/stat` (tor's pid from **S·ctl** `GETINFO process/pid`); not yet in **T** |
| function-level shares, cleanup work | **X** `perf` call graphs. One known cost: every connection free scans the whole connection array (`flood-cost-and-constrained-hosts.md` §5) |
| active connections, circuits, directory streams | **S** `tor_relay_connections{type,direction,state,family}`, `tor_relay_circuits_total`; **.6** `dir_server_conns{state}` |
| event-loop delay | **Gap** |
| worker queue depth and delay | **Gap** on the MetricsPort (tor has `onion_num_pending()` internally). **S·log** `SIGUSR1` logs the cpuworkers' average overhead |
| handshakes requested and assigned | **S·ctl** `GETINFO stats/ntor/requested`, `stats/ntor/assigned` (authenticated channels only) |

## Q9. Do requests produce useful responses, cheap errors, expensive errors or abandoned work?

| Metric | Where |
|---|---|
| outcome counts | **.6** HS actions; **P** request types (404s count as `other`) |
| responses fully handed to their stream | **.6** `dir_responses_total{type="hs_descriptor"|"other"}`; responses queued but abandoned = `hsdir_get{success}` − `dir_responses{hs_descriptor}` − `dir_server_conns{writing_hs_descriptor}` |
| active responses now, by state | **.6** `dir_server_conns{state}` |
| response bytes handed onward, by class | **Gap**. Stock counts directory bytes for its daily history (**S·xi**), not by class and not on the MetricsPort |
| bytes queued now | **Gap** |
| response latency; stream lifetime | **Gap**. **S·xi** `dirreq-v3-tunneled-dl` covers consensus downloads only (completed, timed out, running, speed) |

## Q10. Should a defense act relay-wide, per circuit, per peer or per target, and refuse a stream or close a circuit? (David)

| Metric | Where |
|---|---|
| configured scope, rate, burst, action | torrc and consensus; **S·log** the heartbeat names each defense or says `[… disabled]`. On the MetricsPort: **Gap** |
| would-act vs did-act | **.6** every rule counts while off: `hsdir_circ_reused`/`hsdir_req_reused` (one request per circuit), `hsdir_unknown_prev_hop`, `begindir_over_max`, `hsdir_fetch_over_rate`, `hsdir_fetch_pressure`/`_shed`; when enforcing, action `refused` (0011, 0014), and for 0012 cells − streams (**P**) |
| received / admitted / refused | **P** cells, streams, requests by class |
| circuit churn after a defense acts | **P** `create_cell_total{prev_hop}` |
| CPU and bandwidth | **S** `tor_relay_traffic_bytes`; **X** CPU |
| normal requests' success and latency | **X** the private client lab (stock C tor and Arti clients); a live probe is specified (`../operator/probe-helper-acceptance.md`) but not implemented |
| matched enforcement experiments | **X** `../operator/CANARY-MEASUREMENT-PLAN.md` (a plan) |

Scopes in the series today: per circuit (0011, 0012), per descriptor (0013,
count-only) and relay-wide (0014). Per peer exists nowhere; it would need Q4's
per-channel counts first. "Refuse a stream or close a circuit" is open for
0012 (TinCan's report: closing circuits cut his traffic far more than
refusing streams), and its comparison needs the received/admitted/churn
metrics above, all of which **P** provides.

## What is missing

[`metrics-proposal.md`](metrics-proposal.md) replaces the ranked list that
was here. It merges that list with:

- a second ten-question review written against live `.6` data;
- the operator critique;
- the design reviews of 0016;
- a stock profile that put most of the main thread in connection-cleanup
  scans.

It ranks each addition by data gained per line of code, and maps this
note's question numbers to its own.

The review's broader point stands: before any defense becomes a production
change, the comparison has to come from these metrics plus a known-normal
workload, in the lab first.
