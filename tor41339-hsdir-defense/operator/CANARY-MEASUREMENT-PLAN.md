# Final measurement plan: vipopen pilot, half-host rollout, and controlled trials

Revised agreed design, 2026-10-14. **This revision authorizes documentation
changes and their commit/push only. It does not authorize deployment, service
changes, probes, helper implementation, scheduling, or enforcement.** Another
agent is responsible for building the native Ubuntu 26.04 artifact and pushing
its evidence to the repository. This task does not perform or certify that build.

## Outcome and fixed scope

Characterize received HS directory traffic, inform a human decision about
enforcement, then optionally measure its incremental effect. The selected host
is **vipopen**, Ubuntu 26.04 amd64. Start with **one pilot**, then expand in
small batches toward **half of the host's relays**, retaining stock references.
This supersedes the previous experiment-wide one-relay limit; the one-pilot
limit still applies to the initial deployment stage.

- Keep patches **0001–0007 and the four existing HS counters unchanged**.
  No handoff, outcome, histogram, overlap, or enforcement-action C additions.
- Require a **native Ubuntu 26.04 amd64 build of Tor 0.4.9.14**, delivered by
  the other builder agent under [the build handoff](NATIVE-26.04-BUILD-HANDOFF.md).
  The exact filename, package version, source commit and hashes are taken from
  the published artifact manifest after review; none is invented here.
- The earlier Noble package is historical evidence, not the selected vipopen
  deployment artifact. Its static ABI checks passed, but this design deliberately
  selects a native 26.04 build. Do not silently substitute it for a pending build.
- Use **the same pinned native artifact for every patched member**. Freeze it
  before the pilot and do not rebuild or replace it between observation and
  enforcement. If a later artifact is necessary, stop and replan the comparison.
- Accept the full seven-patch build as the patched baseline. Patches 0003–0007
  remain active with the two optional defenses off; patched-off is not stock.
- One planned process restart is required **per converted relay**. No restart
  is planned for retained stock references. Keep each relay's identity,
  DataDirectory, allocator, memory limits and security configuration unchanged.
- Codex collects/analyzes through a configured persistent arrangement; the
  human operator reviews findings and phase decisions. A chat turn is not a
  monitoring daemon. No runtime collector or schedule exists merely because
  this plan describes one.

The host alias above is an explicit scope identifier requested by the operator.
Keep actual relay identities, endpoints, credentials and host/fleet inventory
counts in a private manifest; use stable opaque member IDs in reports.

## Private roster, rollout size, and comparison groups

Before deployment, freeze the operator-approved vipopen roster. Record the
host's eligible instance population N privately. The planned patched population
is **floor(N/2), including the pilot**; the remainder stays stock. Do not infer
permission to modify other hosts, silently change N, round upward, or recruit
additional instances to replace failed/missing observations. Record exclusions,
resource capacity and any approved change to the roster.

Choose the pilot and future members using prior traffic, HSDir history, role,
capacity and administrative reachability. Match stock references using the
same predeployment evidence; select/randomize within comparable candidates
where practical. Do not choose controls using their eventual treatment outcome.
The pilot may be a convenience choice; identify that limitation.

| Group | Binary / mode | What it can tell us |
|---|---|---|
| Stock reference | Existing stock binary, unchanged | Context and comparison with the full seven-patch build using common metrics; it has no four custom HS counters |
| Patched-off | Pinned native 26.04 build, both defenses inactive | Instrumented observation and the contemporaneous control for an enforcement trial |
| Patched-on | Same pinned native build, exactly one approved defense enabled | Incremental effect of that defense relative to patched-off |

Initially **every patched relay stays off**. During any trial, retain a
contemporaneous patched-off group; never enable the entire patched cohort at
once. Stock-versus-patched-on alone cannot isolate enforcement because the
seven-patch baseline also differs. The approved roster must support both
patched comparison groups; if it cannot, revise the trial design before testing
rather than silently expanding the rollout. One member per group remains
limited descriptive evidence; replication improves confidence.

Use stable IDs such as `pilot`, `patched_01`, and `stock_01`. The pilot keeps its
ID throughout; build group and runtime mode are separate fields with histories.
Each query must select one specific member; aggregate only after per-member
checks. Do not publish the private N or a total host/fleet inventory.

## Milestones and gates

| Milestone | Future authorized work | Completion condition |
|---|---|---|
| Native artifact handoff | Other agent builds/pushes the 26.04 package, manifest and actual lab evidence | Reviewer accepts the immutable artifact and evidence; an uploaded file alone is insufficient |
| Preflight and collection preparation | Freeze roster/roles, privileges, exact configurations, rollback state, health limits, collection and retention | Concrete private preflight complete, including target-specific scrape capacity |
| One pilot | Stage once, validate, restart only the selected pilot, verify its binary/configuration/metrics | Pilot startup and ordinary-load checks pass; operator receives check-in |
| Bounded expansion | After pilot review and later expansion authorization, convert the remaining approved patched members in small batches | Up to the agreed half-host target reached, each member verified; stock references untouched |
| HSDir recovery and passive observation | Track each converted member's own uptime/flag recovery, then gather 7–14 usable days with controls inactive | Observation/report criteria satisfied, or deadline/incident outcome reported |
| Human review | Review patterns, quality, resources, and comparison limitations | Continue, finish, or explicitly approve a bounded enforcement/probe trial |
| Probe preparation | Implement and validate the external helper in mock/isolated lab tests under its own authorization | Acceptance evidence reviewed; no relay C changes |
| Optional trial | Matched patched-off/on groups, one defense at a time, controlled-client checks if approved | Bounded trial completed or stopped, all patched members returned inactive |
| Handoff | Retain fixed binaries inactive pending instruction; dated maintenance review | Human decides continuation or planned removal |

Pilot success during the ~96-hour eligibility recovery only tests startup and
ordinary load; it is **not evidence of stability under an HSDir flood**. A small
expansion before the first flood is possible only with that uncertainty explicit
in the operator's rollout decision. Set batch sizes, review cadence, serving
capacity floor, and per-relay **and host-level** stop criteria in preflight.
Do not restart the whole patched cohort together or use a host-wide Tor action.
A failure pauses further expansion; do not spend the remaining rollout budget
trying new members automatically.

A later deployment instruction must distinguish pilot-only from pilot plus
bounded expansion. Within an approved expansion, proceed only through its
predeclared batch gates. This documentation push authorizes neither.

## Timing, eligibility, and observation

Budget about four days of HSDir recovery **after each member's own restart**;
consensus/distribution delays and other eligibility conditions can add time.
Record T0, first-observed T_flag and uncertainty per member. Do not align all
members to the pilot's clock or compare still-ineligible members with active
HSDirs as if exposure were equal.

Historical HSDir eligibility can qualify a healthy candidate whose flag is
currently absent because of a recent restart, if the operator approves that
selection explicitly. There is no need to wait for recovery merely to reset
uptime again; doing the swap during recovery starts a fresh ~96-hour interval.
Useful subsequent traffic is still not guaranteed.

Proposed defaults are **14 usable HSDir days per patched member**, with 7–14
selected in preflight, daily summaries, and a recovery review at each T0 + 7
days without a flag. Preserve common-time eligible windows for comparisons.
Valid zero traffic counts as observation; quality failures/warmup do not. Set
an absolute study end and extension policy before deployment. Members that
miss the deadline are reported as incomplete, not silently excluded or replaced.

Preserve multiple quiet/flood episodes. Use preregistered baseline, absolute
and relative onset, HS corroboration, and episode-end rules. Peak-hour
contrasts are secondary. No qualifying flood is an inconclusive exposure
outcome, not proof of no attack or ineffective defenses.

## Deployment, access, and collection

Follow [DEPLOY-AND-MEASURE.md](DEPLOY-AND-MEASURE.md) for the exact per-instance
procedure. Stage the reviewed native artifact once, keep it immutable, and
repeat the validated switch separately for each approved patched member.
Never install the package host-wide. Preserve the prior unit/drop-in,
confinement, allocator, holds and maintenance-exclusion state privately.
Shared maintenance changes need explicit scope agreement even if stock relay
processes remain untouched. Preserve stock rollback verification by keeping
the new options out of torrc/includes/defaults.

The four traffic counters come from **Tor MetricsPort**. Existing Prometheus
on the monitoring host scrapes them; a future reporting collector reads its
API for history and exports. ControlPort **GETCONF is only for configuration
state**, and SETCONF changes approved trial modes. The cookie is an admin
authentication credential, not a requirement for MetricsPort reads. Establish
an authenticated, narrowly scoped state-check/control path before deployment;
do not expose the ControlPort or share its credential with report output.

Initial `auto` is acceptable when verified inactive with both parameters absent
from the locally accepted current consensus. A dated public check is historical
context only. Recheck each member at scheduled check-ins; an unexpected active
state invokes verified `0,0` under the incident policy and invalidates that
member's affected interval. Explicit off is valid and must be reported as such.

Arrange **15-second scraping with a 10-second timeout for each approved
experiment target**, including the selected stock references, through the
monitoring owner's authorized configuration path. The supported approach is
exact-address target relabel overrides within the existing job, preserving
static groups and public labels, not duplicate jobs. Check aggregate collection
cost before expanding the target list; a successful one-target preflight does
not establish capacity for the full roster. Prometheus access remains read-only
until a configuration change is explicitly authorized to its owner.

Verify each required series individually, freshness/coverage, per-process CPU
and RSS, and process/service/boot continuity. `resets() = 0` alone is not proof
of no restart. Stock references structurally lack the four custom counters;
record those fields as unavailable, never zero. Keep notice logging,
SafeLogging, normal memory limits and existing access restrictions.

Use persistent incident alerts plus bounded scheduled state/coverage checks
and daily private exports, with named operator ownership. A five-minute check
cadence is a proposed preflight choice, not an installed schedule. Retain at
least 30 days or export before expiry, and extend preservation to cover the
last member's observation, review and trial. Report recovery and collector
gaps; do not imply that an open chat provides unattended incident coverage.

## Enforcement comparisons and limits

The operator approves matched assignments, mode order, time blocks, probe
cadence, settling limits and safety stops after observation. Match using
**pretreatment** load/role/capacity, not request rates already changed by the
defense. Randomize within matched patched candidates where practical. Retain
patched-off controls in every active block. A later crossover may help if its
carryover/settling assumptions are demonstrated; it is not an instant reset.

| Mode | HSDirRefuseUnknownPrevHop | HSDirOneRequestPerCircuit |
|---|---:|---:|
| Patched comparison / live disable | 0 | 0 |
| Previous-hop-only treatment | 1 | 0 |
| Reuse-only treatment | 0 | 1 |

Set both values in one authenticated SETCONF on the **explicitly selected
patched instance**, require successful reply, GETCONF both, and log submission
and verification times per member. Do not send new options to stock binaries.
No torrc edits, SAVECONF, SIGHUP, or restarts for phase changes. Combined
enforcement is outside the initial trial; flood alerts never enable a rule.

Exclude the full rate lookback plus documented settling after each member's
mode transition. Five-minute rates need at least five minutes; 30–60 seconds
does not establish drained circuits. Circuit history persists and disabling a
defense does not restore closed circuits. Native artifacts, allocator and other
settings remain constant across patched-off/on comparisons.

Same-host controls share CPU, RAM, network and failure risk. Relieving treated
relays can benefit their controls. Monitor host pressure as well as per-process
resources, and do not treat the members as independent hosts. Different HSDir
positions and rotating attacks also create unequal exposure. Shared hardware
and simultaneous sampling help comparison but do not make workload identical
or eliminate temporal/adaptation confounding.

T/R/K/U retain the definitions and caveats in the
[capture playbook](capture-and-validate-playbook.md). R/T and U/T are observed
predicates, not attack fractions or prevented-resource percentages; T/(T-R)
and K/(T-R) are window proxies with boundary limitations. Keep missing and
undefined results null. Whole-relay bytes are not HS-only bytes.

Under isolated reuse enforcement, delta R is an inferred count of close
**decisions**; delta K can miss circuits already reused before a toggle. Under
isolated previous-hop enforcement, delta U is a count of 503-refusal decisions,
not delivered responses. The counters cannot attribute overlapping decisions
when both rules are on. Enforcement also changes which future requests reach
the counters and can cause retries or interrupted earlier responses.

## Probe acceptance, reporting, and completion

The existing [hsfetch.py](../engineering/tools/hsfetch.py) remains a lab helper.
Its [acceptance specification](probe-helper-acceptance.md) is not an implemented
or passing test suite. Any later probe phase uses dedicated stock clients and
owned valid fixtures on explicitly approved targets, with no automatic fallback
to other HSDirs. Keep one outstanding request per client and a total experiment
probe budget; adding targets does not multiply the allowed traffic silently.

Use a monotonic overall deadline from submission, correlate the available
context without inventing a request ID, and stop an ambiguous/non-success batch.
Verified client-process reset/readiness is required before recovery where
specified. Never restart a relay for helper recovery. Neither reconnect,
NEWNYM, CLOSECIRCUIT nor indefinite terminal-event waiting proves cleanup.
Report timeouts in denominators and recovery gaps separately. Controlled
receipt/latency does not establish uploads, application availability or all
legitimate clients' experience. No internal handoff counters are added.

Use the capture playbook's cohort report contract: one JSON containing per-member
and comparison records, one bounded CSV with opaque member IDs, and a 6–10-line
summary. Separate stock-reference/full-build observations from patched-off/on
enforcement evidence. Preserve individual results and heterogeneity; do not
replace them with an average of per-relay ratios or count overlapping windows
twice. Raw target manifests, source labels, credentials, descriptors and
identities remain private. Exact-time operator reports require separate
redaction/coarsening before public release.

At study/trial end, leave every patched member on the same binary with verified
inactive defenses until instructed otherwise. Do not automatically unhold,
remove drop-ins, roll back, or convert stock references. Keep a dated human
maintenance review and emergency maintenance exception. On trouble, live-disable
the affected treatment first where appropriate, pause the cohort trial/expansion,
and use only the per-instance binary rollback required by the incident policy.
A member's rollback does not release shared holds, reboot exceptions, profile
changes or the staged binary still required by other patched members. Track
those dependencies privately and restore shared state only after its final
dependency is retired and the operator authorizes restoration.
These documents do not certify PR readiness or claim new build/helper/runtime
checks have passed.
