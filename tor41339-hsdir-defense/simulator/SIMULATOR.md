# Closed-lab BEGIN_DIR/HSDir flood benchmark

This describes a **defensive, loopback-only** benchmark. It runs entirely
inside a private chutney test network with its own directory authorities and
consensus and **no connection to the real Tor network**. Its only purpose is to
measure whether the patches in `../patches/` reduce an HSDir's resource cost
under load while preserving legitimate access. The "load" is a high rate of
ordinary, well-formed HS descriptor requests issued over the control port to
throwaway nodes you created — there is no exploit, no malformed-cell weapon, and
nothing that targets relays you do not own. Do not point any of this at the
live network.


**Network.** Use chutney's `networks/hs-v3` (or a copy) scaled up: ≥4 dir authorities, ≥6 relays all carrying the HSDir flag, ≥3 onion services, ≥2 stock clients, and 1+ "load" client. Every node runs your patched `tor` . Add `TestingTorNetwork 1` (already implied by chutney), `MetricsPort` on each relay (`MetricsPortPolicy accept 127.0.0.1`), and `HeartbeatPeriod 5 seconds`. The whole thing is loopback; it has no route to the public network.

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

**Controls & rigor.** Run each cell ≥3× for variance; include a no-load baseline and an unpatched-binary baseline; pin the consensus for A/B except in the consensus-churn test; record exact tor/chutney commits and torrc. Emit a CSV + a short report with one graph per metric (requests/s vs served, vs CPU, vs legit-success). Explicitly log any cap/truncation so a bounded run isn't read as "covered everything."

**Success criterion (the milestone):** a reproducible demonstration that with enforcement on, the HSDir's served-response bytes and CPU under the reuse load drop toward the one-per-circuit floor **while the stock client's success rate stays ~100%**, and a quantified statement of what the one-request-per-circuit adaptation then costs the attacker (more circuits → onionskin/CREATE load on middles, where DoSCircuitCreation does not apply to relay channels). Negative results are fine and must be reported as-is.

---

## 7. Deliverables back

## Harness pieces in this directory
- `loadclient-testonly.diff` — test-only client change: `EVIL_ISO_SESSIONGRP` makes a client reuse one circuit for several HS fetches; `EVIL_ONEHOP` makes an unpublished relay do one-hop fetches. Throwaway; never for upstream.
- `ctl.py` — control-port driver starting point (HSFETCH loop with cache purge).
