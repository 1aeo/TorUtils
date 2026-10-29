# vipopen pilot, staged half-host rollout, and optional controlled trial

> **On `+tor41339.7`:** there is no `tor_relay_dos_total{type="hsdir_request_total"}`, the counter this document calls T: it equals `tor_relay_hsdir_fetch_total` plus `tor_relay_hsdir_upload_total`, less their `single_hop` and `circuit_dead` actions, so the binary also has three of the four counter names checked below. `../analysis/v7-review.md` maps the other renamed metrics.

> **On `+tor41339.8` (tor 0.4.9.15):** `HSDirOneRequestPerCircuit` is gone, and so are the counters `hsdir_req_reused` and `hsdir_circ_reused`. Tor 0.4.9.15 always closes a circuit at its second onion service request, and counts that request as `tor_relay_dos_total{type="begindir_hsdir_rejected"}`; requests still queued on that circuit are dropped unread, as `tor_relay_begindir_request_total{type="circuit_dead"}`. A `SETCONF` or `GETCONF` that names `HSDirOneRequestPerCircuit` fails on `.8`: leave it out, and treat reuse-only modes as not applicable.

**Status: approved design documentation, not execution authorization.** The
current update changes documents only. Do not build, install, restart, probe,
schedule jobs, or enable enforcement until the human explicitly authorizes the
relevant phase. Start with [the final plan](CANARY-MEASUREMENT-PLAN.md).

Keep patches 0001–0007 and all four existing counters unchanged. The accepted
baseline is the full patched build with the two optional defenses inactive;
0003–0007 still change logging, buffering, validation order, and cache accounting.
Do not describe the full package as behaviorally identical to stock. One pinned
**native Ubuntu 26.04** binary serves every patched member through
observation and any later trial, avoiding a second planned restart per member.
Another agent builds and pushes that artifact; follow
[the build handoff](NATIVE-26.04-BUILD-HANDOFF.md). This documentation task does
not build or deploy it. Begin with one pilot on vipopen, then expand in small
approved batches toward half its relays, including the pilot. Retain stock
references and contemporaneous patched-off controls for later enforcement.
The objective is improved **efficiency and legitimate-client outcomes within
the measured scope**, not recovery from assumed overload. The operator's
comparative snapshots show elevated directory traffic without demonstrated
exceptional CPU/RSS pressure or queue growth; see the final plan's evidence
section. They do not measure the flood's incremental cost or prove no harm.

Read the README, this entire runbook, the
[capture playbook](capture-and-validate-playbook.md), the addendum and evidence
in [the crash review](patch-crash-at-scale-critique.md), and
[package provenance](../engineering/deb/README.md). Historical reviews and lab
results are evidence, not proof of production safety or PR release readiness.

## 0. Private preflight and the HSDir recovery cost

A process restart resets self-reported uptime. Budget about 96 hours before
HSDir eligibility returns, with further consensus/distribution delay possible.
Other eligibility conditions still apply; the flag and traffic do not return on
a guaranteed schedule. Preserve keys and DataDirectory. Normal client selection
follows consensus/ring state, but the flag is not a firewall: requests and
nonzero counters before recovery are possible.

Prepare a private manifest before any host mutation:

| Required item | Evidence / decision |
|---|---|
| Scope and identity | Frozen private vipopen roster; one pilot, planned patched target floor(N/2) including it, retained stock references; per-member unit/config/user/DataDirectory/ports/auth and stable opaque ID; no inventory counts in shared reports |
| Artifact | Builder-delivered native Ubuntu 26.04 amd64 artifact; actual filename/version, source/patch hashes, package and binary SHA256, lab evidence; same frozen build for all patched members |
| Service | Loaded ExecStart and ExecStartPre, source files/drop-ins, environment/specifiers, dependencies/PartOf, stop/start/restart policy, pending manager reloads |
| Confinement | Existing AppArmor profile/attachment, seccomp/Sandbox and other unit security settings; how the `/opt` path preserves them |
| Maintenance | Existing holds/exclusions and contents, upgrades/reboot timers and external automation; shared changes explicitly scoped; review/expiry date and emergency security-maintenance exception |
| Monitoring | Persistent scraper, scheduled read-only checker, existing incident alert path, operator/backup owner, coverage during recovery and observation |
| Baseline | Synchronized main-thread CPU where available, total/worker CPU, RSS and traffic; exact windows, units and sources; process totals cannot silently substitute for main-thread measurements |
| Thresholds | Per-member and host-level sustained limits, serving-capacity floor, batch size/review gates, responder, live-disable/per-instance rollback triggers; expected flood load alone is not failure |
| Data quality | Scrape interval, required series/sources, uniqueness, freshness, coverage/gap limits and restart evidence; distinguish unavailable thread/client evidence from observed zero |
| Trial interpretation | Preregister minimum worthwhile efficiency/useful-service gain, allowable controlled-client impact, precision/exposure and stopping rules; benefit/no_detectable_benefit/regression/inconclusive are permitted outcomes |
| Timing | Selected 7–14 usable days per patched member, per-member T0/flag deadline, common-time comparison exposure, absolute study end/extension policy and postexperiment review |
| Retention | At least 30 days or private daily/window exports; owner handles any Prometheus configuration change |
| Rollback | Original loaded binary/command/config and backed-up changed files; exact restoration plan; no blanket unhold or deletion of pre-existing files |

Proposed defaults: 14 usable days per patched member, a flag-recovery review
at each member's T0 + 7 days, state/health/coverage checks every five minutes, daily human summaries, and
HSDir checks every few hours from T0 + 90 hours. Continuous crash/service alerts
come from the monitoring system, not the daily summary. Record selected values
and available coverage before deployment. Match proposed control assignments
using prior traffic, role and capacity; randomize within comparable candidates where practical.
Do not choose controls based on traffic already affected by enforcement. If
defaults are unsuitable, choose and document replacements. Unset health thresholds or unowned incident alerts
must be resolved before deployment, not improvised during a flood.

Prometheus access is **read-only**. Missing retention/scrape/allowlist support
requires its authorized owner's change or an approved private export path.
Do not silently change Prometheus configuration. No monitor is created by this
runbook; a persistent scheduler/collector must actually be arranged before the
one restart. Codex handles collection/analysis, the human reviews and decides
whether to continue or trial a defense.

Host-wide holds, shared security-profile changes, and automatic reboot policy
are shared-host changes even when restart operations are per-instance. The
selected host is vipopen; include those narrow shared exceptions in the later
deployment authorization. Only the approved patched roster may be converted,
and only after the pilot/batch gates. Retained stock references and other
relays are not changed, restarted or reloaded. Never operate on the unqualified
master `tor` service or use a wildcard restart.

Current HSDir status is preferred, but an operator may select a healthy member
with verified recent HSDir history that is recovering from a restart. Record
that exception; swapping now starts a new uptime gate rather than requiring
recovery first and immediately resetting it again. Initial pilot validation
while ineligible proves startup/ordinary-load behavior, not flood stability.
Any expansion before a flood must explicitly accept that remaining uncertainty.

## 1. Pin and stage the binary (after deployment authorization)

### Path A — unpack the existing package to `/opt`

The selected artifact is the **native Ubuntu 26.04 amd64 package to be
published by the designated builder agent**. Its version, filename, manifest
and test evidence are pending until actually delivered and reviewed. Obtain
these exact values from [the build handoff](NATIVE-26.04-BUILD-HANDOFF.md), not
from the old Noble example. Historical Noble artifacts are not an automatic
fallback for this revised plan.

Before staging, pin package/source/patch/executable digests and review native
lab evidence. Checksums from the same checkout detect corruption; they do not
independently authenticate a build. A strings check proves names are present,
not correct behavior or successful scraping.

The following are future operator steps, not executed by this update. The two
variables must be populated from the **reviewed native artifact manifest**:

```bash
: "${APPROVED_PACKAGE_PATH:?set the reviewed native 26.04 artifact path}"
: "${APPROVED_CHECKSUM_MANIFEST:?set its reviewed checksum manifest}"
sha256sum -c --ignore-missing "$APPROVED_CHECKSUM_MANIFEST"
# REQUIRE the selected .deb entry to be present and OK, not merely exit 0.
# REQUIRE /opt/tor41339 to be an approved new destination for this frozen build.
sudo mkdir -p /opt/tor41339
sudo dpkg-deb -x "$APPROVED_PACKAGE_PATH" /opt/tor41339
/opt/tor41339/usr/bin/tor --version
strings /opt/tor41339/usr/bin/tor | grep -c '^hsdir_\(circ_reused\|req_reused\|request_total\|unknown_prev_hop\)$'
# Expected: 4. Check the extracted executable against its reviewed SHA256.
```

Stage once, with root ownership and no relay-account write access. All approved
patched members reference this same immutable executable. Never unpack over or
replace it after the pilot has started; verify the hash before each expansion
batch. Unpacking runs no maintainer scripts. Keep `/usr/bin/tor` and the
installed stock package in place. `tor-geoipdb` is not needed for the swap.
**No host-wide package installation is part of this experiment.**

### Path B — builder handoff, not an operator-side fallback build

The other agent owns the native package build and its actual validation
results. This task changes documentation only. A missing/failed artifact means
wait for that handoff, not build on the relay, substitute the Noble package, or
change C code. If a corrected artifact is later required, freeze expansion and
review its impact on comparability before replacing any running member.

### 1.1 Switch one authorized instance at a time

This procedure applies first to the pilot and later to each specifically
approved expansion member. `CANARY` means that one member, never an entire
cohort. Each converted member has one planned restart; stock members have none.
The binary is staged once in section 1, not re-extracted for each instance.

All names below are placeholders. Substitute from the private manifest;
`tor@default` and named instances use different defaults/config paths.

1. **Prepare maintenance protections.** Capture current `apt-mark showhold`,
   needrestart configuration, reboot schedules, and any external maintenance.
   Only after the shared scope is agreed, hold `tor` (and `tor-geoipdb` if needed
   by the host's maintenance workflow), add a canary-specific needrestart
   exclusion, and arrange the bounded reboot exception. Do not overwrite a
   pre-existing exclusion file. Do not rely on a grep of one apt setting as
   proof that no reboot mechanism exists. Preserve prior state for restoration.
   Example exclusion syntax, with the at-sign escaped:

   ```perl
   $nrconf{override_rc}{qr(^tor\@CANARY\.service$)} = 0;
   ```

2. **Read source and loaded unit state.** Use `systemctl cat tor@CANARY` and
   `systemctl show tor@CANARY` (relevant properties in the preflight table).
   The last textual `ExecStart=` is not by itself authoritative, and a `zz-`
   filename does not guarantee final precedence. Resolve reset directives,
   specifiers, environment, wrappers, and all drop-ins. Preserve the exact
   effective invocation with only the selected Tor executable changed. If a
   wrapper or custom unit prevents that, resolve it before the restart.

3. **Prepare the per-instance drop-in and confinement.** Example for a verified
   stock *named* instance only:

   ```ini
   [Service]
   ExecStart=
   ExecStart=/opt/tor41339/usr/bin/tor --defaults-torrc /run/tor-instances/%i.defaults -f /etc/tor/instances/%i/torrc
   ```

   A default instance normally uses
   `/usr/share/tor/tor-service-defaults-torrc -f /etc/tor/torrc --RunAsDaemon 0`;
   derive the real command instead of copying the named-instance example.
   Back up any existing destination file. AppArmor can attach by executable
   path even without `AppArmorProfile=` in the unit. Verify that moving to
   `/opt` preserves the profile; review any necessary shared profile change
   before applying it. Do not disable Sandbox/AppArmor to make startup pass.

4. **Validate before the single restart.** Run the patched binary's
   `--verify-config` with the exact resolved defaults, torrc, options, and
   environment required for this instance; require success and
   `Configuration was valid`. Check that the retained stock ExecStartPre also
   accepts the unchanged configuration. Apply `systemctl daemon-reload` only
   after accounting for other pending manager changes, then verify the
   manager's loaded ExecStart/ExecStartPre and security properties. A manager
   reload is not a service restart, but it reads unit changes host-wide.

5. **Perform this member's one authorized restart of `tor@CANARY` only.** Record the
   command's UTC start/end, old/new PID, new process start time, service
   activation/invocation and host boot evidence privately. Require active/ready
   service and `/proc/<new-pid>/exe` resolving to the staged binary. Compare
   effective confinement (including `/proc/<pid>/attr/current` where available),
   configuration identity, user, and data directory to preflight. T0 is the
   new process start timestamp; report command/restart duration separately.

Do not put either new option in torrc, included files, or stock defaults.
The stock verifier rejects those unknown options. Preserve notice logging,
SafeLogging, MetricsPort restrictions, normal `MaxMemInQueues`, and restart
policy. A process path match alone is not sufficient proof of correct startup.

A graceful stop often takes about 30 seconds. With pre-existing tor#41060 under
Sandbox 1, the old process may remain until TimeoutStopSec and be killed.
Record the observed behavior and startup outcome; do not treat these historical
30/60-second examples as guaranteed limits or turn off sandboxing.

### 1.2 Pilot review and bounded expansion toward half

Freeze private N and the approved roster before rollout; the planned patched
population is floor(N/2), including the pilot. Choose opaque IDs and a matched
stock-reference subset from the remaining unchanged relays. Do not publish
inventory counts or silently replace excluded/failed members.

After the pilot's check-in, review startup, configuration, confinement,
allocator, per-process/host health and telemetry against the declared gates.
Pilot-only authorization does not include expansion. Once the operator approves
bounded expansion, repeat section 1.1 **sequentially within small batches** for
only that roster, preserving the same artifact and inactive controls. Record
each member's T0 and results, check the serving-capacity floor and host pressure
between batches, and pause on an incident or failed gate. Do not restart half
the host simultaneously. Routine progress within the approved batch plan does
not require a new permission request for every instance.

An ordinary-load pilot while waiting for HSDir has not tested the flood path.
Record the operator's decision about that residual uncertainty if expansion
precedes a flood. Track recovery/eligible observation per member. Stock
references continue their existing processes and supply common metrics; they
will not expose the four new counters or accept the new ControlPort options.

## 2. Initial observe mode

Leave both options omitted so the patched runtime normally reports `auto`.
Initial `auto` is accepted if the canary's current validated consensus lacks
`hsdir_one_request_per_circ` and `hsdir_refuse_unknown_prev_hop` and no runtime
or configuration override enables either defense. All four counters remain
active regardless of enforcement on patched members. Apply these checks per
patched member; do not query/set the new options on stock reference binaries.

The public 2026-10-14 21:00 UTC consensus lacked both parameters (fetched at
21:49 UTC). This is a dated observation, not a permanent guarantee. Recheck the
canary's actual consensus and effective options before restart where possible,
immediately after startup, and at every scheduled check-in. Authorities can
vote for new parameter names without running this patch's relay code.

No synthetic load, controlled-client probes, or enforcement is part of the
initial passive phase. Do not use `SAVECONF`, and do not change log verbosity to
infer enforcement. Logs at notice omit the protocol-warning enforcement lines.

## 3. Verify the running canary and check in

Use an authenticated, timeout-bounded ControlPort client. Do not expose the
port, print credentials, or treat a failed query as a passing check. Inspect:

```text
GETCONF HSDirOneRequestPerCircuit HSDirRefuseUnknownPrevHop
```

Require successful replies and the expected values. Inspect the full effective
configuration (including includes/defaults/command-line inputs) rather than
only grepping the top-level torrc. Verify the current locally accepted consensus
is readable and time-valid, and parse the exact parameter names from its
`params` line. Missing files, failed authentication, an expired consensus, or
empty command output are unknown evidence, not proof of inactive defenses.

Initial expectation is both `auto`, neither parameter present. If a parameter
appears or values change, resolve the effective state before accepting further
observation windows. Within the authorized incident procedure, an unexpected
active/uncertain enforcement state is made explicitly inactive using:

```text
SETCONF HSDirRefuseUnknownPrevHop=0 HSDirOneRequestPerCircuit=0
GETCONF HSDirRefuseUnknownPrevHop HSDirOneRequestPerCircuit
```

Record reply/verification, time, reason, and the potentially contaminated
interval. A value of `0` is a valid explicit-off state, not a failed `auto`
check. Report it accurately. If control verification fails, escalate through
the health/incident procedure; do not continue claiming known-off behavior.
Runtime changes can be lost on reload/restart, so revalidate after either.

Check local MetricsPort and Prometheus for exactly one fresh series of each:

- `hsdir_circ_reused`
- `hsdir_req_reused`
- `hsdir_request_total`
- `hsdir_unknown_prev_hop`

Also validate all supporting metrics, per-process resources, label selection,
scrape interval and retention. Do not mistake duplicates plus missing types for
four correct series. A scrape problem is investigated separately from a missing
counter at the local MetricsPort; neither permits unapproved Prometheus edits.
The regular DoS heartbeat is supplementary evidence of counter availability;
its scheduling is not the primary verification or enforcement-state check.

**Check-in 1 (pilot, then each expansion batch):** stable opaque member IDs,
completed/pending roster state, each T0 UTC, package/build identity, effective command stock/custom,
verification success, PID changed, correct executable and confinement, four
fresh counters, expected inactive mode, Sandbox state, restart duration, and
exceptions. Share no private unit names or identifying command arguments.

Monitor each converted member from its own T0. From roughly T0 + 90 hours,
inspect that member's entry in a
fresh accepted consensus every few hours. The matching `s` line must contain
HSDir. Record the last observation without HSDir, first observation with it,
and the consensus valid-after/valid-until times. `T_flag` is the first observed
flag time, not a claimed exact authority transition. Check continuity using
process/boot/service history and scrape gaps in addition to `resets()`.

**Check-in 2:** observed hours from T0 to flag, timestamp uncertainty, restart
status (0 only if supported, otherwise unknown), data gaps and inactive mode.
At the predeclared recovery deadline without the flag, stop the automatic wait
and report; the human decides whether to extend. Do not restart to try to
accelerate eligibility.

## 4. Collect 7–14 usable HSDir days per patched member

The human selects the duration before deployment (proposed default 14 days
per patched member). Do not include each member's warmup or unusable gaps.
Valid zero traffic counts as observation. Record wall time, usable time and
common-time comparison exposure separately, and honor the absolute end/extension
policy. Collect multiple quiet/flood episodes; do not stop at the first peak.
Stock references are observed continuously using common metrics without restart;
their missing custom counters are structurally unavailable, not zero or a
failed patched-counter check. Keep individual outcomes, including incomplete
members, and do not hide heterogeneity behind a cohort average.

### 4.1 Prometheus and persistent monitoring

Use the existing private scrape routes and per-member canonical selectors.
The four new counters are emitted by Tor **MetricsPort**; Prometheus stores
those samples and the future collector queries its API for history/exports.
GETCONF checks configuration state only; it is not a traffic-metric source.
Preserve restrictions; never expose MetricsPort publicly or use `accept *`.

Arrange a target-specific **15-second interval / 10-second timeout** for every
approved comparison target, including selected stock references, through the
monitoring owner's authorized path. Existing 2-minute samples cannot be made
15-second samples by polling the query API more often. The read-only preflight
found support for two exact-address relabel overrides of `__scrape_interval__`
and `__scrape_timeout__` in the existing job. Preserve the current static group,
job/instance labels and single target occurrence; do not create a duplicate job
or split a group required by the target-sync tool. Validate only intended
roster members match. Assess aggregate scrape cost as the roster grows; one
pilot's short scrape duration does not prove capacity for half-host collection.

If owner-side changes are required, arrange them before the applicable rollout
stage. Keep at least 30 days or export validated daily/window data before expiry,
extending preservation through the last member's observation/review/trial.
Exports are private, dated, include query/provenance and gaps, and are never
silently overwritten. Raw data is not copied into a shared report.

Use persistent health alerts plus the scheduled state/coverage checker and
human summaries. No healthy daily summary substitutes for overnight incident
coverage. Compare resource pressure against predeclared sustained limits;
expected higher flood load is an observation, not an automatic rollback.

Select baseline/flood windows using the preregistered rules in the
[capture playbook](capture-and-validate-playbook.md). Preserve no-baseline,
no-flood, aborted and missing-data outcomes. A week without a qualifying flood
is not proof that the flood does not exist or that defenses have no effect.

## 5. Observation report and human decision

Produce the private de-identified cohort JSON, combined <=40-row CSV with
opaque member IDs, and 6–10-line summary in the capture playbook. Include
per-member build/mode/coverage and matched comparisons. Separate stock versus
patched-off (full build) from patched-off versus patched-on (incremental
rule). Preserve individual observation coverage/episode history;
peak-hour contrasts are explicitly secondary. No guessed values or hidden
failures. Per-window estimates cannot establish unobserved attack traffic,
legitimate-client failure rates, or causal resource savings.

**Check-in 3:** observation report. Describe measured resource pressure rather
than inferring overload from BEGIN_DIR or asymmetry. High CPU common to peers,
large baseline RSS or fewer transferred bytes do not establish an attack cost.
Preserve client-impact evidence gaps and uncertainty. The human chooses
continued observation,
collection completion, or a separately approved bounded trial. High `R/T` or
`U/T` alone never automatically enables a defense. If both are low, report weak
evidence for these predicates rather than forcing an enforcement experiment.

## 6. Live disable, incident rollback, and end-of-study handoff

Distinguish three actions:

1. **Enforcement trouble:** apply explicit `0,0` through SETCONF and verify
   GETCONF. No binary swap or planned restart; keep metrics running. Record the
   incident and pause the active cohort trial/expansion. Preserve verified
   patched-off controls; any broader shutdown/rollback follows the approved
   incident scope. This disables only the two defenses,
   not patches 0003–0007, and is not a claim of restored stock behavior.
2. **Binary/startup/service failure:** follow the authorized incident policy.
   Restore the exact prior per-instance ExecStart/drop-in/configuration and
   confinement from the manifest, reload manager configuration, and restart
   only the canary. Verify active service and the original executable. This
   costs a new uptime/HSDir interval; safety takes precedence. Preserve incident
   evidence privately and report the interruption.
3. **Normal collection completion:** leave each patched member on the same
   binary with inactive defenses until instructed otherwise. Do not convert
   or restart stock references as cleanup. Do not automatically remove
   the drop-in, unhold packages, remove exclusions, or restart. Schedule the
   agreed dated human maintenance review; do not leave exceptions unowned.

A per-member rollback restores only that member's instance changes. Track
shared-state ownership and dependencies in the private roster: the host-wide
package hold/reboot exception, shared profile changes and staged immutable
binary must remain while any active patched member still depends on them.
Do not unhold, restore shared policy, or remove the binary merely because one
member was rolled back.

Only when no active member depends on a shared experiment change **and the
operator authorizes its restoration**, restore the previous shared state:
unhold only packages newly held for this experiment, preserve earlier holds,
restore modified files, and remove only experiment-created files. Retain any
still-needed per-member exclusion. Verify both per-member and shared-state
restoration before declaring the applicable removal complete.
Binary rollback always needs a process restart; SIGHUP never changes the binary.
Security maintenance can supersede the experiment; report an interrupted run
rather than suppressing required maintenance indefinitely.

## 7. Privacy and output boundary

Use stable opaque member IDs such as `pilot`, `patched_01` and `stock_01`,
with the identity mapping kept private. The plan explicitly names vipopen as
its authorized host scope; operational reports must not add host identifiers.
No relay fingerprints, nicknames, IPs, hostnames,
ContactInfo, onion addresses, descriptor IDs, Prometheus job/instance labels or
URLs, or fleet counts in any shared check-in/report. Keep keys, auth material,
source labels and exact private service/configuration inventory out of tool
output intended for sharing. Keep raw captures in an access-restricted operator
location; no per-request payload or identity logging.

Exact timing and traffic patterns may be correlated with public information.
The agreed detailed UTC report is private to the operator; a public release
requires separate coarsening/redaction. Probe identifiers and raw controller
output are also private and must be sanitized before summaries.

## 8. Optional enforcement trial — separate human approval

First implement and validate the external helper against
[probe-helper-acceptance.md](probe-helper-acceptance.md), under separate work
authorization. The helper and acceptance suite are not implemented or executed
by this documentation change. The original passive phase remains probe-free.

The human approves matched patched-member assignments, the tested helper,
dedicated stock clients, owned descriptor fixtures for each assigned target,
explicit aggregate low probe cadence/budget, matched off/on time blocks, phase
order, settling criteria, per-member/host incident limits and trial end.
Retain a contemporaneous **patched-off control group** in every active block;
never enable every patched member together. Record the efficiency and
controlled-client endpoints, minimum meaningful gain, unacceptable harm,
required exposure/precision and stopping criteria before looking at treatment
results. No detectable benefit or regression is a valid result; do not change
windows, members or duration merely to obtain an improvement. Match using
pretreatment evidence
and randomize within comparable candidates where practical. Stock references
remain useful context but do not isolate a toggle's effect. Run comparable
low-rate checks in the trial's patched-off and active windows, one target per
batch and one outstanding fetch per client across all targets. Do not use an arbitrary service's
404 as evidence of enforcement damage. Do not probe other HSDir targets or
collect payload/identity data from ordinary users.

Each transition is one authenticated command setting both values; require
`250 OK`, then GETCONF both values and record command/verification UTC times.

```text
# Comparison / live disable
SETCONF HSDirRefuseUnknownPrevHop=0 HSDirOneRequestPerCircuit=0
# Previous-hop-only trial (only if approved)
SETCONF HSDirRefuseUnknownPrevHop=1 HSDirOneRequestPerCircuit=0
# Reuse-only trial (only if approved)
SETCONF HSDirRefuseUnknownPrevHop=0 HSDirOneRequestPerCircuit=1
# After EVERY transition
GETCONF HSDirRefuseUnknownPrevHop HSDirOneRequestPerCircuit
```

These are alternative per-member phases, not a script to run consecutively or
broadcast to a cohort. Apply them only to the specifically assigned patched
members; stock binaries do not recognize the options. No torrc edits,
SIGHUP, SAVECONF, or canary restarts are used for trial transitions. Test one
defense at a time; combined enforcement is outside this initial trial. An
unverified or unexpected mode ends the usable analysis segment.

Exclude the full rate lookback after every change, plus the empirically
supported settling interval. Five-minute rates need at least five minutes;
30–60 seconds does not guarantee old circuits/queues have drained. Verify all
nested rate lookbacks, not only the reported outer window. Match conditions
within episodes and repeat comparisons when safe; retain temporal/adaptation
confounding as a limitation. Never infer benefit just because the flood moved
away or because enforcement prevented later requests from reaching the counter.
Lower bandwidth, CPU or request volume is not a successful policy result if
controlled receipt or latency worsens beyond the registered bound. Compare
absolute main-thread CPU together with total/worker CPU and circuit/handshake
demand: enforcement may move work or increase its cost. Do not infer client
benefit from whole-relay throughput. Apply the capture playbook's explicit
benefit/no_detectable_benefit/regression/inconclusive classification and retain
mixed tradeoffs; lack of sufficient exposure or precision remains inconclusive.

Report `delta R` during isolated reuse enforcement as inferred **circuit-close
decisions**, and `delta U` during isolated previous-hop enforcement as inferred
**503-refusal decisions**. `delta K` misses closures of circuits already reused
before a toggle. With both on, reuse closure takes precedence and the overlap
needed to attribute 503s is absent. None of these is a delivered-response count.

Same-host members share CPU, memory, network and failure risk. Treatment can
relieve pressure for controls as well. Preserve host-pressure context, unequal
HSDir/ring exposure and attacker adaptation as comparison limits. A crossover
is a separate predeclared choice requiring demonstrated settling; it does not
instantly restore prior circuits. Aggregate only validated same-build/mode
windows without double-counting episodes and their nested peak windows.

Probe TIMEOUT and failures stay in the attempted-probe denominator; client reset
or bootstrap downtime is separately reported as coverage gaps. On ambiguous
probe state, abort the batch and reset only the dedicated client before a new
batch, with verified teardown/readiness. Do not assume NEWNYM, ControlPort
reconnection, CLOSECIRCUIT, or waiting for a terminal event proves cleanup.
A 503 or circuit close need not produce HS_DESC FAILED.

A RECEIVED event supports controlled descriptor receipt/latency, not application
reachability, successful upload, all-client compatibility, or population-wide
legitimate-client success. Client authorization can still prevent use. Do not
add handoff counters to pretend to measure this. Use existing pressure metrics
as resource indicators, not delivery measurements.

At trial end explicitly return every patched trial member to `0,0`, verify
per member, report individual and matched efficiency/client-impact results,
including neutral or adverse findings and uncertainty, and hand back the
continuation/maintenance decision. No automatic enforcement
scheduler is part of this plan.
