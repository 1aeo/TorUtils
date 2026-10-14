# Upstream CI matrix on amd64: patched vs unpatched

**What ran.** Each cell is tor's own `scripts/ci/ci-driver.sh`, with the
environment variables of the matching job in the tree's `.gitlab-ci.yml`.
- Each cell runs in a fresh git worktree, once on unpatched `main`
  (8dbbbe6e86) and once on `main` plus the v3 series.
- Host: Ubuntu 24.04, gcc 13.3 and clang 18. Upstream CI uses Debian
  bookworm images. Toolchain differences cancel out because every cell
  compares patched with unpatched on the same host.
- `--enable-fatal-warnings` is on in every cell, as in upstream CI.
- `integration` uses chutney at the CI pin 3338f5ca on a private loopback
  network.

**Regression rule.** A regression is anything that passes unpatched but
fails patched.

## Result: no regressions

| Cell | Unpatched | Patched | Regression? |
|---|---|---|---|
| minimal | green | green | no |
| hardened (clang, ASan/UBSan, `ALL_BUGS_ARE_FATAL`) | `unittest_part7`: 5 `sandbox/*` cases abort under LeakSanitizer | identical | no |
| distcheck | green (archives ready) | green (archives ready) | no |
| disable-relay | `test_cbt_mvp.sh` FAIL (tor#41148), 2 of 2 runs | green | no |
| disable-dirauth | green | green | no |
| gpl | green | green | no |
| nss | green | green | no |
| docs (doxygen + asciidoc) | green | green | no |
| tracing (LTTng, distcheck) | green | green | no |
| integration (chutney `test-network-all` + stem) | chutney 4/8 pass (IPv4); IPv6 flavours and stem fail | identical | no |

The generated table is in `CI-DIFF.md` (built by `scripts/ci-diff.py` from
the logs). Raw results are in `RESULTS.txt`, and the gzipped per-cell logs
are in `logs/`.

## Environmental failures, identical on both sides

- **hardened.** In `unittest_part7`, `sandbox/is_active`,
  `chmod_filename`, `chown_filename`, `rename_filename` and `crypto_equix`
  abort with LeakSanitizer "Can't open /proc/PID/task", because LSan cannot
  read `/proc` from inside the seccomp sandbox in this container. Neither
  side has any ASan, UBSan or leak report.
- **integration.** The container has no IPv6 (creating an `AF_INET6`
  socket fails with EAFNOSUPPORT), so this fails on both sides:
  - chutney's `bridges+ipv6-min`, `hs-v3-ipv6`, `ipv6-exit-min` and
    `single-onion-v3-ipv6-md` flavours fail;
  - stem's test tor cannot bind `[::]:1113`.

  `basic-min`, `bridges-min`, `hs-v3-min` and `single-onion-v3` pass on
  both sides.
  - **Stem was not re-run.** Its integration target runs a tor with the
    default directory authorities, which would contact the public Tor
    network. This work stays loopback-only, so I did not rerun it with an
    IPv4-only workaround.
- **`test_cbt_mvp.sh` (tor#41148, a known flake).** It failed only in the
  unpatched `disable-relay` cell, twice. It passed in every patched run.
- **First pass (`logs-first-pass/`).** minimal, hardened, distcheck and
  disable-relay first ran with `PYTHONUNBUFFERED=1` inherited from this
  cloud session. That makes `scripts/maint/practracker/test_practracker.sh`
  fail, by changing how its stderr and stdout interleave relative to
  `testdata/ex0-expected.txt`. The failure was the same on both sides, and
  the test passes once the variable is unset. Those cells were rerun clean,
  and the table above uses the reruns.
