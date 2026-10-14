# Prompt for the deploy, measure and report-back agent

Give the text between the lines to an agent that has SSH/sudo on the host of
**one** of your HSDir relays and read access to your Prometheus (which already
scrapes each relay's MetricsPort, e.g. over a reverse SSH tunnel). The agent
learns the codebase, deploys the count-only build on that one canary, waits out
the ~96 h HSDir-flag gate, captures the flood with the four new counters, and
hands back a de-identified summary for analysis. It checks in three times:
after deploying, when the HSDir flag returns, and with the final report.

---

````
You have operator access (SSH + sudo) to our own Tor relays and read access to our Prometheus, which already scrapes each relay's MetricsPort. This is a DEFENSIVE, observe-only task: run a COUNT-ONLY build of Tor on ONE canary HSDir relay so that, once it regains the HSDir flag, it MEASURES the onion-service-directory flood (tor#41339) it receives. You change nothing about how the relay treats traffic. Then report de-identified numbers back.

=== PART 1 - LEARN THE CODEBASE (before touching anything) ===
Repo: github.com/1aeo/TorUtils, branch `tor41339-hsdir-defense-clean`, directory `tor41339-hsdir-defense/`. Read, in order:
 1. README.md - the problem (a BEGIN_DIR / HS-descriptor flood that the stock DoS defenses do not see), the 7 patches, the lab results.
 2. operator/DEPLOY-AND-MEASURE.md - the runbook you will follow. Especially: §0 (the ~96 h cost), §1.1 (multi-instance hosts: switch ONE instance), §3 (verify), §4.1 (Prometheus), §5 (ratios), §6 (rollback), §8 (logging cost).
 3. operator/capture-and-validate-playbook.md §2.1 - exactly what each counter counts.
 4. operator/patch-crash-at-scale-critique.md - the safety gate (read the addendum at the top).
 5. engineering/deb/README.md - which package to install and how it was built and verified.
Then write yourself a <=10-line summary: what patches 0001 and 0002 do, what the four counters count, why count-only changes nothing, why the binary swap costs ~96 h. If anything in the docs contradicts this prompt, stop and ask.

Facts to check your understanding against:
 - Patch 0001 (known-previous-hop rule): an HS descriptor request whose previous hop is not a relay we know. Counter: hsdir_unknown_prev_hop. It only refuses (503) if HSDirRefuseUnknownPrevHop=1.
 - Patch 0002 (one HS dir request per circuit): counters hsdir_circ_reused (circuits that carried >=2 HS requests, counted once each), hsdir_req_reused (every repeat request), hsdir_request_total (every anonymous HS dir request). It only closes circuits if HSDirOneRequestPerCircuit=1.
 - Both options default to `auto`; with no consensus opinion that means COUNT ONLY. All four counters are counted before any enforcement decision.
 - The package is tor41339-hsdir-defense/packages/tor_0.4.9.14-1~noble+1+tor41339.3_amd64.deb (Ubuntu 24.04, amd64; sha256 in packages/SHA256SUMS). Only the `tor` package is needed; tor-geoipdb is optional unchanged data.

=== HARD RULES ===
 - ONE canary relay. Do not change, restart or reconfigure any other relay.
 - Count-only. Never set HSDirOneRequestPerCircuit or HSDirRefuseUnknownPrevHop to 1. If the log shows "Refusing HS directory request from unknown previous hop" or "Closing circuit after repeated HS directory request", or you see RESOURCELIMIT circuit closes or new HS-dir 503s, enforcement is on by mistake: set the options back to auto (or remove them), reload, and report.
 - Observe only: no load generation, no probing of other relays, no attempt to identify clients. Keep the tor log level at notice (info/debug would explode under a flood) and SafeLogging on.
 - Do not restart the canary at any point after the deploy restart until the measurement is over: a restart resets its uptime (it loses the HSDir flag for another ~96 h) and resets the counters.
 - CONFIDENTIALITY in everything you send back: no relay fingerprints, nicknames, IPs, hostnames, ContactInfo, onion addresses, descriptor keys, Prometheus job/instance labels, or fleet counts. Call the relay "canary".
 - If anything looks wrong (crash, restart loop, RSS or CPU well above that relay's normal, counters missing), roll back per DEPLOY-AND-MEASURE §6 and report.

=== PART 2 - DEPLOY (day 0) ===
 1. Choose the canary: one HSDir relay. On a host that runs several tor@NAME instances, use DEPLOY §1.1 (patched binary in /opt, one systemd drop-in for this instance only). Never install the .deb host-wide on a host with other relays: its postinst restarts every instance and resets all their HSDir flags. Note the relay's normal RSS and CPU.
 2. Fetch the branch and verify the package: `sha256sum -c` against packages/SHA256SUMS (the tor_..._amd64.deb line).
 3. Install per §1.1 (multi-instance) or §1 Path A (single-instance host). In both cases run `sudo apt-mark hold tor tor-geoipdb` so a stock tor upgrade cannot restart the canary during the measurement. Validate with the patched binary's --verify-config before restarting.
 4. Restart ONLY the canary - the one restart. If the host uses Sandbox 1, tor may ignore SIGTERM (pre-existing upstream bug tor#41060): confirm the PID actually changed.
 5. Verify (§3): the running binary is the patched one (`readlink /proc/<pid>/exe`); `curl -s http://127.0.0.1:<its MetricsPort>/metrics | grep 'tor_relay_dos_total{type="hsdir'` shows exactly four lines: hsdir_circ_reused, hsdir_req_reused, hsdir_request_total, hsdir_unknown_prev_hop (all may be 0 for now); the DoS heartbeat line contains "circuits with repeated HSDir requests" and "HSDir requests with an unknown previous hop"; no enforcement log lines.
 6. Prometheus: `tor_relay_dos_total{type=~"hsdir_.*"}` for the canary must return four series - fix any series allowlist / metric_relabel_configs that would drop them. Scrape every 10-15 s. Make sure retention covers at least 12 days from now, or export each window before it ages out.
 7. CHECK-IN 1 (short): T0 = restart time (UTC), install path (§1.1 or Path A), four counters present yes/no, anything unusual. No identifiers.

=== PART 3 - WAIT FOR THE HSDIR FLAG, THEN THE FLOOD ===
 - After the restart the canary is NOT an HSDir for about 96 h (the directory authorities require 96 h of continuous self-reported uptime, plus up to one consensus/hash-ring period). The hsdir_* counters stay near zero meanwhile - expected.
 - From T0+90 h, check every few hours whether the canary's own consensus entry has the "HSDir" flag (its control port `GETINFO ns/id/<its fingerprint>`, or your usual monitoring). Record T_flag (UTC). CHECK-IN 2 (short): hours from T0 to T_flag.
 - After T_flag, hsdir_request_total starts rising. Record a quiet BASELINE window: the first clean >=1 h stretch after T_flag+2 h with no flood.
 - Detect the flood: rate(tor_relay_streams_total{type="BEGIN_DIR"}[5m]) sustained >=5x the post-flag baseline for >=15 min (an attacked relay in our earlier capture went ~180x - it is obvious). The flood rotates across HSDirs, so it may take days to reach the canary.
 - Capture at least one >=1 h FLOOD window (prefer the peak hour; also note when the episode starts and ends). Stop when you have a baseline window and at least one flood window, or at T_flag + 7 days with no flood (then report baseline-only and ask whether to keep waiting).
 - Do NOT enable enforcement. It is a live toggle (DEPLOY §8) but a separate, later decision.

=== PART 4 - COMPUTE (for each window W, canary only) ===
Use increase() over the window, evaluated at the window end E (Prometheus API `query?time=E`, or the `@ E` modifier):
  B  = increase(tor_relay_streams_total{type="BEGIN_DIR"}[W])
  C  = increase(tor_relay_congestion_control_total{state="cc_circuits",action="circs_created"}[W])
  T  = increase(tor_relay_dos_total{type="hsdir_request_total"}[W])
  R  = increase(tor_relay_dos_total{type="hsdir_req_reused"}[W])
  K  = increase(tor_relay_dos_total{type="hsdir_circ_reused"}[W])
  U  = increase(tor_relay_dos_total{type="hsdir_unknown_prev_hop"}[W])
  BW, BR = increase(tor_relay_traffic_bytes{direction="written"|"read"}[W])
  OP, OD = increase(tor_relay_load_onionskins_total{type="ntor_v3",action="processed"|"dropped"}[W])
Derived:
  r_hs              = R / T        share of HS requests that rode an already-used circuit (what patch 0002 would refuse)
  rho_hs            = T / (T - R)  HS requests per HS circuit
  reused_circ_share = K / (T - R)  share of HS circuits that carried >=2 requests (approximate)
  phi               = U / T        share of HS requests from an unknown previous hop (what patch 0001 would refuse)
  hs_share          = T / B        share of BEGIN_DIR streams that were HS descriptor requests
  rho               = B / C        whole-relay streams per created circuit (proxy only)
  write_read_ratio  = BW / BR ;  bytes_per_begin_dir = BW / B
  per-second rates for BEGIN_DIR and hsdir_request_total: median and p95 via quantile_over_time(0.5|0.95, rate(X[1m])[W:15s]), peak via max_over_time(rate(X[1m])[W:15s])
  onionskins processed/s and dropped/s = OP/W, OD/W
If a counter decreased inside a window, the relay restarted: say so in "gaps". Never invent or estimate a number you did not measure - put it in "gaps".

=== PART 5 - REPORT BACK (exactly these three things) ===
(1) One fenced JSON block:
{"deployment":{"install_path":"per-instance (§1.1) | package (Path A)","package_version":"0.4.9.14-1~noble+1+tor41339.3","t0_restart_utc":"...","t_flag_utc":"...","hours_t0_to_flag":x,"restarts_during_measurement":0,"counters_present":["hsdir_circ_reused","hsdir_req_reused","hsdir_request_total","hsdir_unknown_prev_hop"],"enforcement":"off (auto)","sandbox_1":true},
 "baseline_window":{"start_utc":"...","end_utc":"...","duration_s":x,"B":x,"C":x,"T":x,"R":x,"K":x,"U":x,"begin_dir_per_s":{"median":x,"p95":x,"peak":x},"hs_req_per_s":{"median":x,"p95":x,"peak":x},"r_hs":x,"rho_hs":x,"reused_circ_share":x,"phi":x,"hs_share":x,"rho":x,"write_read_ratio":x,"bytes_per_begin_dir":x,"onionskins_processed_per_s":x,"onionskins_dropped_per_s":x},
 "flood_windows":[{"episode_start_utc":"...","episode_end_utc":"...", ...same fields as baseline_window...}],
 "flood_vs_baseline":{"begin_dir_rate_multiple":x,"hs_request_rate_multiple":x},
 "resources":{"rss_mb_normal":x,"rss_mb_flood_peak":x,"cpu_pct_flood_peak":x},
 "gaps":["anything you could not derive, and why"]}
(2) A CSV (<=40 rows) across the flood window at 5-min resolution: t_offset_min,begin_dir_per_s,hs_req_per_s,r_hs,phi,bytes_written_per_s
(3) A 6-10 line plain summary: Is the flood reuse-heavy (r_hs, rho_hs)? Is unknown-previous-hop traffic present (phi)? What share of BEGIN_DIR is HS (hs_share)? Was the relay overloaded (onionskins dropped)? How far above baseline? Which patch would bite (0002 if r_hs is high, 0001 if phi is high, neither if both are ~0)? Anything surprising?
CHECK-IN 3 is this report. Keep the raw capture private; send only the above.

Afterwards: leave the canary running count-only until told otherwise. Do not apt-mark unhold or roll back until asked (rollback is DEPLOY §6, plus `sudo apt-mark unhold tor tor-geoipdb`).
````

---

Hand the JSON, CSV and summary back to the analysis session. The exact HS-only
fractions (`r_hs`, `phi`, `hs_share`) replace the lab's assumed reuse and
unknown-previous-hop inputs, so the off-vs-on lab result becomes a prediction for
*your* flood, and they decide which of the two patches is worth enforcing.
