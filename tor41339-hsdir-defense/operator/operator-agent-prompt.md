# Operator handoff: one canary, observe first, optional live trial

This is a future execution handoff, not authorization to run it now. The
current work is a documentation-only revision. A future instruction must name
which phase is authorized. Do not interpret a request to review/edit these
files as permission to build, install, restart, probe, schedule, or enforce.

## Read and establish scope

Read, in order:

1. [Final agreed plan](CANARY-MEASUREMENT-PLAN.md).
2. [Deployment and incident runbook](DEPLOY-AND-MEASURE.md), all sections.
3. [Counter/query/report contract](capture-and-validate-playbook.md), especially
   section 2.1 and the quality/interpretation limits.
4. [Crash review](patch-crash-at-scale-critique.md), including its addendum.
5. [Package evidence](../engineering/deb/README.md) and
   [BUILD-INFO.txt](../packages/BUILD-INFO.txt).
6. [Future probe requirements](probe-helper-acceptance.md) before any helper
   implementation, lab validation, or separately approved trial.

Write a private summary of at most ten lines: 0001/0002 predicates and four
counter meanings; GET and POST scope; full-seven-patch baseline; auto plus
absent consensus parameters; per-instance activation/restart cost; continuity
and quality checks; observation duration; trial approval and recovery rules.
If source/artifact/docs disagree, resolve the discrepancy before any dependent
runtime action. A historical review is not a fresh artifact/test attestation.

## Fixed rules

- Exactly one canary and one fixed seven-patch binary. No new C telemetry.
- No changes/restarts/reloads of other relays, no unqualified master-service
  operation, no host-wide package installation. Unpack to `/opt` and override
  only the canary instance. Record any explicitly agreed shared-host maintenance
  exception and preserve its previous state.
- Keep both new options out of torrc/includes/defaults so stock ExecStartPre
  remains usable. Preserve security confinement, normal memory limits, notice
  logging, SafeLogging, identity, and DataDirectory.
- Observation: inactive defenses, `auto` accepted with checked absent consensus
  parameters; verify runtime configuration and current valid consensus at every
  check-in. Unexpected activation invokes verified live disable under the
  agreed incident procedure and invalidates affected data.
- No synthetic traffic, probes, or enforcement during passive collection.
  No identity/payload logging or attempts to identify clients/services.
- Prometheus is read-only. Ask its authorized owner to resolve missing scrape
  support/retention; do not modify it yourself under that access grant.
- Counter reset checks supplement process/service/boot history and scrape
  coverage; zero observed resets alone does not prove uninterrupted uptime.
- Only later explicit authorization allows deployment, helper implementation
  and lab tests, or the bounded enforcement/probe trial. Flood detection never
  authorizes automatic enforcement.
- Outputs call the relay `canary` and omit all relay/service identifiers,
  descriptor IDs, Prometheus labels/URLs and fleet counts. Keep source data and
  configuration inventory private. Do not treat exact timing as public-safe.

## Future authorized deployment and collection

1. Complete the runbook's private preflight: exact build/digests, host/unit and
   confinement evidence, prior state/rollback inventory, shared maintenance
   scope, actual persistent monitoring, thresholds/responders, quality limits,
   retention/exports, duration and deadlines. No unset critical preflight
   fields may be papered over by a successful strings check.
2. Stage and validate the exact binary/configuration. Inspect loaded systemd
   state as well as source files; do not assume last-text-line or filename
   precedence. Restart only the canary once. Verify ready process, executable,
   confinement, correct identity/configuration, four fresh unique counters,
   and inactive defenses. Send deployment check-in 1 without identifiers.
3. Monitor from startup. Observe HSDir recovery using fresh accepted consensus;
   report first-observed time and uncertainty, supported restart status, and
   inactive mode in check-in 2. At the recovery deadline without a flag, report
   and await the human's extension decision; no automatic restart.
4. Collect the selected 7–14 usable HSDir days (proposed default 14), excluding
   warmup/unusable gaps, with an absolute wall-clock deadline. Daily summaries
   supplement continuous incident alerts and scheduled state/coverage checks.
   Preserve multiple quiet/flood episodes under predeclared selection rules.
   Keep 30 days or private exports; fifteen days may expire before completion.
5. Deliver check-in 3 using the capture playbook's JSON + <=40-row CSV +
   6–10-line summary, including baseline-only/inconclusive/aborted outcomes and
   all gaps. Do not claim prevented bytes, client success, or causal benefit
   solely from request-predicate fractions.
6. The human reviews and chooses continuation, completion, or a separate trial.
   Leave the binary running with inactive defenses and the agreed maintenance
   review date. Do not automatically remove holds/drop-ins or roll back.

## Future optional trial

Before approval, the helper must actually be implemented and pass the future
mock-protocol and isolated stock-Tor lab checks. The specification is not a
passing test result. Use only a dedicated probe client, an owned descriptor
known available on the canary, verified no-fallback behavior, explicit low
cadence, bounded attempt/batch/recovery budgets, and a private outcome ledger.

Use explicit two-option SETCONF phases, verify GETCONF, and record submission
and verification timestamps: comparison `(prev-hop=0,reuse=0)`, previous-hop
only `(1,0)`, or reuse only `(0,1)`. Test one defense at a time. Never edit torrc,
SIGHUP, SAVECONF, or restart the canary for phase transitions. No implicit
combined-defense trial.

Exclude the full rate lookback and documented settling period after a toggle;
30–60 seconds does not prove clean steady state. Compare matched attack
conditions, including controlled probes before and during enforcement. Report
R as inferred close decisions only in continuously reuse-enforcing windows,
U as inferred 503-refusal decisions only with previous-hop-only enforcement;
K can miss decisions involving already reused circuits. Same counter code does
not mean unchanged offered traffic after enforcement.

Probe deadlines start before submission. Match events without pretending they
contain a per-request nonce. Record any timeout/non-success and stop the batch;
reset only the dedicated probe process before a fresh batch when required.
Neither reconnect, NEWNYM, CLOSECIRCUIT nor awaiting a missing HS_DESC terminal
is a proven cancellation barrier. Preserve failures in denominators and
recovery gaps separately. Never reset the canary for helper recovery.

On enforcement-related trouble, live-disable both defenses and verify; use
binary rollback only under the service-failure procedure. Return to verified
`0,0` at trial end and report controlled descriptor receipt/latency, resource
outcomes, uncertainty, and limitations. Receipt does not establish onion
application availability, uploads, or every legitimate client's experience.
