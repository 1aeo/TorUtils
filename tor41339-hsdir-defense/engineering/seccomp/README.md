# Seccomp sandbox check (amd64)

All runs use a private, loopback-only chutney network (its own authorities and
consensus). Patched tor runs on the authorities and relays with `Sandbox 1`.
The onion service and the client are stock (unpatched) tor.

- `hs-v3-sandbox`: chutney network script. Set env `STOCK_TOR` to the stock
  tor binary and `RELAY_EXTRA` to optional extra relay torrc lines.
- `run-seccomp.sh <label> <relay-tor> [extra-torrc]`: brings the net up, runs
  chutney verify plus 10 ordinary single HSFETCHes from the stock client, and
  sends single DirPort probes. Then it records `/proc/<pid>/status` Seccomp
  mode and scans every node log for `Caught a bad syscall`.
- `dirport-probes.py <port>`: sends single malformed or oversized HTTP requests
  to one lab node's DirPort on 127.0.0.1. These drive the 0003, 0004 and 0005
  parser paths.
- `sandbox-check.sh <datadir>...`: read-only evidence collector for any lab
  node. It reports the torrc Sandbox value, the live Seccomp mode
  (2 = filter), the bad-syscall count and the `hsdir_*` DoS metrics.

## Results

- `out/`: three configurations under `Sandbox 1`: patched-default,
  patched-enforce (`HSDirOneRequestPerCircuit 1`,
  `HSDirRefuseUnknownPrevHop 1`) and unpatched-control.
  - 33/33 tor processes show `Seccomp: 2`.
  - 0 "Caught a bad syscall".
  - 4/4 verify rounds pass in each configuration.
  - 18 single HSFETCHes each: 16 RECEIVED and 2 NOT_FOUND, from an HSDir
    that is not on the ring. The pattern is the same in all three.
  - DirPort probes show 0004 under the sandbox. On a relay, an oversized
    declared or actual body is rejected at once by patched tor; unpatched
    tor waits for the body or buffers it.
- `out-strace-audit/`: the **EPERM audit**. Tor's filter is
  `seccomp_init(SCMP_ACT_ERRNO(EPERM))`, so a refused syscall returns EPERM
  silently and does not raise SIGSYS. The audit therefore attaches
  `strace -f -e status=failed` to every thread of every sandboxed relay and
  authority during the traffic phase. Per-configuration summary
  (`EPERM-SUMMARY.txt`):
  - **patched-default:** only `setsockopt(SOL_TCP, TCP_ULP, "tls")`, 25
    times.
  - **patched-enforce:** the same call, 12 times.
  - **unpatched-control:** the same call once, plus one
    `openat("/proc/sys/vm/overcommit_memory")`.

  `TCP_ULP` with value 0x736c74 ("tls") is OpenSSL's kernel-TLS probe on a
  new connection. The filter refuses it and OpenSSL falls back to userspace
  TLS. The count follows how many connections were opened while strace was
  attached. Whole-run OR-connection counts are comparable: 189, 170 and 157.
  The patched EPERM set is a subset of the stock set, so **the patches add
  no denied syscall** on these paths.
- **Shutdown correction.** Under `Sandbox 1`, nodes do **not** exit on
  SIGINT or SIGTERM, on patched and stock alike (upstream tor#41060; see
  `out/anomaly/`). `chutney stop` sends SIGINT twice and then SIGKILL. The
  earlier note "all nodes exited on chutney stop" meant they were gone
  afterwards, not that they shut down cleanly.
- **New enforcement branches, covered by the closed-lab benchmark.** Stock
  traffic cannot reach these branches. The closed-lab benchmark ran
  `sandbox-check.sh` with `STRACE_SECS=60` on target `004r` under
  `Sandbox 1`, with 0001 + 0002 enforcing, while reuse-22 and then one-hop
  load ran. Evidence: branch `tor41339-hsdir-defense` at 275ae51, in
  `simulator/results/seccomp-newbranches-validation.md` and
  `seccomp-evidence/`.
  - The branches did fire: `hsdir_circ_reused` went 2 → 19 and
    `hsdir_unknown_prev_hop` 0 → 40. Reuse served 1/418; one-hop served
    1/40.
  - `Seccomp: 2`, 0 "Caught a bad syscall", and the **EPERM audit is empty**
    in each 60 s enforcement window.
  - A control run (sandboxed tor traced from startup) captured EPERM for the
    tor#41060 startup signal setup (`rt_sigprocmask` ×4, `rt_sigaction` ×1),
    so the empty windows are a real result.
  - The empty windows also agree with this audit. The kTLS `TCP_ULP` probe
    only happens when a new TLS connection opens, and the target opened none
    during those windows.

**Seccomp conclusion (amd64).** Neither the stock paths (this audit) nor
the new circuit-close and 503 branches (the closed-lab benchmark audit) produce a
syscall that the sandbox refuses. The only EPERMs seen anywhere are
pre-existing and also occur on stock tor: OpenSSL's kTLS probe, glibc's
`overcommit_memory` read, and the tor#41060 thread-creation signal setup.
