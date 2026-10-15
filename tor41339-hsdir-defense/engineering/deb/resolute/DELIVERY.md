# Native Ubuntu 26.04 artifact: builder delivery for the build handoff

This answers `../../../operator/NATIVE-26.04-BUILD-HANDOFF.md` item by item.
It is the builder's evidence for review. It is not deployment authorization,
and the rollout owner still resolves host-specific gaps (listed at the end).
Everything below ran on an isolated build host, in containers; every Tor
process ran in a private loopback-only test network or with no network
interface at all. Nothing touched a production relay or the public Tor network.

## Artifact

| Item | Value |
|---|---|
| Package path | `tor41339-hsdir-defense/packages/tor_0.4.9.14-1~resolute+1+tor41339.3_amd64.deb` |
| Version | `0.4.9.14-1~resolute+1+tor41339.3` (distinct from the Noble `~noble+1+tor41339.3`, which is kept unchanged under its own filename) |
| Package SHA256 | `2bfc8e7012685d9d5d21a4b4fb4bc1174bef4544e6203eff868f9d1d90b973b7` |
| Extracted `usr/bin/tor` SHA256 | `b0df9de1fe27d125ebb64b2e2b80ba30b0aeb4c76f875ee598d49cb4421516b7` |
| Extracted `usr/bin/tor-gencert` SHA256 | `f6fba4a59225e6250150ff47b26f0ead0ab8370b07a21335e9bedb13a5074ae0` |
| Optional data package | `tor-geoipdb_0.4.9.14-1~resolute+1+tor41339.3_all.deb`, SHA256 `a9cb18647f9399ec2291907bdd5fba85e131cd07c6e1c0cc09ead6d736e76f42` (GeoIP data, no code; not needed for the swap) |
| Checksum manifest | `../../../packages/SHA256SUMS` (all four `.deb`s); `.buildinfo` / `.changes` beside them |

Checksums published in the same repository detect corruption; they do not
independently authenticate the build. The `.buildinfo` records the exact
build-dependency versions for anyone rebuilding to compare.

## Source base and patches

- Source package: deb.torproject.org `tor_0.4.9.14-1~resolute+1` (the
  official 26.04 build of the stock release). `.orig.tar.gz` sha256
  `182449ac1c8ff43278da27b69b02040e11d03d0327db6d9126e4190ec6235e4a` (identical
  to dist.torproject.org `tor-0.4.9.14.tar.gz`); `.diff.gz` sha256
  `3e9af7768b449c4808e8bfc504e66907c83e393c2e68e51cadc731c042f35804`, matching
  its `.dsc`. Its Debian packaging differs from the Noble one only in the
  changelog entry.
- Patches: the seven `../../../patches/0001…0007-*.patch`, **unchanged**,
  byte-identical to the branch's `patches/` at `6ce9b53` (that commit was
  `2b8ae1a` before the branch was rebased onto `main`; same content), plus
  `0000-restore-doc-nofooter.conf.patch` (restores a doc build file the release
  tarball omits). Per-patch SHA256s: `../../../packages/BUILD-INFO.txt`. No
  C instrumentation, unrelated fix or automatic enforcement mode was added.

## Builder environment, compiler, flags, libraries

- Driver: `../build-reordered/build-in-container-reordered.sh` with
  `SUITE=resolute` (`dpkg-buildpackage -b`, `set -o pipefail`).
- Image: fresh `ubuntu:26.04` (Canonical LTS image, Ubuntu 26.04.1), digest
  `sha256:51e35c02a42cf2a6646c5879f5752b38098ed0a20056a989f0af3a3c5e697c9a`.
- Compiler: gcc 15.2.0 (`gcc-15 15.2.0-16ubuntu1`).
- Compile flags for `tor` (Ubuntu's `dpkg-buildflags` plus tor's hardening):
  `-g -O2 -flto=auto -ffat-lto-objects -fstack-protector-strong
  -fstack-protector-all -fstack-clash-protection -fcf-protection=full
  -D_FORTIFY_SOURCE=3 -fno-omit-frame-pointer -mno-omit-leaf-frame-pointer
  -fPIE -fasynchronous-unwind-tables -Wformat -Werror=format-security`.
  Link: `-pie -Wl,-z,relro -Wl,-z,now -Wl,-Bsymbolic-functions`.
- Configure (from `debian/rules`, identical to the Noble build):
  `--enable-systemd --enable-gpl --enable-gcc-warnings-advisory` plus the
  Debian defaults. Feature summary: crypto **OpenSSL** (NSS no); libseccomp,
  libscrypt, systemd, liblzma, libzstd yes; compiler and linker hardening yes;
  modules relay, dirauth, dircache, pow. Full text:
  `parity-vs-noble.txt`.
- Linked libraries (NEEDED): `libc.so.6 libcap.so.2 libcrypto.so.3
  libevent-2.1.so.7 liblzma.so.5 libm.so.6 libseccomp.so.2 libssl.so.3
  libsystemd.so.0 libz.so.1 libzstd.so.1`. Runtime versions on 26.04.1:
  OpenSSL 3.5.5, libevent 2.1.12, zlib 1.3.1, liblzma 5.8.3, libzstd 1.5.7.
  `Depends:` is identical to the stock 26.04 package.
- Type=notify support: built `--enable-systemd` and linked to `libsystemd`;
  readiness observed under systemd (below).

## Packaged units and scripts vs stock

Compared with the official unpatched `tor_0.4.9.14-1~resolute+1_amd64.deb`
(sha256 `61f382e60bc59922973ee64f20fabb3aea0fde15851fbcfa1bb6fb4bd8b2fc41`):

- **Identical:**
  - the file list;
  - maintainer scripts (`preinst`, `postinst`, `prerm`, `postrm`) and
    `conffiles`;
  - systemd units (`tor.service`, `tor@.service`, `tor@default.service`) and
    default torrcs;
  - all control fields except `Version`/`Installed-Size`.
- **Different:**
  - `usr/bin/*` (the patched code);
  - `tor.1` / `tor.html` (the two new options documented, plus build dates
    and one asciidoc escape from the restored doc config);
  - `tor-instance-create.8` (build date only);
  - `changelog.Debian.gz` (our entry).

## Validation evidence

1. **Hashes and tests.** Source and patch hashes verified as above.
   `dh_auto_test` runs `make test`, the complete unit-test binary
   `src/test/test`: **1613 ok, 24 skipped, 0 failed**. The 24 skips are
   environment-conditional upstream tests, the same set as the Noble build:
   - 20 `tortls/openssl/*` legacy-OpenSSL tests;
   - `config/include_no_permission` (runs as root);
   - `sandbox/opendir_dirname` and `sandbox/stat_filename`;
   - `util/load_win_lib`.

   No compiler warning on any line the series adds. Full `make check` (unit,
   slow and script tests) on the same patched 26.04 tree: **running at the time
   of this delivery commit**; its result is added as `make-check-summary.txt`
   in a follow-up commit (the artifact does not change).
2. **Dependencies, startup, readiness, counters.**
   - Dependencies: `apt-get install` of only the `tor` package resolved in a
     fresh 26.04 container (`install-run-transcript.txt`), with no missing
     libraries.
   - Startup in a private chutney net: `--verify-config` rc 0, Bootstrapped
     100%, all four `tor_relay_dos_total{type="hsdir_*"}` types present.
   - systemd 259 (`systemd/systemd-transcript.txt`): the `Type=notify`
     `tor@CANARY` reached `active/running` 0.51 s after exec; for this unit
     type that means tor sent `READY=1`. The unit's stock `ExecStartPre`
     verify (stock binary) passed on every start.
3. **Controls** (`controls/`).
   - Setup: a private chutney net in a 26.04 container with no network
     interface, every node running the packaged binary under `Sandbox 1`.
   - Load at one target HSDir: a reuse load (fetches sharing circuits), a
     one-hop load from an unpublished relay identity, and a stock client
     fetching once per fresh circuit.
   - 40 s per phase. Counter deltas are total / repeat requests / reused
     circuits / unknown previous hop:

   | Phase | 0002, 0001 | Reuse served | One-hop served | Stock client | Deltas |
   |---|---|---|---|---|---|
   | default | auto, auto | 100/100 | 20/20 | 43/43 | 163 / 118 / 2 / 20 |
   | explicit off | 0, 0 | 100/100 | 20/20 | 43/43 | 163 / 120 / 0 / 20 |
   | 0002 on | 1, 0 | 0/100 | 10/20 | 42/42 | 103 / 30 / 28 / 20 |
   | 0002 off, live | 0, 0 | 100/100 | 20/20 | 41/41 | 161 / 119 / 2 / 20 |
   | 0001 on | 0, 1 | 100/100 | 0/20 | 43/43 | 163 / 120 / 0 / 20 |
   | 0001 off, live | 0, 0 | 100/100 | 20/20 | 43/43 | 163 / 120 / 0 / 20 |

   What the table shows:
   - **Counters count before decisions:** refused requests are still counted
     (repeat requests and reused circuits while 0002 closes circuits; all 20
     one-hop requests while 0001 returns 503).
   - **Each rule works alone:** it affects only its own target traffic. The
     stock client stayed at 100%.
   - **Live disable:** turning a rule off restores service with the same PID,
     no restart. Both options ended at `auto`.
   - **Sandbox under enforcement:** 0 "Caught a bad syscall" across all node
     logs.
   - **Why 0002 served 0 of 100 reuse fetches:** the reuse load pipelines 5
     fetches per circuit. The second fetch closes the circuit, which also
     drops the first response still in flight.
   - **Why 0002 served 10 of 20 one-hop fetches:** the one-hop client reuses
     its circuit, so every other fetch closes it.
4. **Allocator and systemd restrictions** (`systemd/`).
   - Setup:
     - Two instances, CANARY and SIBLING, each with the fleet's per-instance
       `allocator.conf`, `Environment="LD_PRELOAD=/usr/local/lib/mimalloc/libmimalloc-2.0.9.so"`.
     - mimalloc built from upstream tag `v2.0.9` (commit `28cf67e5`) with
       cmake and gcc 15. `.so` sha256
       `5d8f2655c2f7be60689ca6e4630664dc4050ac699f0fc1144d6f78cfd63e85c3`.
     - Both instances run `Sandbox 1` under the stock unit's hardening
       (`NoNewPrivileges`, `PrivateDevices`, `ProtectSystem`, …).
   - The drop-in kept the preload: `Environment` was unchanged, and mimalloc
     was mapped in every patched process.
   - **Tor Sandbox vs systemd filter:** the canary showed 4 seccomp filters
     with `Sandbox 1` and 3 with `Sandbox 0`. `GETCONF Sandbox` returned 1 and
     0 to match. Tor's own sandbox is exactly one filter; the rest come from
     systemd's unit settings and the container.
   - 0 bad syscalls with mimalloc preloaded under `Sandbox 1`.
5. **Startup/stop and per-instance override** (`systemd/`,
   `sigterm-trials.txt`).
   - Override and rollback: the `zz-tor41339.conf` drop-in, the patched
     binary's `--verify-config`, then one restart of `tor@CANARY`. The
     restart took 30.6 s, and the canary ran `/opt/tor41339/usr/bin/tor` as
     `_tor-CANARY`.
   - Live `SETCONF` toggles and a `reload` (which reverts them to `auto`)
     kept the same PID.
   - Rollback (remove the drop-in, daemon-reload, restart) restored
     `/usr/bin/tor`.
   - **SIBLING:** same PID and `NRestarts=0` through every step.
   - Stop behaviour:
     - Graceful restarts took about 30.5 s (tor's `ShutdownWaitLength`).
     - The rollback stop took 60.7 s: the patched process ignored SIGINT
       under `Sandbox 1`, and systemd killed it at `TimeoutStopSec`.
   - That stop behaviour is the pre-existing upstream bug tor#41060, measured
     with `../../seccomp/sigterm-repro.sh` on 26.04.1 (glibc 2.43):

     | Package | `Sandbox 1` stuck | `Sandbox 0` stuck |
     |---|---|---|
     | Stock 26.04 package | 6/15 | 0/5 |
     | Patched package | 5/15 | 0/5 |

## Not covered here (host-specific or out of the builder's scope)

- **AppArmor:** attachment of the production host's profile to the `/opt`
  path. A container cannot reproduce the host's LSM state; check
  `/proc/<pid>/attr/current` on the host.
- **Real sibling relays:** in the systemd test the SIBLING ran Ubuntu's archive
  tor 0.4.9.11, not deb.torproject.org's stock 0.4.9.14, and both instances
  used a fake loopback authority, not real relays.
- **Load client:** the controls lab's load client is the test-only build
  (patched tree + `../../../simulator/loadclient-testonly.diff`) compiled on
  24.04 and run on 26.04 libraries. The HSDir under test was the packaged
  binary.
- **Revised operator procedures:** the revised preflight, maintenance,
  probe-helper and trial procedures in `../../../operator/` are documentation
  owned by the rollout. They were not executed here.
- **Production conditions:** behaviour under a real flood, on production
  hardware, with production consensus parameters, is untested by design.
