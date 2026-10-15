# What the flood costs an HSDir, and who it can cripple

**Source:** an operator's dashboard snapshot of four of their own production
relays (2026-10-15). One relay was under the BEGIN_DIR / HS-descriptor flood
(tor#41339); the other three were not. The snapshot has per-relay rates and a
CPU profile (sample shares by library and top functions). The rates and profile
are read here against the tor 0.4.9.14 source.

**Anonymized:**
- The relays are **F** (flooded) and **P1–P3** (peers).
- F is not necessarily the relay called `relay_A` in
  `realflood-capture-interpretation.md`.
- No nicknames, fingerprints, IPs or hostnames appear here.

**How sure this is:**
- Code facts come from the pristine release tree (tarball sha256
  `182449ac…5e4a`). Patch behaviour comes from `../patches/`.
- Numbers derived from the snapshot are inferences, with their assumptions
  stated.
- CPU-per-byte figures are **estimates**, not measurements.
- Method: five source-grounded investigations, two adversarial verifiers each,
  a completeness critic, then a final three-reviewer check of this note.
  Corrected figures are used throughout.

## 1. The snapshot

| Relay | BEGIN_DIR/s | Kernel | Tor | OpenSSL | libc | Circuits open | New/s | Closed/s | OR out | OR in | Sockets | MB/s in | MB/s out | Handshakes/s | DESTROY/s | DROP/s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| F (flooded) | 210 | 44% | 24% | 17% | 11% | 43,076 | 45 | 46 | 6,435 | 598 | 11,053 | 13 | 21 | 55 | 91 | 13 |
| P1 | 13 | 49% | 21% | 15% | 10% | 30,490 | 12 | 10 | 5,046 | 17 | 10,545 | 18 | 18 | 43 | 52 | 11 |
| P2 | 6 | 47% | 20% | 17% | 11% | 35,648 | 9 | 11 | 6,341 | 69 | 11,072 | 26 | 26 | 31 | 54 | 4 |
| P3 | 1.6 | 48% | 21% | 17% | 11% | 33,195 | 8 | 6 | 6,551 | 122 | 11,115 | 24 | 25 | 25 | 54 | 8 |

Top functions, % of samples (F / P1 / P2 / P3):
- **Kernel:**
  - `srso_return_thunk` 1.2/2.0/1.8/1.5, `srso_safe_ret` 1.4/1.5/1.4/1.7
  - `entry_SYSCALL_64` 1.0/1.1/1.3/1.3, `rep_movs_alternative` 1.0/0.5/1.4/1.2
  - `_copy_to_iter` 1.1/0.6/0.7/1.0, `memset_orig` 0.7/0.8/1.0/0.8
  - `__tcp_transmit_skb` 0.3/0.5/0.7/0.7, `do_syscall_64` 0.5/0.6/0.5/0.5
  - `tcp_recvmsg_locked` 0.4/0.5/0.5/0.5
- **Tor:**
  - `siphash24` 2.3/2.2/2.6/2.7, `tor_memcmp` 1.3/1.5/1.3/1.1
  - `cell_pack` 0.8/1.1/0.5/0.9, `polyvalx_add_zpad` 0.5/0.7/0.5/0.8
  - **`connection_free_` 0.9/0.1/0.1/0.0**, `polyval_add_block` 0.5/0.2/0.3/0.6
  - `command_process_cell` 0.3/0.4/0.5/0.4
  - `channelpadding_decide_to_pad_channel` 0.5/0.4/0.3/0.3

The operator also reported the flood as "about 1:70, request size to response
size". The dashboard columns are not defined (§7), so read them with care:
- **New/s and Closed/s:** §2's requests-per-circuit figure rests on these.
  - Stock 0.4.9.14 has no all-circuits creation counter.
  - The closest is `tor_relay_congestion_control_total{action="circs_created"}`,
    which counts only congestion-control circuits.
- **OR in/out:** if this is tor's `tor_relay_connections` gauge, the
  "received" side drifts low (connection.c:2105-2111, rephist.c:1719-1738). So
  F's 598 is not evidence of direct one-hop requesters.
- **Handshakes/s:** unknown.
- **DROP/s:** if this is `tor_relay_drop_cell_total`, it counts
  circuit-padding DROP cells this relay sends, not dropped handshakes.

## 2. What the numbers show

**About 5.75 requests per flood circuit.**
- F's excess over the peer mean is +203 BEGIN_DIR/s against +35.3 new
  circuits/s.
- Using each peer alone as the baseline gives 5.6–6.0 (P1 5.97, P2 5.67, P3
  5.63), and about 5.5–6.2 allowing for integer rounding.
- The extra closes (+37/s) and DESTROYs (+37.7/s) match the extra new
  circuits, so the flood circuits are in steady state.
- The 2026-10-13 capture gave 5.69 raw for its flooded relay. That is 5.89 as
  excess over the unflooded relays' mean (F's basis), and 6.02 as excess over
  that relay's own pre-flood baseline.
- **Caveat:** a relay that stayed near its own baseline in that capture showed
  a similar ratio. `relay_B` read 5.85 at baseline and 5.54 in the flood
  window, and is "not proven attacked" in
  `realflood-capture-interpretation.md`. So this ratio alone does not prove
  circuit reuse.

**About 40 KB on the wire per flood request.**
- F sends (21 − 13) − 0.33 ≈ 7.7 MB/s more than it receives. The peers are
  symmetric, so this surplus is bytes F generates itself.
- That works out to 37.7 KB net per flood request, about 40 KB sent once the
  ~2.5 KB of inbound per request is added back.
- Allowing ±0.5 on all six MB/s cells, it is about 30–50 KB sent.
- In descriptor bytes that is about 35–38 KB at the point estimate (roughly
  28–47 KB across the rounding range): large descriptors.
- For scale, a stock-built descriptor is about 14 / 28 / 41 KB at 1 / 2 / 3
  padding blocks. The HSDir cap is 49,999 B, about 103 cells.
- This is inferred from total traffic, not measured (§7 lists the stock
  counters that would measure it).

**The amplification depends on the layer.** A request is about 96 HTTP bytes
in at least two cells (BEGIN_DIR + DATA).

| Layer | Ratio |
|---|---|
| HTTP | about 150× (1-block, ~14 KB descriptor) to 520× (cap); the field's ~170:1 (`claims-ledger.md` D3/D4) sits at the low end |
| Relay cells, reused circuit | 15.5–51.5×; 10.6–19.6× counting SENDMEs |
| Relay cells, fresh circuit per fetch | 8–26×; 8–14.9× with SENDMEs |

- These counts use v0 498-byte DATA payloads. With 0.4.9's CGO cells (488 B)
  each fetch takes 1–2 more cells.
- The operator's 1:70 fits "one 514-byte request cell to about 70–80 response
  cells". Two request cells cannot reach 1:70.
- A fetch of up to about 101 DATA cells fits in the initial congestion window
  (124 cells), so a requester never has to acknowledge to receive it.
- This is not reflection: responses travel back along the requester's own
  circuit, so its middle and guard relays carry them too.

**The CPU mix on F is close to the peers'.** Tor is +3.3 points, kernel −4.0,
OpenSSL +0.7.
- The one flood-specific function is `connection_free_`: 0.9% versus ≤0.1%.
- Each BEGIN_DIR creates and frees two connection objects, a linked exit edge
  and a dir connection (`connection_edge.c:4701-4714`).
- Every free runs an always-on assert that scans the whole connection array
  (`connection.c:970` → `mainloop.c:437`, a linear scan), about 11k entries
  here.
- Caveat: that scan's samples land under `connection_free_` only with
  inlining or inclusive accounting. Check with a call-graph profile before
  relying on it.

**Background, not the flood:**
- `srso_*` is AMD's Speculative Return Stack Overflow mitigation, on all four
  relays.
- `polyval*` is 0.4.9's CGO relay crypto, driven by forwarded traffic.
- `siphash24` is the hash behind tor's per-cell hash-table lookups (the
  circuit-ID map, `circuitlist.c:231`, and the circuitmux map,
  `circuitmux.c:175`).

**All serving work runs on tor's main thread:** TLS, relay crypto, cell
packing and the response copy. Worker threads do only onionskins, consensus
diffs and PoW. A share-only profile cannot tell a main thread at 20% from one
at 100%.

## 3. Would it cripple a compute- or RAM-constrained host?

### Bandwidth and metered hosts: yes, and first

Cost scales with bytes, and nothing lets a small HSDir serve less:
- HSDir placement is a hash ring with no bandwidth weight
  (`hs_common.c:1281`).
- An HSDir stores any validly signed descriptor without checking that it is
  responsible for it (`dircache.c:1608-1621`). A requester can therefore post
  a large descriptor to a chosen HSDir and fetch it there.

At F's rate (about 210 req/s at 30–50 KB each, about 40 KB as the point
estimate):
- It fills 50–84% of a 100 Mbit uplink (about 67% at 40 KB). It saturates
  20–50 Mbit home uplinks.
- It burns a 2 TB/month cap in 2.2–3.7 days on flood bytes alone (about 2.8
  days at 40 KB).
- At the 2026-10-13 capture's 950 req/s, the same cap goes in about 12–19 h. That
  capture's flooded relay's measured 45.3 MB/s output gives 12.3 h.

### CPU: estimates by host class

The per-request main-thread cost is modelled as a fixed part plus a per-byte
part at 40 KB per request. These are **assumptions**:

| Host | Per-byte cost | Fixed cost | Flood alone at 210 req/s | Max served rate, free main thread |
|---|---|---|---|---|
| Modern x86 core | 7–20 ns/B | 20–100 µs | 6–19% of a core | about 1,100–3,300 req/s |
| Cloud vCPU (assumed 1.5× x86) | — | — | 9–28% | about 740–2,200 req/s |
| Raspberry Pi 4 (no AES instructions) | 40–100 ns/B | 100–400 µs | 36–92% | about 230–590 req/s |
| Raspberry Pi 5 (assumed 0.67–1.8 ms per request) | — | — | 14–38% | about 560–1,500 req/s |

- **Field rates against these estimates:**
  - Reports of about 1,100–2,300 req/s at 70–115 MB/s (`claims-ledger.md`
    D7) fall inside the x86 range.
  - Reports above about 3,300 req/s (about 4,100/s; above 10,000/s) would
    exceed one main thread even on large hosts.
- A refused request costs only the fixed part, about 4–40× cheaper than
  serving one.

### RAM: only once bytes cannot drain

- **When requesters read normally, at F's rate:** tens of MB. That is 10k
  extra circuits × 2–5 KB of state, plus a few MB to about 30 MB of responses
  in flight.
- **Stock tor has no admission control.** It writes every descriptor into
  memory, whole, as soon as the request arrives (`dircache.c:1384`).
- **When bytes cannot leave,** because of a capped uplink, `RelayBandwidthRate`
  or requesters that stop reading, memory grows:
  - Stock can pin every response on a stalled circuit: about 10k circuits ×
    5.75 × 38–40 KB ≈ 2.2–2.3 GB at F's shape. That is about 1.6 GB after
    each circuit's 124-cell initial window drains.
  - With one response per circuit, as under enforced 0002 (§5), it is about
    0.4 GB.
  - Either is fatal on a 1 GB host.
  - With SENDME-withholding there is no relay-side timer. Bytes stay pinned
    until the circuit closes or the OOM handler runs.
- **`MaxMemInQueues` will not catch it in time on small hosts.**
  - It defaults to 0.75 × RAM below 8 GB (`config.c:4143`), with RAM read
    from `/proc/meminfo`, so container limits are ignored.
  - It counts only queues, buffers and caches, not circuit, connection or TLS
    state.
  - On a 1–2 GB host the kernel OOM killer probably strikes first.
- **Is F stalled today?** F's numbers alone do not settle it.
  - From F's byte budget, 0.30–0.36 of flood circuits could be
    non-acknowledging at the point estimate, and roughly 0.1–0.5 across the
    rounding range.
  - The same inference on the 2026-10-13 capture bounds that capture's
    flooded relay (a different relay and day) at ≤21%.
  - Elsewhere the stall-or-discard mode does occur: on 66–98 relays a day,
    dir-write history exceeds total write history (`claims-ledger.md` D5).

## 4. Why stock tor has no brake on this path

- **The stream limit is skipped.** BEGIN_DIR is dispatched before the
  per-circuit stream DoS limit (`connection_edge.c:4333` returns before
  `:4340`). That limit is also off by default and per-circuit, at rate 100 /
  burst 300.
- **Circuit-creation limits only cover clients.** `DoSCircuitCreation` counts
  client (unauthenticated) channels only (`dos.c:535`, `:720`).
  - A peer that authenticates as a relay, even an unpublished one, escapes
    it. It can open cheap CREATE_FAST one-hop circuits, handled inline
    without a worker thread (`command.c:365`).
  - Patch 0001 closes the unpublished-identity part of this, for HS requests
    only and only when enforced. It answers 503 to an HS request whose
    previous hop is not a known relay; by default it only counts.
  - It does not limit circuit creation, and a published relay still escapes
    `DoSCircuitCreation`.
- **The "directory busy" check never fires here.**
  - The HS GET handler never calls it: its only callers are
    `dircache.c:962/1071/1130/1228/1324`.
  - It also returns "not low" for linked (BEGIN_DIR) connections
    (`connection.c:3428`).
- **Bandwidth limits cap egress, not demand.** `BandwidthRate` and
  `RelayBandwidthRate` charge the OR connection, so they limit egress. They
  never turn a request away; unsent bytes queue in memory.

## 5. What this means for the defenses

1. **Bytes are the binding resource.** 0001 and 0002 change *how* requests may
   arrive; neither caps bytes served.

2. **0002 (one HS request per circuit), when enforced:**
   - **Effect today:** it cuts F's served flood responses by about 82–83%
     (1 − 1/ρ for ρ = 5.6–6.0). That is about 79% of all F's BEGIN_DIR.
     - It is an upper bound that assumes the requester keeps building circuits
       at about today's rate.
     - The closed-lab reuse-5 cell measured a smaller −67% in served bytes
       (`../README.md`).
   - **Memory:** it limits pinned memory to at most one response per circuit.
     A maximum-size response fits the initial window when the consensus
     `cc_cwnd_init` is ≥ 101 (v0 498-byte DATA cells), or ≥ 103 with 0.4.9's
     CGO cells.
   - **If the requester switches to one request per fresh circuit:**
     - Bytes served do not drop at all. F's flood circuits rise about 5.75×,
       from 35/s to about 203/s.
     - Each request then costs the HSDir an ntor_v3 handshake on its worker
       threads.
     - Those handshakes share one first-in-first-out queue with legitimate
       CREATE cells (admission by `MaxOnionQueueDelay`, default 1750 ms,
       `onion_queue.c:49`), which drops without regard to source.
     - This is tolerable at F's rate. At field rates a 1–2 vCPU HSDir would
       start dropping legitimate circuits.

3. **0001 must ship with 0002.** Without 0001, the cheapest workaround for
   0002 is one-hop CREATE_FAST circuits from self-made relay identities. They
   need no handshake work and pass every stock check. 0002's own commit
   message already requires 0001.

4. **The missing piece is a per-HSDir byte budget for HS descriptor
   responses.** This is a **proposal**, not part of the current 7-patch
   series, which keeps its four counters unchanged.
   - **Where:** checked before the descriptor is copied (between
     `dircache.c:1375` and `:1384`). A refusal costs about 3 cells instead of
     about 80.
   - **Rollout:** count-only first with a would-refuse counter, sized to the
     relay's own capacity.
   - **Effect on legitimate clients:**
     - Each descriptor is stored on 8 HSDirs (2 replicas × `hsdir_spread_store`
       4), and a client picks among 6 of them (2 × `hsdir_spread_fetch` 3;
       `hs_common.h:112,114,116`).
     - Clients skip an HSDir they asked within 15 minutes.
     - So one HSDir shedding load costs a client about one extra circuit.
   - **Risk 1:** an exhausted budget makes denying one targeted service
     cheaper. Over budget, refuse in this order: unknown previous hop, then
     reused circuit, then descriptors fetched beyond their share, and only
     then stock-looking traffic.
   - **Risk 2:** a 503 marks the HSDir as overloaded for an hour
     (`dirclient.c:2137`; `DIR_503_TIMEOUT` 60 min, `routerlist.h:49`).
     - `router_pick_directory_server()` then deprioritizes it as a general
       directory server (`node_select.c:366`).
     - Clients that use directory guards bypass that picker
       (`dirclient.c:345-351`), so the effect falls mainly on relays and
       guardless clients.
     - Choose the refusal status deliberately; this applies to 0001's 503 too.
   - **Not reusable:** stock's "directory busy" check (§4).

5. **Smaller follow-ups (also proposals):**
   - Refuse an HS request while its circuit's window is closed or its stream
     is XOFF'd. That closes the pinning cases 0002 leaves open.
   - Add a count-only gauge of bytes waiting in exit-edge buffers, to make
     stalls visible.
   - Make the `connection_in_array` assert O(1), only if a call-graph profile
     shows it matters. That also needs `conn_array_index` reset in
     `connection_remove`.
   - Lowering `HSV3MaxDescriptorSize` is a weak lever. A cap that keeps 2-block
     descriptors (about 28 KB) would serve at most about 1.3–1.4× fewer bytes
     at F's estimated 35–38 KB descriptors (1.5–1.8× only if flood
     descriptors are 41–50 KB). It also breaks legitimate 3-block descriptors.

6. **Stock DoS options will not help** (§4).

## 6. Advice for constrained HSDirs on stock tor today

- **Set `MaxMemInQueues` explicitly:** physical or container RAM, minus
  baseline RSS, minus headroom.
- **Also set `MaxHSDirCacheBytes`.**
  - Its default is `MaxMemInQueues/5` (`hs_cache.c:1263`), so lowering one
    shrinks the descriptor cache.
  - Under memory pressure stock evicts the least-downloaded descriptors first.
    Flooded descriptors are fetched constantly, so legitimate ones can go
    first.
  - Stock also credits a download at connection close even if nothing was
    delivered (`directory.c:536`).
  - Patch 0007 credits a download only once the response has been flushed to
    the linked exit edge. That is still not proof of delivery, and its commit
    message says it does not affect the fetch flood. It does not change this
    eviction order.
- **`RelayBandwidthRate` protects a bandwidth bill, not the relay.** Pressure
  moves to RAM, and below 51,200 B/s directory service turns off
  (`router.c:1269`).
- **Not `AccountingMax`.**
  - With default rates, tor stops advertising tunnelled directory service
    (`router.c:1325-1328`), which loses HSDir, Guard and V2Dir.
  - It can also hibernate the relay. `AccountingMax 1 TB` (tor's 2^40 B) lasts
    about 14.5 h at F's 21 MB/s output.
- **Last resort: `DirCache 0` + reload (no restart).**
  - Each BEGIN_DIR then gets a one-cell refusal.
  - It costs Guard and V2Dir as well as HSDir, and the flood moves to the
    next HSDir on the ring.

## 7. What to collect from F next (stock tor, no new build)

Share counts and aggregates only, never raw lists.

- **Main-thread CPU:** `pidstat -t -p <pid> 1 60` (or `top -H`), with core
  count and model. This decides the CPU question.
  - A 60 s `perf record --call-graph dwarf` settles the `connection_free_`
    attribution.
  - Share the `perf report --stdio` text, not `perf.data`, whose header
    records the hostname.
- **Byte history:** `grep -E '^BWHistory(Dir)?(Read|Write)(Values|Ends|Interval)' <DataDirectory>/state`.
  - Values are 24-hour buckets (`bw_array_st.h:19`) plus the running day's
    total.
  - Read the running total twice, some hours apart. Divide the difference by
    the BEGIN_DIR counter delta over the same interval.
  - That gives the mean response size, the HTTP ratio, and bytes generated
    versus sent.
- **Memory:** `VmRSS` / `VmHWM` against the peers and against F before the
  flood.
  - Also grep the notice log for `We're low on memory` and
    `Removed .* bytes by killing`.
- **MetricsPort:**
  - `tor_relay_load_global_rate_limit_reached_total{side}`
  - `tor_relay_load_onionskins_total{type,action}` (including
    `type="ntor_v3"`, the handshake 0.4.9 clients mostly use)
  - `tor_relay_load_oom_bytes_total`
  - the series behind each dashboard column, with `instance`, `job` and any
    host, nickname or fingerprint labels removed before sharing
- **`GETINFO orconn-status`:** report only two counts, and do not share the
  list (it contains peer fingerprints and client IP:port pairs).
  - Entries shown as a bare `$FINGERPRINT` (no `~nickname`): authenticated
    peers this relay knows from neither the consensus nor a descriptor. That
    is 0001's "unknown previous hop".
  - Entries shown as `address:port`: unauthenticated clients, which stock
    already refuses for HS requests.
- **Two SIGUSR1 dumps, 60 s apart.** Keep only these lines:
  - "For N Exit/Directory connections" (buffer use);
  - the create and destroy cell counts;
  - "ntor onionskins have averaged" (ntor v1 only).
- **Consensus `params` line** from the cached consensus: `cc_cwnd_init`,
  `circwindow`, `HSV3MaxDescriptorSize`, `sendme_accept_min_version`, `DoS*`.
- **Definitions** of the dashboard columns New/s, Closed/s, OR in,
  Handshakes/s and DROP/s, and the layer at which 1:70 was measured.

With the count-only build, the counters `T = hsdir_request_total`,
`R = hsdir_req_reused` and `U = hsdir_unknown_prev_hop`, taken as deltas over
a window, give:
- ΔT/(ΔT−ΔR): HS requests (fetches and uploads) per circuit that made one;
- ΔU/ΔT: the unknown-previous-hop share.

ΔT/(ΔT−ΔR) is not the same quantity as §2's BEGIN_DIR per new circuit.

## 8. Open items

- §2's response size and §3's capacity numbers rest on F's out-minus-in
  surplus until the byte history (§7) is read.
- The CPU estimates are uncalibrated against F.
- Whether F's flood circuits stall is open; RSS settles it.
- `claims-ledger.md` P1/P2 still describe an earlier design: on by default, a
  1-bit flag, and an edit inside `connection_dir_is_anonymous`. The current
  series is count-only by default, uses a 2-bit counter and a separate guard,
  and leaves that function untouched.
