# Paste-over prompt: continue the tor#41339 HSDir-flood defensive work on x86/Linux

You are continuing an in-progress **defensive security** effort for Tor **relay operators** whose Guard/HSDir relays are affected by the 2026 BEGIN_DIR/onion-service-descriptor flood tracked upstream as **tor#41339**. The goal is a small, upstreamable patch series for **Tor 0.4.9.14** that bounds the flood's resource cost on an HSDir while preserving all legitimate directory traffic, plus a **closed-lab benchmark** that measures the patches' effect so we do not have to wait for live-network data.

Everything below is defensive and must stay that way. Hard rules:
- **All load testing runs only inside a private, self-contained `chutney` test network** (its own directory authorities, its own consensus, loopback only). **Never** point any generator, client, or relay at the real Tor network, and never build anything whose purpose is to send traffic to relays you do not own. The simulator exists to benchmark a defense on your own throwaway nodes.
- The "flood" is just a high **rate of ordinary, well-formed BEGIN_DIR / HSDir requests** issued over the control port inside that private net. There is no exploit, no malformed-cell weapon, no targeting logic. If a task seems to call for anything that would work against the live network, stop and reduce it to the private-lab equivalent.
- Keep the operator-confidentiality rule: no real hostnames, IPs, fingerprints, or infra details in anything that could become public (commit messages, MRs, issue comments).

Prior work was done on an arm64 Mac; arm is the bottleneck (qemu-emulated amd64 crashed gcc, so the amd64 package, the seccomp sandbox, and amd64 CI are all unbuilt). You are on native x86-64 Linux to remove that and to run the simulator at scale.

---

## 1. What is already established (do not re-derive; verify only if you touch it)

A 24-agent proof pass adjudicated **31 claims PROVEN, 10 PARTLY (refinements), 0 REFUTED**. Full evidence is in the handoff bundle (section 3). Highlights:

- **The gap:** in Tor 0.4.9.14, `connection_exit_begin_conn()` dispatches `BEGIN_DIR` into `connection_exit_connect_dir()` (src/core/or/connection_edge.c:4333) *before* the per-circuit stream limiter at :4340, so `DoSStreamCreation*` never applies to BEGIN_DIR. HS descriptor GET/POST handlers never call the bandwidth `write_low` check; a self-generated (unlisted) relay identity passes `connection_dir_is_anonymous()`; HSDirs store/serve any validly-signed descriptor with no hash-ring/flag check.
- **Compatibility invariant (PROVEN):** stock C Tor (`ISO_STREAM`, dirclient.c) and Arti both use **one circuit per HSDir request**; Onionbalance uploads via C Tor's HSPOST. So "one HS request per circuit" has no stock false positives except a tiny consensus-skew window for the known-relay rule (~1.2e-6 per request; worst-hour upper bound ~4e-3).
- **Field data (PROVEN/PARTLY):** the Sep–Oct wave is **fetch** traffic (write:read ~170:1), hitting **310–433 HSDirs/day** (rotating daily) at 5–133 MB/s; network dir-write rose from ~7.8 Gbit/s (June) to ~59–64 Gbit/s. HSDir pool fell from ~4,900 (May–June avg; **not** 5,400) to ~1,620. Target correlates with the **HSDir flag**, Guard-or-not.
- **Efficacy is NOT measured yet.** The "95%/80% fewer served" figures are an upper bound resting on four unverified premises (that iji's relay was an HSDir; that nearly all BEGIN_DIR were served HS requests; that flood circuits use CREATE2; that every counted stream was fully served). **This is exactly what the simulator must replace with a real measurement.**

Open limitations you are here to close:
1. **No native amd64 build** → amd64 `.deb` and the **seccomp sandbox** path untested.
2. **No under-attack measurement** → patch efficacy and the attacker-adaptation prediction are unproven.
3. 0002's false-positive rate is a model estimate, not observed under consensus churn.

---

## 2. The patch series you are continuing (v2 — the current state)

Seven commits against upstream `main` (also apply cleanly to `maint-0.4.9` and the 0.4.9.14 tag). As of the last run: **full unit suite 1613 ok / 0 fail on both main and maint-0.4.9; behavioral mutation 51/51; checkSpace + lintChanges clean; upstream CI (make check, distcheck, hardened ASan/UBSan, disable-relay/-dirauth, gpl, nss, docs, integration 8/8 chutney flavours) green on aarch64; ~378M-exec fuzz of the touched parsers found nothing.** Focus for the **deb.torproject.org** package (not Ubuntu's archive, which ships 0.4.9.11 and rejects patch 0006).

- **0001 — one onion-service dir request per circuit.** Helper `connection_dir_note_hs_request()` in directory.c (reached via dir_conn→linked edge→on_circuit); 1-bit `already_received_hsdir_request` on `or_circuit_t`; two 2-line call sites in dircache.c (GET + POST). **Enforcement (circuit close, RESOURCELIMIT) defaults OFF** — torrc `HSDirOneRequestPerCircuit` (AUTOBOOL) overrides consensus `hsdir_one_request_per_circ` overrides a count-only default. Counting is unconditional and once-per-circuit, so the heartbeat line and `tor_relay_dos_total{type="hsdir_circ_reused"}` mean the same in both modes. `connection_edge.c` untouched.
- **0002 — known previous hop for HS requests.** Separate predicate `connection_dir_check_prev_hop()` at the two HS call sites with its **own** 503 reason ("Rejecting HS request: previous hop is not a known relay"), its **own** torrc `HSDirRefuseUnknownPrevHop` + consensus `hsdir_refuse_unknown_prev_hop`, **independent of `RefuseUnknownExits`**, count-only default. `connection_dir_is_anonymous()` NOT modified.
- **0003** — rate-limit/throttle the malformed-HTTP-request warnings (down-level the parser's size/Content-Length failures). Wording corrected ("bugfix on all supported versions of Tor").
- **0004** — non-authorities cap an upload body at `hs_cache_get_max_descriptor_size()`; **now also rejects a declared `Content-Length >= max_bodylen` immediately** in `fetch_from_buf_http` (the reviewer-reproduced early-rejection gap), scoped to the `!force_complete`/dir-server path (all callers audited).
- **0005** — a dir server discards anything a client sends after its request; **now clears trailing bytes that arrive in the SAME read once state→SERVER_WRITING, preserving an incomplete COMMAND_WAIT request** (the reviewer-reproduced immediacy gap). Test rewritten to drive the real COMMAND_WAIT→SERVER_WRITING transition.
- **0006** — in `desc_decode_plaintext_v3`, check the signature length before the Ed25519 cert verification (pure move; accept set unchanged). Message softened (no absolute µs figure; notes an attacker can use a valid-length signature, so it only cheapens the 88-char padded case).
- **0007** — credit HSDir `n_downloaded` only when the response is fully flushed to the linked edge (not on every close); message states the accounting boundary (flush to edge ≠ network delivery).

Known packaging detail: 0002 edits `doc/man/tor.1.txt`, which makes the build regenerate `tor.html.in` via asciidoc; the release tarball omits `doc/nofooter.conf`. Restore that file from the `tor-0.4.9.14` tag (or keep asciidoc out of the build) when building the `.deb`.

**Before anything public:** re-author all 7 commits to one chosen identity and a single `Co-Authored-By` trailer (follow your session's attribution reminder for the exact line; make it identical across all 7). Put **0002 before 0001** (or squash them) and state that 0001 must not be backported without 0002.

---

## 3. Handoff bundle (this directory in 1aeo/torutils)

This directory (`tor41339-hsdir-defense/`) holds the bundle:
- `patches/0001..0007*.patch` — **the current series** (primary); `patches/torspec-draft.txt` — companion param-spec / rend-spec-v3 text.
- `analysis/claims-ledger.md` — the claim ledger with adjudicated verdicts (31 PROVEN / 10 PARTLY / 0 REFUTED) and corrections.
- `simulator/loadclient-testonly.diff` — the **test-only** client change (env `EVIL_ISO_SESSIONGRP` makes a client reuse one circuit for several HS fetches; `EVIL_ONEHOP` makes an unpublished relay do one-hop fetches). Drives the simulator's "reuse" and "unknown-hop" cases. Throwaway harness, never for upstream.
- `simulator/ctl.py` — control-port driver starting point. `simulator/SIMULATOR.md` — the full design (also §6 below).

These patches are v2. A finalization pass (the three fixes in `analysis/claims-ledger.md` under "PATCH DEFECTS": the POST-under-enforcement test, the heartbeat label, the 0007 ticket ref) produces v3; if `patches/` here still says v2 in the README, apply those three fixes first (they are small and described precisely).

Everything else you need, re-fetch:
- Tarball: `curl -O https://dist.torproject.org/tor-0.4.9.14.tar.gz` (sha256 `182449ac1c8ff43278da27b69b02040e11d03d0327db6d9126e4190ec6235e4a`).
- Upstream git: `git clone https://gitlab.torproject.org/tpo/core/tor.git` (base commits: main `8dbbbe6e`, maint-0.4.9 `ccd9eb86`). GitLab rate-limits clones (HTTP 429) — retry with backoff; the REST API and `/-/issues/<n>/discussions.json` work anonymously.
- chutney: `git clone https://gitlab.torproject.org/tpo/core/chutney.git` (CI pins commit `3338f5cae5dbce3f6c465326784b8b34952bcd62`). Needs Python ≥ 3.11.
- deb.torproject.org noble source: pool `main/t/tor/tor_0.4.9.14-1~noble+1.dsc` + `.orig.tar.gz` + `.diff.gz`.

---

## 4. Environment setup on x86-64 Linux

Use Debian bookworm (upstream's CI base) and Ubuntu 24.04 (the deploy target). Build deps (from upstream's CI `before_script`):
```
automake autoconf build-essential ca-certificates file git curl pkg-config \
libevent-dev liblzma-dev libscrypt-dev libseccomp-dev libssl-dev zlib1g-dev \
python3 python3-venv clang llvm libubsan1 libclang-rt-dev asciidoc xmlto doxygen \
libnss3 libnss3-dev timelimit gnupg lcov gcovr cppcheck clang-tools devscripts equivs
```
Build the reference binary:
```
tar xf tor-0.4.9.14.tar.gz && cd tor-0.4.9.14
./configure --disable-asciidoc && make -j"$(nproc)" src/app/tor src/test/test
```
Apply the series onto upstream main for CI parity:
```
mkdir -p /work && (cd /work && git clone <tor>) ; cd /work/tor
git checkout 8dbbbe6e && git checkout -b v2
git -c user.email=ci@x -c user.name=ci am /path/to/0001..0007*.patch
./autogen.sh && ./configure --enable-fatal-warnings && make -j"$(nproc)"
```

---

## 5. Priority tasks on x86 (highest value first)

### Task A — native amd64 build, seccomp sandbox, and amd64 CI (closes limitation 1)
1. Build the series on native amd64 with `--enable-fatal-warnings`; run `make check` and `make distcheck`. Expect 1613 unit tests, 0 failures (the only known flake is `test_cbt_mvp.sh`, tor#41148, a shutdown race that fails equally on unpatched — classify it against unpatched main, don't attribute it to the patches).
2. Replicate the upstream CI matrix on amd64 using the tree's `scripts/ci/ci-driver.sh` with the env vars from `gitlab-ci-main.yml`: debian-minimal, debian-hardened (`CC=clang HARDENING=yes ALL_BUGS_ARE_FATAL=yes`), debian-distcheck, debian-disable-relay, debian-disable-dirauth, debian-gpl, debian-nss, debian-docs, debian-integration. For each, run the same job on unpatched main and diff.
3. **Seccomp sandbox (amd64-only path, never run under arm):** run the patched `tor` with `Sandbox 1` as a relay in the private chutney net; confirm the new code paths (the dircache helper, the directory.c predicate, the proto_http early-reject, the hs_cache flush credit) issue no syscall the sandbox filter rejects. `grep -rn Sandbox` and `src/lib/sandbox/sandbox.c`; a sandbox violation aborts with `(Sandbox) Caught a bad syscall`. This is the single most likely amd64-specific regression and cannot be checked on arm.
4. Build the `.deb` from the deb.torproject.org noble source on amd64 (restore `doc/nofooter.conf` as in section 2), install in a fresh Ubuntu 24.04, `tor --verify-config`, start a ~2-min unpublished relay with a MetricsPort, and confirm `tor_relay_dos_total{type="hsdir_circ_reused"} 0` with enforcement off by default.

### Task B — the closed-lab attack simulator (closes limitation 2; the main new deliverable)
Build a reproducible benchmark that, **entirely inside a private chutney network**, drives a controllable rate of HSDir directory requests and measures the HSDir's resource cost and legitimate-traffic success, with the defense off vs on. Design in section 6. The deliverable is a script + a results table + graphs that answer: *does enforcement reduce resource pressure while preserving legitimate access, and what does the cheapest attacker adaptation cost?*

### Task C — 0002 false-positive rate under consensus churn (closes limitation 3)
In the private net, script authority consensus changes (add/remove a middle relay between consensus periods) and measure how often a legitimate HS fetch routed through a just-added middle gets the 0002 503 at an HSDir on the older consensus. Compare with the ~1.2e-6/request model estimate and the exit-parity baseline. Vary `hsdir_refuse_unknown_prev_hop` and the torrc override to confirm independent rollback.

### Task D — finalize for upstream
Re-author/dedupe trailers; reorder 0002 before 0001; refresh `scripts/maint/practracker/exceptions.txt` against a real in-sync tree (the tarball snapshot's exceptions file is stale); draft the tor#41339 MR text and the companion torspec MR (param-spec entries for `hsdir_one_request_per_circ` and `hsdir_refuse_unknown_prev_hop`; rend-spec-v3 one-request-per-circuit sentence) — keep all operator infra details out.

---

## 6. The closed-lab simulator — detailed design

**Network.** Use chutney's `networks/hs-v3` (or a copy) scaled up: ≥4 dir authorities, ≥6 relays all carrying the HSDir flag, ≥3 onion services, ≥2 stock clients, and 1+ "load" client. Every node runs your patched `tor` from Task A. Add `TestingTorNetwork 1` (already implied by chutney), `MetricsPort` on each relay (`MetricsPortPolicy accept 127.0.0.1`), and `HeartbeatPeriod 5 seconds`. The whole thing is loopback; it has no route to the public network.

**Load generator (benchmark driver, not a weapon).** The flood is a high *rate* of ordinary requests, generated three ways, all through the control port of nodes you own in this private net:
1. **Fetch load:** repeatedly `HSFETCH <onion> SERVER=<target-HSDir-fingerprint>` from the load client, purging the client descriptor cache between fetches (NEWNYM or a fresh client) so each is a real request to the chosen HSDir. One request per circuit is the stock path.
2. **Reuse load (the intra-circuit multiplier the patch targets):** run the load client built with `EVIL_ISO_SESSIONGRP` so several HSFETCHes share one circuit; vary requests-per-circuit over {1, 5, 22} to match the observed field ratios.
3. **Unknown-hop load (what 0002 targets):** run the generator as an unpublished relay (`EVIL_ONEHOP`, `PublishServerDescriptor 0`, `AssumeReachable 1`) doing one-hop HS fetches.
Parameterize target rate (requests/s), concurrency, and total duration. Drive it with a small Python control-port script (reuse `evidence/prior-macos-chutney/ctl.py` as a starting point). Keep a stock client running the whole time issuing normal fetches/connections, to measure legitimate success.

**Also measure the adapted attacker** the patch pushes toward: one well-formed HS request per fresh circuit (passes 0001), and — with 0002 enabled — from a *known* middle. This is the honest "after adaptation" cost the reviewer asked for.

**Measure at the target HSDir, off vs on** (sweep the matrix: enforcement {count-only default, 0001 on, 0002 on, both on} × load {fetch, reuse-5, reuse-22, one-hop, adapted-one-per-circuit}):
- CPU (per-process, main-thread %), RSS, and `tor_relay_load_onionskins_total{...}` processed/dropped.
- `tor_relay_traffic_bytes{direction=...}` and dir bytes generated vs sent; circuits created/open; `tor_relay_streams_total{type="BEGIN_DIR"}`.
- The new counter `tor_relay_dos_total{type="hsdir_circ_reused"}` and the 0002 refusal counter; circuit closes.
- **Legitimate success:** the stock client's fetch/connect success rate and latency throughout (this is the "preserving legitimate access" half — a defense that also breaks real clients fails).
- Upstream cost of the adaptation: CREATE cell rate / onionskin queue on the middle relays (to show where the cost moves).

**Controls & rigor.** Run each cell ≥3× for variance; include a no-load baseline and an unpatched-binary baseline; pin the consensus for A/B except in Task C; record exact tor/chutney commits and torrc. Emit a CSV + a short report with one graph per metric (requests/s vs served, vs CPU, vs legit-success). Explicitly log any cap/truncation so a bounded run isn't read as "covered everything."

**Success criterion (the milestone):** a reproducible demonstration that with enforcement on, the HSDir's served-response bytes and CPU under the reuse load drop toward the one-per-circuit floor **while the stock client's success rate stays ~100%**, and a quantified statement of what the one-request-per-circuit adaptation then costs the attacker (more circuits → onionskin/CREATE load on middles, where DoSCircuitCreation does not apply to relay channels). Negative results are fine and must be reported as-is.

---

## 7. Deliverables back
- amd64 CI + distcheck + sandbox results (patched vs unpatched), and the amd64 `.deb` with an install/run transcript.
- The simulator: script(s), raw CSVs, graphs, and a report with the off-vs-on matrix and the adaptation cost.
- 0002 churn false-positive measurement vs the model.
- The finalized, re-authored series (0002 first), refreshed practracker exceptions, and draft tor#41339 + torspec MR text.
- An updated `claims.md` ledger: move P6 (efficacy) and the 0002 FP-rate from estimate to measured (or report why not), and fill the amd64/sandbox rows.

Work defensively, keep it in the lab, and report negative or surprising results honestly rather than tuning the benchmark to look good.
