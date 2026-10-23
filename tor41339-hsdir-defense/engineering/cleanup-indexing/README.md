# cleanup-indexing — remove list-size-dependent BEGIN_DIR teardown cost

Backport to the `.6` series (and stock 0.4.9.14) of the connection-list
cleanup indexing that tor#41339's BEGIN_DIR flood makes expensive, plus
refusing an over-limit BEGIN_DIR before it allocates. **The same optimisation
is already in tor `main` (`b035c0f5` + the `dos_begindir_*` series, 2026-10-21);
this directory is the 0.4.9.14 backport and its validation.**

Read `../../analysis/cleanup-indexing.md` first (three verdicts, before/after
tables, reconciliation of the 0.85–0.9% vs 90.5% profiles, the upstream-
integration finding, limitations). `../../INVARIANT-AUDIT.md`
(`engineering/cleanup-indexing/INVARIANT-AUDIT.md`) has the per-list invariant
and mutation audit.

## Layout
```
patches/against-0.4.9.14/   items 1-3, git format-patch on base 8fe2745
patches/item4-fixup-of-0012/ item 4 as a fixup! of the series' 0012
bench_cleanup.c             scaling microbenchmark (real libtor lifecycle)
INVARIANT-AUDIT.md          invariant + mutation audit for all three lists
ITEM4-ON-DOT7.md            the .7 rebase of item 4 (keeps the new BEGIN_DIR counts)
NOTE-FROM-METRICS-AGENT.md  the peer note that prompted the .7 rebase (verbatim)
patches/item4-on-dot7/      item 4 reworked + built+tested on the full .7 series
UPSTREAM-NOTE.md            draft note to the Tor network team (not sent)
CANARY-ROLLBACK.md          unexecuted .7 canary/rollback plan
results/scaling-*.json      microbenchmark raw (baseline vs patched)
results/mutation.json       9/9 index-update mutants killed
results/lab/{S0,S1}/        de-identified chutney lab (measure/perf/normal-client)
lab/                        lab + build scripts (chutney, perf, bench, mutate)
lab/Dockerfile.labtools     how the lab image adds perf + chutney (network at build only)
```

## Reproduce
All in the `tor41350-build:2404` container, network disabled, from a clone of
tor at `8fe2745` (0.4.9.14) with the four commits applied:

- Per-commit check: `build-one.sh <name> check -- --enable-fatal-warnings --disable-asciidoc`
- Scaling microbenchmark: `bench-build-run.sh <tree> <label>` (needs the dev
  tree's `libtor-testing.a`; prints JSON like `results/scaling-*.json`).
- Mutation test: `mutate.py` (edits each index update, rebuilds, runs the
  mainloop tests, expects all mutants killed).
- Chutney lab (needs `mlci-lab` image, `--privileged` for perf, `--network
  none`): `in-lab.sh <label> <tor-binary> <rate> <seconds> <conc> <target>`.

Everything is loopback-only; no traffic is ever sent to the public network.
