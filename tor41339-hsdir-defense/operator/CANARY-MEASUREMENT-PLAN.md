# Final canary measurement and optional enforcement plan

Agreed design, 2026-10-14. **Documentation only: no deployment, build, probe,
helper implementation, scheduled monitoring, or enforcement is authorized by
this document's creation.** Runtime work starts only on a later instruction.

## Outcome and fixed scope

Run one pinned binary on **one canary** to characterize received HS directory
traffic, inform a human decision about enforcement, and, if separately
approved, measure the operational effects of a live enforcement trial.

- Retain patches **0001–0007 and the four existing HS counters unchanged**.
  Do not add handoff, outcome, histogram, overlap, or enforcement-action C
  counters for this experiment. GET/POST outcome telemetry is deferred.
- The candidate artifact is
  `tor_0.4.9.14-1~noble+1+tor41339.3_amd64.deb` for Ubuntu 24.04 amd64.
  Pin the actual source commit, package digest, and binary digest before use;
  branch names and `--version` alone do not identify the experiment's build.
- Accept the **full seven-patch build as the baseline**. Patches 0003–0007
  remain active with the two optional defenses off. This is not a promise of
  unchanged stock behavior. Compare inactive/active defenses on the same build.
- One planned canary restart activates the binary. Keep the identity,
  DataDirectory, normal memory limit, and security confinement. Later mode
  changes use ControlPort `SETCONF`, followed by `GETCONF`, with no restart.
- Codex collects and analyzes through an explicitly configured persistent
  collection/check-in arrangement; the human operator reviews the results and
  decides phase transitions. A chat turn is not continuous monitoring.
- No fleet changes, live load generation, identifying clients/services,
  per-request payload logging, or public reporting of private identifiers.

## Phase sequence and decision gates

| Phase | Work after its separate authorization | Exit condition |
|---|---|---|
| Preparation | Pin artifact; read reviews; complete private preflight, rollback inventory, monitoring, retention, health limits, and ownership | Operator reviews concrete preflight; all required fields complete |
| Deployment | Unpack to `/opt`; override one instance; validate exact configuration; restart only that instance; verify binary, counters, confinement, and inactive defenses | Deployment check-in passes, or incident procedure applies |
| HSDir recovery | Monitor health and continuity from startup; check fresh consensus for HSDir | Flag observed and documented, or predeclared recovery deadline reached |
| Passive collection | Gather **7–14 usable HSDir days**, multiple quiet/flood episodes and resource data; no synthetic probes and no enforcement | Planned observation duration reached; human receives report |
| Human review | Assess observed predicates, data quality, overload, and evidence limits | Continue observation, stop collection, or explicitly authorize a bounded trial |
| Probe preparation | Implement helper and pass its deterministic/loopback lab acceptance tests; prepare a dedicated stock client and owned descriptor | Evidence reviewed; not implied by observation approval |
| Optional trial | Low-rate controlled fetch checks in comparison and active windows; test one defense at a time; live disable on agreed failure criteria | Bounded trial complete or stopped; report outcomes and uncertainty |
| Handoff | Leave defenses inactive and retain the binary pending operator instruction; set a dated maintenance/continuation review | Human decides continued observation or planned removal |

Proposed planning defaults are **14 usable days** (operator may select 7–14),
daily summaries, and a recovery review at T0 + 7 days if HSDir has not returned.
These are choices to confirm in preflight, not already running schedules. The
~96-hour HSDir delay is an expectation, not a guaranteed return time. Do not
count this warmup or unusable gaps toward the observation duration; record both
usable duration and wall-clock duration. Set an absolute observation deadline
and extension policy so missing data cannot create an indefinite task.

## Deployment and observation requirements

Follow [DEPLOY-AND-MEASURE.md](DEPLOY-AND-MEASURE.md). In particular:

1. Preserve the original package holds, maintenance exclusions, service files,
   loaded unit configuration, security settings, and rollback target privately.
   Shared host maintenance changes need explicit scope agreement. Read-only
   Prometheus access does not authorize changes to scrape or retention config.
2. Never install this package host-wide on a multi-instance host or operate on
   the unqualified master `tor` service. Unpacking runs no maintainer scripts.
3. Keep both new options out of torrc and its includes. The stock pre-start
   verifier does not recognize them. Preserve the current MetricsPort access
   restrictions, notice logging, SafeLogging, and normal `MaxMemInQueues`.
4. Initial `auto` is accepted when runtime configuration is `auto` and the
   canary's current validated consensus lacks both parameters. Recheck at
   every scheduled check-in. Log consensus validity and state privately.
5. Verify each of the four counters individually, freshness, coverage, and
   selector uniqueness. A total cardinality of four is insufficient by itself.
   Counter values need not remain zero before the flag returns.
6. Preserve at least 30 days of relevant data, or export validated daily/window
   captures before expiry. Four-day warmup + fourteen observation days + a
   possible trial exceeds the default fifteen-day horizon.
7. Verify continuity using process start/activation history, boot history,
   scrape coverage, and counter behavior. `resets() = 0` alone is not proof of
   no restart. Missing evidence is reported as unknown.
8. Predeclare sustained resource/service-health limits, alert recipients,
   response times, and emergency actions. Expected flood-related CPU increases
   are not automatic rollback triggers; distinguish a relay fault from a
   scrape/analysis fault.

At 2026-10-14 21:49 UTC the public consensus valid after 21:00 UTC contained
neither `hsdir_one_request_per_circ` nor `hsdir_refuse_unknown_prev_hop`.
[Historical snapshot](https://collector.torproject.org/recent/relay-descriptors/consensuses/2026-10-14-21-00-00-consensus).
This is historical evidence, not a substitute for the live preflight/check-in.
Authorities can vote for names using generic consensus-parameter configuration;
absence today does not make future inclusion impossible. An unexpected active
state invalidates the affected observational interval and invokes the agreed
live-disable procedure.

## Measurement and interpretation

Use [capture-and-validate-playbook.md](capture-and-validate-playbook.md) for
counter definitions, window selection, queries, and the JSON/CSV/summary output.

- `T`: anonymous HS requests reaching the guard, including GET and POST.
  `R`: requests after the first on a circuit. `K`: circuits reaching their
  second HS request, counted once. `U`: requests whose previous hop is not
  known through the consensus/descriptor lookup.
- `R/T` and `U/T` describe observed predicates, not proven attack fractions or
  legitimate-client failure rates. Their overlap is not measured.
- `T/(T-R)` and `K/(T-R)` are secondary window-based proxies. Circuit histories
  cross boundaries; `T-R` may be zero with positive `T`, and `K/(T-R)` may
  exceed one. Undefined/missing/nonfinite results are null, never invented.
- Prespecify quiet-window rules, a sustained relative flood trigger with an
  absolute rate floor and HS-request corroboration, and episode-end criteria.
  Preserve representative episodes; peak-hour comparisons are secondary.
- Whole-relay bandwidth, CPU/RSS, handshake drops, and queue/OOM indicators
  measure operational effects. They do not isolate HS response delivery.
  HSDir OOM bytes describe reclaimed descriptor-cache memory.
- No qualifying flood is an inconclusive observation, not proof of no attack
  or that a defense is ineffective. One canary does not establish fleet-wide
  effects. Aggregate receipt rates do not identify individual users.

## Optional enforcement trial

The human approves a concrete schedule, tested helper, test fixture, mode order,
comparison durations, probe cadence, settling criteria, stop limits, and
rollback response before any live trial. A flood alert never enables a defense
automatically. Keep this binary throughout; do not turn both defenses on in the
initial trial.

| Phase | `HSDirRefuseUnknownPrevHop` | `HSDirOneRequestPerCircuit` |
|---|---:|---:|
| Comparison / live disable | 0 | 0 |
| Previous-hop defense only | 1 | 0 |
| Reuse defense only | 0 | 1 |

Send both values in one authenticated `SETCONF`, require successful reply,
query both with `GETCONF`, and record submission/verification times. Keep
observation `auto` separate from these explicit trial states. Changes or
reloads invalidate unverified state; never use `SAVECONF` to persist them.

Exclude the full rate lookback after every toggle (at least five minutes for
five-minute rates), plus a documented settling period supported by the data.
No fixed 30–60-second delay guarantees that prior circuits/queues have drained.
Old circuit history persists; disabling enforcement does not restore closed
circuits. Do not allow any analysis lookback to straddle a transition.

Compare matched windows under comparable flood conditions, with repeated
comparisons where safe. A quiet later week is not evidence of mitigation.
Changing enforcement changes which requests can reach the counters: circuit
closure prevents later requests and may interrupt a first response, while
retries/adaptation change demand. Report resource effects alongside the
predicates, not a reduction in predicates alone as prevented traffic.

Under continuous isolated reuse enforcement, `delta R` is an inferred count
of reuse-triggered circuit-close decisions, not a delivered-response metric.
`delta K` can miss closures on circuits already reused before the toggle.
Under isolated previous-hop enforcement, `delta U` counts 503-refusal decisions,
not delivered 503s. Combined-mode attribution is unresolved without overlap or
action telemetry and is outside the initial trial.

## Probe helper and client-impact evidence

The current [hsfetch.py](../engineering/tools/hsfetch.py) is a lab helper, not
an accepted measurement collector. Its future requirements and full acceptance
matrix are in [probe-helper-acceptance.md](probe-helper-acceptance.md).

Use a dedicated stock client, a valid descriptor belonging to an owned service
and known to be available on the canary, and one outstanding request. Measure
from submission using one monotonic overall deadline. Verify replies/events;
matching service/server alone does not distinguish late repeated requests.

On ambiguous timeout: record it, stop the batch, and reset only the dedicated
probe client before a new batch if needed. Do not wait forever for a terminal
event: 503 and circuit closure need not emit `HS_DESC FAILED`. Neither
ControlPort reconnection, `NEWNYM`, nor `CLOSECIRCUIT` is a guaranteed completed
cleanup acknowledgement. Test actual isolation and readiness after reset;
never restart the canary for probe recovery.

Probe results establish controlled descriptor receipt and latency, not general
application availability, upload success, or all legitimate users' experience.
`RECEIVED` can coexist with missing/bad client authorization. Handoff counters
would only measure an internal buffer transfer, so they are deliberately omitted.
Count timeouts in outcomes and report recovery gaps separately. Use the same
low-rate checks in the later comparison and active windows; initial collection
stays entirely passive.

## Reporting, privacy, and completion

Deliver the de-identified JSON, at most 40 CSV rows for the selected main flood
window, and a 6–10-line summary specified in the capture playbook. Include
baseline-only, inconclusive, aborted, missing-data, and unknown-state outcomes.
Separate observational evidence, controlled-client evidence, and inferred
enforcement decisions. Preserve exact private provenance and mode history.

Call the relay **canary**. Never return fingerprints, nicknames, addresses,
hostnames, ContactInfo, descriptor IDs, Prometheus job/instance labels or URLs,
or fleet counts. Keep raw source material private. Exact UTC times and traffic
patterns can be correlated: this is a private operator report, and publication
requires a separately redacted/coarsened copy.

At collection/trial end, leave the same binary running with inactive defenses
until instructed otherwise. Do not automatically unhold packages, remove the
drop-in, or roll back. Record a dated human review of the continuing maintenance
exception; an indefinite hold is not the default. Safety faults invoke the
pre-agreed incident procedure. These documents neither certify PR merge
readiness nor claim future helper tests or production checks have passed.
