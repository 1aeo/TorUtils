# tor#41339 patch series — crash-at-scale critique

Skeptical lead review of the DEFENSIVE series (0001–0007) as applied in
`/home/user/tor41339/build/v3-main/src`. Every raw finding below was
re-traced from a real caller / attacker input against the applied code before
being trusted; the default disposition was REJECTED unless a concrete reachable
path could be constructed. Scope: remote-reachable crash / abort / UAF /
overflow / unbounded-memory under high concurrency and hostile input.

## Verdict

Safe to run on a production HSDir under flood. **Zero CRITICAL/HIGH crash,
memory-safety, or unbounded-memory risks found.** All three reviewer findings
are low-severity performance / resource-occupancy observations, not defects;
the series on balance *reduces* per-stream memory and per-request cost. The
count-only observe build is cleared for deployment.

## Confirmed risks

**None at CRITICAL or HIGH.** No reviewer finding, and nothing surfaced during
independent re-tracing, constitutes a reachable crash, abort, use-after-free,
overflow, or unbounded-memory growth at scale. The three raw findings were all
self-classified `perf-degradation` / low, and that classification survives
verification. There is nothing here that must be fixed before deploy.

## Plausible / conditional (verified real, low severity, worth awareness)

These are genuine, reachable code facts. None is a crash; each is a bounded
cost or occupancy tradeoff. Listed so they are on the record, not because they
gate deploy.

- **0005 — the 10 MB server inbuf byte-cap is now dead code for dir servers.**
  CONFIRMED as a code fact: `connection_dir_process_inbuf()`
  (`directory.c:606`) hits the `DIR_CONN_IS_SERVER → buf_clear; return 0`
  branch on every server read, so the later
  `MAX_DIRECTORY_OBJECT_SIZE` / "Too much data received" teardown
  (`directory.c:615`) is unreachable for `DIR_PURPOSE_SERVER` connections.
  *Not a crash and not an unbounded-memory regression:* `buf_clear()`
  (`buffers.c`) frees every chunk and resets `datalen` on each read, so
  per-stream resident memory drops from up to 10 MB to roughly one read, and
  the connection is not freed under the caller (no dangling inbuf pointer is
  held across the clear). Liveness is preserved in production: I confirmed
  `TestingDirConnectionMaxStall` is *forced* to its 5-minute default on any
  non-test relay (`config.c:3997–4009,4025` REJECT any other value) and is
  enforced for `DIR_CONN_IS_SERVER` off `timestamp_last_write_allowed`
  (`mainloop.c:1200–1218`), so a client that sends forever without draining
  its answer is torn down after ~5 min; `MaxMemInQueues` OOM still covers
  these conns. Residual: under a BEGIN_DIR flood (exempt from
  `DoSStreamCreation`) an attacker holds a connection slot plus read/discard
  CPU for up to the stall window instead of being cut at 10 MB. Aggregate
  pressure is bounded by `ConnLimit`, the stall timer, and OOM. Operational
  awareness item; matches the commit message's stated "per stream, not in
  total" scope. If an operator wants a tighter bound, options are a shorter
  dir-conn stall or a per-read discard counter that closes after N bytes — not
  required for safety.

- **0004 — a per-request `net_params` linear scan on the broadest dir path.**
  CONFIRMED: `directory_handle_command()` (`dircache.c:1761`) computes
  `max_body_len` unconditionally on every call on non-authorities via
  `hs_cache_get_max_descriptor_size()` → `networkstatus_get_param(NULL,
  "HSV3MaxDescriptorSize",…)` → `get_net_param_from_list()`
  (`networkstatus.c:2478`), a `SMARTLIST_FOREACH` + `strcmpstart` over the
  consensus param list; and because the function re-runs per read for an
  incomplete request, it recomputes per read. *Not a stall/crash:* the param
  list is a small fixed constant (tens of entries), the scan is lockless and
  allocation-free, and the patch's early Content-Length reject plus the smaller
  body cap remove far more work than this adds — net effect is a cost
  reduction. Optional micro-opt: hoist the lookup, or cache per consensus.

- **0001 / 0002 — added `net_params` scans gated behind attack conditions.**
  CONFIRMED and correctly gated. `dos_should_enforce_hsdir_one_request_per_circ()`
  (0001) runs its `auto`-mode scan only inside the
  `circ->already_received_hsdir_request` branch of
  `connection_dir_note_hs_request()` (`directory.c:297`), i.e. only on circuit
  *reuse*; stock one-request-per-circuit traffic pays zero. 
  `dos_should_refuse_unknown_hsdir_prev_hop()` (0002) runs only after
  `connection_dir_prev_hop_is_known_relay()` returns false in
  `connection_dir_check_prev_hop()` (`directory.c:355`), i.e. only on an
  *unknown* previous hop; stock traffic with a consensus relay prev-hop pays
  zero. The known-relay lookup itself is `router_get_consensus_status_by_id` →
  `smartlist_bsearch` (O(log N), `networkstatus.c`) plus an O(1) digestmap
  fallback — the same primitive the exit `RefuseUnknownExits` path already runs
  per BEGIN cell. An attacker who forces these paths pays one small scan per
  request, which short-circuits the much costlier descriptor serve. Minor.

## Rejected findings (crash theories that do NOT hold — settled, do not re-litigate)

- **"Removing the 10 MB cap leaves server dir-conns unbounded → OOM crash."**
  REJECTED. Per-read `buf_clear()` keeps resident memory bounded to one read;
  the production-active 5-minute stall timer and `MaxMemInQueues` both tear the
  conn down. Per-stream memory is strictly *lower* than before the patch.

- **"0006's moved signature-length assert can fire on hostile input."**
  REJECTED. `R3_SIGNATURE` is `T1_END(…, EQ(1), NO_OBJ)` (`hs_descriptor.c:139`):
  mandatory exactly once, exactly one arg. `tokenize_string()` enforces
  min/max count and arg count *before* `desc_decode_plaintext_v3()` runs, and
  `find_by_keyword()` (`parsecommon.c:435`) only asserts on a token the grammar
  guarantees present. Moving the `find_by_keyword(R3_SIGNATURE)` +
  `tor_assert(n_args==1)` ahead of `cert_parse_and_validate()`
  (`hs_descriptor.c:2217`) only widens its reach over descriptors that
  tokenized successfully but fail cert parsing — for those the invariant still
  holds, so it cannot newly fire. The 88-char padded signature is rejected by
  the `strlen != ED25519_SIG_BASE64_LEN` check (`goto err`), never an assert.

- **"0004's `max_bodylen` could be 0 (reject-all) or underflow the log cast."**
  REJECTED. `hs_cache_get_max_descriptor_size()` is
  `networkstatus_get_param(…, default 1, INT32_MAX)` clamped to
  `[1, INT32_MAX]` (`hs_cache.c:1223`), then `MIN(MAX_DIR_UL_SIZE, …)`, so
  `max_body_len ∈ [1, 16 MB]`, never 0. GET requests carry no body and are
  untouched even at the pathological value 1. The early reject
  (`proto_http.c:105`) uses the same `<=` boundary as the pre-existing
  actual-bytes check (`proto_http.c:86`) and returns `-1` before any
  `buf_get_bytes`/alloc, so it rejects strictly *sooner*, never *more*. The
  `(int)max_bodylen-1` / `(int)contentlen` casts are log-only and in range.

- **"0001/0002 casts (`TO_OR_CIRCUIT`/`TO_EDGE_CONN`) or `p_chan->identity_digest`
  crash on a self-generated / malformed prev hop."** REJECTED.
  `connection_dir_is_anonymous()` (`directory.c:202`) validates the full
  `dir_conn → linked_conn (EDGE_CONNECTION_MAGIC) → on_circuit (non-origin,
  not marked) → p_chan (non-NULL via BUG guard)` chain synchronously one call
  before the casts, with no intervening I/O, so the magic tags always match and
  `p_chan` is non-NULL. `channel_t.identity_digest` is an inline `char[]`, not
  a pointer, so an unknown/self-generated identity is a plain bsearch/map miss,
  not a deref fault. A one-hop / client / DirPort HS request is refused earlier
  (single-hop / `is_encrypted`) before these functions' casts are reached.

- **"0007 double-credits or uses `hs_ident` after free."** REJECTED. The old
  `connection_dir_about_to_close()` credit site is *gone* (verified: the only
  `hs_cache_mark_dowloaded_as_dir` call in `directory.c` is the new one at
  line 685). The new site runs inside `connection_dir_finished_flushing()`
  (`directory.c:684`), a write-ready callback on a live conn, guarded by
  `if (conn->hs_ident)` and by the early `marked_for_close` return
  (`directory.c:655`); the helper (`hs_cache.c`) does an O(1) `digest256map_get`
  + increment and tolerates a NULL lookup. Exactly one credit per fully-flushed
  response; no UAF, no double-free.

- **"Enforcement's `circuit_mark_for_close()` frees the circuit/conn under the
  caller (UAF)."** REJECTED. `circuit_mark_for_close_` only sets a flag and
  schedules postloop cleanup; teardown runs after the current read event
  returns. Reads of `conn->base_.state` / `conn->inbuf` afterward
  (`directory.c:592,606`) are on a live conn. Moreover this is the
  *enforcement* path and is not exercised in the count-only observe build (see
  deploy gate).

## Safe-at-scale (independently verified)

- **Assert reachability.** All touched asserts are invariants or pre-existing:
  0006's moved signature check (grammar-guaranteed), `tor_assert(conn)` /
  type asserts in `directory_handle_command` and `connection_dir_*`, 0007's
  `tor_assert(ident)` (satisfied by the `hs_ident` guard),
  `proto_http.c` `tor_assert(r==0)` / `tor_assert(body_used)` (untouched). The
  `tor_fragile_assert()` in `finished_flushing`'s default case is
  non-fatal in production (`tor_assert_nonfatal_unreached_once`) and off the HS
  path. No attacker-reachable fatal assert.

- **Circuit / connection close ordering.** 0001 enforcement mark is deferred,
  no synchronous free, RESOURCELIMIT is not in circpad's keep-open allowlist,
  duplicate-mark guarded. 0007 credit runs only on a live, flushing conn and
  exactly once. Linked-conn invariant preserved across mid-request close.

- **Bounded state.** 0001/0002 add two 1-bit fields to the already-allocated
  `or_circuit_t` and two process-global `uint64_t` counters, incremented at
  most once per circuit (0001) / once per unknown-prev-hop request (0002) —
  O(1) memory, no per-request allocation, no map/list growth; wrap is
  cosmetic (statistics only). Metrics store is reset per scrape; heartbeat
  smartlist is torn down each call.

- **Buffer / parse bounds.** `buf_clear` is chunk-walk-and-free, memory-safe at
  both 0005 call sites with no pointer held across it. 0004 early reject leaves
  inbuf and out-params untouched on `-1` (no leak, no partial consume). 0005
  never clears a still-incomplete request (guarded on `SERVER_WRITING`, set
  only after a full request drained); clients keep their response body
  (`DIR_CONN_IS_SERVER` guard). 0006 reads a NUL-terminated memarea string;
  only an exact 86-char base64 reaches `ed25519_signature_from_base64`, which
  decodes a fixed 64-byte signature.

- **Per-request cost / locking.** No new locks anywhere; all patched hot-path
  functions run on the single main thread over lockless globals. Added work is
  O(1) bitfield ops plus, only on attack/reuse paths, a small constant
  `net_params` scan and an O(log N) consensus bsearch. 0003 is a pure
  log-flood reduction (warn→info + rate-limit). Net per-request cost under
  flood is lower than pre-patch.

## Deploy gate

**The count-only observe build is safe to run on a production HSDir under
flood.** Green light.

- In observe mode the enforcement branches are inert. 0001 closes a circuit
  only when `dos_should_enforce_hsdir_one_request_per_circ()` is true; 0002
  returns a 503 only when `dos_should_refuse_unknown_hsdir_prev_hop()` is true.
  Both are false in the shipped default (`HSDirOneRequestPerCircuit` /
  `HSDirRefuseUnknownPrevHop` = `auto`, consensus params default off), and with
  the torrc options explicitly set to `0`. So `circuit_mark_for_close()` (0001)
  and the 503 refusal (0002) are **never executed** in observe mode — only the
  `uint64_t` counters, the per-circuit bits, the bsearch/scan, and the
  heartbeat/MetricsPort output run. Even if an enforcement-path defect existed
  (none found), it would not be exercised.

- The non-gated changes — 0003 (log rate-limit), 0004 (body-size cap + early
  Content-Length reject), 0005 (discard post-request input), 0006 (signature
  length check), 0007 (credit-on-flush) — are active in both modes and were all
  verified safe above. They harden or reduce cost and introduce no crash,
  memory-safety, or unbounded-memory path.

- Recommended posture for first production exposure: observe-only (defaults),
  watch `tor_relay_dos_total{type="hsdir_circ_reused"}` and
  `{type="hsdir_unknown_prev_hop"}` plus the two DoS heartbeat lines, and keep
  `MaxMemInQueues` at its normal value as the memory backstop for 0005. Flip to
  enforcement only after the observe data confirms the false-positive rate.

---
*Review level: high. Findings reported: 0 confirmed CRITICAL/HIGH; 3 verified
low-severity perf/occupancy items; 6 crash theories rejected with reasons.*
