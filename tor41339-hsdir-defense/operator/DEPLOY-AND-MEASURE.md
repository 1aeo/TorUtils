# One-canary deployment, passive measurement, and optional live trial

**Status: approved design documentation, not execution authorization.** The
current update changes documents only. Do not build, install, restart, probe,
schedule jobs, or enable enforcement until the human explicitly authorizes the
relevant phase. Start with [the final plan](CANARY-MEASUREMENT-PLAN.md).

Keep patches 0001–0007 and all four existing counters unchanged. The accepted
baseline is the full patched build with the two optional defenses inactive;
0003–0007 still change logging, buffering, validation order, and cache accounting.
Do not describe the full package as behaviorally identical to stock. One binary
serves observation and any later trial, avoiding a second planned restart.

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
| Scope and identity | Exactly one currently eligible HSDir; unit, torrc/includes/defaults, user, DataDirectory, MetricsPort, ControlPort/auth; identifiers never in shared reports |
| Artifact | Exact source commit, seven-patch hashes, package and binary SHA256, base Tor version, Ubuntu/architecture/library compatibility; explain any version change |
| Service | Loaded ExecStart and ExecStartPre, source files/drop-ins, environment/specifiers, dependencies/PartOf, stop/start/restart policy, pending manager reloads |
| Confinement | Existing AppArmor profile/attachment, seccomp/Sandbox and other unit security settings; how the `/opt` path preserves them |
| Maintenance | Existing holds/exclusions and contents, upgrades/reboot timers and external automation; shared changes explicitly scoped; review/expiry date and emergency security-maintenance exception |
| Monitoring | Persistent scraper, scheduled read-only checker, existing incident alert path, operator/backup owner, coverage during recovery and observation |
| Baseline | Previous-day per-process CPU/RSS summaries, units/CPU normalization and sampling; existing traffic context, not a substitute for post-flag HS baseline |
| Thresholds | Sustained service/resource limits, alert delay and responder, live-disable/binary-rollback triggers; expected flood load alone is not a failure |
| Data quality | Scrape interval, each required series/source, uniqueness, freshness, minimum coverage and maximum allowed gap; restart evidence sources |
| Timing | Selected 7–14 usable observation days, flag-recovery deadline, absolute end/extension policy, check-in cadence, dated postexperiment review |
| Retention | At least 30 days or private daily/window exports; owner handles any Prometheus configuration change |
| Rollback | Original loaded binary/command/config and backed-up changed files; exact restoration plan; no blanket unhold or deletion of pre-existing files |

Proposed defaults: 14 usable days, a flag-recovery review at T0 + 7 days,
state/health/coverage checks every five minutes, daily human summaries, and
HSDir checks every few hours from T0 + 90 hours. Continuous crash/service alerts
come from the monitoring system, not the daily summary. Record selected values
and available coverage before deployment. If defaults are unsuitable, choose
and document replacements. Unset health thresholds or unowned incident alerts
must be resolved before deployment, not improvised during a flood.

Prometheus access is **read-only**. Missing retention/scrape/allowlist support
requires its authorized owner's change or an approved private export path.
Do not silently change Prometheus configuration. No monitor is created by this
runbook; a persistent scheduler/collector must actually be arranged before the
one restart. Codex handles collection/analysis, the human reviews and decides
whether to continue or trial a defense.

Host-wide holds, shared security-profile changes, and automatic reboot policy
are shared-host changes even if only one process restarts. Prefer an eligible
host with less shared scope when practical; otherwise include those narrow
exceptions in the deployment authorization. Do not change/restart/reload any
other relay. Never operate on the unqualified master `tor` service.

## 1. Pin and stage the binary (after deployment authorization)

### Path A — unpack the existing package to `/opt`

Candidate: `../packages/tor_0.4.9.14-1~noble+1+tor41339.3_amd64.deb`, Ubuntu
24.04 amd64. Read `BUILD-INFO.txt` and the matching manifest, and pin the actual
reviewed commit/digests. Checksums from the same checkout detect corruption;
they do not independently authenticate a build. A strings check establishes
names are present, not that the code is correct or that metrics are scraped.

The following are future operator steps, not commands executed by this update:

```bash
cd tor41339-hsdir-defense/packages
sha256sum -c --ignore-missing SHA256SUMS
# REQUIRE the specific tor .deb line to be present and OK, not merely exit 0.
# REQUIRE /opt/tor41339 to be an approved new destination or verified same build.
sudo mkdir -p /opt/tor41339
sudo dpkg-deb -x tor_0.4.9.14-1~noble+1+tor41339.3_amd64.deb /opt/tor41339
/opt/tor41339/usr/bin/tor --version
strings /opt/tor41339/usr/bin/tor | grep -c '^hsdir_\(circ_reused\|req_reused\|request_total\|unknown_prev_hop\)$'
# Expected: 4. Also record the extracted executable's SHA256 privately.
```

Unpacking runs no maintainer scripts. Keep `/usr/bin/tor` and the installed
package in place. `tor-geoipdb` is not needed for this binary swap. **Do not use
host-wide package installation for this experiment**, including as a shortcut
on a multi-instance host. Verify root ownership and that the staged executable
is not writable by the relay account.

### Path B — build only if the pinned artifact cannot be used

A new build is separate preparation, never an on-relay improvisation. Follow
[the build instructions](../engineering/deb/REBUILD-FROM-CURRENT-SERIES.md),
retain the same seven patches and four counters, and review its provenance and
lab results before deployment. Match systemd notification support and the
production feature/library set. This documentation update does not build a
package or certify a replacement artifact. Keep the selected artifact fixed
through all observation and trial phases.

### 1.1 Switch exactly one systemd instance

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

5. **Perform the one authorized restart of `tor@CANARY` only.** Record the
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

## 2. Initial observe mode

Leave both options omitted so the patched runtime normally reports `auto`.
Initial `auto` is accepted if the canary's current validated consensus lacks
`hsdir_one_request_per_circ` and `hsdir_refuse_unknown_prev_hop` and no runtime
or configuration override enables either defense. All four counters remain
active regardless of enforcement.

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

**Check-in 1:** T0 UTC, package/build identity, effective command stock/custom,
verification success, PID changed, correct executable and confinement, four
fresh counters, expected inactive mode, Sandbox state, restart duration, and
exceptions. Share no private unit names or identifying command arguments.

Monitor from T0. From roughly T0 + 90 hours, inspect the canary's entry in a
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

## 4. Collect 7–14 usable HSDir days

The human selects the duration before deployment (proposed default 14 days).
Do not include the four-day warmup or unusable gaps. Record wall time and usable
time separately and honor the absolute end/extension policy. Collect multiple
quiet/flood episodes; do not stop at the first favorable peak hour.

### 4.1 Prometheus and persistent monitoring

Use the existing private scrape endpoint and selectors. Preserve restrictions;
never expose MetricsPort publicly or broaden access to `accept *`. Prefer an
existing 10–15-second scrape if available; use the observed interval in the
analysis. If owner-side changes are required, arrange them before deployment.
Keep at least 30 days or export validated daily/window data before expiry.
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

Produce the private de-identified JSON, <=40-row CSV for a selected main flood
window, and 6–10-line summary in the capture playbook. Include the entire
observation's coverage/episode history alongside representative windows;
peak-hour contrasts are explicitly secondary. No guessed values or hidden
failures. Per-window estimates cannot establish unobserved attack traffic,
legitimate-client failure rates, or causal resource savings.

**Check-in 3:** observation report. The human chooses continued observation,
collection completion, or a separately approved bounded trial. High `R/T` or
`U/T` alone never automatically enables a defense. If both are low, report weak
evidence for these predicates rather than forcing an enforcement experiment.

## 6. Live disable, incident rollback, and end-of-study handoff

Distinguish three actions:

1. **Enforcement trouble:** apply explicit `0,0` through SETCONF and verify
   GETCONF. No binary swap or planned restart; keep metrics running. Record the
   incident and stop the active trial. This disables only the two defenses,
   not patches 0003–0007, and is not a claim of restored stock behavior.
2. **Binary/startup/service failure:** follow the authorized incident policy.
   Restore the exact prior per-instance ExecStart/drop-in/configuration and
   confinement from the manifest, reload manager configuration, and restart
   only the canary. Verify active service and the original executable. This
   costs a new uptime/HSDir interval; safety takes precedence. Preserve incident
   evidence privately and report the interruption.
3. **Normal collection completion:** leave the patched binary running with
   inactive defenses until instructed otherwise. Do not automatically remove
   the drop-in, unhold packages, remove exclusions, or restart. Schedule the
   agreed dated human maintenance review; do not leave exceptions unowned.

When a rollback/removal is authorized, restore the previous maintenance state:
only unhold packages newly held for this experiment; preserve earlier holds;
restore modified files and remove only experiment-created files. Do not blindly
remove a shared exclusion/profile. Verify restoration before declaring success.
Binary rollback always needs a process restart; SIGHUP never changes the binary.
Security maintenance can supersede the experiment; report an interrupted run
rather than suppressing required maintenance indefinitely.

## 7. Privacy and output boundary

Call the relay `canary`. No relay fingerprints, nicknames, IPs, hostnames,
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

The human approves the tested helper, dedicated stock client, owned descriptor
fixture, explicit low probe cadence, matched off/on durations, phase order,
settling criteria, incident limits, and trial end. Run identical low-rate checks
in the trial's comparison and active windows. Do not use an arbitrary service's
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

These are alternative phases, not a script to run consecutively. No torrc edits,
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

Report `delta R` during isolated reuse enforcement as inferred **circuit-close
decisions**, and `delta U` during isolated previous-hop enforcement as inferred
**503-refusal decisions**. `delta K` misses closures of circuits already reused
before a toggle. With both on, reuse closure takes precedence and the overlap
needed to attribute 503s is absent. None of these is a delivered-response count.

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

At trial end explicitly return to `0,0`, verify, report the results/limitations,
and hand back the continuation/maintenance decision. No automatic enforcement
scheduler is part of this plan.
