# Canary / rollback plan — cleanup indexing backport (UNEXECUTED)

This plan is not authorization to deploy. No relay was changed. Request-policy
controls (`HSDirOneRequestPerCircuit`, `HSDirRefuseUnknownPrevHop`,
`DoSBeginDirLimitEnabled`, `DoSBeginDirMaxStreams`, `HSDirDescriptorFetchLimit`,
`HSDirFetchBudget`) stay **exactly as they are in the `.6` deployment** —
this change is a pure cleanup-cost optimisation and item 4 only reorders an
already-present check. It neither enables nor alters any defense.

## Preconditions
- Build a `.7` candidate = `.6` series + items 1–3 (cherry-picked) + item 4
  (folded into 0012), **after** switching items 1–3 to tor `main`'s
  self-healing index repair (`connection_list_index()` with a `BUG()` +
  `smartlist_pos()` fallback) rather than this backport's hard asserts.
- Reproduce: `make check` green with `--enable-fatal-warnings` and with
  `--disable-module-relay`; `check-spaces` clean; the 9 mainloop tests and
  `test_dos_begindir_refused` pass; scaling microbenchmark shows 0 scan
  comparisons; `sizeof(connection_t)` unchanged.
- Package parity: the `.7` deb differs from `.6` only by these commits; every
  defense default stays as in `.6` (all `auto`/off); confirm the 24/26-series
  metric contract is unchanged (this change adds none).

## Canary
- One pilot host, one patched instance, against a same-host **patched-off
  control** running the current `.6` build, same ExecStart/config otherwise.
- Observe for 7–14 usable HSDir-days: main-thread CPU (`/proc/<pid>/task/
  <pid>/stat`), RSS, DoS heartbeat, the `.6` BEGIN_DIR/dir metrics, and
  legitimate-client reachability signals already defined in the operator kit.
- Success signal: under comparable BEGIN_DIR load, the patched instance uses
  less main-thread CPU per unit of directory work than the control, with no
  change in served-response correctness, no new warns/BUGs, and no assertion.
- Non-signal: absolute request/byte volume (driven by the attacker, not us).

## Rollback triggers (any one)
- Any `[err]`/assertion/`BUG` referencing mainloop/connection cleanup, or a
  crash, on the patched instance.
- A tor_assert on an index invariant (should be impossible after adopting the
  self-heal; if it happens, revert and report).
- Served-response correctness or legitimate-client reachability worse than the
  control beyond noise.
- Memory growth divergence from the control.

## Rollback
- Stop the patched instance, restore its ExecStart to the `.6` binary (kept in
  place), reload. No state migration: the change is in-process bookkeeping
  only, no on-disk or consensus format change, no option change. Confirm the
  instance rejoins with the `.6` metric contract.
