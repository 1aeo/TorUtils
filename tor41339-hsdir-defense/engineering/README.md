# tor#41339 defensive series: amd64 engineering results

**Scope.** Native amd64 build and unit tests, the upstream CI matrix
(patched vs unpatched), the seccomp sandbox check, the deb.torproject.org
noble `.deb`, and the mechanical finalization of the series and the torspec
text.

**Environment.**
- Host: Ubuntu 24.04.5, x86-64, gcc 13.3, clang 18.
- tor `main` at 8dbbbe6e86. chutney at the CI pin 3338f5ca.
- Tarball `tor-0.4.9.14.tar.gz` sha256 `182449ac…5e4a`, verified. The
  deb.torproject.org noble `.orig.tar.gz` has the same hash.

**Network.** Every network run here is a private, loopback-only chutney
network with its own directory authorities and consensus. No traffic went to
the real Tor network. Only stock (unpatched) tor clients and onion services
generated traffic, as ordinary single requests.

**Method.** Every claim below is a patched-vs-unpatched comparison on the same
host, so toolchain or host noise cancels out.

## Summary

| Item | Result |
|---|---|
| A.1 build, `--enable-fatal-warnings` | patched: 0 warnings |
| A.1 unit tests | patched **1613 ok / 0 fail**; unpatched 1602 (the series adds 11) |
| A.1 `make check` scripts | equal on both sides (see the note on `test_practracker.sh` below) |
| CI matrix (ci-driver.sh) | **No regressions** (nothing passes unpatched and fails patched). Green on both sides: minimal, distcheck, disable-dirauth, gpl, nss, docs, tracing. disable-relay: green patched; the unpatched run failed `test_cbt_mvp` (tor#41148). Environmental failures identical on both sides: hardened LSan in `sandbox/*`; integration IPv6 flavours and stem (no IPv6 in the container). See `ci-matrix/` |
| Seccomp (`Sandbox 1`, amd64) | 33/33 processes in seccomp filter mode (`Seccomp: 2`); 0 "Caught a bad syscall". Stock HS GET/POST and DirPort parser paths behave identically to unpatched (0004 visible). **EPERM audit** (the filter's default action is EPERM, not SIGSYS; strace on every thread of every sandboxed relay/authority): patched-default and patched-enforce return EPERM only for OpenSSL's kTLS probe `setsockopt(SOL_TCP, TCP_ULP, "tls")`. The unpatched control shows the same probe plus glibc's `/proc/sys/vm/overcommit_memory` read. So the patched EPERM set is a subset of stock: **no new denied syscall**. See `seccomp/out-strace-audit/` |
| `.deb` (deb.torproject.org noble 0.4.9.14-1~noble+1 + series) | built in a fresh 24.04 container (`dh_auto_test`: 1613 ok). Installs in a fresh 24.04 container; `--verify-config` passes; private-net relay reaches Bootstrapped 100%; `hsdir_circ_reused 0`; enforcement `auto` (off). See `deb/` |
| Reordered series (0002 first) | final tree identical to v3 plus 3 practracker exception lines. **All 7 commits** build with 0 warnings and pass `make check`, `check-spaces` and `check-changes` (unit ok 1603 → 1613). See `series-reordered/` |
| torspec | ready-to-apply patch in `../patches/torspec-param-spec.patch`; placement appended to `../patches/torspec-draft.txt` |

## Environment notes (not regressions)

- **`scripts/maint/practracker/test_practracker.sh`.** It fails whenever
  `PYTHONUNBUFFERED=1` is in the environment, which this build environment
  exports. Unbuffered stdout changes how the self-test's stderr and stdout
  interleave relative to `testdata/ex0-expected.txt`. It fails identically on
  unpatched `main`, and it passes once the variable is unset. All final CI
  cells and the per-commit runs have it unset.
- **`debian-hardened` (clang ASan/UBSan, `ALL_BUGS_ARE_FATAL`).** In
  `unittest_part7` the 5 tests `sandbox/is_active`, `chmod_filename`,
  `chown_filename`, `rename_filename` and `crypto_equix` abort with
  LeakSanitizer "Can't open /proc/PID/task". This happens identically on
  unpatched `main`: LSan cannot read `/proc` from inside the sandbox in this
  container. Neither side has any ASan, UBSan or leak finding.
- **`test_cbt_mvp.sh` (tor#41148).** It passed in A.1 on both sides. In the
  CI matrix it failed once, in the **unpatched** `disable-relay` cell, which
  confirms it is a pre-existing flake.
- **Sandboxed tor ignores SIGTERM: upstream tor#41060 (open), present on
  unpatched `main`.**
  - Controlled repro with `DisableNetwork 1`: under `Sandbox 1`, the tor
    process did not exit on SIGTERM in 15/15 runs, for both patched and
    stock. Under `Sandbox 0`, it exited in 15/15 runs for both.
  - Cause, from strace (`seccomp/out/anomaly/`): once the filter is
    installed, glibc 2.39 `pthread_create` calls
    `rt_sigprocmask(SIG_BLOCK, ~[], &old)`. The filter refuses it with EPERM,
    because it allows SIG_BLOCK only in fragile-hardening and LTTng builds.
    glibc then restores the uninitialized `old` set with `SIG_SETMASK`.
  - Result: the main thread blocks INT, QUIT and TERM. This explains the
    earlier "SIGTERM-blocked" observation, and the reordered `.deb`'s tor
    not exiting on SIGTERM. Neither is caused by the series.

## Not covered here

- **Runtime coverage of two enforcement branches: done in the closed-lab
  benchmark.** Stock traffic cannot reach the 0002 circuit-close (RESOURCELIMIT)
  or the 0001 503. The closed-lab benchmark exercised both under `Sandbox 1`.
  Counters rose (`hsdir_circ_reused` 2 → 19, `hsdir_unknown_prev_hop` 0 → 40),
  there were 0 bad syscalls, and the EPERM audit was empty in each 60 s
  window. Evidence: `tor41339-hsdir-defense` at 275ae51,
  `simulator/results/seccomp-newbranches-validation.md`. Summarized in
  `seccomp/README.md`.
- **Patch 0001's false-positive rate under consensus churn** is measured in
  the closed-lab benchmark (`../analysis/prevhop-false-positive.md`).
