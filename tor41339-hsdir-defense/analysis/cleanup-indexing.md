# Connection-list cleanup indexing — analysis and lab results

Removing the list-size-dependent bookkeeping that the tor#41339 BEGIN_DIR
flood drives in connection teardown, plus refusing an over-limit BEGIN_DIR
before it allocates. Independent implementation and private-lab validation on
tor 0.4.9.14 and the `.6` series. Nothing was deployed; no traffic was sent to
the public network.

## Three verdicts

1. **Does the fix remove the hotspot?** Yes, mechanically and by measurement.
   The two scans the live profile attributed 90.47% of sampled main-thread
   userspace CPU to — `smartlist_remove(active_linked_connection_lst, conn)`
   in linked-connection teardown (50.58%) and the `connection_array`
   absence scan inside `connection_free_()` (39.89%) — are replaced by O(1)
   indexed operations. In the scaling microbenchmark against real tor
   lifecycle code they drop from up to **625 million** pointer comparisons per
   cleanup pass to **zero**, and fixed-size cleanup stops growing with the
   unrelated connection count (flat ~0.07–0.16 ms regardless of N or A, versus
   0.9–20 ms unpatched). This is CPU **amplification** removal, not a
   whole-relay speedup: it does not stop malicious requests arriving.

2. **Should it go into the next build (.7)?** Yes, as a backport, with one
   change: adopt tor `main`'s self-healing index-repair instead of this
   backport's hard assertions (see §6). The `.6` stack it targets runs
   0.4.9.14, which does **not** contain the upstream indexing. The four
   commits apply cleanly on the `.6` tip, pass `make check` with
   `--enable-fatal-warnings` and `--disable-module-relay`, add no new
   practracker problem kind, grow `connection_t` by **0 bytes**, and change no
   metric, option, or defense behaviour (item 4 only reorders one existing
   check). Low risk; real benefit only under heavy connection churn.

3. **Is it ready to send upstream?** It is **already upstream.** While this was
   being written, tor `main` merged an independent implementation of the same
   optimisation: `b035c0f5 "mainloop: Index global connection lists and
   membership checks"` (David Goulet, 2026-10-21) plus `142b3d44 "dos: Rate
   limit BEGIN_DIR per circuit"` and `cc22fd44 "circ: Refuse a second
   BEGIN_DIR on authenticated circuits"`, which between them also refuse
   BEGIN_DIR **before allocation**, ahead of the hibernation check, with the
   same `END_STREAM_REASON_MISC`. So there is nothing new to send upstream for
   0.4.9+; the remaining value is the **0.4.9.14 backport** for the deployed
   `.6`/`.7` build. The task brief's "would go upstream on their own" is
   overtaken by events — the check it asked for ("is this already integrated?")
   is the headline finding.

## What was built

Four commits. Items 1–3 are stock-only main-loop changes; item 4 is a
`.6`-series change to patch 0012.

| # | Commit (on 0.4.9.14 base `8fe2745`) | Change |
|---|---|---|
| 1 | `e3285030` mainloop: Check the array index, not the array, when freeing | reset `conn_array_index=-1` in `connection_remove()`; `connection_free_()` checks the index (O(1)) instead of scanning `connection_array` |
| 2 | `6c22493c` mainloop: Keep each connection's index in the list of conns to close | new `closeable_conn_index`; O(1) membership/removal on `closeable_connection_lst` |
| 3 | `91112dce` mainloop: Keep each linked connection's index in the active list | new `active_linked_conn_index`; O(1) membership/removal on `active_linked_connection_lst` |
| 4 | `fixup! dos: ... limit on open BEGIN_DIR streams` (on `.6`) | move `dos_should_refuse_begindir()` ahead of `edge_connection_new()` in `connection_exit_begin_conn()` so a refused BEGIN_DIR allocates nothing |

Patches: `engineering/cleanup-indexing/patches/against-0.4.9.14/` (items 1–3,
`git format-patch`) and `.../item4-fixup-of-0012/`. The `.6` integration
branch carries all four (items 1–3 cherry-picked, item 4 as a `fixup!` of
0012). Base commit recorded: `8fe2745` (release-0.4.9 tip; the `tor-0.4.9.14`
tag `4d6a948` is an ancestor). The three touched cleanup files are
byte-identical between `8fe2745` and the `.6` tip `c5195c0`.

## Reconciling the 0.85–0.9% and the 90.5%

They are not in conflict; they measure different denominators, and this task
verified both from the stored evidence (hash-matched ELF
`a9dad633…`, build-id `727743e3…`; re-tally script
`engineering/cleanup-indexing/lab/`).

- **0.85–0.9%** (earlier profiles, `flood-cost-and-constrained-hosts.md` §1.2)
  is `connection_free_`'s share of **whole-process** samples — kernel (~44% on
  that host), OpenSSL, libc and idle worker threads all included.
- **90.47%** (`live-main-profiles-20261021…`) is the two scans' share of the
  **main thread's userspace** samples only (the profiled relay, one main thread, 4282 samples,
  0 lost). An independent re-tally against the matching ELF reproduces
  2166 + 1708 = 3874 / 4282 = 90.47%, with non-tor leaf samples kept in the
  denominator.

A small whole-process share is most of the main thread's tor code because the
main thread is one of many threads and shares the core with the kernel and
crypto. The broader cleanup-function share on that relay is 91.22%; the two
verified *loops* are 90.47% of that thread's userspace. Neither figure is
shown to be the binding constraint on forwarding — the relay was near one core
on the main thread, and the fix removes amplification, not the arriving
requests. Two other captured relays spent only ~14% in the
broader cleanup functions, and the post-restart `.6` observations are quiet;
the 90.5% is the sustained-low-output-flood phenotype, not a universal.

## Before/after — scaling microbenchmark (authoritative)

Real `libtor` lifecycle code (`connection_add` / `connection_mark_for_close` /
`close_closeable_connections` / `connection_start`/`stop_reading_from_linked_conn`
/ `connection_free_`), `--wrap` counting the exact full-list comparisons each
`smartlist_remove`/`smartlist_contains` performs (it scans the whole list, not
up to first match), with marking and teardown counted separately and counting
runs separated from 11-trial timing runs. **All list lengths are synthetic
parameters; production N/A/C/H were never captured.** Harness:
`engineering/cleanup-indexing/bench_cleanup.c`; raw:
`results/scaling-{baseline,patched}.json`.

`N` = total connections, `A` = active-linked, `C` = closing this pass,
`H` = held-open backlog. `cpu` is per-pass median over 11 trials (ARM64,
Noble toolchain container).

| sweep | N | A | C | H | scan cmps (stock→patched) | cpu ms (stock→patched) | speedup |
|---|--:|--:|--:|--:|--:|--:|--:|
| vary_N | 2000 | 0 | 500 | 0 | 1.62M → 0 | 0.87 → 0.070 | 13× |
| vary_N | 16000 | 0 | 500 | 0 | 14.6M → 0 | 4.47 → 0.084 | 53× |
| vary_N | 64000 | 0 | 500 | 0 | 44.6M → 0 | 12.29 → 0.091 | 135× |
| vary_A | 32000 | 4000 | 500 | 0 | 41.6M → 0 | 11.59 → 0.103 | 112× |
| vary_A | 32000 | 30000 | 500 | 0 | 73.6M → 0 | 20.19 → 0.151 | 133× |
| vary_C | 32000 | 4000 | 100 | 0 | 10.0M → 0 | 2.65 → 0.020 | 135× |
| vary_C | 32000 | 4000 | 1000 | 0 | 112.7M → 0 | 32.29 → 0.265 | 122× |
| vary_C | 32000 | 4000 | 4000 | 0 | 624.8M → 0 | 199.42 → 1.231 | 162× |
| held_open | 32000 | 4000 | 500 | 200 | 98.0M → 0 | 26.66 → 0.118 | 226× |
| held_open | 32000 | 4000 | 500 | 2000 | 103.7M → 0 | 27.98 → 0.158 | 177× |
| normal_small | 200 | 20 | 10 | 0 | 1.66M → 0 | 0.456 → 0.003 | 163× |
| normal_small | 1500 | 50 | 25 | 5 | 4.20M → 0 | 1.08 → 0.007 | 161× |

Reading:
- **Fixed-C cleanup no longer grows with unrelated N or A.** Stock cleanup of a
  fixed C=500 rises 0.87→12.29 ms as N goes 2k→64k; patched stays ~0.07–0.09 ms.
- **The two scans disappear.** Patched does 0 `smartlist_remove`/`contains`
  comparisons at every point; it does a fixed number of `smartlist_del` +
  index writes (3 per closed BEGIN_DIR pair).
- **Targeted bookkeeping is linear in C.** Patched cpu scales ~linearly with C
  (0.020→1.231 ms for C 100→4000); stock is super-linear (O(C·(N+A))).
- **No normal-workload regression.** The small-workload points are 160×+
  faster and sub-millisecond; see the lab for request-level latency.
- **Struct/memory:** `sizeof(connection_t)` is **152 bytes before and after** —
  the two new `int` fields fill existing alignment padding on 64-bit. Zero
  per-connection memory overhead.

The `normal_small` 1.66M-comparison figure at N=200 looks large only because
the 11 timing trials re-run the pass; per single pass at N=200,C=10 it is a
few thousand comparisons. The point stands: even tiny workloads pay a scan the
patch removes.

## Before/after — private chutney lab (end-to-end, honest limits)

Loopback-only chutney net (`--network none`, `--privileged` for perf;
4 dir-auths + 5 HSDir relays + 2 clients + 3 onion services, each node the
tor binary under test), real HS-descriptor BEGIN_DIR load driven by `HSFETCH
… SERVER=<target>` against one target HSDir, `perf record` on the target's
**main thread only** (tid = pid), main-thread CPU from
`/proc/<pid>/task/<pid>/stat`. Harness: `engineering/cleanup-indexing/lab/`;
de-identified results: `engineering/cleanup-indexing/results/lab/`.

| build | BEGIN_DIR/s reached | main-thread CPU-s / window | teardown share in perf | normal HS fetches |
|---|--:|--:|---|---|
| S0 stock 0.4.9.14 | ~16 | 0.12 | `close_closeable_connections→connection_free_minimal` 5.15%, `connection_unlink` 0.74% | 2/3 received (one transient HS-desc miss) |
| S1 stock + items 1–3 | ~8–16 | 0.12 | same path 3.28%, no separate `connection_unlink` scan branch | 3/3 received, 0.00–0.04 s |

**What the lab shows, and what it does not.** At the scale one host sustains
(~8–16 BEGIN_DIR/s, small N), the teardown cost is dominated by
`connection_free_minimal` (buffer frees, memwipe), **not** the list scans — at
small N the array/active scans inside it are a negligible fraction. So the lab
does **not** reproduce the 90.5% share; it reaches only a few percent of the
main thread in the teardown *functions*, within which the scans are tiny. This
is expected and consistent with the operator profile being a sustained
~5,585 BEGIN_DIR/s flood with large N — roughly **350× the rate this net
sustains**. To reach a regime where the two scans are ≥90% of main-thread
userspace CPU, N (and the per-second close count) must be two-to-three orders
of magnitude higher; the microbenchmark reaches the equivalent comparison
counts directly (625 M comparisons / 199 ms per pass at N=32000, C=4000).
The lab's positive results are therefore: (a) the patched teardown share is
lower and has no `connection_unlink` scan branch, directionally consistent;
(b) **normal HS-descriptor request/response completes correctly** under the
patched binary (3/3, sub-50 ms) — real BEGIN_DIR request and response, not a
synthetic toggle; (c) **no assertion, BUG, or leak** in the target's logs
under either build. The absolute CPU (0.12 s over the window) is too low and
too close between builds for a trustworthy per-stream delta at this scale; the
per-stream µs figures in the raw JSON are reported but not relied on.

## Findings, ranked by severity

1. **(Informational, highest impact) The optimisation is already in tor main.**
   `b035c0f5` (indexing) and the `dos_begindir_*` series refuse-before-alloc
   landed upstream 2026-10-21, independently. Failure scenario avoided: filing
   an upstream MR that duplicates merged work, or shipping a `.7` that diverges
   from upstream semantics. Action: treat this as a backport; align with
   upstream (§6).
2. **(Design) This backport asserts where upstream self-heals.** On an
   inconsistent index, upstream logs a non-fatal `BUG()` and falls back to an
   O(n) `smartlist_pos()` search; this backport `tor_assert()`s. Failure
   scenario: a latent index bug that upstream would log-and-survive would
   instead abort a `.7` relay. For production, adopt upstream's self-heal.
3. **(Test gap, mitigated) Over-limit BEGIN_DIR refusal is not exercised
   end-to-end.** Item 4's behaviour is covered by the unit test
   `test_dos_begindir_refused` (two streams connected, the third refused with
   END MISC and **no** connection allocated — the array holds exactly 4
   conns), but a live over-limit flood needs intra-circuit stream reuse, which
   requires the test-only load client (`simulator/loadclient-testonly.diff`,
   `EVIL_ISO_SESSIONGRP`) that was not built here. Failure scenario: a refusal
   path bug that only appears under real circuit reuse. Remaining untested:
   the live per-circuit over-limit refusal and its per-refusal cost.
4. **(Scope) The lab cannot reproduce the production hotspot share.** As above;
   the microbenchmark is the scaling evidence. Failure scenario: over-claiming
   a measured whole-relay speedup. Stated plainly: not claimed.

## Interaction of item 4 with items 1–3

The brief notes 0012, when enforcing, makes things worse: a refused BEGIN_DIR
allocates `n_stream` and then `connection_free_()`s it, and on stock that free
pays a full O(N) `connection_array` absence scan (same scan the `vary_N` table
measures — up to 44.6 M comparisons at N=64000). Items 1–3 turn that free into
O(1); item 4 removes the allocate-and-free entirely. So on the `.6` backport
(which has both) a refused BEGIN_DIR is O(1) and allocation-free; item 4's
standalone saving (without items 1–3) would be the whole O(N) scan per refusal.

## Exact builds, tests, and environment

- **Toolchain:** container image `tor41350-build:2404`
  (`sha256:4090b389…`), Ubuntu 24.04, gcc 13.3.0, ARM64, in the `torbench`
  colima VM (16 cpu / 32 GiB). Lab image `mlci-lab:2` (`sha256:ac01a258…`)
  adds perf (linux-tools 6.8.0-147), chutney `3338f5c` (2026-01-21), stem
  1.8.2. All builds and the lab ran with the container network disabled.
- **Per-commit `make check`, `--enable-fatal-warnings --disable-asciidoc`:**
  items 1, 2, 3 each **33 PASS / 1 SKIP / 0 FAIL** (34 automake jobs);
  tip + `--disable-module-relay` **28 PASS / 6 SKIP / 0 FAIL**;
  `.6` + items 1–4 **33 PASS / 1 SKIP / 0 FAIL**. `make check-spaces` clean on
  every commit. Full unit binary: **1605 tests ok, 24 skipped** (items 1–3),
  including the 9 new mainloop tests and the existing
  dir/hs_cache/hs_client/hs_service/conflux/oom/relaycell/metrics/dos tests.
- **practracker:** no new problem *kind*. The only delta vs stock is
  `connection.c` file-size 6026→6035 lines (already over its grandfathered
  exceptions value of 5700, so stock itself reports it); `make check` does not
  run practracker (check-local = check-spaces, check-changes, check-includes,
  shellcheck).
- **Mutation testing:** 9/9 index-update mutants killed by the mainloop unit
  tests (`results/mutation.json`).
- **Scaling microbenchmark:** `bench_cleanup.c` linked against each build's
  `libtor-testing.a`, 11 trials/point, 20 points. Raw JSON in `results/`.
- **Chutney lab:** `lab/in-lab.sh` per build; raw measure/perf/normal-client in
  `results/lab/`.

Commands are in `engineering/cleanup-indexing/lab/` (`build-one.sh`,
`dev-make.sh`, `bench-build-run.sh`, `mutate.py`, `in-lab.sh`, `load.py`).

## Unverified / not done

- No production deployment, relay restart, defense enablement, or public-network
  traffic (out of scope by instruction).
- The 90.5% production share was **not** reproduced in the lab (scale limit, §
  above); it is cited from the stored hash-verified capture and re-tallied, not
  re-measured live.
- Per-stream main-thread CPU delta between S0 and S1 is **not** established at
  lab scale (absolute CPU too low). The scaling claim rests on the
  microbenchmark.
- Live over-limit BEGIN_DIR refusal (item 4) not exercised; needs the
  test-only reuse client.
- The operator's raw `perf report --stdio` text was not separately requested;
  the stored capture (`live_profile_verified_disassembly.txt`, perf-script)
  was already hash-matched to the profiled ELF and used directly.
- Slow-reader / aborted-stream behaviour under the patch is covered by unit
  tests (`hold_open_until_flushed`, linked-peer teardown) but not by a loopback
  lab case (loopback readers are never slow).

## Draft note to the Tor network team

See `engineering/cleanup-indexing/UPSTREAM-NOTE.md`.

## Canary / rollback (unexecuted; request-policy controls unchanged)

See `engineering/cleanup-indexing/CANARY-ROLLBACK.md`.
