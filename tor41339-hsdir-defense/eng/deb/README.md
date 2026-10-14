# amd64 noble `.deb`: lab build artifact

> **NOT FOR DEPLOYMENT YET.** This package is a lab artifact. It has not
> completed review. Do **not** install it on a live relay or HSDir until the
> series review clears and the operator runbook on `tor41339-hsdir-defense`
> points at a released, validated package.

- `packages/`: `tor_0.4.9.14-1~noble+1+tor41339.1_amd64.deb` and
  `tor-geoipdb_…_all.deb`, with `SHA256SUMS`, `.buildinfo` and `.changes`.
- `build/`: how it was built. A fresh `ubuntu:24.04` container ran
  `build-in-container.sh` on the deb.torproject.org noble source package
  `tor_0.4.9.14-1~noble+1`. The orig tarball sha256 is `182449ac…5e4a`,
  identical to dist.torproject.org. The quilt series in `debian-patches/`
  is:
  - `0000` restores `doc/nofooter.conf`, which the release tarball omits;
  - `0001`–`0007` are the v3 patches in their original order. The reordered
    series changes only commit boundaries and `exceptions.txt`, so the
    compiled code is the same.

  `dh_auto_test` passed: 1613 tests ok.
- `install-run/`: install and run test. A second fresh `ubuntu:24.04`
  container installed the packages and ran `tor --verify-config` on the
  default and lab torrcs. It then ran an unpublished relay (MetricsPort,
  `Sandbox 1`) joined only to a private loopback chutney network.
  - It reached Bootstrapped 100%, with `Seccomp: 2` and 0 bad syscalls.
  - `tor_relay_dos_total{type="hsdir_circ_reused"}` and
    `{type="hsdir_unknown_prev_hop"}` stayed at 0 for 120 s.
  - `tor --dump-config full` shows `HSDirOneRequestPerCircuit auto` and
    `HSDirRefuseUnknownPrevHop auto`. The lab consensus has no `hsdir_*`
    params, so enforcement is off and the relay only counts.
  - `first-attempt-INVALID-port-clash/` is kept for transparency. That run
    shared chutney's fixed ports with another lab net and never bootstrapped.

## Rebuild from the reordered series (`…+tor41339.2`)

This build exists for provenance: its source order matches the series
proposed upstream (`../series-reordered/`). It is still **not for
deployment**, as above.

- `packages-reordered/`: `tor_0.4.9.14-1~noble+1+tor41339.2_amd64.deb`,
  sha256 `379f8afa…7b02`. Same pipeline; the quilt series is `0000`
  followed by the reordered `0001`–`0007`. `dh_auto_test`: 1613 ok.
- **Code identity with `…+tor41339.1`:** in `/usr/bin/tor`, `.text`,
  `.rodata` and `.data` are byte-identical and the address-normalized
  disassembly diff is 0 lines. Only `.note.gnu.build-id` differs. See
  `packages-reordered/code-identity-vs-tor41339.1.txt`.
- `install-run-reordered/`: fresh-container install. `--verify-config`
  returns 0 for both torrcs. The private-net relay reached Bootstrapped 100%
  and was reachable, with `Seccomp: 2`, both `hsdir_*` counters at 0 over
  120 s, and 0 bad syscalls.

**Shutdown with `Sandbox 1`.** In this run tor did **not** exit within 5 s
of SIGTERM. This is the known upstream bug tor#41060, and it is present on
unpatched `main` too. On glibc 2.39, after the seccomp filter is installed,
`pthread_create`'s `rt_sigprocmask(SIG_BLOCK)` is refused with EPERM, and
glibc then restores an uninitialized signal mask that blocks
TERM/INT/QUIT. See `../seccomp/out/anomaly/`. A controlled repro gave:
Sandbox 1, stuck 15/15 for patched and for stock; Sandbox 0, exited 15/15
for both. Operators running `Sandbox 1` should expect systemd to fall back
to SIGKILL at `TimeoutStopSec`. This is independent of this series.
