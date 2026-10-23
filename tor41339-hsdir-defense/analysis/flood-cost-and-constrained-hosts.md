# What the flood costs an HSDir, and who it can cripple

> **Status (revised 2026-10-15 with operator measurements).** Two findings
> reproduce: the flooded relay's traffic increase, and its elevated
> `connection_free_` cost. Three stronger claims are **not established** by the
> measurements: "bandwidth fails first", exact descriptor sizes, and a 79–83%
> mitigation effect. §1–§2 give the measured data. §3–§6 separate measurement
> from source-based reasoning and model estimates.
>
> **Updated 2026-10-23.** Another relay's count-only counters, posted to
> tor-relays on 22 October, have since shown per-circuit reuse of onion
> service requests directly (`begindir-questions.md`). The series has been
> renumbered: the one-request-per-circuit and unknown-previous-hop rules are
> now both options of 0011, and a pressure-gated byte budget (0014) ships
> off. §4–§8 use the current numbering.

**Sources:**
- The operator's own measurements of four of their production relays:
  - retained Prometheus data;
  - three attributable CPU profile reports;
  - fresh read-only CPU, RSS and counter readings;
  - the relays' published extra-info.
- The tor 0.4.9.14 source, from the pristine release tree (tarball sha256
  `182449ac…5e4a`) and `../patches/`.

No settings were changed and no new profiles were recorded for this note. The
operator's full de-identified reconciliation (25 claims) is kept privately and
is not in this repository.

**Anonymized:**
- The relays are **F**, flooded on 2026-10-14/15, and **P1–P3**, not flooded.
- F is not necessarily the relay called `relay_A` in
  `realflood-capture-interpretation.md`.
- No nicknames, fingerprints, IPs, hostnames or ports appear here.
- Times are UTC.

## 1. Measurements

### 1.1 F across the flood (retained Prometheus data)

| Window (UTC) | BEGIN_DIR/s | Written − read, MB/s | Whole-process CPU, cores |
|---|---:|---:|---:|
| Oct 14 14:10–14:40, before onset | 3.76 | 0.21 | 0.93 |
| Oct 14 14:40–15:10, onset | 233.50 | 8.81 | 1.00 |
| Oct 15 00:40–01:10, higher-rate episode | 1,030.48 | 48.44 | 0.95 |
| Oct 15 03:40–04:10, near the profile reports | 205.71 | 7.53 | 0.84 |
| Oct 15 15:06–15:36, after the flood | 1.94 | 0.23 | 0.87 |

- Rates use the actual observed spans: about 28 minutes for tor's counters and
  29 minutes for process CPU.
- No counter decreases occurred in these windows.

### 1.2 Near the profile reports (about 210 BEGIN_DIR/s)

**F against the peers:**

| | F | P1 | P2 | P3 |
|---|---:|---:|---:|---:|
| BEGIN_DIR/s | 210 | 13 | 6 | 1.6 |
| New circuits/s | 45 | 12 | 9 | 8 |
| MB/s in / out | 13 / 21 | 18 / 18 | 26 / 26 | 24 / 25 |
| `connection_free_`, % of samples | 0.85–0.9 | 0.1 | 0.1 | 0.0 |

- In the two attributable control profiles, `connection_free_` was 0.07% and
  0.08%.
- **Library shares were unchanged by the flood.** F was kernel 44%, tor 24%,
  OpenSSL 17%, libc 11%. The peers were 47–49%, 20–21%, 15–17%, 10–11%.
- **Background, not the flood.** These were the same on all four relays:
  - `srso_*`: AMD's Speculative Return Stack Overflow mitigation.
  - `polyval*`: 0.4.9's CGO relay crypto.
  - `siphash24`: tor's per-cell hash-table lookups (`circuitlist.c:231`,
    `circuitmux.c:175`).
- **Nothing was being shed.** There were no increments in the onionskin-drop,
  tor OOM-freed or bandwidth-limit counters.

**Host and main thread:**
- The host has a 64-core server CPU, about 300 GiB of memory available and a
  10 Gbit/s interface.
- Interface transmit averaged 73% of the reported link speed.
- **During the flood, F's main thread was 77–94% of one core. So were the
  unflooded relays' main threads.** Other threads were idle.

### 1.3 After the flood (2026-10-15 ~15:13)

| Relay | RSS now | Peak RSS | BEGIN_DIR/s | New circuits/s | Read / write, MB/s |
|---|---:|---:|---:|---:|---:|
| F | 5.5 GB | 5.8 GB | 2.4 | 5.5 | 23.4 / 24.4 |
| P1 | 4.8 GB | 5.3 GB | 2.4 | 10.5 | 23.9 / 24.0 |
| P2 | 5.4 GB | 5.6 GB | 4.3 | 10.4 | 20.2 / 20.6 |
| P3 | 10.4 GB | 10.5 GB | 0.5 | 8.3 | 32.7 / 32.8 |

- F's main thread was 79% of one core over 15 s, at quiet traffic.
- Onionskins dropped, the global rate-limit counter, OOM bytes and the outbound
  stop flag were all 0.

### 1.4 Directory byte history (F's published extra-info)

The state-file history and notice log need root, so the published extra-info
stands in for them:
- **2026-10-14:** directory reads 2.47 GB and directory writes 29.3 GB, about
  **12 bytes out per byte in**.
- **The five published days:** 12–27 bytes out per byte in.
- Directory writes were a few percent of total bytes written. On F, directory
  writes never exceeded total writes.

### 1.5 What the dashboard columns are

| Column | Meaning |
|---|---|
| DROP/s | `tor_relay_drop_cell_total`: circuit-padding DROP cells, not dropped handshakes. Its help text says "received"; in 0.4.9.14 the counter is incremented on the padding write path (`rephist.c:2805-2808`). |
| Handshakes/s | ntor plus ntor_v3 onionskins processed |
| OR in | The opened-connections gauge, a poor census (see below) |
| New/s | Built from the congestion-control `circs_created` counter, which counts only congestion-control circuits (`congestion_control_common.c:410`) |

The OR in gauge read 598 during the flood. A socket count on the ORPort at the
same time showed about 2,300 direct clients and 2,500 relays. It read 33 after
the flood. It is not a count of one-hop requesters.

## 2. What the measurements do and do not show

**The traffic increase reproduces.**
- The written-minus-read surplus rose from 0.21 MB/s before onset to 8.81
  MB/s at onset and 48.44 MB/s in the higher-rate episode.
- Per added BEGIN_DIR that is about 37 KB at onset, 36 KB near the profiles,
  and 47 KB in the higher-rate episode.
- These are **aggregate estimates** from traffic asymmetry, not measured
  descriptor lengths.

**The "1:70" ratio is replaced.**
- It came from an assumed 0.5 KB request.
- F's own directory history gives about **12:1** directory bytes out per byte
  in on 2026-10-14, and 12–27:1 over five days. That mixes the flood with
  ordinary directory traffic.
- Wire-level and HTTP-level amplification factors remain unmeasured.

**Requests per circuit flags the flood, but does not prove reuse.**
- During the flood F ran about 4.7 BEGIN_DIR per new circuit (210/45). The
  unflooded relays ran 0.06–0.4, then and after.
- At onset, the excess was 5.65 BEGIN_DIR per extra congestion-control
  circuit.
- That denominator counts only congestion-control circuits, not all circuits.
  So per-circuit HS-request reuse is not established on F.
- The earlier capture's unflooded-relay value of about 5.8 came from a
  different capture, not this host.
- **Since then:** on another relay under the flood, the count-only counters
  showed 84% of onion service requests arriving on a circuit that had
  already made one, about 6.4 per such circuit, all from authenticated
  previous hops (`begindir-questions.md`). Reuse is established there; F's
  was not measured.

**The CPU cost did not show as extra CPU.**
- Whole-process CPU stayed at 0.84–1.00 cores in every window, including the
  1,030 BEGIN_DIR/s episode.
- Main threads were 77–94% of one core on flooded and unflooded relays alike.
- **Interpretation, not established:** on this host each relay's main thread
  runs near one core from ordinary forwarding. Flood work would then show up
  as work displaced inside that budget, not as added CPU. F's lower relayed
  input during the flood (13 MB/s against 18–26 MB/s on the peers) fits this,
  but so does a smaller relay.
- The one flood-specific CPU signal is `connection_free_` (0.85–0.9% vs
  0.07–0.1%). Each BEGIN_DIR creates and frees two connection objects
  (`connection_edge.c:4701-4714`). Each free runs an always-on assert that
  scans the whole connection array (`connection.c:970` → `mainloop.c:437`).
  Whether the scan's time lands under `connection_free_` depends on inlining;
  a call-graph profile would settle it.

**Memory was not the issue on F.**
- F's peak RSS was 5.8 GB. Unflooded P3's was 10.5 GB.
- No tor OOM activity was recorded.

**No resource was shown to be the binding constraint on this host.** It had
bandwidth and memory headroom, and nothing was shed.

## 3. Constrained hosts: what follows, and what is only a model

**Bandwidth (arithmetic, not demonstrated here).** The surplus is what the
flood spends:
- About 8 MB/s near the profiles is about 64 Mbit/s. That would fill a small
  uplink and use a 2 TB monthly allowance in about 2.9 days.
- At the higher-rate episode (48 MB/s), 2 TB lasts about 11.5 hours.
- Whether this binds first depends on capacity. It did not bind on this host.

**Exposure does not scale with capacity (source).**
- HSDir placement is a hash ring with no bandwidth weight
  (`hs_common.c:1281`).
- A small HSDir therefore gets the same per-descriptor demand as a large one.

**CPU (model only, unmeasured).**
- Serving runs on tor's single main thread: TLS, relay crypto, cell packing
  and the response copy.
- Estimates that put a 210 req/s flood at a few percent of a modern core and
  a large share of a Raspberry Pi core are **not measured**.
- On F, the main thread at 210 req/s looked like the unflooded relays', which
  were already near one core from ordinary forwarding. Constrained-host CPU
  needs measuring on such a host.

**RAM (source, size unmeasured).**
- Stock tor writes each descriptor response into memory whole when the
  request arrives (`dircache.c:1384`), with no admission check.
- If responses cannot drain, because of slow readers or a capped uplink,
  those buffers accumulate until circuits close or tor's OOM handler acts.
- How large that gets on a constrained host is **unmeasured**. The earlier
  model figures are withdrawn pending lab measurement.
- **`MaxMemInQueues` defaults** (`config.c:4096-4160`):
  - below 8 GiB of RAM: 0.75 × RAM;
  - at 8 GiB or more: 0.4 × RAM;
  - then clamped to between 0.25 GiB and 8 GiB on 64-bit (2 GiB on 32-bit).
- RAM is read from `/proc/meminfo`, so container limits are ignored. It
  bounds queues, buffers and caches, not the whole process's RSS.

## 4. Why stock tor has no brake on this path (source)

- **The stream limit is skipped.** BEGIN_DIR is dispatched before the
  per-circuit stream DoS check (`connection_edge.c:4333` returns before
  `:4340`). That check is also off by default and per-circuit.
- **Circuit-creation limits only cover clients.** `DoSCircuitCreation` counts
  client (unauthenticated) channels only (`dos.c:535`, `:720`).
  `HSDirRefuseUnknownPrevHop` (0011) addresses HS requests whose previous hop
  is not a known relay, for HS requests only and only when enabled; by
  default the series only counts.
- **The "directory busy" check does not apply.**
  - The HS GET handler never calls it: its callers are
    `dircache.c:962/1071/1130/1228/1324`.
  - It also returns "not low" for BEGIN_DIR (linked) connections
    (`connection.c:3428`).
- **Bandwidth limits cap egress, not demand.** `BandwidthRate` and
  `RelayBandwidthRate` limit egress but never turn a request away.

## 5. What this means for the defenses

1. **Measure before deciding.** The count-only build gives each figure
   directly; all are cumulative counters, so take deltas over a window:
   - **HS requests per circuit that made one:** ΔT/(ΔT−ΔR), from
     `hsdir_request_total` (T; in `.7`, the fetches and uploads that are
     neither `single_hop` nor `circuit_dead`) and `hsdir_req_reused` (R). This
     is not the
     same quantity as BEGIN_DIR per new circuit.
   - **Unknown-previous-hop share:** ΔU/ΔT, from `hsdir_unknown_prev_hop` (U).
   - **Circuits that carried two or more:** `hsdir_circ_reused`.

   `.6` also counts every BEGIN_DIR stream by what it asked for and its
   outcome, and `../operator/begindir-breakdown.py` prints all of it.
   `.7`'s 0016 counts every BEGIN_DIR cell by its place on its circuit,
   not only HS requests, and its 0018 counts response bytes by request
   type. Queued bytes would still need a new gauge or lab
   instrumentation.
2. **The one-request-per-circuit rule's effect depends on measured reuse.**
   - If the flood's requests really share circuits at about F's ratio,
     `HSDirOneRequestPerCircuit` (0011) would keep about 21% of the flood's
     BEGIN_DIR and cut about 79%, or about 83% if roughly 10 of F's 45
     circuits/s are ordinary.
   - That is an **upper bound conditional on reuse**, which §2 does not
     establish for F. The closed-lab reuse-5 cell measured −67% in served
     bytes (`../README.md`).
   - If requests arrive one per circuit, the rule does not reduce bytes
     served, and each request then also costs a circuit handshake. Those
     handshakes share a queue with legitimate circuits (`onion_queue.c:49`,
     `MaxOnionQueueDelay` 1750 ms).
3. **The two rules of 0011 cover different senders.** The one-request rule
   does not address one-hop requests from relay identities we don't know;
   `HSDirRefuseUnknownPrevHop` does. Each is enabled separately.
4. **A byte budget exists as an option; enabling it is not recommended by
   default.** 0014 sheds descriptor fetches only after a second goes over a
   relay-wide budget, and ships off, counting what it would shed. The private
   client lab measured stock C tor and Arti clients fetching while HSDirs shed
   (`../engineering/client-lab/`). Enabling it on production relays is a
   separate decision, after the measurements in §7 and these tests:
   - legitimate-client success, given that each descriptor is stored on 8
     HSDirs and a client picks among 6 (`hs_common.h:112,114,116`);
   - starvation: whether descriptors within their own rate still get served
     under sustained pressure, and with slow readers;
   - retries: a shed fetch is retried at another HSDir, which moves load
     rather than removing it;
   - behaviour if request patterns change;
   - the refusal itself. 0014 closes the circuit rather than answering 503,
     because a 503 marks the HSDir overloaded for an hour in
     `router_pick_directory_server()` (`dirclient.c:2137`,
     `routerlist.h:49`, `node_select.c:366`).
5. **Upstream candidate: the scan in every connection free.**
   `connection_free_()` always asserts `!connection_in_array(conn)`, a linear
   scan of the whole connection array (`connection.c:970`, `mainloop.c:437`),
   and each BEGIN_DIR stream frees two connections. With N open connections
   that is about 2N pointer comparisons per stream, so its cost grows with
   both the request rate and the relay's size (arithmetic, unmeasured). It
   also matters for 0012: it refuses a BEGIN_DIR after allocating its edge
   connection and frees it through the same path, so enforcing it under a
   flood would pay one full scan per refused cell; checking before the
   allocation avoids that. A check at the connection's own `conn_array_index`
   would be O(1), but `connection_remove()` does not reset that index today.
   A call-graph profile should show how much of `connection_free_`'s share
   is the scan.

## 6. Advice for constrained HSDirs on stock tor (source-based)

- **Set `MaxMemInQueues` from the memory tor can really use**, especially in
  containers, where the default ignores the container's limit. It bounds
  queues, buffers and caches, not total RSS, so leave room for the rest.
- **Also set `MaxHSDirCacheBytes`.** Its default is `MaxMemInQueues/5`
  (`hs_cache.c:1263`), so lowering one shrinks the descriptor cache too.
- **`RelayBandwidthRate` protects a bandwidth bill, not the relay.** Below
  51,200 B/s it also turns off directory service (`router.c:1269`).
- **`AccountingMax` caps transfer; it does not stop the flood.** It is the
  right tool for a hard transfer allowance, but with default rates tor then
  stops advertising tunnelled directory service (`router.c:1325-1328`),
  losing HSDir, Guard and V2Dir, and it can hibernate the relay.
- **`DirCache 0` + reload stops serving directory requests** without a
  restart, at the cost of Guard and V2Dir as well as HSDir.

## 7. What to collect next

**Stock tor, during a flood.** Share counts and aggregates only:
- main-thread and whole-process CPU, together with forwarded throughput, to
  test the displacement interpretation;
- a call-graph profile, shared as text: `perf report --stdio`, not
  `perf.data`, whose header records the hostname;
- RSS and the OOM, onionskin-drop and rate-limit counters;
- directory and total byte history (needs root).
  - These are 24-hour buckets (`bw_array_st.h:15-23`).
  - Directory and total bytes are counted at different layers
    (`connection.c:3652` onward), so their difference is not queue occupancy
    or response size.

**Count-only build:** the counters in §5.1.

**Lab, before any enforcement decision:** the tests in §5.4.

## 8. Open items

- On F: per-circuit HS-request reuse and the unknown-previous-hop share are
  unmeasured (another relay's are in `begindir-questions.md`). Served
  descriptor bytes and queued bytes are unmeasured everywhere.
- Constrained-host CPU and memory behaviour are unmeasured.
- The operator could not verify the original perf recording metadata or the
  fourth comparison profile.
- `claims-ledger.md` P1/P2 still describe an earlier design: on by default, a
  1-bit flag, and an edit inside `connection_dir_is_anonymous`. The current
  series is count-only by default, uses a 2-bit counter and a separate guard,
  and leaves that function untouched.
