# Controlled descriptor-fetch helper: design and acceptance specification

**Status: SPECIFICATION ONLY — NOT IMPLEMENTED OR TESTED.** This document
defines future changes and checks for
[`engineering/tools/hsfetch.py`](../engineering/tools/hsfetch.py). The current
script remains a minimal lab helper; this specification is not evidence that
it meets these requirements. No helper implementation, Tor build, test run,
probe, deployment, or enforcement change is authorized by this document alone.

## Purpose and boundaries

After passive collection and human review, optional controlled checks can
measure whether a stock Tor client receives a known-good descriptor from the
assigned approved relay, and how long that takes. The deployment pilot keeps
the opaque ID `pilot`; later approved probe batches can assign it or another
approved patched member as their one target. Run
predeclared, matched checks on patched relays with enforcement off and on
before and during an approved enforcement trial. All such patched targets
must use the same reviewed Ubuntu 26.04 seven-patch artifact, identified by its
version and digest; record the separately built artifact's provenance before
use. This complements relay counters and resource measurements without
changing relay C code or adding metrics.

These checks are **outside the initial passive collection phase**. Before
public-network use, the human operator must approve the target set, owned test
services, client configuration, aggregate cadence and request budget, time
limits, and experimental modes. Each batch has exactly one assigned target.
Membership in an approved cohort is not permission for automatic fallback or
requests to any unassigned target. An approved rollout or enforcement trial
does not implicitly authorize probes, uploads, or tests against additional
HSDirs. Stock reference relays may contribute passive comparison metrics;
active checks against them require separate explicit inclusion in the approved
probe target set.

The scope is controlled descriptor-fetch receipt and latency. It does not
measure all legitimate clients, descriptor uploads, application reachability,
or every repeated-circuit use case. In Tor 0.4.9.14, `HS_DESC RECEIVED` also
occurs for missing or bad client authorization; it is not proof that a client
can decrypt the descriptor and connect to the service. Use a test service that
does not require client authorization, or separately verify the test client's
authorization. Never label these results a network-wide legitimate-client
failure rate.

## Required preflight

The future implementation must refuse to start a measurement batch unless all
of the following are explicit and verified:

1. **Consent, target, and mode.** Record the operator's approval reference,
   allowed phase, immutable assigned target, and declared comparison role for
   the batch. The target's actual enforcement state must be known, with
   timestamped state checks bounding the batch. Do not infer mode from cohort
   membership. Unknown, contradictory, or changing state blocks new submissions
   and invalidates attribution to a stable mode. Match patched-off and
   patched-on checks using the predeclared schedule, client/fixture policy,
   deadlines, and request budgets; do not choose checks afterward by outcome.
2. **Dedicated stock client.** Use a probe-only stock Tor client with its own
   process, control endpoint, and DataDirectory, separate from all relays and
   any user's browsing client. Prove process ownership before any cleanup.
   This helper must never restart, stop, reload, or reset the canary or another
   relay. No unrelated application may use the probe client during a batch.
3. **Owned descriptor fixture.** The test service belongs to the operator and
   the assigned target is known to hold its current, valid descriptor. Verify
   fixture readiness separately for every target and maintain it across
   descriptor time-period changes. An arbitrary owned service need not be
   stored by an approved target; an expected 404 is not collateral damage.
   Any controlled publication needed to establish the fixture requires a
   separately approved preparation step. Do not infer that `SERVER=` makes
   the assigned target responsible for the service or causes it to obtain a
   descriptor.
4. **One target per batch and no fallback.** Each explicit request names only
   the batch's assigned target. Validate that the chosen client configuration
   disables automatic descriptor refetches, including retries to another
   approved cohort member or back to the assigned target. All measured fetches
   must originate from the scheduled explicit command. `SERVER=` alone is
   insufficient: it selects the initial request's destination, while teardown
   can enter the ordinary refetch path. If no supported, validated way to
   prevent fallback is available, public-network probing remains blocked.
5. **Client readiness.** Authentication, event subscription, bootstrap,
   usable directory information, target availability, and fixture readiness
   are established before timing a fetch. Use bounded setup deadlines.
   Bootstrap and recovery time are recorded separately from fetch latency.
6. **Explicit limits.** Supply a low request cadence, maximum attempts,
   maximum batch duration, per-attempt deadline, setup/recovery deadlines,
   and bounded input-buffer sizes. Do not inherit the existing script's
   0.5-second gap. The approved minimum interval applies between submission
   starts; never run parallel attempts within a client or catch up after missed
   slots. Maintain one global cadence and total request budget across all
   targets, batches, and probe clients, with any additional per-target caps.
   Expanding the approved cohort must not multiply load by creating independent
   per-relay budgets. Exhausting the global budget blocks every new submission.
7. **Private storage.** Agree on a local protected output location, access
   controls, retention period, and deletion owner. Verify storage availability
   before submission; inability to record an outcome ends the batch.

One candidate to investigate in the isolated lab is
`FetchHidServDescriptors=0` on the **probe client only**: the 0.4.9.14 automatic
refetch guard checks it, while explicit HSFETCH uses a different launch path.
This is a source-supported candidate, **not a validated recipe**. Acceptance
must establish that explicit requests work and failure paths produce no
automatic descriptor fetches, even to an approved target. Do not change any
relay's configuration for it.

## Protocol and state model

Use an incremental Tor control-protocol parser, not a loop that treats every
line beginning with `5` as failure or every HS event as the current request.
Handle fragmented lines, multiline replies, and interleaved asynchronous
events, with explicit size limits. Authentication material must never be
logged. Subscribe only to necessary event classes; do not subscribe to or
persist `HS_DESC_CONTENT`, HTTP bodies, or descriptor payloads.

A batch moves through `PREFLIGHT -> READY -> PENDING -> READY` for verified,
unambiguous receipt successes only. Any non-success, including FAILED, command
rejection, unresolved timeout, I/O failure, unexpected protocol state, target
violation, or correlation ambiguity moves it to `ABORTED`.
`ABORTED` has no transition back to `READY` in the same client generation.
This rule applies across **all** targets: selecting a different cohort member
does not clear a pending request or permit work after an abort. At most one
request may be outstanding in a probe-client process, regardless of target.

Change targets only between cleanly completed batches, after the prior batch's
reply/event handling and validated lifecycle checks establish no unresolved
work. Run target, fixture, mode, and budget preflight again. Reusing the same
dedicated client after a clean batch is allowed; a new client per relay is not
required unless the validated lifecycle contract requires stronger isolation.
Record every target/batch transition privately. Never round-robin targets
within a batch or use a target change as timeout recovery.

For each attempted submission:

1. Allocate a local batch/attempt number, bind it to the assigned target and
   declared comparison role, and record UTC for comparison with relay metrics.
   Local numbers and cohort labels are bookkeeping; Tor does not echo them as
   request identifiers.
2. **Start a monotonic deadline before writing the HSFETCH command.** Include
   command-write time, the final command reply, REQUESTED, and terminal-event
   processing in the same bounded attempt. Socket inactivity timeouts alone
   are insufficient: unrelated events must not extend the total deadline.
3. Allow only one outstanding command/fetch per client across all targets.
   Track the final command reply separately from asynchronous events. A
   `250 OK` acknowledges acceptance of the command, not successful descriptor
   retrieval. A rejected command is a measured non-success, not an unsubmitted
   attempt.
4. Correlate events to the normalized service address and canonical HSDir
   identity. Normalize optional address suffix/case and control-protocol
   identity decoration using validated formats; do not compare nicknames.
   Verify descriptor context against the matching REQUESTED event and the
   fixture's expected time period when available. Never accept an event for
   another service, server, descriptor context, or client generation. An event
   from a different approved relay is still unrelated to this batch; cohort
   membership never makes it a valid match.
5. Require a consistent command reply and matching REQUESTED/terminal
   sequence for a verified result. Tor 0.4.9.14 sends command OK before the
   launch events. Parse interleaving without losing events; unexpected order,
   missing prerequisites, or contradictory replies must not fabricate success.
   REQUESTED records a launch attempt, not proof the request reached the HSDir.
6. End the timed outcome on a verified RECEIVED, verified FAILED, command
   rejection, or the absolute deadline/error. Record the observed sequence
   and classify an incomplete sequence separately. A matching terminal event
   without the required reply/context is unverified, not a receipt success.
7. Before another normal attempt after success, fully process the prior
   command reply and terminal event, check already buffered events for
   duplicates, enforce the minimum interval, and ensure no unresolved work
   remains. A duplicate terminal or contradictory event is an ambiguity
   requiring batch abort, not another success. Non-success ends the batch.

HS_DESC events have no per-HSFETCH request ID. Matching the same
service/server/descriptor tuple cannot, by itself, distinguish a late event
from an earlier identical request. One outstanding request and event matching
are necessary but do not solve that protocol limitation. In particular, never
start a new request after a timeout and attribute the next matching event to
it. If an implementation claims it can distinguish otherwise identical late
events without an additional isolation boundary, reject that claim. A later
implementation must document and validate its pinned stock-Tor lifecycle
contract for normal sequential reuse: a successful, fully handled request
leaves no earlier fetch or retry that can supply a later terminal event. A
buffer check alone is not proof of that contract. Arbitrarily fabricated
identical late events cannot be attributed with certainty. If the real Tor
lab produces that pattern after a supposedly resolved success, acceptance
fails and batches/client generations must be isolated further. A reset after
every successful request is not required when the validated contract holds.
Do not silently erase this limitation from the report.

## Timeout, cancellation, and recovery

`TIMEOUT` means no verified result was obtained before the local deadline. It
does not mean Tor emitted FAILED, that the request stopped, or that the target
never served the response. Record the timeout once and abort the batch.

Do not wait indefinitely for RECEIVED/FAILED. In 0.4.9.14, HTTP 503 is handled
before the HS-specific response handler and can leave no corresponding
HS_DESC terminal event. Closing a circuit can emit a stream-close event;
neither `CLOSECIRCUIT` nor a control `250 OK` proves immediate HS_DESC FAILED
or absence of pending/refetched work. Reconnecting the ControlPort, closing
the helper socket, and `NEWNYM` are not cancellation guarantees.

Before a new batch after a non-success or unresolved work, stop the
**dedicated probe-client process**, verify that exact process has exited, and
then start/reset the client under its approved lifecycle policy. This applies
even if the next batch would use a different target. Verify readiness again.
If process ownership, shutdown, or readiness cannot be established within its
bounded deadline, stop the experiment and report the gap; do not keep attempting
recovery or launch a second overlapping client.

Keep the probe client's DataDirectory and guard state across approved restarts
where supported; do not delete its directory or rotate identities/guards to
obtain favorable results. A reset clears live pending work through process
exit, not by deleting persistent state. Apply the same policy in observation
and enforcement modes. Report restart counts, recovery gaps, and warmup
exclusions because freshly built circuits and bootstrap delays can change the
latency distribution. Preserve only the private data needed for that policy
and the agreed retention period.

An ambiguity or mode change while an attempt is pending must yield an explicit
indeterminate/aborted outcome for that submitted attempt. Safety cleanup must
not remove it from the denominator or turn it into a success.

## Outcomes, denominators, and reporting

The goal is to measure legitimate-client impact within this controlled test's
scope, not to demonstrate that enforcement succeeds. Preregister acceptable
receipt/timeout/latency bounds and the minimum coverage/precision needed for a
comparison. A policy that lowers traffic while causing unacceptable test-client
harm is not a benefit. Preserve no detectable benefit, regression and mixed
tradeoffs alongside any improvement; insufficient precision/exposure remains
inconclusive. Do not selectively repeat successful-looking batches or discard
valid failed/time-out outcomes to obtain a favorable result.

Distinguish **policy outcomes** from **collector correctness**. A correct helper
may faithfully observe policy-related failure or regression. That is a valid
experiment result, while broken correlation or accounting is a collector fault
that limits inference. Passing helper acceptance is not evidence of a benign
or effective enforcement policy.

Keep a private append-only record of attempted submissions, bounded metadata
from relevant control events, outcome, and recovery. Do not store authentication
secrets, payloads, descriptor contents, or unrelated client events. Event
identifiers needed for correlation remain private and are removed from shared
reports.

Count an attempt once when command submission is first attempted. If a write
fails after an uncertain partial submission, retain the attempt as
`submission_indeterminate`; do not assume it was never sent. Separately record
whether the command was acknowledged. Preflight failures and missed schedule
slots have no submitted request and belong in coverage/recovery gaps.

For each assigned target and verified stable mode, report:

- Attempted submissions, acknowledged commands, verified RECEIVED, verified
  FAILED, command rejections, timeouts, and indeterminate/protocol/I/O outcomes.
  Every submitted attempt has exactly one outcome; categories reconcile.
- Descriptor-receipt success fraction: verified RECEIVED divided by **all
  attempted submissions**, including failures, timeouts, and indeterminate
  submissions. Also show the outcome counts so collector failures remain
  visible. This is an experiment-level receipt fraction, not an attribution
  of every failure to enforcement.
- Receipt latency quantiles for verified receipts, explicitly labeled as
  conditional on success, plus the deadline and timeout fraction. Never
  silently drop timeouts or insert them as exact measured latency values.
- Planned/observed coverage, elapsed duration, mode checks, client resets,
  fixture gaps, and recovery gaps. Samples crossing a mode transition remain
  in the audit totals but are excluded from either stable-mode comparison.
- Client version, target artifact version/digest, declared comparison role,
  relevant settings, test limitations, and consistent timing definitions.
  Name the initial pilot `pilot`; use stable opaque IDs for later approved
  targets and keep their identity mapping private. Omit service addresses,
  descriptors, fingerprints, nicknames, hostnames, addresses, and control or
  monitoring endpoints from shared output.

Reconcile target/mode totals with the global attempt budget. Keep individual
target results available when producing matched patched-off versus patched-on
comparisons; cohort aggregation must not hide uneven probe coverage or mode
changes. Compare stock references separately from patched-off controls, since
the former also differ in software. Do not relabel stock observations as an
estimate of the toggles' isolated effect.

No number inferred from a missing event may be reported as measured HTTP 503,
actual circuit closure, or actual client receipt. Receipt tests do not replace
the relay-side counters or demonstrate application-level success.

## Acceptance matrix for a future implementation

All cases below are **required future checks, not executed results**. Use
deterministic mock control-protocol transcripts first, then a separate,
isolated loopback/private Tor lab with a stock probe client and controlled
fixtures. The acceptance suite must not contact public Tor relays or onion
services. Confirm that the lab configuration itself prevents public-network
access. No test execution is part of this documentation change.

| Case | Required observable behavior |
| --- | --- |
| Valid descriptor receipt | One acknowledged submission with matching REQUESTED and RECEIVED produces one verified receipt and monotonic latency; no duplicate count. |
| HTTP 404 / NOT_FOUND | Record the matching failure once and abort the batch; do not interpret an absent fixture as evidence of collateral damage. |
| HTTP 503 with no HS terminal event | Deadline expires, one timeout is retained, batch aborts, and no new submission occurs before verified client-process reset. No endless drain. |
| No reply and no event | Bound write/read/whole-attempt duration; record timeout or submission uncertainty and abort. |
| Missing REQUESTED | A later apparent terminal cannot become a verified success without the required context; classify incomplete/indeterminate and stop within the deadline. |
| Missing final command reply | REQUESTED/terminal events do not silently substitute for the reply; no verified success and no unbounded wait. |
| Reply timing and event ordering | Delayed ACK consumes the same deadline; unrelated events may interleave; inconsistent ordering or contradictory reply fails closed without misattribution. |
| Fragmented and multiline input | Partial reads and protocol continuation lines parse correctly; bounded buffers and total deadline remain effective. |
| Interleaved unrelated events | Wrong service, HSDir, or descriptor context never satisfies the pending request or resets its deadline. Evidence of unexpected descriptor fetch activity aborts the batch. |
| Event from another approved cohort member | Never attribute it to the assigned target, count it as its success, or silently change the batch target; detect unexpected fetch activity and abort. |
| Concurrent submission to a different approved target | Reject it while any request is pending in that client. One-outstanding applies across the entire client, not once per target. |
| Target change between batches | Permit only after a clean completed batch and renewed target/fixture/mode/budget checks; keep target immutable within each batch. No forced client restart is required after a validated clean completion. |
| Late same-tuple event after timeout | Batch is already aborted: retain the timeout, do not begin another request, and never turn the late event into a new attempt's success. |
| Target switch after timeout or ambiguity | Block all new targets in that client generation until verified probe-client process reset and readiness. An approved alternate target is not a recovery mechanism. |
| Indistinguishable same-tuple event across attempts | Document the protocol limit; a test must not claim a local sequence number solves it. Validate the pinned stock-Tor success/terminal contract. If the real lab produces an old terminal after a later REQUESTED despite resolved success, fail acceptance and require stronger batch/client-generation isolation. |
| Duplicate terminal event | Count at most once; detected ambiguity stops the batch. No duplicate success or denominator drift. |
| EOF or read error | Stop promptly with one explicit outcome, no busy loop, and no new submission in that client generation. |
| Write failure / partial command | Preserve submission uncertainty in the denominator; deadline and batch abort still apply. |
| Continuous unrelated event stream | The monotonic deadline expires on time despite ongoing readable input. |
| Circuit/stream closes without HS FAILED | No terminal-event assumption; bound the attempt and require verified client-process cleanup before recovery. |
| Reconnect or NEWNYM without process exit | Must not satisfy the reset prerequisite or authorize another request after unresolved work. |
| Client reset fails or readiness never returns | Recovery has a bounded end; report the gap and stop. Never touch a relay or spawn an overlapping client. |
| Wrong process ownership | Refuse cleanup and further probes; do not kill an inferred or unverified process. |
| Automatic fallback or retry attempt | Fail acceptance if the configured stock client automatically fetches the descriptor after any tested outcome, including 404, 503, connection loss, and cancellation. This includes the assigned target and every other approved cohort member. |
| Unknown or changed enforcement mode | Block new submissions; preserve and mark pending/transition samples indeterminate for mode attribution. Assigned cohort role cannot override the target's measured mode. |
| Missing consent or passive-only phase | Preflight rejects the batch before any HSFETCH or test-descriptor publication. |
| Fixture missing, expired, or wrong authorization | Block or explicitly mark fixture-invalid measurements; never attribute these failures to enforcement. |
| Rate/budget boundary and missed slots | Enforce explicit global cadence and total budget across clients/targets, plus per-target caps; no per-client parallel requests or catch-up burst. Adding targets does not reset or multiply budget. |
| Matched off/on schedule or artifact mismatch | Reject an undeclared comparison or mismatched patched artifact; retain excluded samples in accounting and document the gap rather than selecting favorable replacements. |
| Sensitive output or full buffers | No payload/authentication content in logs; bounded metadata storage; public output passes identifier redaction. |
| Accounting reconciliation | Every attempted submission appears once; failures/timeouts stay in the denominator; recovery gaps are reported separately. |
| Neutral or adverse policy outcome | A correctly observed no-gain or degraded receipt/latency scenario is preserved and reportable under the declared assessment rule. Lower traffic/resource figures cannot hide failed attempts; the helper is not required to manufacture a positive policy conclusion. |

The isolated stock-client lab must additionally establish that explicit
HSFETCH bypasses the client descriptor cache, reaches each batch's assigned
fixture, and produces no automatic descriptor retries or fallback across the
complete failure matrix, including when several lab targets are approved.
Verify the actual path and circuit/stream isolation rather than asserting a
fixed hop count from the helper: Tor 0.4.9.14 normally adds
the selected HSDir to its anonymous path, and client options can affect path
length. Sequential stock fetches do not by themselves exercise every request
reuse pattern the relay defense can encounter.

Acceptance evidence should name the stock-client version, configuration,
fixture revision, deterministic transcript cases, lab isolation controls, and
results. Only after implementation and these checks pass may the operator
review a concrete low-rate public-network probe proposal. Keep this document's
status unchanged until real evidence exists; a successful documentation review
does not make the helper implemented, tested, or approved for live use.

## Source basis for the requirements

The reviewed Tor 0.4.9.14 paths explain the relevant limits:

- `src/feature/control/control_cmd.c`, `handle_control_hsfetch`: command OK
  precedes launch events; HSFETCH ignores the descriptor cache. SERVER selects
  initial destinations. `handle_control_closecircuit` marks closure and replies
  OK; it does not promise a particular HS terminal event.
- `src/feature/hs/hs_client.c`, `directory_launch_v3_desc_fetch`,
  `client_dir_fetch_200`, `can_client_refetch_desc`, and
  `hs_client_refetch_hsdesc`: REQUESTED follows launch; RECEIVED includes
  authorization-related decode outcomes; ordinary refetch has separate guards
  and destination selection.
- `src/feature/dirclient/dirclient.c`, `connection_dir_client_reached_eof` and
  `connection_dir_client_refetch_hsdesc_if_needed`: HTTP 503 returns before the
  HS response handler, and connection cleanup can enter ordinary refetch.
- `src/core/or/connection_edge.c`, `connection_edge_destroy`: circuit
  teardown emits stream closure, not a guaranteed HS_DESC FAILED.
- [`engineering/tools/hsfetch.py`](../engineering/tools/hsfetch.py): current
  event matching, per-read timeout, and default gap do not meet this design.

Recheck these assumptions against the exact stock-client version selected for
the future experiment. Source review is not a substitute for the acceptance
checks above.
