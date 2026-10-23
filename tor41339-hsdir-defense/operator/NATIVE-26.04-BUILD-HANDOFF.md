# Native Ubuntu 26.04 artifact handoff for the vipopen experiment

**Owner: the separate builder agent designated by the human operator.** This
document specifies the artifact this plan will consume. The documentation agent
must not build, install, publish a substitute package, implement the probe
helper, or deploy as part of this update. The builder's separate authorization
comes from the operator, not from reading this file.

## Requested artifact

- Ubuntu **26.04 / Resolute**, **amd64**, Tor **0.4.9.14**, using the existing
  packaging workflow and all **seven patches 0001–0007 unchanged**.
- Retain the four existing MetricsPort counter types and both live controls;
  do not add C instrumentation, unrelated fixes or an automatic enforcement mode.
- Match the required production feature set, including systemd Type=notify
  support. State compiler, build flags, crypto/library choices and source base.
- Keep the Noble package and its historical evidence recoverable. The new
  artifact must be distinctly versioned and identifiable; do not relabel or
  replace the Noble file under its old filename.
- Publish the actual artifact path/version, package SHA256, extracted binary
  SHA256, source commit/patch hashes, source-package provenance, pinned builder
  environment, dependency/link information, and actual test results to the
  repository. Do not invent a package filename in the deployment runbook before
  delivery. Record skipped/failed/unavailable checks honestly.

The `.deb` is a transport artifact for **unpacking**. It will not be installed
host-wide in this experiment. If the packaged units/scripts differ from stock,
explain them in provenance, even though production uses a per-instance override.

## Validation evidence expected from the builder

Run validation only under the builder's separate authorization in an isolated
Ubuntu 26.04 environment; no production relay or public-network load tests.

1. Verify source and patch hashes and run the existing relevant/full unit suite.
   Identify the exact test set and outcomes; earlier Noble results do not prove
   this native build has passed.
2. Verify dependency resolution, startup and configuration validation, systemd
   notification readiness, and all four MetricsPort types in a private lab.
3. Check both default controls and explicit off settings. Confirm counters
   increment before decisions and remain available when each rule is enabled
   individually and then disabled live. Validate the existing behavior rather
   than changing the C series to make a test pass silently.
4. Exercise applicable host security/allocator settings, including the existing
   mimalloc preload and systemd restrictions, in the 26.04 lab where reproducible.
   Clearly separate Tor Sandbox state from systemd's syscall filter; a process
   reporting seccomp alone does not establish Tor's Sandbox setting.
5. Record startup/stop behavior, including any sandbox-related issue. Verify a
   per-instance override/rollback in the isolated environment without package
   installation actions affecting sibling relay processes.

No artifact is accepted merely because `--version` or a strings check passes.
The rollout owner reviews the submitted evidence and resolves any host-specific
validation gaps before the single pilot restart.

## Delivery and experiment freeze

Deliver on **tor41339-hsdir-defense-clean**, alongside code and the plan, as
requested by the operator. Coordinate through normal non-forced Git updates;
preserve concurrent documentation commits. The documentation updater must
likewise preserve the builder's commits and never overwrite its artifacts.

Once delivered, record the reviewed commit, actual package path/version and
both hashes in the private rollout manifest. Freeze that one artifact for the
pilot and every expanded patched member. Do not let later builder pushes
silently change the artifact used in a running cohort.

The older Noble binary passed static ABI inspection on vipopen, but that does
not replace this native-build requirement or prove runtime readiness. Until
the native artifact and its evidence are delivered and accepted, the rollout
is **waiting for the builder**, with no deployment implied.
