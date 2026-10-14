# Seccomp validation of the NEW enforcement branches (amd64, Sandbox 1)

Closes the one seccomp item the stock-traffic runs could not: that 0001's
`circuit_mark_for_close` (RESOURCELIMIT) and 0002's 503 refusal issue no
sandbox-denied syscall. Private loopback chutney net, target HSDir `004r` under
`Sandbox 1`, 0001+0002 enforcing, driven by reuse-22 then one-hop load from the
test-only load clients while the target was audited with strace.

## Why strace, not just "0 bad syscall"
Tor's sandbox is `seccomp_init(SCMP_ACT_ERRNO(EPERM))` — a denied syscall
returns EPERM *silently*; it does not raise SIGSYS / "Caught a bad syscall". So
`bad_syscall=0` is necessary but weak. The strong test is an strace EPERM audit
of the live process while the new branches fire.

## Result (target 004r, Sandbox 1)
- `Seccomp: 2`, `Seccomp_filters: 1`; `bad_syscall=0` throughout.
- Branches confirmed firing during the strace windows: `hsdir_circ_reused`
  2 → 19, `hsdir_unknown_prev_hop` 0 → 40; reuse-22 served **1/418**, one-hop
  served **1/40** — i.e. 0001 closed the reused circuits and 0002 refused the
  unknown-prev-hop requests, *under the sandbox*.
- **EPERM audit over each 60 s enforcement window: empty** — zero denied
  syscalls on the new code paths.

## Method validated (so "empty" means clean, not "strace didn't run")
A standalone `tor-patched` launched under `Sandbox 1` + `DisableNetwork 1`,
straced from startup, captured 32 failed syscalls including **5 EPERM: 4×
`rt_sigprocmask`, 1× `rt_sigaction`** — the glibc-2.39 pthread_create signal
setup the filter denies. This (a) proves strace attaches to and captures EPERM
from a sandboxed tor, so the empty steady-state windows are genuine, and (b)
independently reproduces the pre-existing upstream tor#41060 mechanism (stock
*and* patched ignore SIGTERM under Sandbox 1 because glibc leaves a
pointer-shaped signal mask after that denied `rt_sigprocmask(SIG_BLOCK)`). These
EPERMs fire only at thread creation (startup), outside the enforcement windows,
and are not from the patch.

## Cross-confirmation (independent broad EPERM audit)
A separate audit straced every thread of all 9 sandboxed relays/authorities
across 3× verify + 18 HSFETCH + DirPort probes, patched vs unpatched. The only
EPERM returns anywhere were a benign baseline set: `setsockopt(SOL_TCP,
TCP_ULP, "tls")` (OpenSSL's kernel-TLS probe per new TLS conn — the filter
refuses it, OpenSSL falls back to userspace TLS; pre-existing in stock),
an occasional `openat("/proc/sys/vm/overcommit_memory")`, and the startup
`rt_sigprocmask(SIG_BLOCK)`. Counts: patched-default 25, patched-enforce 12,
unpatched-control 1 (+1 overcommit) — all TCP_ULP, scaling with new-connection
count (OR-conns 189/170/157). **The patched EPERM set is a subset of stock.**
My new-branches windows showing an empty EPERM set is consistent with this:
the reuse/one-hop load reuses established channels, so few new-TLS TCP_ULP
probes fell inside the 60 s windows, and nothing outside the benign baseline
appeared on the close/503 branches. The two audits together are definitive.

## Conclusion
The new enforcement branches add **no sandbox-denied syscall** on amd64. The
amd64 seccomp gate is closed for both the stock paths (0 bad syscalls across
patched-default / patched-enforce / unpatched control) and the new
close/503 branches (this audit). Teardown of a Sandbox-1 net needs a SIGKILL
fallback because of tor#41060.
