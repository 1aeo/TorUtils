# Patch 0001 false-positive behaviour (lab)

Private loopback patched chutney net, 0001 (`HSDirRefuseUnknownPrevHop`)
enforcing on all 6 relays, `RefuseUnknownExits` forced to **0** throughout (so
any effect is 0001 acting independently, not the exit rule).

## Steady-state false-positive bound
Legitimate single HS fetches from the stock client (known, consensus middles)
for ~8 min, spanning many short testing-net consensus periods:

- **2,416 legit fetches, 2,400 served, `hsdir_unknown_prev_hop` delta = 0.**
- **Zero false 503s.** Observed FP rate 0.0; empirical bound **< 1/2416 ≈
  4.1e-4**, consistent with the ~1.2e-6 model estimate (which predicts ≈0 in
  2,416). (The detector is the counter, not a client event: a 503 on an HS
  fetch emits no `HS_DESC FAILED`, so a wrongly-refused legit fetch would show
  only as an `hsdir_unknown_prev_hop` increment — there were none. The 16
  non-served fetches were probes to a not-currently-responsible HSDir, not
  refusals, since the counter stayed at 0.)

## Mechanism (why steady-state FPs are ~0)
Per `networkstatus.c` `update_consensus_networkstatus_fetch_time_impl`, a dir
cache (HSDir) fetches consensus N+1 in `[fresh_until+slop, +slop+interval/2]`
while an ordinary client starts at `fresh_until + 3/4·interval` — so a
steady-state client is never *ahead* of an HSDir on relay membership. The FP
window (client knows a relay the HSDir doesn't yet) opens only for a client
that bootstraps or re-fetches mid-interval, or an HSDir whose own fetch failed.
The 0/2,416 steady-state result is exactly what that predicts.

## Toggle / independent rollback
- `HSDirRefuseUnknownPrevHop` **1**: one-hop (unknown-prev-hop) requests served
  **0**, counter +17 → refused.
- `HSDirRefuseUnknownPrevHop` **0**: same requests served **12/12**, counter
  still +12 → served again, still counted (count-only).
- Done with `RefuseUnknownExits=0` the whole time → 0001 is **independent** of
  the exit rule, and its rollback is a single torrc AUTOBOOL (the consensus
  parameter `hsdir_refuse_unknown_prev_hop` is the same predicate one layer up).

## Exit-parity
0001 applies the same "previous hop must be a known relay" test that exits have
used since 0.2.2 (`RefuseUnknownExits`). Its consensus-skew exposure is
therefore the *same class* the network already accepts for exit streams — not a
new failure mode.

## Limitation / follow-up
The **induced-skew window** (force a fresh client through a just-added relay to
a lagging HSDir and time the 503 window) was not directly measured here; the
natural rate = window-fraction × P(path uses a just-added relay) × P(lagging
HSDir) remains the analytic ~1.2e-6, now lab-bounded `< 4.1e-4` with **0
observed** and the steady-state mechanism confirmed. Directly measuring the
window (add a published relay, probe per-HSDir recognition time) is a clean
follow-up. Separately, on the operator's **stock** production relays φ (the real
unknown-prev-hop fraction of their flood) is unmeasurable without the count-only
build — see `analysis/realflood-capture-interpretation.md`.
