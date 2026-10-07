# Quetzalcoatl relay family — public Tor Metrics record (independent reproduction)

Prepared 2026-10-07 from public CollecTor data only. All times are UTC. Every **Fact** cites a fingerprint
(first 8 hex characters where unambiguous; full values are in the cited CSVs), a timestamp and a source
table. Every **Inference** is labelled, with its reasoning and what would confirm or refute it. Nothing
here attributes the activity to anyone beyond what the timing shows.

## 0. Data, method and sanity check

**Data (Facts).**
- Consensuses: `consensuses-2026-05` … `consensuses-2026-10` (CollecTor archive). 3,810 distinct
  valid-after hours, 2026-05-01 00:00:00 → 2026-10-07 02:00:00, de-duplicated by valid-after. Nine hourly
  slots are absent: 2026-05-09 03:00 and 04:00; 2026-06-02 14:00–18:00; 2026-07-16 19:00; and
  **2026-10-01 19:00**, which falls inside the attack window (`net/missing_consensuses.csv`).
- Server descriptors: `server-descriptors-2026-05` … `-10`. 3,006,543 files scanned; 2,767,399 unique
  (de-duplicated by descriptor digest); 239,144 duplicates appear in more than one monthly archive.
  The last descriptor is dated 2026-10-07 02:18:04.
- Votes: `votes-2026-10` has 1,301 votes from 9 authorities.
- AS data: CAIDA RouteViews pfx2as 2026-10-01 12:00 and CAIDA as-org 20261001, cross-checked against the
  IPFire Location DB of 2026-10-01.

**Scripts.** `collector_family_history.py` was run unmodified with `--start 2026-05 --end 2026-10
--descriptors-start 2026-05` and wrote `summary.md` and the original CSVs in this folder. The second-level
analysis uses separate scripts in `../scripts/`: `build_netdb.py`, `derive_tables.py` and
`family_analysis.py`, which writes the `repro_*.csv` files here.

**Definitions.**
- *Restart time* = published − uptime, to the second. A new boot time counts as a restart only if it is
  not earlier than the previous descriptor's publication time; otherwise it is uptime drift. 41,346
  drift shifts were discarded network-wide.
- *Reload* = a descriptor whose content changed while the boot time did not.
- *Host* = an IPv4 address.

**Sanity check (PROMPT.md step 4): PASSED.** `summary.md`, section "Switzerland2 descriptors", and
`switzerland2_descriptors.csv` show:

| relay | last 68-line descriptor | first 22-line descriptor |
|---|---|---|
| 29FEFE36… (ORPort 9000) | 2026-10-01 15:43:20 (uptime 2) | 2026-10-02 09:34:04 (uptime 64246) |
| 8427937D… (ORPort 9100) | 2026-10-01 15:43:21 (uptime 3) | 2026-10-02 09:34:04 (uptime 64246) |

Policy sha1 changed from `748d311cce` (68 lines) to `03744c8f55` (22 lines). From the uptimes, both
relays booted at **2026-10-01 15:43:18**, and the 09:34:04 descriptors carry the **same boot time**. The
2026-10-02 policy change on Switzerland2 was therefore a live reload, not a restart.

## Key numbers

| item | value | source |
|---|---|---|
| Family members ever seen (seeds + exact family contact) | 764 = 362 seeds + 402 non-seed relays with the exact Quetzalcoatl contact | repro_family_members.csv |
| Active in October (any consensus ≥ 2026-10-01) | **277 relays on 73 IPv4 hosts**: 176 seeds + **101 relays not in the seed list** | repro_family_members.csv |
| Seeds not seen after June | 186 (last seen 05-12: 158; 05-13: 8; 05-28: 6; 06-16: 2; 06-17: 12) | repro_family_members.csv |
| Policy flip to near-open | 277 relays / 73 hosts, **2026-10-02 09:27:42 → 09:35:18**, 273 by reload | repro_policy_changes.csv |
| First / last flip | F532DA2085F87777CE05EA947BF7B4F49B625754 (104.168.0.177) 09:27:42 / DD68CED74414FF446E52596462CEDAEF7E66BED7 (192.3.47.172) 09:35:18 | same |
| 2026-10-01 restart | 72 hosts / 275 relays, 15:36:30 → 15:47:53 (bulk 15:42–15:47), unsorted | repro_bursts.csv |
| 2026-10-05 sweep | **70 hosts / 253 relays, 08:56:30 → 10:39:50**, text-sorted (14 of 2,415 pairs inverted) | repro_sweep_20261005.csv |
| Onionoo view of the same sweep | 55 hosts / 152 relays, 08:56:30 → 10:26:56 | onionoo snapshot |
| Family share before the attack | 8.98 % of Exit-flagged relays (276/3,075) and 5.40 % of exit weight at 2026-10-01 12:00 | repro_exit_share.csv |
| OUR_POLICY published by a family relay? | **No** (0 descriptors) | descriptors |
| Attacker-pattern events before 2026-08-28 03:25:11 | **None found** | §3 |

## 1. Exit-policy changes since 2026-08-01

**Facts.**
- 321 descriptor-level policy-text changes by family relays since 2026-08-01 (`repro_policy_changes.csv`;
  full table in Appendix A).
  - **277 changes accept-list → near-open.** These are 277 relays on 73 hosts, all between
    2026-10-02 09:27:42 and 09:35:18. Per minute: 09:27 1, 09:28 27, 09:30 51, 09:31 40, 09:32 54,
    09:33 57, 09:34 31, 09:35 16.
    - Old summary (all 277): `accept 20-21,43,53,79-81,194,220,389,443,…` (the 68-line operator
      accept-list).
    - New summary (all 277): `reject 25,119,135-139,445,465,563,587,993,995,1214,4661-4666,6346-6429,6699,6881-6999`.
    - In 273 of the 277, the boot time did not change: a reload. The boot times come from the
      2026-10-01 15:42–15:47 restarts (173 relays booted in minute 15:43).
    - The other 4 (919EBE30 23.95.117.249, B2A4EFD1 67.215.234.141, 6A6A34B5 91.132.144.59,
      C829B3C5 199.195.251.119) had not published since before the 10-01 restart. Their 10-02
      descriptor carries both a new boot (10-01 15:43:09–15:43:29; 17:28:07 for C829B3C5) and the new
      policy, so reload and restart cannot be told apart for them.
    - By AS (relays/hosts): HostPapa AS36352 125/27; FranTech AS53667 48/24; netcup AS197540 40/14;
      Contabo Asia AS141995 24/3; Contabo GmbH AS51167 16/2; MAXKO AS211619 16/2; Contabo Inc AS40021 8/1.
    - The IPv6 policy changed in the same descriptors (277 `ipv6_policy` changes on 2026-10-02:
      accept-list → `reject 25,119,135-139,…`; `descriptor_changes.csv`).
  - **44 changes accept-list → accept-list** (2026-08-18 8; 08-19 8; 08-23 8; 08-30 8; 09-01 8; 09-13 1;
    09-21 1; 09-22 1; 09-27 1). Each coincides with an address change in the same descriptor (the
    relay's own-IP `reject` line changed). After normalization (own-IP and private lines removed) the
    policy is identical. These are host moves, not policy edits (`descriptor_changes.csv`, field
    `address`).
- **Former non-exits:** none. Every family relay that changed was an accept-list exit before. The two
  "non-exit" relays in `family_daily.csv` until 2026-08-25 are look-alikes outside the family (§7).
- The near-open text has a fixed line order: own-IP + private lines, then `reject *:25`, `*:465`,
  `*:587`, `*:993`, `*:995`, then tor's default policy, then `accept *:*`
  (`policies/03744c8f55*.txt`).
  - **Inference:** this is what `ExitPolicy reject *:25,465,587,993,995` with ExitRelay produces (tor
    appends its default policy). The text alone is generic. The timing and the identical boot times
    are the evidence.

The required table (fingerprint, nickname, IP, old class, new class, published time) is Appendix A, with
all 321 rows.

## 2. Clusters, bursts and host order

Host events are restarts (seconds, drift-filtered) and reloads, chained when gaps are ≤ 20 min
(`repro_bursts.csv` also has 60-min chaining). Inversions are counted against a text sort, a numeric sort
and a dot-ignoring sort of the IPs; random order inverts about half the pairs. Appendix B lists every
burst since 2026-08-20.

**Facts: key bursts.**

| burst | hosts / relays | event | inversions str / num / nodot | note |
|---|---|---|---|---|
| 2026-10-01 14:44:58 – 14:47:03 | 5 / 5 | restart | 9/7/9 of 10 | single relays: 66.63.170.221, 45.95.169.104, 23.95.117.249, 107.189.8.56, 23.94.148.16 |
| **2026-10-01 15:36:30 – 15:47:53** | **72 / 275** | 277 restarts | 1184/1303/1183 of 2556 (unsorted) | bulk 15:42–15:47; Switzerland2 boot 15:43:18 (host #30) |
| **2026-10-02 09:27:42 – 09:35:18** | **73 / 273** | 273 reloads (policy flip) | 1056/1029/1051 of 2628 (unsorted) | |
| 2026-10-04 01:10:53 – 05:47:26 | 72 / 269 | restarts | 1526/1151/1525 of 2556 (unsorted) | spread over 4.6 h; Switzerland2 05:47:26 |
| **2026-10-05 08:56:30 – 10:39:50** | **70 / 253** | restarts | **14** / 1157 / **9** of 2415 | text-sorted; longest ascending run 23 (str) / 28 (nodot) |

**Earlier routine runs (Facts), for comparison:**
- 2026-09-08 23:47:43 – 09-09 01:05:43: 69 hosts / 273 relays; platform 0.4.9.11 → 0.4.9.12.
- 2026-09-23 23:33:54 – 09-24 01:03:01: 69 hosts / 252 relays; 0.4.9.12 → 0.4.9.13.
- 2026-08-26 02:51–04:33: 45 hosts.
- 2026-08-30 15:45–17:07: 37 hosts.

These runs are unsorted (about 45 % of pairs inverted), but their order repeats: Kendall τ = 0.99
(n = 66) between the 09-08 and 09-23 runs, and τ ≈ 0.99–1.00 among the 07-30, 07-31, 08-09, 08-26 05:41
and 08-31 runs. The 10-05 sweep has τ between −0.17 and 0.36 against every earlier run.

**Inferences.**
- The 10-05 08:56 sweep walked the hosts in text-sorted IP order. Its few out-of-place hosts suggest a
  sort that ignores the dots: 107.189.14.4 before 107.189.1.9, and 104.244.79.61 → 107.174.146.126 →
  107.172.111.164. This is a different tool or order from the family's own routine runs, which repeat
  one fixed unsorted order (τ ≈ 0.99).
  - Confirm or refute: host logs of who ran `systemctl restart tor` on each host between 08:56 and
    10:40; whether the operator's tooling ever sorts its inventory.
- The 10-01 15:42–15:47 restart touched all 72 family hosts in about 11 minutes, during the window when
  the operator reports attacker activity on Switzerland2 (15:35–15:43). Its order is neither sorted nor
  the routine order (τ = 0.34 vs 09-08, 0.39 vs 09-23).
  - Confirm: management-server logs (SSH sessions or orchestration runs to all hosts at 15:3x–15:4x).
- The 10-04 01:10–05:47 restarts (one per host, spread over 4.6 h) look like unattended reboots after a
  kernel update, not a sweep. The operator reports a kernel upgrade and reboot on Switzerland2 at
  05:46. **Operator to confirm.**

## 3. Before 2026-08-28 03:25:11

**Facts: nothing matching the attacker's patterns was found before the known infection.**
- **Policy flips:** none to near-open or OUR_POLICY anywhere in the family, and none anywhere in the
  network: the first attacker-class descriptor of any relay is 2026-10-01 14:49:51
  (`net/attacker_transitions.csv`). Pre-infection family policy changes are all own-IP changes on host
  moves: 2026-08-18 ×8 and 2026-08-19 ×8, normalized-identical.
- **Restart sweeps:**
  - 242 family bursts of ≥ 5 hosts before 2026-08-28. They are part of a constant routine background:
    tens of bursts per month, with repeating order (τ ≈ 0.99 between runs) and versions upgraded in
    step.
  - None of the pre-infection bursts is text-sorted. The best is 2026-08-21 07:02, 6 hosts, 1/15
    inversions, which is not distinctive at that size.
  - The two largest pre-infection runs, 2026-08-09 02:36 (45 hosts) and 2026-08-26 02:51 (45 hosts), are
    unsorted (545/990 inversions for 08-26).
- **Contact changes:** none in the whole window (0 `contact_sha1` changes).
- **Family-set changes:** 308, all tied to relays joining, leaving or moving (e.g. 2026-08-18, 08-19,
  08-23 with 8 relays each).
- **Platform changes:** routine upgrades. 2026-05-07 (1,404), 05-10, 06-02, 06-25/26 (0.4.9.11 rollout);
  2026-09-08/09 → 0.4.9.12 and 09-23/24 → 0.4.9.13. The public posts list 0.4.9.12 and 0.4.9.13 as
  security releases of 2026-09-08 and 09-23 (`../net/public_reports_notes.md`).
- **Address changes:** 266 in the window, as hosts moved in blocks of 8 relays (e.g. 2026-05-10,
  05-31, 06-02, 08-18, 08-19).
- **Relays joining or going missing:**
  - The family shrank from 742 present relays (2026-05-01 12:00) to 186 (2026-06-01 12:00). 158 seeds
    were last seen on 2026-05-12 and ~300 non-seed relays in May (`repro_family_members.csv`). This is
    a large operator-side restructuring three months before the infection. **Operator to confirm.**
  - Between 2026-08-01 and 08-28 only one family relay left for good: 958F6572… (192.3.42.78:9100), last
    in a consensus 2026-08-19 06:00. Its IP:ORPort was taken over by a new key, 80F322ED…, first
    published 2026-08-19 05:45:28 (`net/identity_replacements.csv`).
  - The other departures listed in `summary.md` for 08-18, 08-19 and 08-26 are look-alike relays
    outside the family (§7).

**Inference.** The public record gives no sign of an earlier victim before 2026-08-28. The family's
activity before that date is routine operator work. That is consistent with an infection on
2026-08-28, but the public record cannot exclude silent access that did not change any descriptor.

## 4. Did any relay publish the Oct-1 "OUR_POLICY" summary?

**Facts.**
- **No family relay ever published it.** There are 0 descriptors with that summary among the 764 family
  fingerprints.
- **Network-wide, 46 relays of 22 exact contact strings did**, 33 distinct full texts in all
  (`net/attacker_transitions.csv`, `net/policy_lineage.csv`).
- Earliest: **2026-10-01 14:49:51, 4F72DEF09B015E9B6F210597083D95D8A3BC38AD "TorDola1",
  185.231.33.82** (Datashield AS211720, contact `dolas422@gazeta.pl`). Three sibling relays followed
  at 14:49:57, 14:50:00 and 14:50:03.
- Then 40 relays on 28 hosts of 21 other contact strings switched between 15:33:55 and 15:39:19. 39
  are on FranTech AS53667 and 1 is 103.39.237.147 on Elxer AS133255. Of these, 38 were reloads.
- All 46 share one ordered rule list: `reject *:25, *:465, *:587, *:110, *:143, *:993, *:995, *:3389,
  *:135, *:137-139, *:445, accept *:*`. Port 136 is not rejected. This ordered sequence appears in no
  other policy anywhere in May–October (`net/ourpolicy_line_order.csv`).

**Inference.**
- The operator says this edit went into the unused `/etc/tor/torrc` on Switzerland2. That explains why
  no family relay published it: they run from instance torrcs.
- Other operators on the same provider run tor from `/etc/tor/torrc`. Their relays published OUR_POLICY
  within minutes of the Switzerland2 activity (15:35–15:43).
- Details are in `../NETWORK_FINDINGS.md` §1 and §6.

## 5. Flags and departures

**Facts** (`repro_flag_timeline.csv`, `flag_events.csv`, `../net/votes_*.csv`).
- **Exit on former non-exits:** not applicable to the family, which had no non-exits. All 277 family
  relays carried Exit before and after 2026-10-02 (277 Exit at 2026-10-04 12:00).
- **Family departures on 2026-10-04:** present relays fell from 277 (14:00) to 272 (15:00), 248, 230,
  210, 153 (19:00), 31 (20:00) and 8 (21:00).
  - These departures were **silent**: no descriptor between leaving and the 2026-10-05 sweep, checked
    against descriptors published at or after the first missing consensus.
  - **Inference:** operator shutdown. The operator reports stopping relays after the 13:56 contact.
- **BadExit / MiddleOnly in the consensus:** first at **2026-10-04 21:00**, on the 8 family relays
  still present.
  - Votes: gabelmoo voted BadExit+MiddleOnly from 2026-10-04 18:00, moria1 from 19:00, longclaw from
    21:00. dannenberg voted MiddleOnly from 18:00, bastet from 20:00, maatuska from 10-05 08:00.
  - faravahar and tor26 know the BadExit flag but never voted it for these victims.
  - dizum, faravahar and tor26 never voted MiddleOnly for them.
  - In the consensus, BadExit needs a majority of the listing authorities that know the flag; it was
    reached when longclaw joined at 21:00.
- **After the 10-05 sweep:** 82 family relays were back at 10:00 (81 with BadExit+MiddleOnly) and 218 at
  11:00 (167 flagged).
- **At 2026-10-05 12:00 and 13:00, 208 and 111 family relays were in the consensus with the near-open
  `p` line but without BadExit, MiddleOnly or Exit.**
  - longclaw and maatuska stopped listing them at 12:00 (rejection by omission). That left 2 of 4
    BadExit-knowing listing authorities and 4 of 7 MiddleOnly votes, neither a majority.
  - **Inference:** a side effect of the flag-majority rule as authorities began rejecting at different
    hours.
- **Final departure:**
  - Votes show the family relays losing Running at 13:00–14:00; Running = 0 in every vote at 14:00.
    No family relay is in any consensus from 2026-10-05 14:00.
  - 35 of the 277 published a few more descriptors after their last consensus appearance (41
    descriptors).
  - **Inference:** a mix of authority rejection (longclaw and maatuska from 12:00, faravahar from 14:00,
    gabelmoo from 16:00) and Tor being stopped again.
- The `summary.md` line "BadExit gained by 175 / MiddleOnly by 175" counts only gains between
  consecutive intervals. Relays that came back after an absence already flagged are counted as
  "gained … after_gap" in `flag_events.csv`.

## 6. Other descriptor changes, for operator confirmation

Source: `repro_other_changes.csv`, whole window.
- **Contact:** 0 changes.
- **Nickname:** 0 changes. Every family relay is called `Quetzalcoatl`.
- **Platform / version:** 2,845 changes; after 2026-08-28 only the two upgrade waves and the moved
  relays below.
  - 2026-09-01: 8 relays 0.4.9.8 → 0.4.9.11.
  - 2026-09-08/09: 273 relays 0.4.9.11 → 0.4.9.12.
  - 2026-09-13, 09-21, 09-22, 09-27: one relay each, 0.4.9.9 → 0.4.9.12/13.
  - 2026-09-23/24: 276 relays 0.4.9.12 → 0.4.9.13.
- **Address / host moves after 2026-08-28:**
  - 2026-08-30 06:37:59: 8 relays, 149.102.153.38 → 96.44.159.202 (e.g. 28F47B28).
  - 2026-09-01 03:37:56: 8 relays, 45.141.215.169 → 192.210.214.13 (e.g. B04176E9).
  - Single relays moved off 150.40.126.172:
    - 2026-09-13 01:27:49, 392BEFDC → 192.3.212.126;
    - 2026-09-21 03:48:46, F532DA20 → 104.168.0.177, ORPort 110 → 9000;
    - 2026-09-22 01:45:49, 07DCECDF → 107.175.218.6, ORPort 143 → 9000;
    - 2026-09-27 01:45:51, DD68CED7 → 192.3.47.172, ORPort 7100 → 9000.
- **Family set:** changed together with each move above.
- **ed25519 master key:** no change on any family relay.
- **New RSA identities at an existing IP:ORPort:**
  - May–June: 17 replacements (2026-05-10/11 on 185.241.208.184 and 185.241.208.50; 06-08 on
    67.215.237.232; 06-17 on 192.227.183.149).
  - 2026-08-19 05:45:28: one on 192.3.42.78:9100.
  - None after 2026-08-28.
- **IPv6 policy:** 2026-08-23 05:00:42, 8 relays gained an IPv6 accept-list with the move to
  66.63.170.221. On 2026-10-02 all 277 switched to the near-open IPv6 summary (attack).
- **Family-cert line count:** 616 changes, mostly the line missing in the first descriptor after a
  restart (benign).

**Inference: events after 2026-08-28 that look like the operator's own work and should be confirmed:**
- the two version upgrades (09-08/09 and 09-23/24), which match the public 0.4.9.12 and 0.4.9.13
  security releases;
- the host moves of 08-30, 09-01, 09-13, 09-21, 09-22 and 09-27, including the ORPort normalization to
  9000;
- the routine restart runs of 08-28 to 09-30 listed in Appendix B (e.g. 08-30 15:45, 08-31 01:32,
  09-03 16:56, 09-05 11:19, 09-28 03:27);
- the 10-04 01:10–05:47 reboots;
- the shutdown of 10-04 15:00–21:00.

The 10-05 08:56 sweep is the one large family event whose ordering differs from the operator's routine.

## 7. Outsiders

**Facts** (`repro_family_members.csv`, `summary.md`).
- **402 relays outside the seed list carry the exact family contact, nickname `Quetzalcoatl` and a
  family line listing seeds.** They are family members missing from Switzerland2's MyFamily line.
  - 300 were last seen in May; 101 were active in October; 6 last in August.
  - Of the 101 active in October, 14 are on hosts that carry no seed relay: e.g. 154.53.58.161,
    194.163.136.187, 45.95.169.104, 45.95.169.32, 46.250.243.29, 5.104.84.183, 62.72.47.105,
    67.215.236.114, 67.215.237.232, 96.44.154.224, 96.44.159.202.
- **5 look-alike relays use a similar nickname but a different contact:**
  - `Quetzalcoat` 10E2D754… and 6CCA19F8… (185.66.71.170, contact `wonderlandolivesalad@atomicmail.io`,
    non-exit), 2026-05-14 → 2026-08-25/26;
  - `Quetzalcoatl346` 4F91F5F9… and C3768F73… (144.172.112.37, `neslo1y2dc@seznam.cz`) and C7E2C0FC…
    (23.94.84.118, `2l3btt9b3mt@hotmail.com`), 2026-08-18 16:23 → 08-19 22:26. These are exits with an
    accept-list.
  - None of them published an attacker policy.
- No relay outside the family lists family fingerprints in its family line without also carrying the
  family contact. Every "family-line" hit in `summary.md` is a family relay.

**Inference.**
- The look-alikes are unrelated operators with similar names. `Quetzalcoatl346` appeared nine days before
  the known infection and lived about 30 h. The timing alone does not tie it to the incident.
- Confirm: ask the operator whether they recognise these contacts.

## 8. Extra questions

### 8.1 How large was the active family in October?
**Fact:** 277 relays on 73 IPv4 hosts were in at least one consensus from 2026-10-01; 276 were present at
2026-10-01 12:00. Of the 277, 176 are seeds and **101 are not in the 362-fingerprint seed list**. 186
seeds were not active after June. By AS (relays/hosts): HostPapa 125/27, FranTech 48/24, netcup 40/14,
Contabo Asia 24/3, MAXKO 16/2, Contabo GmbH 16/2, Contabo Inc 8/1.

### 8.2 How many hosts did the 2026-10-05 sweep reach? Why does Onionoo say 55?
**Fact:** CollecTor records restarts on **70 hosts (253 relays) from 08:56:30 to 10:39:50**. The first
restart on the last new host is 96.44.159.202 at 10:25:53; later events are more relays on hosts already
reached (`repro_sweep_20261005.csv`).
**Fact:** a live Onionoo query, `details?family=29FEFE36…` (relays_published 2026-10-07 13:00), returns
168 relays on 57 hosts. 152 of them on 55 hosts have `last_restarted` 2026-10-05 08:56:30–10:26:56.
That reproduces the operator's figure exactly.
**Explanation (Fact):**
- Onionoo's family view only contains relays in Switzerland2's effective (mutual) family.
- 15 of the 70 sweep hosts are outside it. 14 carry only non-seed relays; the 15th is 94.72.104.135,
  whose 8 seed relays Onionoo does not list in that family.
- The 55 is therefore the subset of the sweep visible from Switzerland2's family view, not the whole
  sweep.

### 8.3 Real port impact of the new policy
**Fact** (`repro_port_impact.csv`):
- The operator's accept-list allowed **79 ports**; the near-open policy allows **65,311**.
- **65,235 ports were newly opened**, including 982 below 1024.
- **Three ports were closed: 563, 993 and 995.** The operator's accept-list included 563 (nntps).
  PROMPT.md mentions only 993 and 995.
- Newly allowed examples: 22, 23, 110, 143, 3389, 6667, 3306, 5432, 1433, 27017 and 6379. Port 25
  stays rejected.
- The IPv6 policy was opened the same way.

### 8.4 Family share of exits and exit weight
**Fact** (`repro_exit_share.csv`, Exit-flag relays and consensus weights):
- 2026-10-01 12:00: 276 of 3,075 Exit relays (8.98 %), 5.40 % of Exit-flag weight.
- 2026-09-24…30 mean: 8.70 % of relays, 5.42 % of weight.
- During the attack, 2026-10-02 12:00 → 10-04 12:00: 8.9–9.0 % of Exit relays and 5.08–5.30 % of exit
  weight.
- The family carried near-open policies from the 2026-10-02 10:00 consensus to the 2026-10-04 20:00
  consensus without BadExit (about 59 hourly consensuses).

### 8.5 Events after 2026-08-28 that look like the operator's own work
See §6 (Inference list) and Appendix B.

## 9. Independent verification and pitfalls

- **Verification:** the key numbers were re-derived by different code paths in
  `../scripts/verify_independent.py` (output in `../net/verification_independent.txt`). It works from
  the raw archives and the original script's CSVs instead of the DB, uses rule-sequence matching instead
  of the summarizer, counts flags straight from raw `s` lines, and uses IPFire instead of CAIDA.
  - The summarizer agrees with the authorities' `p` lines on every consensus-referenced descriptor
    checked: 203,044 / 203,044, 2026-09-24 → 10-07.
  - Results are listed in `../NETWORK_FINDINGS.md` §9. Every key family number reproduces:
    - 277 relays / 73 hosts;
    - 70-host / 253-relay sweep with 14 inversions;
    - 10-01 72 hosts / 275 relays;
    - Switzerland2 68 → 22 lines;
    - first and last flips.
- **Duplicate descriptors** were counted two ways: 239,144 by signed digest and 237,493 by file name.
  The 1,651 difference is identical signed content filed under two names.
- **Missing hours:** 9, listed in §0. Coverage counted from file *names* wrongly adds 6 more hours
  (2026-05-08 21:00 – 05-09 02:00): those consensuses exist but were written late, e.g.
  `2026-05-09-00-03-03-consensus` holds valid-after 2026-05-08 23:00. Coverage is counted by valid-after.
- **Duplicate descriptors:** 239,144 across monthly archives, removed by digest.
- **Uptime drift:** 41,346 boot shifts were discarded because the computed boot time is earlier than the
  previous publication.
- **Minute truncation:** `restart_events.csv` from the original script truncates to minutes. All
  ordering here uses seconds. With seconds, the 10-05 sweep has 14 inversions versus 18 in
  `summary.md`'s minute-level cluster.
- **End of window:** "absent at end" is measured against the last consensus scanned, 2026-10-07
  02:00:00.
- `summary.md` lists final departures only from 2026-08-01, and its daily table includes look-alike
  relays.
- **Refused descriptors and rejection:** the family's 10-04 departures are silent, so they were stopped.
  The 10-05 departures follow authority omission plus loss of Running.

## 10. Inferences in brief (with what would confirm or refute them)

1. **The policy flip of 2026-10-02 09:27:42–09:35:18 was one scripted reload across all 73 family
   hosts.**
   - For: 273 of 277 boot times unchanged; one identical text everywhere; 7.6 minutes.
   - Refute: host logs showing per-host local changes at other times.
2. **The 10-01 15:42–15:47 family-wide restart and the 10-05 08:56 sorted sweep were not the operator's
   routine runs.**
   - For: neither matches the routine order (τ ≈ 0.99 between routine runs); the 10-05 sweep is
     text-sorted.
   - Confirm: management-server and host auth logs.
3. **The family's 10-04 15:00–21:00 departures were the operator's shutdown.** They are silent in
   CollecTor. Confirm with operator records.
4. **No earlier compromise is visible publicly.** No attacker-pattern event anywhere before
   2026-10-01 14:49:51. Refute: host forensics showing earlier attacker presence that left no
   descriptor trace.

---
Appendix A: `_appendix_policy_changes.md` (321 rows, also `repro_policy_changes.csv`).
Appendix B: `_appendix_bursts.md` (bursts since 2026-08-20 and host orders of the key bursts).
