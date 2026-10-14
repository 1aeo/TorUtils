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
| CI matrix (ci-driver.sh) | see `ci-matrix/` (*pending final table*) |
| Seccomp (`Sandbox 1`, amd64) | **0 bad syscalls**. 33/33 processes in seccomp filter mode (`Seccomp: 2`). Stock HS GET/POST and DirPort parser paths exercised. See `seccomp/` |
| `.deb` (deb.torproject.org noble 0.4.9.14-1~noble+1 + series) | built in a fresh 24.04 container (`dh_auto_test`: 1613 ok). Installs in a fresh 24.04 container; `--verify-config` passes; private-net relay reaches Bootstrapped 100%; `hsdir_circ_reused 0`; enforcement `auto` (off). See `deb/` |
| Reordered series (0002 first) | final tree identical to v3 plus 3 practracker exception lines. Per-commit build and test: see `series-reordered/` (*pending final run*) |
| torspec | ready-to-apply patch in `torspec/`; placement appended to `../patches/torspec-draft.txt` |

## Environment notes (not regressions)

- **`scripts/maint/practracker/test_practracker.sh`.** It fails whenever
  `PYTHONUNBUFFERED=1` is in the environment, which this cloud session
  exports. Unbuffered stdout changes how the self-test's stderr and stdout
  interleave relative to `testdata/ex0-expected.txt`. It fails identically on
  unpatched `main`, and it passes once the variable is unset. CI cells run
  after this was found unset it, and the earlier cells are rerun clean.
- **`debian-hardened` (clang ASan/UBSan, `ALL_BUGS_ARE_FATAL`).** In
  `unittest_part7` the 5 tests `sandbox/is_active`, `chmod_filename`,
  `chown_filename`, `rename_filename` and `crypto_equix` abort with
  LeakSanitizer "Can't open /proc/PID/task". This happens identically on
  unpatched `main`: LSan cannot read `/proc` from inside the sandbox in this
  container. Neither side has any ASan, UBSan or leak finding.
- **`test_cbt_mvp.sh` (tor#41148).** It passed in A.1 on both sides. In the
  CI matrix it failed once, in the **unpatched** `disable-relay` cell, which
  confirms it is a pre-existing flake.
- **Seccomp anomaly.** One harness run was aborted (my harness shell was
  killed). Afterwards, 6 of 11 tor processes, two of them the **stock**
  binary, had SIGTERM blocked in the main thread with a pointer-like
  `SigBlk` mask, and ignored SIGTERM. This did not reproduce in 3 clean runs
  (33 processes, all exited on `chutney stop`). It is not attributable to the
  patches. Evidence is in `seccomp/out/anomaly/`.

## Not covered here

- **Runtime coverage of two enforcement branches.** The 0001
  circuit-close (RESOURCELIMIT) branch and the 0002 503 branch cannot be
  reached under seccomp with stock traffic, because a stock client never
  reuses a circuit and always arrives from a known previous hop.
  - Static audit: the added non-test code makes no direct syscalls.
    `circuit_mark_for_close` only marks the circuit, and the close runs
    through the same mainloop path every circuit close uses.
    `write_short_http_response` is tor's existing 503 writer, and here it
    returned a 503 under `Sandbox 1` with 0 bad syscalls.
  - The benchmark track runs its enforcement-on cells with the target HSDir
    under `Sandbox 1` and collects `seccomp/sandbox-check.sh` output. That
    output will be added here when it arrives.
- **Patch 0002's false-positive rate under consensus churn** (Task C) moved
  to the benchmark track.
