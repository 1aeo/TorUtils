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
 2. operator/DEPLOY-AND-MEASURE.md - the runbook you will follow, all of it. Key parts: §0 (the ~96 h cost), §1 Path A + §1.1 (unpack to /opt, switch ONE systemd instance), §3 (verify, control-port helper, HSDir-flag check), §4.1 (Prometheus), §5 (ratios and caveats), §6 (rollback).
 3. operator/capture-and-validate-playbook.md §2.1 - exactly what each counter counts.
 4. operator/patch-crash-at-scale-critique.md - the safety gate (read the addendum at the top).
 5. engineering/deb/README.md - what the package is and how it was built and verified.
Then write yourself a <=10-line summary: what patches 0001 and 0002 do, what the four counters count, why count-only changes nothing, why the binary swap costs ~96 h. If anything in the docs contradicts this prompt, stop and ask.

Facts to check your understanding against:
 - Patch 0001 (known-previous-hop rule): counts HS descriptor requests whose previous hop is not a relay in our consensus -> hsdir_unknown_prev_hop. It would refuse them (503) only if enforcement were on.
 - Patch 0002 (one HS dir request per circuit): hsdir_request_total = every anonymous HS dir request; hsdir_req_reused = every request on a circuit that already carried one; hsdir_circ_reused = circuits that carried >=2, counted once each. It would close such circuits only if enforcement were on.
 - Both options (HSDirOneRequestPerCircuit, HSDirRefuseUnknownPrevHop) default to `auto`; with no consensus opinion (no authority votes these parameters) that means COUNT ONLY. All four counters are counted before any enforcement decision.
 - The binary comes from tor41339-hsdir-defense/packages/tor_0.4.9.14-1~noble+1+tor41339.3_amd64.deb (Ubuntu 24.04, amd64). You UNPACK it to /opt (dpkg-deb -x, runs no scripts) and point only the canary's systemd unit at it. tor-geoipdb is not needed.

=== HARD RULES ===
 - ONE canary relay. Do not change, restart or reload any other relay. Never run `systemctl restart|reload|stop tor` (no @NAME): that hits every instance on the host. Never `dpkg -i`/`apt install` the .deb on a host with more than one tor@ instance: its postinst restarts all of them and every one loses its HSDir flag for ~96 h.
 - Count-only. Never put HSDirOneRequestPerCircuit or HSDirRefuseUnknownPrevHop in the torrc (any value): it is unnecessary, and the unit's stock ExecStartPre verify (stock /usr/bin/tor) rejects the unknown option, so the next start would fail. Never SETCONF them to 1.
 - Enforcement check (DEPLOY §3, at deploy and at each check-in): the torrc has no HSDir* lines; the canary's cached consensus `params` line has no hsdir_one_request_per_circ / hsdir_refuse_unknown_prev_hop; GETCONF shows both `auto`. (The enforcement log lines are LOG_PROTOCOL_WARN and invisible at notice, so logs cannot tell you.) If any of these shows enforcement, run `SETCONF HSDirOneRequestPerCircuit=0 HSDirRefuseUnknownPrevHop=0` on the canary's ControlPort (0 = never enforce; `auto` would follow the consensus) and report it.
 - Observe only: no load generation, no probing of other relays, no attempt to identify clients or onion services. Keep the tor log level at notice (info/debug would explode under a flood) and SafeLogging on.
 - No restart of the canary after the one deploy restart until the measurement is over: a restart resets its uptime (another ~96 h without the HSDir flag) and the counters. That includes host reboots, needrestart, and unattended upgrades (DEPLOY §1.1 step 1 covers the hold and the needrestart exclusion; if the host auto-reboots, tell me before deploying).
 - CONFIDENTIALITY in everything you send back: no relay fingerprints, nicknames, IPs, hostnames, ContactInfo, onion addresses, descriptor IDs, Prometheus job/instance labels or URLs, or fleet counts. Call the relay "canary".
 - If anything looks wrong (crash, restart loop, RSS or CPU well above that relay's normal, counters missing), roll back per DEPLOY §6 and report.

=== PART 2 - DEPLOY (day 0) ===
 1. Choose the canary: one relay that currently has the HSDir flag, on a host whose relays run as tor@NAME systemd instances (a single-relay host's is tor@default). Note its instance name, torrc, DataDirectory, MetricsPort and ControlPort, and its normal RSS and CPU over the last day.
 2. Fetch the branch. In tor41339-hsdir-defense/packages: `sha256sum -c --ignore-missing SHA256SUMS` (the .deb line must say OK). Unpack per DEPLOY §1 Path A; the strings check must print 4.
 3. Follow DEPLOY §1.1 steps 1-4 exactly: apt hold + needrestart exclusion; read the effective ExecStart (`systemctl cat`, LAST ExecStart= line); write the zz-tor41339.conf drop-in repeating that line with only the binary path changed; daemon-reload; `--verify-config` with the patched binary must print "Configuration was valid". If the effective line differs from the stock one shown, copy yours and say so at check-in.
 4. Step 5, the one restart: record T0 (UTC), restart ONLY tor@CANARY, confirm the PID changed and /proc/<pid>/exe is /opt/tor41339/usr/bin/tor. ~30 s is normal; up to 60 s under Sandbox 1 (pre-existing tor#41060).
 5. Verify (DEPLOY §3): the MetricsPort shows exactly four tor_relay_dos_total{type="hsdir_..."} lines (0 for now); the enforcement check passes. Later, at the first DoS heartbeat (one HeartbeatPeriod after T0, 6 h by default), the "DoS mitigation since startup" log line also shows "circuits with repeated HSDir requests" and "HSDir requests with an unknown previous hop".
 6. Prometheus: `count(tor_relay_dos_total{type=~"hsdir_.*", <canary selector>})` must be 4 - fix any metric_relabel_configs/allowlist that drops them. Note the scrape interval. Retention must cover T0 + ~12 days (15 d default is fine), or export each window before it ages out.
 7. CHECK-IN 1 (short): T0 (UTC), the drop-in's ExecStart matched stock yes/no, verify-config OK, PID changed, four counters in Prometheus, enforcement check passed, Sandbox 1 on/off, restart duration, anything unusual. No identifiers.

=== PART 3 - WAIT FOR THE HSDIR FLAG, THEN THE FLOOD ===
 - After the restart the canary is NOT an HSDir for about 96 h (the directory authorities require 96 h of continuous self-reported uptime, plus up to one consensus period/hash-ring period). hsdir_request_total stays near zero meanwhile - expected.
 - From T0+90 h, check every few hours with the HSDir-flag check in DEPLOY §3 (the canary's own cached consensus; the `s` line must contain HSDir). Record T_flag (UTC). Also confirm `resets(tor_relay_traffic_bytes{direction="read",<canary>}[<T0 to now>])` is 0 - otherwise the canary restarted and the clock restarted with it. CHECK-IN 2 (short): hours from T0 to T_flag, restarts 0 yes/no, enforcement check passed.
 - After T_flag, hsdir_request_total starts rising. BASELINE window: the first clean >=1 h stretch starting >=2 h after T_flag with no flood.
 - Detect the flood: rate(tor_relay_streams_total{type="BEGIN_DIR",<canary>}[5m]) sustained >=5x the baseline for >=15 min (an attacked relay in our earlier capture went ~180x - it is obvious). The flood rotates across HSDirs, so it may take days to reach the canary.
 - Capture at least one >=1 h FLOOD window (prefer the peak hour; also record when the episode starts and ends). Stop when you have a baseline window and at least one flood window, or at T_flag + 7 days with no flood (then report baseline-only and ask whether to keep waiting).
 - Do NOT enable enforcement. It is a live toggle (DEPLOY §8) but a separate, later decision.

=== PART 4 - COMPUTE (for each window [S, E], canary only, W = E - S in seconds) ===
Evaluate every query at the window end E through the HTTP API: `curl -s "$PROM/api/v1/query" --data-urlencode 'query=<Q>' --data-urlencode 'time=<E as RFC3339>'` (or append `@ <E unix>` right after the range selector, e.g. `X[3600s] @ 1767225600`). Add your canary selector to every series. First check `resets(tor_relay_traffic_bytes{direction="read"}[Ws])` = 0; if not, the relay restarted inside the window: say so in "gaps" and pick another window.
  B  = increase(tor_relay_streams_total{type="BEGIN_DIR"}[Ws])
  C  = increase(tor_relay_congestion_control_total{state="cc_circuits",action="circs_created"}[Ws])
  T  = increase(tor_relay_dos_total{type="hsdir_request_total"}[Ws])
  R  = increase(tor_relay_dos_total{type="hsdir_req_reused"}[Ws])
  K  = increase(tor_relay_dos_total{type="hsdir_circ_reused"}[Ws])
  U  = increase(tor_relay_dos_total{type="hsdir_unknown_prev_hop"}[Ws])
  BW = increase(tor_relay_traffic_bytes{direction="written"}[Ws])     BR = same with direction="read"
  OP = increase(tor_relay_load_onionskins_total{type="ntor_v3",action="processed"}[Ws])     OD = same with action="dropped"
Derived:
  r_hs              = R / T        share of HS requests that rode an already-used circuit (what patch 0002 would refuse)
  rho_hs            = T / (T - R)  HS requests per HS circuit
  reused_circ_share = K / (T - R)  share of HS circuits that carried >=2 requests
  phi               = U / T        share of HS requests from an unknown previous hop (what patch 0001 would refuse)
  hs_share          = T / B        share of BEGIN_DIR streams that were HS descriptor requests
  rho               = B / C        whole-relay streams per created circuit (proxy only)
  write_read_ratio  = BW / BR ;  bytes_per_begin_dir = BW / B
  onionskins processed/s and dropped/s = OP / W, OD / W
  per-second rates for BEGIN_DIR and hsdir_request_total: median and p95 = quantile_over_time(0.5|0.95, rate(X[1m])[Ws:15s]); peak = max_over_time(rate(X[1m])[Ws:15s]). If the scrape interval is above 15 s, use rate(X[4*interval]) and a subquery step equal to the interval, and say so.
Caveats to state, not fix: rho_hs and reused_circ_share are approximate (circuits straddle window edges); C counts congestion-control circuits only; B, the byte counters and onionskins are whole-relay, not directory-only. If T is 0 in a window, ratios with T in the denominator are null. Never invent or estimate a number you did not measure - put it in "gaps".

=== PART 5 - REPORT BACK (exactly these three things) ===
(1) One fenced JSON block:
{"deployment":{"install_path":"per-instance drop-in (§1.1)","package_version":"0.4.9.14-1~noble+1+tor41339.3","t0_restart_utc":"...","t_flag_utc":"...","hours_t0_to_flag":x,"restarts_during_measurement":0,"restart_seconds":x,"counters_present":["hsdir_circ_reused","hsdir_req_reused","hsdir_request_total","hsdir_unknown_prev_hop"],"enforcement":"off (auto; no torrc lines, no consensus params)","sandbox_1":true,"scrape_interval_s":x},
 "baseline_window":{"start_utc":"...","end_utc":"...","duration_s":x,"B":x,"C":x,"T":x,"R":x,"K":x,"U":x,"BW":x,"BR":x,"OP":x,"OD":x,"begin_dir_per_s":{"median":x,"p95":x,"peak":x},"hs_req_per_s":{"median":x,"p95":x,"peak":x},"r_hs":x,"rho_hs":x,"reused_circ_share":x,"phi":x,"hs_share":x,"rho":x,"write_read_ratio":x,"bytes_per_begin_dir":x,"onionskins_processed_per_s":x,"onionskins_dropped_per_s":x},
 "flood_windows":[{"episode_start_utc":"...","episode_end_utc":"...", ...same fields as baseline_window...}],
 "flood_vs_baseline":{"begin_dir_rate_multiple":x,"hs_request_rate_multiple":x},
 "resources":{"rss_mb_normal":x,"rss_mb_flood_peak":x,"cpu_pct_normal":x,"cpu_pct_flood_peak":x},
 "gaps":["anything you could not derive, and why"]}
(2) A CSV (<=40 rows) across the main flood window at 5-min resolution (query_range, step=300s): t_offset_min,begin_dir_per_s,hs_req_per_s,r_hs,phi,bytes_written_per_s. Use rate(X[5m]); for r_hs and phi divide with `/ ignoring(type)` (the two sides carry different type labels).
(3) A 6-10 line plain summary: Is the flood reuse-heavy (r_hs, rho_hs)? Is unknown-previous-hop traffic present (phi)? What share of BEGIN_DIR is HS (hs_share)? Was the relay overloaded (onionskins dropped)? How far above baseline? Which patch would bite (0002 if r_hs is high, 0001 if phi is high, neither if both are ~0)? Anything surprising?
CHECK-IN 3 is this report. Keep the raw capture private; send only the above.

Afterwards: leave the canary running count-only until told otherwise. Do not unhold, remove the drop-in, or roll back until asked (rollback is DEPLOY §6).
````

---

Hand the JSON, CSV and summary back to the analysis session. The exact HS-only
fractions (`r_hs`, `phi`, `hs_share`) replace the lab's assumed reuse and
unknown-previous-hop inputs, so the off-vs-on lab result becomes a prediction for
*your* flood, and they decide which of the two patches is worth enforcing.
