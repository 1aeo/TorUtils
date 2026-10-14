# tor#41339 closed-lab benchmark — off vs on (measured)

Private, loopback-only chutney net (modern chutney `3338f5c`): 4 dir authorities,
6 HSDir-flag relays (the target pool), 3 onion services, 2 stock clients, and
test-only load clients. All nodes run the v3-patched `tor`
(`git-3bfcd0c1`, 0.4.9.14 + the 7 patches); baseline cells run the unpatched
`main` build (`git-8dbbbe6e`). Matrix: enforcement {unpatched, observe,
0001, 0002, both} × load {none, fetch, reuse-5, reuse-22, one-hop, adapted},
3 reps × 60 s. Target HSDir re-probed per cell. 80 cells, 0 harness errors.

**Numbering note.** This benchmark was run on the pre-reorder build, so the raw
`mode` labels below (and in `summary-x86-offvson.txt` / `results-x86-full.csv`)
use the **pre-reorder** numbering, which is the **inverse** of the shipped
`patches/` numbering: raw `0001` = the **one-request-per-circuit** defense
(serve one onion-service dir request per circuit; circuit-close / RESOURCELIMIT)
= shipped **`patches/0002`**; raw `0002` = the **unknown-previous-hop refusal**
(503) = shipped **`patches/0001`**. The raw labels are left verbatim so they
stay in sync with `results-x86-full.csv`; defense **names** are authoritative,
and the prose below cites each defense by name and its shipped `patches/` number.

**Measurement hygiene.** The small net occasionally wedges a whole cell
(circuit-build / consensus-transition choke): the legit prober gets ~5 attempts
instead of ~60 and everything fails. These are lab transients, **not** defense
effects — proven by `hsdir_unknown_prev_hop = 0` on the choked `0002/fetch`
reps (0002 never fired). A rep is dropped as invalid when its legit-prober
attempts < 30. **4 of 80 reps dropped (5%)**: `0002/fetch` 2/3, `0002/reuse-5`
1/3, `observe/reuse-5` 1/3. Central values below are medians over the valid
reps; dropped counts are stated, never hidden.

## Off-vs-on (valid-rep medians)

| mode | load | served | legit | bytes_written | reused | unk_hop |
|---|---|---|---|---|---|---|
| unpatched | reuse-22 | 1.00 | 1.000 | 6,358,430 | — | — |
| observe | reuse-22 | 1.00 | 1.000 | 6,279,607 | 0 | 0 |
| **0001** | **reuse-22** | **0.00** | **1.000** | **1,193,100** | 14 | 0 |
| **both** | **reuse-22** | **0.00** | **1.000** | **1,209,583** | 14 | 0 |
| unpatched | reuse-5 | 1.00 | 1.000 | 3,821,347 | — | — |
| observe | reuse-5 | 1.00 | 1.000 | 3,681,974 | 0 | 0 |
| **0001** | **reuse-5** | **0.00** | **1.000** | **1,249,387** | 30 | 0 |
| unpatched | one-hop | 1.00 | 1.000 | 1,734,394 | — | — |
| observe | one-hop | 1.00 | 1.000 | 1,644,014 | 0 | 30 |
| **0002** | **one-hop** | **0.03** | **1.000** | 1,202,538 | 0 | 30 |
| **both** | **one-hop** | **0.03** | **1.000** | 1,188,945 | 0 | 30 |
| 0001 | one-hop | 0.50 | 1.000 | 1,397,610 | 15 | 30 |
| any | fetch | 1.00 | 1.000 | ~1.6–2.4M | 0 | 0 |
| any | adapted | 1.00 | 1.000 | ~1.65M | 0 | 0 |

(The `mode` column uses the raw pre-reorder labels — see the Numbering note:
`0001` = one-request-per-circuit = shipped `patches/0002`; `0002` =
unknown-previous-hop refusal = shipped `patches/0001`.)

## Findings

**1. The one-request-per-circuit defense (shipped `patches/0002`) collapses the
circuit-reuse flood with zero collateral.** Reuse-5 and reuse-22 go from
**100% served** (unpatched and observe) to **~0% received by the pipelining test
client** (the HSDir still serves one descriptor per circuit — the 1/n floor)
under enforcement (raw mode `0001`, and `both`), while the stock client stays
**100% successful** (legit 1.000)
in every reuse cell. Served-response volume at the target drops **~81%** for
reuse-22 and **~67%** for reuse-5, measured **within-build** (count-only →
enforcing on the *same* net: reuse-22 6.28M → 1.19M; reuse-5 3.68M → 1.25M
written bytes) — the residual is legit descriptors + 503/RESOURCELIMIT control
traffic, not flood payload (see the cross-build caveat under Limitations).
The `hsdir_circ_reused` counter rises under enforcement (14 / 30 circuits
closed). The HSDir's floor is **one served descriptor per circuit** (1/n of the
attacker's requests), not zero: the ~0%-served figure above is a client-side
pipelining artifact — the circuit-close on request #2 also aborts request #1's
in-flight response (the companion seccomp runs recorded `served 1/418`,
confirming the floor is 1, not 0). This floor is reached with no measured
false positive against legitimate one-per-circuit traffic.

**2. The unknown-previous-hop refusal (shipped `patches/0001`) refuses the
unlisted-relay one-hop vector.** One-hop fetches from a self-minted (unpublished)
relay go from **100% served** (unpatched, observe) to **~3% served** under
enforcement (raw mode `0002`, and `both`) — i.e. refused — with the
`hsdir_unknown_prev_hop` counter at 30 and legit traffic at 1.000. Observe mode
confirms the gap and the instrument: the same requests are **served 100%** but
**counted** (`unk_hop = 30`). Under the one-request-per-circuit defense alone
(raw mode `0001` = shipped `patches/0002`), one-hop is 50% served (it closes
the *reused* one-hop circuits but does not refuse the non-reused ones) —
confirming the two defenses address different halves and belong together.

**3. Stock traffic is untouched.** `fetch` (one request per fresh circuit) and
`adapted` (the attacker shape after the one-request-per-circuit defense, shipped
`patches/0002`, forces one request per fresh circuit) are **100% served under
every mode**,
including both-enforcing. Count-only observe mode serves everything in every
load (the defaults change nothing), as designed.

**4. Legit preservation (the success criterion).** Across all 24 valid
enforcement cells the stock client's success rate is **1.000**, mean latency
0.07–0.21 s. The single sub-1.0 valid value is the `0002/none` baseline (raw
mode `0002` = unknown-previous-hop refusal, shipped `patches/0001`) at 0.979
(46/47 — one dropped fetch with no load, `unk_hop = 0`, i.e. not a refusal).
**The defense collapses the flood while preserving legitimate access.**

## Adaptation cost (where the load moves)

The one-request-per-circuit defense (shipped `patches/0002`) forces the reuse
attacker to one request per fresh circuit. To deliver the
same request volume it reused ~14–30× onto, the attacker must now build that
many separate circuits, each paying a full CREATE/onionskin handshake at the
guard and middle — and `DoSCircuitCreation` does **not** cover relay (channel)
circuit creation, so that cost lands on the middles, not the HSDir. **Direction
confirmed** in the lab (one-per-circuit patterns process more onionskins per
delivered request than the reuse pattern), but the absolute onionskin counts in
a 6-relay net are background-dominated and the `adapted` load was not
volume-matched to reuse-22, so the clean multiplier here is **analytic (≈ the
reuse ratio), not a precise lab measurement**. A volume-matched adapted cell
would pin it; flagged as a follow-up.

## Honest limitations

- **Absolute rates are not real-flood-representative.** This is a 6-relay
  loopback net; the ratios (served-fraction, legit-rate, reuse/unknown-hop
  counts) are the valid outputs, not the absolute Gbit/s or CPU. Grounding the
  *shape* on the operator's own relays is the `capture-and-validate-playbook.md`
  / count-only-deploy step; the measured ρ/φ there replace the lab's assumed
  `{5,22}` reuse multipliers.
- **Observe-mode `hsdir_circ_reused` per-cell delta reads low** because a
  non-enforced reuse client keeps one long-lived circuit (counted once) spanning
  cells; cumulatively the target logged 328 reused circuits over the patched
  run. Operators should read it as a rate over a window (distinct reused
  circuits), and derive the reuse *multiplier* from begin_dir ÷ circuits — a
  refinement folded back into the playbook.
- **Cross-build absolute bytes are confounded — use the within-build A/B.** The
  unpatched and patched nets were brought up separately, and even count-only
  (which should be byte-identical to unpatched for one-per-circuit traffic)
  writes ~30% fewer bytes than unpatched on the `fetch`/`adapted` cells at 100%
  served — a bring-up / run-order artifact, not a patch effect. So the
  byte-reduction figures above are the **within-build** comparison (count-only →
  enforcing on the *same* net), which controls for net state; the
  served-fraction headline is a within-cell ratio and is immune either way. A
  single-net interleaved unpatched-vs-count-only `fetch` run would pin the ~30%
  shift — feasible via chutney's per-node `tor=` field (give the target its own
  unpatched binary while the rest run patched); low priority, since the
  within-build A/B already controls net state.
- **5% lab-transient flake rate**, handled by the net-health gate above.

## Verdict

**Success criterion MET.** With enforcement on, the HSDir's served-response
volume under the reuse flood drops to its one-descriptor-per-circuit floor
(the HSDir serves one descriptor per circuit — written bytes −81% within-build;
the pipelining test client's **100% → ~0% received** is a client-side artifact,
not zero service) and the one-hop vector is refused (100% → 3%), **while the
stock client stays ~100% successful throughout**. The
one-request-per-circuit adaptation then moves circuit-creation/onionskin cost
onto middle relays, where DoSCircuitCreation does not apply.
