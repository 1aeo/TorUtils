# Operator handoff: native 26.04 pilot, half-host cohort, optional live trial

This is a future execution handoff, not authorization to run it now. The current
request authorizes documentation edits and commit/push only. A later runtime
instruction must identify the authorized phase and roster. Another agent owns
the native Ubuntu 26.04 build and its repository delivery. Do not build,
install, restart, probe, schedule, or enforce merely because these files exist.

## Read and establish scope

Read, in order:

1. [Final agreed plan](CANARY-MEASUREMENT-PLAN.md).
2. [Native artifact handoff](NATIVE-26.04-BUILD-HANDOFF.md) and the actual
   builder-delivered manifest/provenance/evidence when available.
3. [Deployment and incident runbook](DEPLOY-AND-MEASURE.md), all sections.
4. [Counter/query/cohort report contract](capture-and-validate-playbook.md),
   especially section 2.1 and stock-versus-patched metric requirements.
5. [Crash review](patch-crash-at-scale-critique.md), including its addendum,
   and [historical package evidence](../engineering/deb/README.md). Historical
   Noble tests do not validate the new native 26.04 artifact.
6. [Future probe requirements](probe-helper-acceptance.md) before any separately
   authorized helper implementation, lab validation, or live probe trial.

Write a private summary of at most ten lines: the two predicates and four
counter meanings; GET/POST scope; native artifact freeze; one pilot then half;
stock and patched-off controls; initial auto with absent consensus parameters;
per-member restart/recovery; observation/quality rules; human trial decision;
probe recovery/privacy limits. Resolve source/artifact/docs discrepancies before
dependent runtime work. Do not call a build or test passed without evidence.

## Fixed rules

- Host scope: **vipopen**, Ubuntu 26.04 amd64. Freeze the private roster N;
  one pilot first, then approved small batches to **floor(N/2), including the
  pilot**. Retain stock references among unchanged relays. No silent roster
  expansion/replacement or changes to other hosts.
- Use one builder-delivered, reviewed native Ubuntu 26.04 Tor 0.4.9.14 artifact
  with the seven patches and four counters unchanged. No new C telemetry.
  Do not deploy the historical Noble package as an unapproved fallback.
- No master-service/wildcard operation or host-wide package installation.
  Stage once to `/opt`, verify and freeze the executable, then switch each
  selected instance separately. One planned restart per converted member;
  none for stock references. Do not overwrite the staged binary after pilot use.
- Preserve per-instance identities, DataDirectories, allocators, normal memory
  limits and security confinement. Capture rollback state and explicitly scope
  host-wide maintenance exceptions. Keep new options out of torrc/includes/
  defaults so stock ExecStartPre and rollback configuration remain usable.
- Initial observation is inactive: `auto` is accepted only with verified
  runtime state and absent parameters in current accepted consensus. Check
  each patched member, not just the pilot. An unexpected active state invokes
  verified live disable under the incident policy and invalidates affected data.
- Stock references have no new counters/options. Missing T/R/K/U on stock is
  structural unavailability, not zero or a patched-telemetry failure. Do not
  send new GETCONF/SETCONF options to stock binaries.
- All four traffic counters come from **MetricsPort**. Prometheus scrapes
  them; the future collector reads its API for history. ControlPort GETCONF is
  for mode verification and SETCONF only for approved transitions.
- Initial collection is passive: no load generation, probes, automatic
  enforcement, identity tracking or payload logging. Keep notice/SafeLogging.
- Prometheus remains read-only for this agent unless the operator authorizes
  its owner to make the specific collection change. Use exact-target 15s/10s
  overrides for the approved comparison targets, including stock references;
  preserve job/instance labels and static groups, and avoid duplicate jobs.
- Validate per-member metric identity, cadence, coverage, freshness and process/
  service/boot continuity. `resets()=0` alone is not proof of uninterrupted uptime.
- Human review controls expansion scope and later trial decisions. Pilot-only
  authorization is not authorization to expand; within an approved batch plan,
  routine verified steps need no extra confirmation per instance. A flood alert
  never enables a defense automatically.
- Use stable opaque IDs (`pilot`, `patched_01`, `stock_01`) and private mappings.
  The selected host alias is a design scope identifier; operational outputs
  omit relay/service identities, addresses, descriptors, endpoints/labels,
  credentials and total host/fleet inventory counts. Exact timing is not
  automatically safe for public redistribution.

## Future authorized preparation, rollout, and observation

1. Wait for the other agent's native artifact and actual evidence. Record the
   accepted source/build/package identity and both package/executable hashes;
   do not invent a filename or treat an artifact upload as a passing test.
2. Complete private preflight: fixed pilot/expansion/stock-reference roster,
   pretreatment matching and group assignments, privilege/control paths,
   loaded unit/configuration and confinement evidence, maintenance restoration,
   per-member and host thresholds, capacity floor, batch gates, monitoring
   ownership, aggregate scrape capacity, quality/retention/export rules, and
   per-member plus absolute study deadlines. Arrange real persistent monitoring.
3. Stage and verify the immutable native build. Validate exact pilot startup
   configuration and stock pre-start verification; restart only the pilot.
   Verify process, binary, confinement, identity/configuration, required metrics
   and inactive mode. Send the de-identified pilot check-in.
4. Review the pilot against declared startup/ordinary-load gates. It has not
   demonstrated flood stability while waiting for HSDir. Under later approved
   bounded expansion, convert the remaining selected patched members in small
   sequential batches, verify each, and stop further expansion on a failed
   per-member or host gate. Keep the same binary and stock reference processes.
5. Monitor each member from its own T0 and observe flag recovery using fresh
   accepted consensus. Historical HSDir eligibility can support an explicitly
   approved member currently recovering from restart; swapping starts its new
   ~96-hour gate. Report first-observed flag time/uncertainty and supported
   restart status. At its recovery deadline, report rather than restart or
   extend automatically. Do not align every relay to the pilot's recovery clock.
6. Gather the chosen 7–14 usable HSDir days per patched member (proposed default
   14) plus common-time control observations. Warmup/failed-quality intervals
   do not count; valid zero traffic does. Preserve multiple episodes and quiet
   periods, missing exposure and incomplete members. Maintain >=30 days or
   exports through the last member's review/trial; a daily summary does not
   replace continuous incident alerts.
7. Deliver the capture playbook's schema-v2 cohort JSON, combined <=40-row CSV,
   and 6–10-line summary. Separate per-member data, stock/full-build comparisons,
   and later patched-off/on results. Preserve heterogeneity; pool numerators and
   denominators only over compatible nonoverlapping windows, not a mean of
   ratios. Missing stock HS counters stay null.
8. The human reviews and chooses continuation, completion, or a bounded trial.
   Leave every patched member running inactive pending instruction; no automatic
   removal/unhold/rollback or conversion of stock references. Keep a dated
   maintenance review and security-maintenance exception.

## Future optional trial

The external helper must first be implemented and pass its mock-protocol and
isolated stock-Tor lab acceptance tests under separate authorization. No C
changes are needed. Use dedicated stock clients, owned valid fixtures on the
assigned targets, disabled automatic fallback, explicit low **aggregate**
probe cadence/budget, bounded setup/attempt/batch/recovery limits, and private
outcome ledgers. One target per batch and one outstanding fetch per client
across all targets; a pending/aborted batch cannot be escaped by switching target.

Retain a contemporaneous **patched-off control group** during every treatment
block. Choose matched assignments using pretreatment data, with randomization
where practical. Stock references supply context, not an isolated estimate of
a toggle's effect. Do not turn on the whole patched cohort at once. If the
roster cannot support both patched groups, revise the trial before proceeding.

Use explicit two-option SETCONF on each assigned patched member, then verify
GETCONF and record UTC submission/verification times: comparison `(0,0)`,
previous-hop only `(1,0)`, or reuse only `(0,1)`, in `(prev-hop,reuse)` order.
Test one defense at a time. No torrc edits, SIGHUP, SAVECONF or restarts for mode
changes. No new-option commands on stock or implicit combined-defense trial.

Exclude the full rate lookback plus documented settling for each member; a
30–60-second pause does not establish steady state. Compare predeclared matched
time blocks, preserve unequal HSDir exposure, and account for shared host
CPU/RAM/network pressure and spillover benefits to controls. A later crossover
needs its own carryover assumptions; disabled rules do not restore closed
circuits. Same-host members are not independent-host replications.

Under continuous isolated reuse enforcement, report delta R as inferred close
decisions; K can miss circuits reused before the toggle. With previous-hop-only
enforcement, delta U counts 503-refusal decisions, not delivered responses.
Combined-mode attribution lacks overlap telemetry. Enforcement changes which
future requests reach the counters; lower traffic alone is not prevented work.

Probe deadlines start before submission. Match available context without
inventing a request nonce. Retain failures/timeouts in denominators, abort
non-success/ambiguous batches, and verify reset/readiness of only the dedicated
probe client before recovery. Reconnect, NEWNYM, CLOSECIRCUIT or waiting for a
missing terminal event does not prove cleanup. Never reset any relay for a
helper problem. Report recovery gaps and latency conditional on receipt.

On enforcement trouble, verified live-disable the affected patched treatment
and pause the trial/expansion under the agreed incident scope. Binary rollback
is per-instance and only where required. A single-member rollback must not
release shared maintenance protections or remove the staged binary required by
remaining patched members. Restore shared state only after its dependencies
end and the operator authorizes it. At trial end return all patched trial
members to verified `0,0`, report per-member/matched resource and controlled
receipt outcomes with limitations, and hand back the continuation decision.
Receipt does not establish uploads, application availability, every legitimate
client's experience, or an independent-host effect.
