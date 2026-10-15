# Measuring the tor#41339 canary and reporting the evidence

This is the measurement specification for **one canary**, using the existing
four HSDir counters and stock telemetry. Deployment and operational controls
are in [DEPLOY-AND-MEASURE.md](DEPLOY-AND-MEASURE.md). Preparing or reviewing this
document does not authorize deployment, production collection, probes, or an
enforcement trial. Each operational phase requires the authorization specified
in that runbook.

## 1. Scope and the question this experiment answers

Keep one fixed, identified build of the full seven-patch series throughout the
experiment. First observe with both enforcement controls verified inactive.
Initial `auto` is acceptable when the current validated consensus contains
neither HSDir parameter and no configuration or runtime override enables a
rule. Check the effective state as specified in the deployment runbook.
Explicit `0,0` is used for later trial comparison and incident recovery; do
not treat an initial `auto` value alone as proof that enforcement is inactive.
After **7–14 eligible observation days**, give the human reviewer the report
before deciding whether to authorize a short trial. The proposed default is
**14 eligible days**; the reviewer chooses the duration before collection.

The observation asks how much traffic reaches the HS request guard, how often
it reuses circuits, and how often its previous hop is classified as unknown.
It can identify patterns a rule matches. It cannot prove that every matching
request is malicious, predict saved bandwidth, establish legitimate-client
success, or establish a network-wide effect from one relay.

“Count-only” describes the two controls in patches 0001 and 0002. Patches
0003–0007 also change behavior and accounting. The full build with both controls
off is the experiment's baseline; it is **not stock Tor with only counters
added**. Keep its source commit, package version, artifact digest, and relevant
configuration fixed and privately recorded. A later comparison concerns this
same build with a different control state.

Do not add C counters, histograms, per-request logs, or descriptor/identity
tracking for this plan. Accept the measurement limits below. The existing lab
can explain mechanisms, but matching a few ratios does not validate production
throughput, reproduce a request distribution, or make a causal effectiveness
prediction trustworthy.

## 2. What the counters mean

### 2.1 The four HSDir counters

All four are process-lifetime monotonic counters exposed as
`tor_relay_dos_total{type="..."}`. The anonymous HS request guard
`connection_dir_allow_hs_request()` counts **both descriptor GET and POST
requests**, before either enforcement decision. They are request observations,
not counts of successful fetches, completed uploads, or delivered responses.

| Symbol | `type` value | Event counted |
|---|---|---|
| T | `hsdir_request_total` | Every anonymous HS directory request reaching the guard. |
| R | `hsdir_req_reused` | Every request whose circuit already carried at least one HS request. |
| K | `hsdir_circ_reused` | The second HS request on a circuit, counted once for that circuit. |
| U | `hsdir_unknown_prev_hop` | Every HS request whose previous hop fails `connection_or_digest_is_known_relay()`, using consensus or held-descriptor knowledge. |

The per-circuit saturating state is `0 -> 1 -> 2`, where 2 means “two or
more.” A circuit carrying 22 requests contributes 22 to T, 21 to R, and 1 to K.
U is a request counter, not a circuit or identity counter. “Unknown” describes
this relay's lookup result; it does not prove the peer is an attacker or that
the request traversed exactly one hop.

For an observation window, `T - R` counts **first-request transitions inside
that window**. K counts second-request transitions inside it. These are not
necessarily the same circuit cohort: the first request can precede the window
and later requests can fall inside it. Therefore:

- `T / (T - R)` is a window proxy, not a measured distribution or exact mean
  over all circuits active in the window.
- `K / (T - R)` is a transition ratio, not a bounded circuit share. It can
  exceed 1 without a counting bug.
- `T - R` can be zero even when T is positive. Return `null` for the associated
  ratios in that case; a one-hour window does not remove this possibility.

The heartbeat includes “circuits with repeated HSDir requests” and “HSDir
requests with an unknown previous hop.” It is a coarse cross-check. Notice logs
do not establish enforcement state, and heartbeat timing is not a data-quality
or restart oracle.

### 2.2 Supporting stock telemetry

| Signal | Metric and selection | Meaning and limitation |
|---|---|---|
| B | `tor_relay_streams_total{type="BEGIN_DIR"}` | BEGIN_DIR streams terminated here; includes directory work other than HS requests. |
| C | `tor_relay_congestion_control_total{state="cc_circuits",action="circs_created"}` | Congestion-control circuits created, not all circuits or HS circuits. |
| BW, BR | `tor_relay_traffic_bytes{direction="written"}` and `{direction="read"}` | Whole-relay byte counters, not served HS-descriptor bytes. |
| OP, OD | `tor_relay_load_onionskins_total{type="ntor_v3",action="processed"}` and `{type="ntor_v3",action="dropped"}` | Whole-relay ntor_v3 handshake processing and drops. Zero drops do not exclude other overload. |
| Queue pressure | `tor_relay_dos_total{type="circuit_killed_max_cell_outq"}` | Stock output-queue-related circuit kills; does not attribute a failed HS response to a rule. |
| HSDir memory pressure | `tor_relay_load_oom_bytes_total{subsys="hsdir"}` | HSDir-cache bytes reclaimed during OOM handling; **not response-queue loss, failed responses, or delivered bytes**. |
| Open circuits | `tor_relay_circuits_total{state="opened"}` | Instantaneous gauge; do not apply `increase()` or `rate()` as if it were a counter. |

Other stock DoS counters may be useful corroboration when their definitions and
configuration are recorded. Their absence of increments does not prove absence
of a flood. The `dirreq-v3-*` request statistics describe network-status
requests, not HS descriptor fetches. Directory traffic histories are also not
HS-only traffic measurements.

Use an **existing, identified per-process** CPU/RSS source for the canary, not
host totals or another Tor instance. Record sampling cadence, aggregation and
units. In this report, RSS is MiB (`bytes / 2^20`) and CPU percent uses **100% per
logical CPU**; record any conversion from an existing normalized source. If the
required process series do not exist, report the gap rather than install a new
exporter or substitute a host measurement.

## 3. Register the measurement and quality gates before deployment

Privately record the selected duration, exact canary selector, expected labels,
metric definitions, scrape interval, resource sources, window rules, and
analysis version. An identifying selector is necessary internally but must not
appear in the returned report. Predeclare:

1. **Safety thresholds:** per-process RSS/CPU baseline statistics over the
   preceding day; absolute and relative limits; required breach durations;
   memory headroom; relevant pressure-counter limits; and the response required
   by the deployment runbook. “Well above normal” is not a threshold. Missing
   baseline data must be resolved before choosing thresholds.
2. **Data thresholds:** minimum scrape coverage, maximum permitted gap, allowed
   sample age, and counter/series continuity requirements. Choose actual
   numerical limits before looking at candidate flood windows.
3. **Detection rules:** the absolute BEGIN_DIR rate floor, HS-request
   corroboration rule, onset/end persistence, and how baseline windows are
   selected. No universal rate floor is assumed here.
4. **Resource summary:** the normal statistic (for example, the prior day's
   median and p95), the peak definition and sampling interval, and whether the
   comparison uses predeployment or same-build observation data. Keep both
   periods distinguished when available.

Every query must use the fixed selector for **only the canary**. Before
accepting a result, require exactly one fresh series for each expected metric
and label combination, including one for each of the four named HS types.
`count(...)=4` alone is insufficient: a duplicate can hide a missing type.
Account explicitly for any HA replicas or label changes; do not sum duplicates
or silently change selectors.

For every analysis window and each required series, record observed versus
expected samples, coverage fraction, maximum inter-sample gap, and freshness.
Check successful scrapes as well as the metric's own samples. A successful
scrape can still omit a metric. Absence, a stale series, or a query with an
unexpected result cardinality is a gap, never zero.

Use independent process-start and service/journal evidence, including boot
continuity when applicable, to establish restarts. Inspect counter resets as a
cross-check for **all relevant counters**. `resets(bytes_read[W])=0` means no
observed decrease; it does not prove no restart. A gap or label change can hide
one. A window crossing a restart, unresolved discontinuity, mode change, or
failed quality gate is not a valid comparison window. Report it and select a
different window if possible; never stitch the incident away silently.

Retention must cover warmup, observation, human review, and a possible later
trial. **At least 30 days** is the planned horizon, or retain private immutable
exports before shorter retention expires. Four warmup days plus fourteen
observation days already exceed a 15-day store. Extend the export horizon if
review or trial timing goes beyond it. Prometheus access is read-only: do not
edit relabeling, rules, retention, or scrape configuration. Missing collection
or retention is a prerequisite for its authorized owner to resolve.

## 4. Eligibility, baseline, and episode windows

Record `T0` as the **new process start time**, separately from the restart
command's start/end and elapsed duration. `T_flag` is the UTC time of the first
check that observes the HSDir flag in the canary's current valid consensus;
record that consensus's validity times separately.
A periodically checked flag time is an observation, not an exact transition
timestamp. Preserve the check interval or transition bounds as uncertainty.

The uptime/eligibility recovery period is **not** part of the requested
7–14-day observation. A usable period requires the flag, known inactive
mode, continuity evidence, and accepted telemetry. **Observed zero traffic is
valid data**, not a reason to exclude a quiet interval or extend collection.
Flag presence alone does not prove current ring traffic. Record eligible
elapsed time separately from wall-clock elapsed time and exclude intervals
that fail the declared eligibility or quality gates. Before deployment, agree a calendar deadline and
whether gaps may extend collection; do not wait indefinitely if eligibility
or telemetry never becomes usable. Absent qualifying traffic is an outcome,
not an automatic extension.

### 4.1 Baseline

Choose the first qualifying clean period of at least one hour starting at
least two hours after `T_flag`, after eligibility and data quality are
established. A measured zero-traffic baseline is allowed; its relative rate
multiples are undefined. Predeclare how “clean” is assessed. Retain additional comparable
quiet windows across the eligible observation when available; traffic can vary
with time and HSDir assignment. Use same-build, both-controls-off data for the
main baseline.

If no qualifying quiet baseline exists, do not manufacture one from the lowest
observed hour. Report `no_clean_baseline`, provide the qualified episode or
elevated-traffic observations, and leave baseline multiples null. An episode
before a baseline is established can be retained as a candidate, but cannot
satisfy a baseline-relative detection claim until the registered criteria can
be evaluated. Retrospective classification must be labeled.

### 4.2 Suspected flood episodes

Let `b0` be the baseline's mean BEGIN_DIR rate, `B_baseline / W_baseline`. For
positive `b0`, the primary onset condition is a five-minute BEGIN_DIR rate at
least `max(5 * b0, A)`, sustained for at least 15 minutes, where `A` is the
operator-selected absolute floor. Require the preregistered corroborating rise
in the HS request rate. State that criterion numerically before collection.

If the baseline is zero or unavailable, the relative criterion is undefined.
Use only a separately predeclared absolute/corroboration criterion and identify
the resulting classification as such; do not claim an infinite or fivefold
increase. BEGIN_DIR alone is not sufficient to label the event an HS flood.

Use an explicitly lower exit threshold and a declared below-threshold dwell
time to define episode ends. Record onset as the beginning of the sustained
qualifying run, detection time separately, and end uncertainty from the
sampling cadence. If an episode remains active when observation ends, its end
is unknown; report it as right-censored.

Retain **multiple qualifying episodes** over the registered observation rather
than stopping at the first. Analyze full episodes as the main results. A
secondary peak hour may be chosen by a predeclared rule, such as the highest
mean HS-request rate among fixed aligned hours fully inside an episode. Mark
that selection explicitly. Peak-versus-quiet comparisons describe a selected
extreme, not the typical episode or a causal treatment effect. Preserve short
episodes as observations even if they cannot supply a complete one-hour
window.

At the agreed endpoint, report one of: `observed_episodes`, `baseline_only`,
`no_clean_baseline`, `inconclusive`, or `aborted`. `baseline_only` means no
qualifying episode was observed during the covered eligible time, not that
the network has no flood. State insufficient exposure or quality separately.
Any extension or later enforcement remains a human decision.

## 5. Reproducible computation

For each accepted window `[S,E]`, let `W=E-S` in seconds. Query the HTTP API
with **`time=E` for every instant query**. Expand `W` to a literal duration in
PromQL (for example, `[3600s]`) and add the exact private canary selector to
every series. Keep endpoint, credentials, queries with identifying labels, and
raw API responses private. Require API success, expected result cardinality,
and review any warnings or informational annotations.

Use API evaluation time consistently instead of adding `@ E` to arbitrary
inner selectors. Pinning the inner selector of a rate subquery would freeze
its samples and invalidate its temporal quantiles.

### 5.1 Counter estimates

The following are query templates: replace `<canary>` and `Ws`; do not submit
the placeholders. Each selected series must independently pass §3.

```promql
B  = increase(tor_relay_streams_total{type="BEGIN_DIR",<canary>}[Ws])
C  = increase(tor_relay_congestion_control_total{state="cc_circuits",action="circs_created",<canary>}[Ws])
T  = increase(tor_relay_dos_total{type="hsdir_request_total",<canary>}[Ws])
R  = increase(tor_relay_dos_total{type="hsdir_req_reused",<canary>}[Ws])
K  = increase(tor_relay_dos_total{type="hsdir_circ_reused",<canary>}[Ws])
U  = increase(tor_relay_dos_total{type="hsdir_unknown_prev_hop",<canary>}[Ws])
BW = increase(tor_relay_traffic_bytes{direction="written",<canary>}[Ws])
BR = increase(tor_relay_traffic_bytes{direction="read",<canary>}[Ws])
OP = increase(tor_relay_load_onionskins_total{type="ntor_v3",action="processed",<canary>}[Ws])
OD = increase(tor_relay_load_onionskins_total{type="ntor_v3",action="dropped",<canary>}[Ws])
```

These are notation assignments, not executable PromQL assignment syntax.
Prometheus `increase()` and `rate()` extrapolate to window boundaries and
adjust observed counter decreases. They can produce fractional results from
integer counters and can conceal a restart in an apparently smooth result.
Describe the outputs as **estimates from measured scraped counters**, not exact
integer event totals. Preserve their numerical precision and method rather
than rounding them into invented counts. Quality checks remain mandatory.

### 5.2 Derived quantities and their labels

Compute ratios from the accepted window totals in analysis code, or use
explicit correct vector matching in PromQL. Different `type`, `direction`,
`state`, or `action` labels do not match automatically. Never fix a mismatch by
silently summing unrelated series.

| Field | Formula | Interpretation |
|---|---|---|
| `r_hs` | R / T | Observed HS requests on previously used circuits; a request-predicate fraction. |
| `phi` | U / T | Observed HS requests classified as having an unknown previous hop. |
| `rho_hs` | T / (T - R) | Window transition proxy; see §2.1. |
| `reused_circ_share` | K / (T - R) | Legacy field name retained for compatibility; **transition ratio**, possibly above 1. |
| `hs_share` | T / B | HS guard requests per BEGIN_DIR stream; approximate share because request and stream events can straddle boundaries. |
| `rho` | B / C | Whole-relay BEGIN_DIR streams per congestion-control circuit; proxy only. |
| `write_read_ratio` | BW / BR | Whole-relay byte ratio. |
| `bytes_per_begin_dir` | BW / B | Whole-relay written bytes per BEGIN_DIR stream; not descriptor size. |
| `onionskins_processed_per_s` | OP / W | Whole-relay ntor_v3 processed rate. |
| `onionskins_dropped_per_s` | OD / W | Whole-relay ntor_v3 drop rate. |

R/T and U/T have the matching request denominator by construction, but their
reported estimates inherit scrape and window uncertainty. They are **not
fractions of attack traffic stopped**. The predicates can overlap; never add
R and U to claim combined coverage. Without an overlap counter, the observed
union is only bounded by `max(R,U)/T` and `min(1,(R+U)/T)` when the data support
those calculations. Do not invent an overlap estimate.

For **every** computation, return `null` if an input is missing, nonfinite, or
invalid, or if its denominator is nonpositive. This includes T, T-R, B, C, BR,
W and comparison baseline rates. Explain the cause in `gaps`. Preserve actual
observed zero numerators when their denominator is valid. Do not clamp a
boundary-affected circuit ratio to 1 or coerce missing values to zero.

### 5.3 Rate summaries and comparison multiples

Let scrape interval be `i`. Use rate lookback `L=max(60 seconds,4*i)` and
subquery step `d=max(15 seconds,i)`, substituting literal durations. For X
equal to BEGIN_DIR or HS request total, evaluate at E:

```promql
quantile_over_time(0.5, rate(X{<canary>}[Ls])[Ws:ds])
quantile_over_time(0.95, rate(X{<canary>}[Ls])[Ws:ds])
max_over_time(rate(X{<canary>}[Ls])[Ws:ds])
```

These are time-quantiles and the maximum of **smoothed rate estimates**, not
instantaneous one-second counts or the true unsmoothed peak. Record L and d.
The earliest rate sample can use data before S; retain and validate the full
support `[S-L,E]`. For mode comparisons, require that support to be entirely
inside the same accepted, settled mode (§6). Document this boundary support
for episode summaries too; it is different from the `[S,E]` counter window.

Compare **mean rates** between accepted flood and baseline windows:

```text
begin_dir_rate_multiple = (B_flood / W_flood) / (B_baseline / W_baseline)
hs_request_rate_multiple = (T_flood / W_flood) / (T_baseline / W_baseline)
```

Do not divide a peak by a mean and label it this multiple. State which flood
window supplies the top-level comparison, and retain per-episode comparisons
when several episodes are reported.

## 6. Later enforcement: separate approval and limited claims

### 6.1 Rule selection from observation

High r_hs establishes a reuse pattern matched by 0002; high phi establishes an
unknown-hop pattern matched by 0001. Near-zero values mean little of the
observed request population matched those predicates. They do not establish
whether the remaining population is legitimate, what would happen after
adaptation, or the amount of resources a rule would save.

The human reviewer receives the observation report before any trial. Initial
trial candidates are **one rule at a time**, on the same fixed build and same
canary, with both-off intervals for comparison. Combined enforcement is
excluded from the initial trial. Do not change consensus parameters or other
relays. The runbook owns the exact control procedure and rollback behavior.

### 6.2 Mode windows, transitions, and causal limits

Privately record control intent, acknowledged application time, confirmed
effective state of both rules, and any reload/configuration/consensus changes.
Do not infer mode from notice logs. Each mode window must retain the same
build and pass the data and restart gates. A state change splits the window.

Determine settling empirically from the observed traffic and resource series;
predeclare the acceptance criterion and maximum waiting time. There is no
promised 30–60-second settling period. Exclude the transition and settling
period, then leave a **full rate lookback** before the first rate sample used
for comparison. If stable comparable windows do not exist, report the trial
as inconclusive. A fixed delay does not establish equivalent workloads.

Circuit history persists across a live toggle. If a circuit made requests 1
and 2 while off, request 3 after enabling reuse enforcement increments R,
does not increment K, and enters the closure branch. Switching back off does
not recreate closed circuits or recover abandoned responses. Therefore
`delta closures = delta K = delta R` is **not a valid general identity**.

Within a verified constant-mode interval:

- With reuse enforcement on, R counts reuse **closure decisions/branch
  invocations**. It is not independently measured unique circuit destruction
  or completed-client-response loss. K remains the second-request transition
  counter. Equating K and R additionally requires no relevant circuit to
  arrive with a preexisting two-or-more state.
- With unknown-hop enforcement on and reuse enforcement off, U counts the
  corresponding **503-response decisions/attempts**, not responses received by
  clients.
- With both on, the reuse branch precedes the unknown-hop 503 branch.
  `503 decisions = U - overlap(unknown and reused)`, and that overlap is not
  available from the four counters. Exact separate action attribution is
  unresolved; combined mode would require its own later protocol.

Pre-enforcement counting does not preserve a fixed offered workload: closure
prevents future requests from reaching the guard, can interrupt earlier
responses, and can provoke retries or adaptation. A lower T, R/T, byte rate,
CPU, or RSS after a toggle does not alone prove benefit. Use comparable
episodes, preserve time trends and pressure signals, and explicitly distinguish
an observational association from a causal estimate. A quiet later week is not
an enforcement control for a flooded earlier week.

### 6.3 Client checks and outcome limits

The existing counters do not distinguish GET/POST outcomes, HS-only bytes,
successful response delivery, or the legitimate-client population. Stock OOM
and queue-pressure counters do not fill those gaps. Patch 0007's directory
buffer completion is an internal handoff, not evidence that the client
received the descriptor.

If a later trial includes controlled-client checks, follow
[probe-helper-acceptance.md](probe-helper-acceptance.md) and its separate
authorization and acceptance requirements. This link authorizes no probing.
Do not assume an existing helper already measures correct success, failure,
cache behavior, target selection, or latency. A timeout or missing event must
not silently become success. Even accepted controlled checks establish only
the tested client/path/service experience, not fleet-wide or all-client
success. Return only approved aggregate probe results and limitations.

## 7. Report contract

Return exactly: **(1) one fenced JSON report, (2) one CSV of at most 40 data
rows, (3) a six-to-ten-line plain-language summary**. No raw captures, selectors,
endpoint URLs, fingerprints, nicknames, IPs, hostnames, ContactInfo, onion
addresses, descriptor IDs, Prometheus job/instance labels, or fleet counts.
Call the relay “canary.” Private UTC window times are allowed in this report;
public redistribution requires a separate confidentiality review because
precise timing can aid correlation.

### 7.1 JSON fields and missing-data policy

The following is a **valid JSON template, not a measured result**. Populate
only from accepted evidence. Null means unknown/not applicable and requires
an explanation in `gaps`; zero means an observed zero. Boolean fields must
also remain null when unverified. Replace the template status and criteria
with the registered values and actual outcome.

Each entry in `flood_windows` and `mode_windows` contains **every measurement
field in `baseline_window`** below. Flood entries additionally contain
`episode_start_utc`, `episode_end_utc`, `episode_right_censored`, `window_kind`
(`full_episode` or `peak_hour`), `mode`, and its baseline rate multiples.
Mode entries additionally contain `mode`, `mode_confirmed_utc`,
`settled_after_utc`, `rate_support_start_utc`, and interpretation limits.
Observation mode is `observe`; isolated trial modes are `reuse_only` and
`unknown_prev_hop_only`. Do not omit a missing value from an otherwise valid
window just to make it look complete. If no baseline exists, set
`baseline_window` to null and retain its reason.

```json
{
  "status": "inconclusive",
  "deployment": {
    "install_path": "per-instance drop-in (DEPLOY section 1.1)",
    "package_version": null,
    "source_commit": null,
    "artifact_sha256": null,
    "restart_command_start_utc": null,
    "restart_command_end_utc": null,
    "t0_process_start_utc": null,
    "t0_restart_utc": null,
    "t_flag_utc": null,
    "flag_last_observed_absent_utc": null,
    "flag_consensus_valid_after_utc": null,
    "flag_consensus_valid_until_utc": null,
    "flag_check_interval_s": null,
    "hours_t0_to_flag": null,
    "restarts_during_measurement": null,
    "restart_seconds": null,
    "execstart_matched_stock": null,
    "verify_config_ok": null,
    "pid_changed": null,
    "counters_present": [],
    "enforcement": null,
    "sandbox_1": null,
    "scrape_interval_s": null
  },
  "observation": {
    "planned_eligible_days": 14,
    "eligible_days_observed": null,
    "calendar_deadline_utc": null,
    "coverage_fraction_minimum": null,
    "maximum_allowed_gap_s": null,
    "begin_dir_absolute_floor_per_s": null,
    "relative_onset_multiple": 5,
    "onset_persistence_s": 900,
    "hs_corroboration_rule": null,
    "exit_threshold_rule": null,
    "exit_persistence_s": null,
    "baseline_selection_rule": null,
    "peak_selection_rule": null,
    "retained_through_utc": null
  },
  "method": {
    "counts": "Prometheus increase estimates from scraped counters",
    "instant_query_time": "window end E",
    "rate_lookback_s": null,
    "rate_subquery_step_s": null,
    "reused_circ_share_meaning": "window second-request/first-request transition ratio, not bounded share"
  },
  "baseline_window": {
    "start_utc": null,
    "end_utc": null,
    "duration_s": null,
    "rate_support_start_utc": null,
    "coverage_fraction": null,
    "maximum_gap_s": null,
    "restart_evidence_complete": null,
    "B": null,
    "C": null,
    "T": null,
    "R": null,
    "K": null,
    "U": null,
    "BW": null,
    "BR": null,
    "OP": null,
    "OD": null,
    "begin_dir_per_s": {"median": null, "p95": null, "peak": null},
    "hs_req_per_s": {"median": null, "p95": null, "peak": null},
    "r_hs": null,
    "rho_hs": null,
    "reused_circ_share": null,
    "phi": null,
    "hs_share": null,
    "rho": null,
    "write_read_ratio": null,
    "bytes_per_begin_dir": null,
    "onionskins_processed_per_s": null,
    "onionskins_dropped_per_s": null,
    "output_queue_circuit_kills": null,
    "hsdir_oom_reclaimed_bytes": null
  },
  "flood_windows": [],
  "mode_windows": [],
  "flood_vs_baseline": {
    "flood_window_index": null,
    "begin_dir_rate_multiple": null,
    "hs_request_rate_multiple": null
  },
  "csv_window": {
    "start_utc": null,
    "end_utc": null,
    "duration_s": null,
    "flood_window_index": null,
    "selection_reason": null
  },
  "resources": {
    "scope": "canary process",
    "source_description_without_identifiers": null,
    "sampling_interval_s": null,
    "normal_statistic": null,
    "normal_period_start_utc": null,
    "normal_period_end_utc": null,
    "rss_unit": "MiB",
    "rss_mib_normal": null,
    "rss_mib_flood_peak": null,
    "cpu_pct_basis": "100 percent per logical CPU",
    "cpu_pct_normal": null,
    "cpu_pct_flood_peak": null,
    "registered_stop_thresholds": null,
    "threshold_breaches": []
  },
  "probe_aggregates": {
    "performed": false,
    "audit_totals": {
      "attempted_submissions": null,
      "acknowledged_commands": null,
      "verified_received": null,
      "verified_failed": null,
      "command_rejected": null,
      "timeouts": null,
      "submission_indeterminate": null,
      "protocol_or_io_indeterminate": null,
      "aborted_indeterminate": null
    },
    "by_mode": [],
    "excluded_transition_attempts": null,
    "recovery_gaps": [],
    "limitations": "No authorized probe phase represented in this template"
  },
  "mode_history": [],
  "gaps": ["Template only; replace with measured evidence and specific limitations"]
}
```

`counters_present` lists only the verified type names
`hsdir_circ_reused`, `hsdir_req_reused`, `hsdir_request_total`, and
`hsdir_unknown_prev_hop`. Record the actual effective configuration in
`enforcement`, rather than assuming `auto` means off. `mode_history` entries
contain UTC boundaries, intent, acknowledged and confirmed state for both
controls, and any uncertainty, without control endpoints or identities.
The compatibility field `t0_restart_utc` is an alias of
`t0_process_start_utc`, not the restart-command start. Compute
`hours_t0_to_flag` from that process timestamp and the first-observed flag
timestamp, preserving its stated uncertainty.

The window's `coverage_fraction` is the minimum across its required series;
`maximum_gap_s` is the maximum across them. Preserve per-series quality details
privately and name affected metric types, without identifying labels, in gaps.
Pressure counters use the same accepted-window increase method. A later probe
phase must populate `probe_aggregates.by_mode` with one object per accepted
mode/window: `mode`, `mode_window_index`, the count fields in `audit_totals`,
`receipt_fraction`, `timeout_fraction`, `receipt_latency_ms_median`,
`receipt_latency_ms_p95`, `attempt_deadline_s`, `planned_attempts`,
`observed_duration_s`, `client_resets`, and `gaps`. Record the tested client
version and relevant settings without identifying services or endpoints.
Receipt fractions divide verified receipts by **all attempted submissions**,
including uncertain submissions, timeouts and other non-success outcomes.
Receipt-latency quantiles are conditional on verified receipt; never insert
timeouts as measured latency or silently drop them from the denominator.

The outcome categories are mutually exclusive and must sum to attempted
submissions. Acknowledged commands are a separate subset, not another outcome
or evidence of receipt. `protocol_or_io_indeterminate` excludes the separately
classified uncertain submissions and aborted attempts. Preserve attempts
crossing a transition in audit totals and identify them as excluded from
stable-mode comparisons. Preflight failures and missed schedule slots belong
in coverage/recovery gaps, not invented attempts. A single pooled success
rate is insufficient for an off/on comparison.

### 7.2 CSV: five-minute bins in the selected main window

Choose a complete main hour where possible. The CSV covers a declared window
of at most **200 minutes**, even when the full episode is longer. Preserve full
episode statistics in JSON. Use `query_range`, step 300 seconds, with
evaluation timestamps **S+300, S+600, ..., E** for a window whose duration is
an integer number of five-minute bins. A row is labeled by its end offset.
Do not evaluate at S and present the preceding five minutes as part of this
window. Align the chosen endpoints explicitly and report any omitted edges.

Use five-minute `rate()` values for BEGIN_DIR, HS request total and written
bytes, and the following ratio templates with the same fixed canary selector:

```promql
rate(tor_relay_dos_total{type="hsdir_req_reused",<canary>}[5m])
/ ignoring(type)
rate(tor_relay_dos_total{type="hsdir_request_total",<canary>}[5m])

rate(tor_relay_dos_total{type="hsdir_unknown_prev_hop",<canary>}[5m])
/ ignoring(type)
rate(tor_relay_dos_total{type="hsdir_request_total",<canary>}[5m])
```

Require exactly one matching series on each side after ignoring `type` and
accepted quality in each bin. If the scrape cadence/coverage is insufficient
for reliable five-minute estimates, report that gap rather than substitute
unlabeled longer-lookback rates. Write `null` in missing or undefined numeric
CSV fields; include the reason in JSON. No event or no usable main window means
a **header-only CSV**, not invented zero rows:

```csv
t_offset_min,begin_dir_per_s,hs_req_per_s,r_hs,phi,bytes_written_per_s
```

### 7.3 Six-to-ten-line summary

State the observation status, covered eligible time and episode count; the
mean-rate increase above baseline or why it is unavailable; r_hs and phi;
the qualified rho_hs/transition ratio and hs_share; observed ntor_v3 drops and
resource/pressure evidence; which rule matches the observed pattern; and the
main gaps or surprising observations. If a later trial was authorized, state
its modes, controlled-probe scope and limits, and distinguish association from
causal evidence. Zero drops means “no observed ntor_v3 handshake drops,” not
“the relay was not overloaded.” No data means unknown, not success.

## 8. Privacy and operational boundaries

Keep raw metrics, labels, query endpoints, consensus identifiers, control
responses, logs, and any approved probe configuration private. Collect no
client or relay identity tables, descriptor/blinded-key tables, stream bodies,
per-service statistics, or per-request timestamps for received relay traffic.
The later controlled probe ledger may privately time its own submitted test
attempts as specified in the helper acceptance document. Do not claim
client IPs are structurally unobservable on every path: an authenticated
unknown relay peer can use a one-hop path. The aggregate instrument does not
record its identity or address.

Use the existing MetricsPort and access controls. Keep notice logging and
SafeLogging enabled. No load generation, probing of other relays, or optional
client checks are authorized by the observation specification. Follow the
deployment runbook for safety stops, the canary's maintenance controls, and
post-observation state. Reporting completion does not authorize a reload,
restart, uninstall, unhold, enforcement toggle, or indefinite extension.
