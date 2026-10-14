# Prompt for the deploy-and-measure agent

Give the text below (between the lines) to an agent that has operator access to
one of your production Tor HSDir relays (shell/SSH, ability to install or build
a binary, edit torrc, reload the service) and that can hand its output back to
the lab-simulation analysis.

---

````
You have operator access to our own Tor relay(s). This is a DEFENSIVE task: deploy a COUNT-ONLY ("observe") build of Tor that MEASURES the tor#41339 onion-service-descriptor flood we are receiving, so we can ground a closed-lab simulation of a mitigation. You will change NOTHING about how the relay treats traffic — observe mode only increments count-only MetricsPort counters. Work carefully and reversibly on ONE relay (a canary) first.

SOURCE MATERIAL (read these first): on the `tor41339-hsdir-defense` branch of our `1aeo/torutils` repo, read:
- `tor41339-hsdir-defense/operator/DEPLOY-AND-MEASURE.md`  (the step-by-step runbook — follow it)
- `tor41339-hsdir-defense/operator/capture-and-validate-playbook.md`  (rationale + exact metric names + feature→meaning)
- `tor41339-hsdir-defense/operator/patch-crash-at-scale-critique.md` if present (the safety gate)
- the patches in `tor41339-hsdir-defense/patches/0001-*.patch … 0007-*.patch` (the build input)

HARD RULES — do not cross:
- ONE canary relay first. Do not touch the rest of the fleet unless explicitly told.
- Keep enforcement OFF (count-only). The two torrc options MUST be `auto` (or `0`): `HSDirOneRequestPerCircuit auto`, `HSDirRefuseUnknownPrevHop auto`. If you ever see a circuit closed with RESOURCELIMIT or a new HS-dir 503 caused by these, you are NOT in observe mode — stop and fix the torrc.
- Back up the stock binary BEFORE swapping, so rollback is one copy-back + reload. Validate with `tor --verify-config` before reloading production.
- Prefer `reload`/SIGHUP over `restart` to avoid dropping live circuits.
- SAFETY GATE: if `patch-crash-at-scale-critique.md` exists and its deploy gate does NOT clear the count-only observe build, STOP and report back instead of deploying.
- CONFIDENTIALITY: metadata only. Never put a relay fingerprint, nickname, IP, hostname, ContactInfo, or onion address in your output. Relays do not see client IPs on multi-hop circuits — do not attempt to capture client identity. Honor SafeLogging. Keep raw captures private; share back only derived aggregate numbers.

STEPS (details in DEPLOY-AND-MEASURE.md):
1. Obtain the patched Tor: install the noble `.deb` (version `0.4.9.14-1~noble+1+tor41339.2`) if attached to the branch, else build from the 7 patches on `tor-0.4.9.14` per the runbook. Verify `tor --version`.
2. Add the observe-only torrc block (the two `auto` options + `MetricsPort 127.0.0.1:9035` + `MetricsPortPolicy accept 127.0.0.1` + `HeartbeatPeriod 60 seconds`). Reload onto the patched binary.
3. VERIFY observe mode: `curl -s http://127.0.0.1:9035/metrics | grep 'tor_relay_dos_total{type="hsdir'` shows the four counters present (circ_reused, req_reused, request_total, unknown_prev_hop — the pre-telemetry .deb shows only circ_reused + unknown_prev_hop); confirm no RESOURCELIMIT closes / no new 503s in the log; legitimate traffic unaffected.
4. CAPTURE: scrape MetricsPort every 10s across (a) a FLOOD window and (b) a QUIET BASELINE window (use the runbook's loop, or our existing MetricsPort pipeline — just ensure these keys are sampled over time): tor_relay_streams_total{type="BEGIN_DIR"}, tor_relay_traffic_bytes{direction="written"/"read"}, tor_relay_congestion_control_total{state="cc_circuits",action="circs_created"}, tor_relay_load_onionskins_total{type="ntor_v3",action="processed"} (and action="dropped"), tor_relay_dos_total{type="hsdir_circ_reused"}, {type="hsdir_req_reused"}, {type="hsdir_request_total"} and {type="hsdir_unknown_prev_hop"} (a current-series build exposes all four; the pre-telemetry .deb shows only circ_reused + unknown_prev_hop — see DEPLOY-AND-MEASURE §3). Prometheus can scrape the loopback MetricsPort directly; see DEPLOY-AND-MEASURE §4.1 for the scrape_config and loopback-reachability options. Counters are cumulative; a decrease means a tor restart (reset) — segment and sum positive deltas only.
5. COMPUTE and OUTPUT (de-identified), for BOTH windows:
   - whole-relay requests-per-circuit multiplier ρ = Δ BEGIN_DIR / Δ circs_created  (≈5.69 on the attacked relay during the flood; circs_created includes non-directory circuits, so ρ is a proxy that holds when HS-dir flood traffic dominates). NOTE: Δ hsdir_circ_reused / Δ BEGIN_DIR is a DIFFERENT signal — the fraction of circuits reused, which undercounts in observe mode — do not report it as the multiplier.
   - HS-only repeat-request fraction r_hs = Δ hsdir_req_reused / Δ hsdir_request_total  (the EXACT per-request reuse fraction; current-series build only). HS-only multiplier ρ_hs = 1 / (1 − r_hs).
   - unknown_prev_hop_fraction φ = Δ hsdir_unknown_prev_hop / Δ hsdir_request_total  (EXACT HS-only denominator on the current-series build; fall back to Δ hsdir_unknown_prev_hop / Δ BEGIN_DIR as a lower-bound proxy only if request_total is unavailable, e.g. the pre-telemetry .deb)
   - request_rate_begin_dir_per_s (median, p95, peak), write_read_ratio = Δ bytes_written/Δ bytes_read, bytes_per_begin_dir, circuits_created_per_s, onionskins_processed_per_s, onionskins_dropped_per_s
   Emit ONE fenced JSON block:
   {"scope":{"hsdir_relays":N,"tor_version":"0.4.9.14+tor41339","patched_counters_present":true},
    "flood_window":{"start":"...","end":"...","duration_s":N,"rho_requests_per_circuit":x,"r_hs":x,"rho_hs":x,"phi_unknown_prev_hop_fraction":x,"request_rate_begin_dir_per_s":{"median":x,"p95":x,"peak":x},"write_read_ratio":x,"bytes_per_begin_dir":x,"circuits_created_per_s":x,"onionskins_processed_per_s":x,"onionskins_dropped_per_s":x},
    "baseline_window":{...same fields...},
    "gaps":["anything you could not derive and why"]}
   Plus a ≤30-row CSV of t_offset_s,begin_dir_per_s,bytes_written_per_s across the flood window, and a 4–6 line plain summary: is it reuse-heavy (ρ) or one-per-circuit? unknown-prev-hop present (φ)? overloaded (onionskin drops)? how far above baseline?
6. ROLLBACK when done capturing: remove the two HSDir* torrc lines (or set 0) and reload; restore the stock binary if you swapped it. Confirm back to stock.

Be honest: if a window is too short, counters reset mid-window, or a value isn't in the data, put it in "gaps" rather than guessing. Do not invent numbers. When finished, share the JSON + CSV + summary back to the lab-simulation analysis.
````

---

Hand the JSON/CSV/summary that comes back to me. I set the lab generator to the
reported ρ and φ and shape, re-run the matrix, and the off-vs-on result becomes
a prediction tuned to *your* flood rather than public averages.
