# Client-reachability lab for ticket 41339 descriptor-fetch shedding

> This lab was written for, and run on, the `+tor41339.5` and `.6`
> packages, and this document uses their names. It also runs on the `.7`
> packages: they accept `.6`'s option name `HSDirDescriptorFetchLimit`, with
> a deprecation warning, for what `.7` calls `HSDirFetchShedding`, and the
> scripts read `.7`'s `tor_relay_hsdir_fetch_total` as `.6`'s
> `tor_relay_hsdir_get_total`. A `.7` build without the Debian packaging's
> alias needs `HSDirFetchShedding` in `phases.json`, `clientlab.py` and
> `arti/arti_probe.py`.

## Purpose

This lab measures what real onion-service clients experience when HSDirs
refuse ("shed") onion-service descriptor fetches. Two unmodified client
implementations are measured side by side, under the same conditions:

- a stock **C tor** client (the packaged tor, as a chutney client node), and
- an **Arti** client (a release build, configured for the private network).

Each phase sets the HSDirs' shedding options, runs a load, and has both
clients fetch a page from a loaded onion service **D** and from a control
onion service **E** at the same time. The lab records whether each request
succeeded, how long it took, and every descriptor fetch the client made for
it: which HSDir it asked, in what order, and how that fetch ended. A refused
fetch, and the client's failover to another HSDir, are therefore visible per
request, for both clients.

The load comes from a "load client": an ordinary, test-only tor client in
the lab that issues many well-formed descriptor fetches, so that an HSDir is
pushed over its fetch limits and its shedding path runs. It is a measurement
tool for this defensive change only.

## Isolation guarantees

- The whole lab runs in **one Docker container started with
  `--network none`**. The container has a loopback interface and nothing
  else; the entrypoint checks this and stops with `RESULT: FAIL` if any
  other interface exists.
- Every process (directory authorities, relays, onion services, the C tor
  clients, the load client, the Arti client, the HTTP server) binds
  `127.0.0.1` only. The network has its own authorities and consensus, so no
  process can learn of, or reach, any relay outside the container.
- Every input (chutney, the simulator helpers, the load-client binary, the
  Arti binary, this directory) is mounted **read-only**. Only the output
  directory is writable.
- No tor or Arti process runs on the host. The host only runs `docker`.

## Files

| file | role |
|------|------|
| `run-client-lab.sh` | host runner: checks inputs, starts the container, fails closed |
| `in-lab.sh` | container entrypoint: interface check, chutney net, HTTP server, load client, harness, diagnostics |
| `clientlab.py` | the harness: phases, load, both client probes, metrics, JSON + tables, PASS/FAIL |
| `phases.json` | the data-driven phase list (edit freely; see its `_comment`) |
| `clientlab41339` | chutney network: 4 authorities and 6 relays (all HSDirs, each with a MetricsPort), 6 C tor client nodes, 6 onion services |
| `httpd.py` | tiny loopback HTTP server that every onion forwards to (port 5858 to `127.0.0.1:4747`) |
| `arti/mkconf.py` | writes an `arti.toml` for the private network from the chutney node dirs |
| `arti/` (other files) | standalone Arti experiments (isolation, retry behaviour) and notes on how Arti fetches descriptors; see `arti/NOTES.md` |

## Inputs

| variable | meaning | default |
|----------|---------|---------|
| `IMAGE` | lab image with the tor package under test, chutney's Python deps and curl (built from `../deb/resolute/controls/Dockerfile`) | `lab24v6` |
| `CHUTNEY` | chutney checkout (mounted read-only) | required |
| `LOADCLIENT` | the test-only load-client tor binary | required |
| `ARTI` | Arti binary built with the onion-service client; `none` runs the C tor client only | required |
| `OUT` | results directory | required |
| `PHASES` | comma list of set names (`dry`, `full`) and/or phase names | `dry` |
| `PHASE_S` | seconds of load per phase; client requests are spread over it | `60` |
| `BUDGET` | `HSDirFetchBudget` value the `BUDGET` token expands to (ignored by builds without the option) | `16384 bytes` |
| `TOR_BIN` | optional tor binary bound over the image's `/usr/bin/tor` | unset |
| `SIM` | the simulator helper scripts (`sim.py`, `ctl_lib.py`, `loadclient_up.sh`) | `../../simulator/scripts` |
| `SANDBOX` | `Sandbox` for the chutney nodes | `1` |
| `DOCKER_CPUS` | optional `--cpus` limit for the container | unset |

The Arti binary must be built with the `onion-service-client` feature (a
default feature). It is linked against the system OpenSSL and SQLite, so a
binary built on Ubuntu 24.04 runs in both the 24.04 and 26.04 lab images.

## How to run

```
CHUTNEY=<chutney checkout> \
LOADCLIENT=<test-only load-client tor> \
ARTI=<arti binary> \
OUT=<results dir> \
IMAGE=lab24v6 PHASES=full PHASE_S=60 BUDGET="56 KBytes" \
./run-client-lab.sh
```

The dry run (`PHASES=dry`) takes about 10 minutes: about 3 minutes to start
the network, four phases of about 65 seconds each, and up to 3 minutes of
waiting for time-period boundaries to pass (see below). The `full` set
(seven phases) takes about 12 to 15 minutes. `PHASES=dry` is for a `.5`
image, whose only refusal is the old per-descriptor limit.

The run **fails closed**. The runner exits nonzero and prints
`RESULT: FAIL: <reason>` if an input is missing, the container has a
non-loopback interface, any C tor client node, the load client or Arti does
not bootstrap, the onion descriptors never reach an HSDir, Arti exits, a
phase raises an error, or **any** request in the baseline phase B0 fails.
B0 always runs first, whatever `PHASES` says. Only a run where all of this
holds ends with `RESULT: PASS` and exit status 0.

## How each client is measured

Both clients fetch `http://<onion>:5858/` with curl through their SOCKS
port, with a unique SOCKS username per request.

- **C tor.** Requests rotate over the six client nodes. Before each request
  the harness sends `SIGNAL NEWNYM`, which clears that client's descriptor
  cache and its memory of which HSDirs it already asked (tor allows one
  NEWNYM per 10 seconds per client, hence six nodes). The HSDir fetches come
  from `HS_DESC` control events. A fetch the HSDir refuses by closing the
  circuit produces `REQUESTED` and no `RECEIVED` or `FAILED` event; the
  harness records it as `no_reply`. The client then asks another HSDir by
  itself.
- **Arti.** One Arti process (`arti proxy`), configured by `arti/mkconf.py`
  from the running network. Arti keeps descriptors per SOCKS isolation, and
  a new username is a new isolation, so every request fetches the descriptor
  again (verified against the relays' GET counters, see `arti/NOTES.md`).
  The HSDir fetches come from Arti's log (`tor_hsclient` at trace level):
  each `hsdir for ..., trying <ed>/$<rsa>` line is an attempt, and a
  `failed hsdir desc fetch ... error=...` line ends it (`closed` when the
  HSDir closed the circuit, `timeout`, `not_found`, `other`). Arti asks up
  to six HSDirs one after another, with no delay, then gives up.
- HSDir identities from both clients are mapped to chutney node names
  (`000a`..`009r`).
- The two clients, and D and E, are probed **concurrently**: four request
  series spread evenly over each phase and offset from one another, so they
  sample the same load without piling up.

Two lab settings matter for Arti and are recorded in the result:
`hsdir_interval` (the network's 8-minute time period, which Arti cannot
infer from a test network) and `cbtmintimeout = 2000` (a 2-second floor on
learned circuit timeouts: on loopback Arti otherwise learns timeouts of tens
of milliseconds and reports a busy HSDir as timed out, mixing "slow" with
"shed").

## Time periods

The network's onion-service time period is 8 minutes (24 voting intervals).
At each boundary the set of HSDirs holding each descriptor changes, and C tor
follows the consensus time, up to one voting interval late. Before each phase
the harness waits, if needed, so that the phase does not straddle a boundary
(`period_guard_wait_s` in the result), finds the HSDirs holding D and E again,
and checks after the phase that D's holders did not change
(`holders_changed`).

## Reading the output

`$OUT/client-lab-transcript.txt` is the console log. It ends with two
tables and the result line.

Per phase, client and onion:

| column | meaning |
|--------|---------|
| `ok/req` | successful requests / requests |
| `p50_s`, `p90_s` | latency of successful requests (curl total time) |
| `fail_p50` | median time until a failed request failed |
| `hsdir/ok` | mean descriptor fetch attempts per successful request (1 = first HSDir answered) |
| `hsdir/fail` | mean descriptor fetch attempts per failed request |
| `failover_ok` | successful requests that needed more than one HSDir |
| `hit_limited(ok)` | requests that asked at least one HSDir with `HSDirDescriptorFetchLimit=1` (and how many of those succeeded). The limit applies per descriptor, so for E, which is not loaded, it only says which HSDirs E's requests used. |
| `fail_after_desc` | failed requests for which some HSDir did serve the descriptor: the failure came later (introduction or rendezvous), not from the HSDirs |

Per phase, relays: `load/s` is the descriptor fetches the loaded HSDirs
answered or refused per second; `refused`, `over_rate`, `pressure` and
`shed` are the summed deltas of `tor_relay_hsdir_get_total{action="refused"}`
and `tor_relay_dos_total{type="hsdir_fetch_over_rate"|"hsdir_fetch_pressure"|"hsdir_fetch_shed"}`;
`begin_dir` is `tor_relay_streams_total{type="BEGIN_DIR"}`; `TP` is the time
period number.

A request series is spread over `[4 s, PHASE_S - 4 s]` of the phase. If a
slow request (curl gives up after 20 s) puts a series behind schedule, its
next requests run back to back until it catches up, and the load keeps
running until every series has ended, so no request runs without the
phase's load. Requests that would start more than 25 s after the planned
end are recorded as skipped (`skipped_window_over`).

`$OUT/client-lab-result.json` has everything, per phase: the relay
configuration applied, D's and E's holders, the load targets and achieved
rates, every relay's metric deltas, and for every request its client node,
SOCKS username, curl status, latency and the list of HSDir fetch attempts
with outcomes. A failed request also keeps its event trail: for C tor the
`HS_DESC`, `CIRC` and `STREAM` control events for that onion, for Arti its
`hs conn to ...` log lines (introduction and rendezvous steps).
`$OUT/logs/` keeps the Arti config and log and every node's notice log.

The transcript also prints the number of "Caught a bad syscall" lines across
all node logs, the HSDirs' refusal log lines, and each relay's Sandbox and
seccomp state; relay pids are checked unchanged across each phase.

## What the `.6` runs showed

Three runs on the packaged `+tor41339.6` builds (`results/`): the full set
on `lab24v6` (Ubuntu 24.04) and on `lab26v6` (26.04, with C3), and B0 + C3
again on `lab24v6`. Arti 2.7.0, 60 s phases, `BUDGET="56 KBytes"` (about
four of D's 14 KB descriptors a second), D held by 8 HSDirs. Totals:

| phase | HSDirs shedding | C tor D | Arti D | C tor E | Arti E | HSDir attempts per D success |
|-------|-----------------|---------|--------|---------|--------|------------------------------|
| B0 | none, no load | 18/18 | 30/30 | 18/18 | 30/30 | 1.0 |
| C0 | none (observe) | 16/16 | 24/24 | 16/16 | 24/24 | 1.0 |
| C1 | all | 20/20 | 39/40 | 20/20 | 40/40 | 1.7–2.3 |
| C3 | all, load client at its maximum | 19/20 | 37/40 | 20/20 | 40/40 | 2.2–2.9 |
| C2 | the one clients ask first | 32/32 | 48/48 | 12/12 | 48/48 | 1.0–1.06 |
| S0 | none (observe), spread load | 16/16 | 24/24 | 16/16 | 24/24 | 1.0 |
| S1 | all, spread load | 20/20 | 40/40 | 20/20 | 40/40 | 1.0–1.15 |

- **Below and at the budget nothing is refused.** In the observe phases (C0,
  S0) the HSDirs counted 2,870–2,920 (C0) and 971–974 (S0) fetches they
  would have shed, and refused none; both clients reached D and E on every
  request from the first HSDir asked.
- **Shedding everywhere (C1, C3).** Each of D's HSDirs was asked for about
  7 (C1) to 10 (C3) of D's descriptors a second, 1.7 to 2.5 times its
  budget, so D's fetches beyond its own rate went to the lottery, with odds
  of about one in two (C1) to one in three (C3). A client whose
  fetch was shed asked the next HSDir at once; D was reached on 115 of 120
  requests, at 1.7 to 2.9 HSDir attempts per success, with the median
  latency going from 0.23–0.30 s (B0) to 0.37–0.63 s (p90 up to 3 s for
  C tor). Every one of the 5 failed requests had been shed at all 6 HSDirs
  in its fetch set; Arti failed those at once (0.3–0.5 s), C tor after
  about 1.7 s. E, the unloaded control, was mostly within its own rate,
  so answered first, and was reached on every request; its few shed fetches
  were probably two clients fetching E at one HSDir within a second, over
  the lab's `Rate=1` (not verified).
- **Shedding at one HSDir (C2)** costs clients nothing: they fail over to
  the next HSDir.
- **Spread load (S1):** several onions, each below its own rate, put one
  HSDir over its budget; that HSDir shed by lottery, and both clients
  reached D and E on every request, moving on from that HSDir when shed.
- **Relays:** `refused` equalled `hsdir_fetch_shed` in every enforcing phase
  (for example 1,487 and 1,395 in C1, 2,900 and 2,768 in C3); no bad
  syscalls; Sandbox 1 and the pid unchanged on every relay. Shedding closes
  the load client's circuits, so the load the HSDirs see drops (C1: 55
  fetches/s against 79 in C0).
- **What the lab does not show:** it has no capacity limit, so it measures
  clients' experience of shedding, not the relay protection that justifies
  it; and its load is a single client, so C3 is the strongest shedding it
  produced (about 80 fetches/s). Real HSDirs would see the same per-attempt
  odds at a budget near their capacity only under a much larger flood.

## What the `.5` dry runs showed

Three dry runs on the `lab24v5` image (packaged `+tor41339.5` tor, Arti
2.7.0, 60 s phases; D's descriptor is 14 KB and is held by 8 HSDirs, 6 of
which are in each client's fetch set). Totals over the three runs:

| phase | client | D ok/req | D p50 / p90 (s) | HSDirs per success | E ok/req |
|-------|--------|----------|-----------------|--------------------|----------|
| B0 | C tor | 18/18 | 0.26 / 0.33 | 1.00 | 18/18 |
| B0 | Arti | 30/30 | 0.25 / 0.41 | 1.00 | 30/30 |
| C0 | C tor | 24/24 | 0.42 / 1.33 | 1.00 | 24/24 |
| C0 | Arti | 36/36 | 0.43 / 0.60 | 1.00 | 36/36 |
| P5one | C tor | 41/43 | 0.46 / 0.71 | 1.07 | 18/18 |
| P5one | Arti | 72/72 | 0.50 / 0.69 | 1.10 | 72/72 |
| P5all | C tor | 20/30 | 0.54 / 0.80 | 2.55 | 18/18 |
| P5all | Arti | 28/48 | 0.49 / 0.76 | 2.68 | 48/48 |

- **B0, C0:** both clients reached D and E on every request, from the
  first HSDir asked, also under a steady load of about 80 fetches per
  second at D's HSDirs with enforcement off.
- **P5one** (one HSDir in the fetch set refusing D): a request that asked
  the refusing HSDir and was refused moved on to another HSDir at once and
  succeeded (C tor 3 times, Arti 7 times), at about the usual latency. The
  two failed C tor requests had received the descriptor at the first
  attempt and then stalled in introduction or rendezvous until curl gave up
  after 20 s (`fail_after_desc`); they are not HSDir failures. The same
  stall happened once in a loaded `full`-set phase on `.5`, never for Arti.
- **P5all** (every HSDir holding D refusing nearly every fetch of D): both
  clients still got through on about 60% of requests, because a fetch that
  finds a token in its HSDir's bucket is answered, at the cost of 2.5 to
  2.7 HSDir attempts per success. Every failed request (C tor 10, Arti 20)
  had asked all 6 HSDirs of its fetch set, once each, one after another,
  with no backoff (median gap 59 ms for Arti and 72 ms for C tor; the
  longest 0.24 s for Arti, 1.07 s for C tor). Arti then failed the request at once
  (SOCKS reply 1, general failure; median 0.46 s after the request); C tor
  about 1.3 s after its last refused fetch (SOCKS reply 4, host
  unreachable; median 1.72 s). Neither client reports a refused fetch as
  such: C tor emits `HS_DESC REQUESTED` and no `FAILED` event, Arti logs
  `Stream not connected`.
- E, the control, was reached on every request. Once an E fetch was
  refused at a limited HSDir (the stand-in's `Rate=1 Burst=1` applies to
  E's own bucket too, and two clients fetched E there within a second); Arti
  moved on to the next HSDir.
- Relay side: no bad syscalls, every relay kept Sandbox 1 and its pid.
  With refusals on, the load client's requests that were already queued on
  a circuit the HSDir had just closed were answered `503` and counted as
  `hsdir_get_total{action="single_hop"}` (the HSDir treats a directory
  request on a circuit marked for close as not anonymous): 850 to 1000 of
  them next to 1900 to 2000 refusals per P5all phase. Real clients send one
  fetch per circuit, so this only appears with circuit-reusing load.

## Phases

| phase | set | load | HSDir configuration | shows |
|-------|-----|------|---------------------|-------|
| B0 | both | none | defaults | baseline: both clients reach D and E (gate for the whole run) |
| C0 | both | steady, D at every HSDir holding it | `FetchLimit=0`, per-descriptor `Rate=1 Burst=2`, small budget on `.6` | enforcement off; on `.6` the pressure / shed counters move (observe mode) and nothing is refused |
| P5all | dry | as C0 | `.5` per-descriptor refusal (`FetchLimit=1 Rate=1 Burst=1`) on every HSDir holding D | what each client experiences when nearly every fetch of D is refused |
| P5one | dry | as C0 | the same, on one HSDir clients ask for D | failover from a refusing HSDir |
| C1 | full | as C0 | `.6` shedding (`FetchLimit=1`, small budget, `Rate=1 Burst=2`) everywhere | relay-wide budget under a flood of one descriptor: D's excess fetches go to the lottery, E's fetches are within their rate and answered first |
| C3 | full | as C0, with the load client at its maximum rate | as C1 | lower lottery odds: the limit of what client retries recover |
| C2 | full | as C0 | `.6` shedding on one HSDir clients ask for D | failover from a shedding HSDir |
| S0 | full | steady, several onions at one common HSDir, each at 4/s (below its rate) | observe mode, default per-descriptor rate | the relay over budget with no descriptor over its rate |
| S1 | full | as S0 | `.6` shedding everywhere | the lottery among fetches within their rate; clients fail over to other HSDirs |

On the `.5` build `HSDirFetchBudget` does not exist and is dropped, and
`HSDirDescriptorFetchLimit=1` refuses every fetch over the per-descriptor
bucket. That refusal closes the circuit with no reply, the same mechanism
the `.6` build uses when it sheds, which makes P5all/P5one a stand-in for
client behaviour under shedding.

A **steady** load sends one fetch to every target HSDir every `1/rate`
seconds, so every HSDir is loaded in every second. That matters on `.6`,
which sheds only in a second that follows an over-budget second: a bursty
load (a few fetches, then a pause of two seconds) triggers shedding in the
seconds it is idle.

## Choosing the budget and the load (.6)

The harness measures the size `S` of D's descriptor (`desc_bytes_D` in the
result; the length the budget counts). For the `full` phases:

- `BUDGET` about `4 * S` bytes (`S` was 14,109 bytes in the dry run, so
  `BUDGET="56 KBytes"`). With `Rate=1 Burst=2`, D's flood
  contributes about one fetch per second within its rate; fetches within
  their rate are answered first up to half the budget (`2 * S`), which
  leaves room for E's fetches.
- C phases: steady load of 10 fetches per second at each HSDir holding D
  (`rate_per_hsdir`), about `10 * S` per second, 2.5 times the budget, so
  every second sheds and D's excess fetches are answered with odds of about
  `(4S - S) / (10S - S)`, one in three. The dry run reached 79 fetches per
  second at D's 8 HSDirs with enforcement off (39 per second while every
  HSDir refused, because each refusal costs the load client a circuit).
- S phases: each spread onion at 4 per second at one common HSDir (below
  the default rate of 5), so four or five onions give `16 * S` to `20 * S`
  per second, well over the budget, with no descriptor over its own rate.

Refusals cost the load client circuits, so the HSDirs see less load in
C1/C2/S1 than in C0/S0 (as in P5all). If `shed` in C1 stays well under half
of D's fetches at its HSDirs, raise `rate_per_hsdir` (for example to 15)
rather than lowering `BUDGET`: below about `4 * S`, D's own fetches within
its rate use up the half of the budget reserved for such fetches, and E's
fetches fall into the lottery too.

Check after the run that `load/s` matches the intended rate, that
`pressure` and `shed` moved on the loaded HSDirs in C0/S0 with nothing
refused, and that `refused` equals `shed` in C1/C2/S1.
