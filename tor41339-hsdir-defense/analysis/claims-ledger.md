# Claims ledger

Every claim below must end up PROVEN (primary evidence reproduced), REFUTED, or
UNPROVABLE-HERE (with the reason and the best available evidence). Judgments
(e.g. "upstream odds") are labelled JUDGMENT and are not proven, only argued.

## History / provenance
- H1. The comment at src/core/or/connection_edge.c:4338-4339 ("in the future we may want to have a similar defense for BEGIN_DIR and BEGIN sent to OS.") was written by trinity-1686a in commit eca9973e ("remove todos"), authored 2023-10-18, committed by David Goulet the same day.
- H2. It replaced a TODO from commit 1b907d13 (2023-09-10): "should this be moved higher to protect from a stream DoS on directory requests, and possibly against an onion service?"
- H3. In MR !756 (ticket tor#40736) dgoulet wrote: "I think this could be beneficial yes however, I do wonder if we would need different options for all 3 cases as in BEGIN general circuit, BEGIN onion service and BEGIN_DIR ... merge this as is and we can then iteratively come back for more defenses."
- H4. DoSStreamCreation first shipped in 0.4.9.1-alpha (2024-12-03) and reached stable in 0.4.9.5 (2026-02-12).
- H5. tor-0.4.9.14.tar.gz SHA-256 = 182449ac...e4a, matching dist.torproject.org; the release signature verifies with a Tor release key.
- H6. The Ubuntu 24.04 package tor 0.4.9.14-1~noble+1 (deb.torproject.org) is built from a byte-identical orig tarball and carries no application-source patches (only debian/ files).
- H7. As of 2026-10-13, upstream main (8dbbbe6e) and maint-0.4.9 (ccd9eb86) contain no BEGIN_DIR/HSDir flood limiter; tor#41339 is open; the only shipped change is the 0.4.9.13 log rate limit (MR !1048, commit 44631448e).

## Code behaviour (tor 0.4.9.14)
- K1. BEGIN_DIR returns into connection_exit_connect_dir() (connection_edge.c:4333) before dos_stream_new_begin_or_resolve_cell() (:4340), so DoSStreamCreation never applies to BEGIN_DIR.
- K2. When the OOM handler kills a circuit, marked_circuit_streams_free_bytes() also frees the linked directory connection's buffers (circuitlist.c:2502).
- K3. tor's per-circuit token bucket (token_bucket_ctr with second timestamps) cannot express a rate below 1 token/second.
- K4. connection_dir_is_global_write_low() exempts linked (tunneled BEGIN_DIR) connections via connection_is_rate_limited(); the HS descriptor GET handler never calls it; removing the exemption would make any relay whose write bucket emptied in the last second refuse all tunneled directory requests.
- K5. A client whose non-HS directory request is refused marks that relay as not Running until its next consensus (connection_dir_client_request_failed -> router_set_status).
- K6. connection_dir_is_anonymous() requires only an authenticated (non-client) previous hop, not a known relay; a self-generated relay identity passes.
- K7. Stock C tor isolates every anonymized directory request (incl. HS descriptor fetch/upload) on its own circuit (dirclient.c ISO_STREAM), and a circuit that carried an ISO_STREAM stream is never reused for another stream. This holds for every C tor version still on the network.
- K8. Arti makes each HSDir fetch and upload on a fresh circuit (all Arti versions that can fetch/upload v3 descriptors). Onionbalance uploads through C tor's HSPOST.
- K9. C tor's HSPOST validates the descriptor locally and rejects an 88-character signature with "554 Invalid descriptor"; stock C tor always writes 86-character (unpadded) signatures; current stem and Arti write 86; tor-netdoc 0.6.3-0.9.0 (2023) wrote padded signatures.
- K10. Tor already closes an intro-point circuit that receives a second INTRODUCE1 (already_received_introduce1).
- K11. DoSStreamCreation is absent from the 2026-10-13 07:00 consensus (so off unless torrc enables it); its source defaults are rate 100/s, burst 300.
- K12. Relays without DirCache fetch directory documents over one-hop BEGIN_DIR circuits on authenticated (non-client) channels, and those requests may share a circuit (ISO_SESSIONGRP).
- K13. HSDirs store and serve any validly signed descriptor without checking hash-ring responsibility or holding the HSDir flag.
- K14. PoW protects only the introduction phase, which happens after the descriptor fetch.
- K15. Guard and HSDir flags both require DirCache (tunnelled-dir-server); hidden-service-dir is always advertised.

## Data
- D1. Tor Metrics dirbytes: dirwrite June median 7.8 Gbit/s; 70 Gbit/s on 2026-07-22; Sep median 63.6; Oct (to the 9th) median 58.9; dirread 7.9 Gbit/s on 2026-08-28 vs ~0.55 baseline.
- D2. CollecTor extra-info: ~360-430 HSDirs/day carry 5-133 MB/s of directory responses; the hit set rotates daily; every large outlier held HSDir; Guard status makes no difference.
- D3. It is fetch traffic (extra dirwrite : extra dirread ~170:1), not consensus downloads.
- D4. Median ~16 KB generated per response (assuming ~95-byte requests).
- D5. On 72-88 relays, dirreq-write-history exceeds write-history (generated > sent).
- D6. HSDir pool: ~5,400 (May-June) -> ~2,300 (2026-10-10, daily average) -> 1,620 in the 2026-10-13 07:00 consensus, of which 1,233 are Guards.
- D7. Field reports: iji 1,167 BEGIN_DIR/s with ~53 new circuits/s; jko 1,940 -> 2,050 BEGIN_DIR/s at 100 -> 105 MiB/s, then ~4,100/s with >800 onionskins/s, 13-17k -> ~80k circuits, ~12 GB; KhanKrum 1,400-2,300/s at 70-115 MB/s and 676/s at 7.1 MB/s; forest >10,000/s on Oct 13; forest's patch "did nothing whatsoever".
- D8. forest may never have enabled the limiter: DoSStreamCreationEnabled defaults off and his mail misspelled the option.
- D9. gk's PoW remark was about the analysis#113 circuit/INTRODUCE wave, not this flood.

## Patches
- P1. 0002 closes a circuit (RESOURCELIMIT) on its second onion-service directory request; helper in directory.c, two 2-line call sites in dircache.c, 1-bit flag; +77 non-test lines (48 non-comment); consensus param hsdir_one_request_per_circ default 1; counts in heartbeat and tor_relay_dos_total{type="hsdir_circ_reused"} even when the param is 0; connection_edge.c untouched.
- P2. 0001 changes one expression in connection_dir_is_anonymous() (+6/-2 executable) to require a known relay unless should_refuse_unknown_exits() is false.
- P3. 0003-0005 (+21/-9 non-test) throttle the HTTP warnings, cap non-authority request bodies at the HS descriptor max, discard input after the request; no effect on the fetch flood.
- P4. 0006 is a pure move (net -1) that skips one Ed25519 verification (~26 us) per wrong-length upload; accept/reject set unchanged.
- P5. 0007 (+12/-16) credits n_downloaded only once the response is written out.
- P6. Effect estimate: before attacker adaptation, 0002 cuts served HS responses ~95% at iji's relay and ~80% at jko's (bound: served <= number of circuits).
- P7. Dropping the DoSStreamCreation hoist is right: off in consensus; default burst 300 is 14-60x above 5-22 per circuit; wrong layer.
- P8. After adaptation (one circuit per request) the cost moves to circuit creation, which DoSCircuitCreation does not cover on relay channels.
- P9. Full unit suite 1587/1588 (the failure is pre-existing on macOS); checkSpace and lintChanges clean; practracker +2 lines in an already-over-budget function.
- P10. chutney (macOS): 96/96 uploads, 16/16 fetches, zero refusals; a circuit-reusing client had its circuit closed on the 2nd request; an unpublished relay's one-hop fetches got 503 from every HSDir; the off switch works.
- P11. The series applies cleanly to upstream main and maint-0.4.9, and to the Ubuntu 24.04 package source.
- P12. JUDGMENT: upstream acceptance odds as stated (0001 high once discussed, 0002 high, 0003-5 high/medium, 0006 high, 0007 medium).

---
# ADJUDICATED VERDICTS
# 31 PROVEN, 10 PARTLY (refinements, not refutations), 2 JUDGMENT, 0 REFUTED.

PROVEN (high confidence, independently reproduced):
  H1 H2 H3 H4 H5 H6 H7  (provenance; GPG release sig by dgoulet+ahf keys in README; full deb.torproject.org chain)
  K1 K2 K3 K6 K9 K10 K13 K14 K15  (code behaviour; HSPOST rejects 88-char sig at runtime; no responsibility/flag check)
  K7 K8  (invariant: C tor ISO_STREAM + Arti fresh circuit per HSDir request; 2758 lab HS requests, 0 false closes)
  D1 D3 D7  (metrics units confirmed Gbit/s; fetch not consensus; field quotes verbatim)
  P1 P2 P9 P10  (sizes/placement; CI make check+distcheck+hardened+modules+gpl+nss+docs+integration 8/8 on main AND maint-0.4.9; 378M fuzz execs 0 findings; 9 static analyzers 0 real new; coverage maps every line)

PARTLY (refined, see corrections in this file's body):
  K4 (write-low scope narrower), K5 (is_running also restored by new channel/SIGHUP), K12 (one-hop sharing scoped)
  D2 (310-433 HSDirs/day; Guard DOES differ: non-Guard HSDirs hit too), D4 (16 KB only under 95-byte-request assumption),
  D5 (66-98 relays/day dw>wh), D6 (pool ~4,900 May-June NOT 5,400; min 628 on 08-02), D8 (misspelling argument dropped),
  D9 (gk PoW remark about intro-phase wave; exclusion is our inference), P6 (95%/80% upper bound; 4 unverified premises), P11 (deb build needs nofooter.conf; arm64 only)

JUDGMENT (not provable): P7 (dropping hoist is right), P12 (upstream acceptance odds)

KEY LIMITATIONS to disclose:
  - amd64 never built natively (qemu crashed gcc); seccomp-sandboxed amd64 .deb unbuilt. Patches are arch-neutral C.
  - No under-attack/real-network test; P6/P8 are predictions; 0001 FP rate (~1.2e-6/req, worst-hour upper bound ~4.2e-3) is a model estimate.
  - Series applies to deb.torproject.org noble 0.4.9.14 pkg, NOT Ubuntu archive tor 0.4.9.11 (0006 fails there).
  - 503 on HS fetch emits no HS_DESC FAILED event (absence of FAILED != absence of 503).

PATCH DEFECTS fixed in v2: authorship/dup-trailers; series order (0001 before 0002);
  overclaiming wording; 0002 default-on + no torrc override; 0001 coupled to RefuseUnknownExits;
  0004 declared-Content-Length early rejection; 0005 immediate-clear + transition test; 6 killer tests (mutation 78%->100%).

---
# x86 MEASURED UPDATE (2026-10-14, native amd64 + closed-lab matrix)
Moves the open limitations from estimate to measured. Evidence on this branch
under simulator/results/ and analysis/.

- LIMITATION #1 (amd64 never built; seccomp unbuilt) — CLOSED. amd64 gcc 13.3
  --enable-fatal-warnings 0 warnings; unit suite 1613 ok/0 fail; Sandbox 1 clean
  (Seccomp:2, 0 "bad syscall") across patched-default/enforce/unpatched; the new
  0002-close and 0001-503 branches add no EPERM-denied syscall (two independent
  strace EPERM audits; patched set is a subset of stock); amd64 .deb built,
  installed, count-only-at-default metric confirmed; CI matrix shows no patch
  regression (practracker = PYTHONUNBUFFERED artifact, hardened LSan aborts
  identical on unpatched, tor#41148 reproduced on UNPATCHED). Reordered series
  (0001 first) builds commit-by-commit.
- P6 (efficacy) — MEASURED (was 95%/80% upper bound w/ 4 unverified premises).
  Off-vs-on matrix: under enforcement the HSDir serves <=1 descriptor per
  circuit (1/n floor); the pipelining test client records ~0% (client-side
  artifact, NOT zero service), within-build written-bytes -81% reuse-22,
  -67% reuse-5, and the one-hop vector 100%->~3%, stock client ~100%
  throughout. Lab ratios not
  absolute rates; 5% lab-transient flake gated + reported.
- P8 (adaptation cost) — direction confirmed; multiplier analytic (lab onionskin
  background-dominated). One-per-circuit moves CREATE/onionskin load to middles
  where DoSCircuitCreation does not apply to relay channels.
- 0001 FP rate — LAB-BOUNDED (was ~1.2e-6 model estimate). 2,416 legit fetches,
  0001 enforcing, RefuseUnknownExits=0 -> 0 false 503s; bound < 4.1e-4,
  consistent with the model; steady-state mechanism confirmed; AUTOBOOL rollback
  + independence verified. Induced-skew window = follow-up.
- OPERATOR REAL-FLOOD CAPTURE (stock relays) — flood real & field-scale
  (~1,119 BEGIN_DIR/s/HSDir across all cohort HSDirs, count redacted;
  DoSStreamCreation disabled on all); the rho (requests-per-circuit) PROXY is
  computable on stock (Δ BEGIN_DIR ÷ Δ circs_created; relay A ≈5.69), but the
  clean hsdir_circ_reused reuse counter and phi (unknown-prev-hop) are NULL on
  stock relays (patch-only counters). Whether 0001/0002 address THIS operator's
  flood is unconfirmed
  until the count-only observe deploy; a tentative circuit-rejection reuse
  inference was checked against dos.c and REJECTED. See
  analysis/realflood-capture-interpretation.md.
