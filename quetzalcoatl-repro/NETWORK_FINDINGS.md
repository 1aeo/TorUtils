# Network-wide findings: attacker exit policies, October 2026 (independent reproduction)

Prepared 2026-10-07 from public CollecTor data: consensuses, server descriptors and October votes,
2026-05-01 → 2026-10-07 02:18 UTC. AS data comes from CAIDA pfx2as 2026-10-01 and as-org 20261001,
cross-checked with IPFire Location 2026-10-01.

- **Facts** cite a fingerprint, a UTC timestamp and a table under `net/`.
- **Inferences** are labelled and state how to confirm or refute them.
- No attribution is made beyond what the timing shows.
- The family-level report is `out/FINDINGS.md`; the provider analysis is `PROVIDER_MEMO.md`.

## Definitions

- **Victim:** any relay that published a descriptor whose IPv4 policy summarizes, with the
  re-implemented `policy_summarize`, to either
  - **near-open:** `reject 25,119,135-139,445,465,563,587,993,995,1214,4661-4666,6346-6429,6699,6881-6999`, or
  - **OUR_POLICY:** `reject 25,110,135,137-139,143,445,465,587,993,995,3389`.
- **Summarizer validation:** the re-implementation matches the authorities' consensus `p` line on all
  98,830 consensus-referenced descriptors checked in October, joined by descriptor digest.
- **Operator:** an exact contact string. Relays without a contact line are treated as separate unknown
  operators.
- **Family:** the 362 seeds plus relays carrying the exact Quetzalcoatl contact (764 fingerprints).
- **Restart:** boot time = published − uptime, to the second, with the drift rule.
- **Reload:** a content change without a new boot.

## Summary

| item | value |
|---|---|
| Victims (≥ 1 attacker-class descriptor) | **377 relays**: 277 family + 100 others; 331 near-open first, 46 OUR_POLICY first; 147 hosts; 53 contact strings |
| Earliest attacker descriptor anywhere | **2026-10-01 14:49:51, 4F72DEF09B015E9B6F210597083D95D8A3BC38AD "TorDola1" 185.231.33.82 (AS211720), OUR_POLICY** |
| Earliest near-open | 2026-10-02 09:27:42, F532DA2085F87777CE05EA947BF7B4F49B625754 (family, 104.168.0.177) |
| Attacker-class descriptors before 2026-10-01 | **none** (May–September, any relay) |
| Victims by AS | FranTech AS53667 129 (81 non-family), HostPapa AS36352 125 (family), netcup AS197540 40 (family), Contabo Asia AS141995 24 (family), Contabo GmbH AS51167 16 (family), MAXKO AS211619 16 (family), Contabo Inc AS40021 8 (family), Datashield AS211720 5, ALEXHOST AS200019 5, Snaju AS399646 2, Redoubt AS400304 2, BSE Software AS9044 2, DataWagon AS27176 1, Elxer AS133255 1, The Constant Company AS20473 1 |
| Non-family hit rate, relays in the consensus of 2026-10-01 14:00 | **FranTech 71/101 (70.3 %) vs. all other ASes 13/9,054 (0.14 %)**, Fisher p ≈ 1.5e-139 |
| Still publishing an attacker policy at the end | **35 relays** (all non-family; last descriptor attacker-class and published ≥ 2026-10-06 02:18:04; 26 near-open, 9 OUR_POLICY). None is in the final consensus (2026-10-07 02:00). |
| Peak usable exit-weight exposure | **7.46 %** of non-BadExit Exit-flag weight (351 victims, 2026-10-04 01:00; most relays: 352 at 04:00, 7.43 %) |
| BadExit / MiddleOnly per consensus | baseline ~36–38 / 31–33 → 98/79 (10-04 21:00) → 159/154 (10-05 10:00) → **243/238 (10-05 11:00)** → 35/30 (10-05 12:00) |

## 1. Victim census and waves

**Facts.**
- 377 victims. The full list, with state at the end of the window, is `net/victims.csv`; rendered
  table in `net/_appendix_victims.md`.
- 435 class transitions into or out of the attacker classes (`net/attacker_transitions.csv`):
  - 370 into;
  - 11 relays whose first descriptor already carried an attacker policy (new keys or new relays);
  - 24 between near-open and OUR_POLICY;
  - 30 out.
- Chained with gaps ≤ 15 min they form **19 waves** (`net/waves_15min.csv`, `net/waves_15min_events.csv`).
- Host order is tested with ties handled: same-second events are not ordered (`net/wave_host_order.csv`).

| # | time (UTC) | relays / hosts / operators | what happened | reload / restart | ASes | host order (inverted share of comparable pairs: str / num / nodot) |
|---|---|---|---|---|---|---|
| 1 | 10-01 14:49:51 → 14:50:03 | 4 / 4 / 1 | other reject-list → **OUR_POLICY** (TorDola, TorDola1-3; `dolas422@gazeta.pl`) | 4 reloads | Datashield AS211720 | 0 / 0.5 / 0 (4 hosts) |
| 2 | **10-01 15:33:55 → 15:39:19** | **40 / 28 / 21** | accept/other → **OUR_POLICY** | 38 reloads, 2 restarts | FranTech 39, Elxer 1 | 0.29 / 0.38 / 0.29; 16 Polyphemus relays (4 hosts) at 15:37:16 |
| 3 | **10-02 09:27:42 → 09:44:12** | **316 events / 108 hosts / 29** | family 277 accept → near-open (09:27:42–09:35:18); non-family: 15 into near-open, 15 OUR_POLICY → near-open, 9 OUR_POLICY reverted (8 byte-exact to their pre-10-01 policy; C3233B17 to a different accept-list) | 311 reloads, 5 restarts | HostPapa 125, FranTech 87, netcup 40, Contabo 48, MAXKO 16 | family 0.40 / 0.39 / 0.40; non-family sub-run 09:36:57–09:40:33 (31 FranTech hosts) **0.075 / 0.31 / 0.071** |
| 4 | 10-02 10:15:20 → 10:21:10 | 5 / 5 / 4 | **non-exit → near-open** (incl. `diskstats@mailboxly.example`) | reloads | FranTech 4, BSE 1 | — |
| 5–7 | 10-02 11:51:14, 14:26:22, 18:53:05 | 1 each | → near-open | reloads | BSE, DataWagon, FranTech | — |
| 8 | **10-03 10:26:02 → 11:04:30** | 23 / 15 / 13 (10 contacts + 3 without contact) | 15 non-exit/accept → near-open; then **8 new identity keys** at the same hosts, first descriptor near-open (10:39:20–11:04:30) | 14 restarts, 8 first, 1 reload | FranTech 17, Redoubt 2, Snaju 2, ALEXHOST 2 | 0.54 / 0.46 / 0.54 (parallel) |
| 9 | 10-03 11:46:10 | 1 | new key devvulLV 95AA4899 near-open | first | FranTech | — |
| 10 | 10-03 13:28:38 | 1 | non-exit → near-open (InnerRelayRP 9BB10876) | restart | Constant AS20473 | — |
| 11 | 10-03 16:17:09 → 16:18:40 | 4 / 4 / 4 | non-exit → near-open | restarts | ALEXHOST 3, FranTech 1 | 0 / 0.5 / 0 (4 hosts) |
| 12 | 10-04 08:26:36 | 1 | new relay TorDola4 EEF7AB01, first descriptor OUR_POLICY | first | Datashield | — |
| 13 | 10-04 17:49:24 → 17:52:02 | 6 / 6 / 4 | accept/other → near-open: 4 had been OUR_POLICY on 10-01 and reverted on 10-02 (F507D9EE, 607DD424, 0CB83F63, 67221DF5); 2 had no earlier attacker policy (0932F900, D76D33B4) | restarts | FranTech | 0.40 / 0.73 / 0.33 |
| 14 | **10-04 22:21:18 → 22:47:33** | **23 / 23 / 22** (18 contacts + 4 without contact) | **rollback**: 9 near-open → OUR_POLICY, 13 near-open → their pre-attack policy, 1 new key with OUR_POLICY | 22 restarts | FranTech 18, ALEXHOST 3, DataWagon 1, Constant 1 | **0.016 / 0.24 / 0.020 (text-sorted)** |
| 15–16 | 10-05 06:24:35, 07:46:34 | 1 each | near-open/OUR → non-exit | restarts | FranTech | — |
| 17–18 | 10-06 09:14:03, 12:00:43 | 4 + 1 | TorDola OUR_POLICY → a new accept-list | restarts | Datashield | — |
| 19 | 10-06 22:40:08 | 1 | drear FC088734 OUR_POLICY → accept-list | restart | FranTech | — |

- **Wave 14 is a byte-exact rollback.** For 22 of its 22 pre-existing relays, the new policy text is
  byte-identical to the text in force before their last change; the 23rd event is a new key
  (`net/rollback_check.csv`, `scripts/net_rollback_check.py`). Relays that went OUR_POLICY → near-open
  on 10-02 went back to OUR_POLICY; relays that were non-exit, other reject-list or accept-list before
  10-02/03 went back to exactly that.
- **Earliest appearance anywhere:** OUR_POLICY at 2026-10-01 14:49:51 (TorDola1). near-open at
  2026-10-02 09:27:42 (family relay F532DA20).
- No descriptor of any relay in May–September summarizes to either class (`net/policy_lineage.csv`).

**Facts: state at the end of the window** (last consensus 2026-10-07 02:00:00; last descriptor
2026-10-07 02:18:04):
- 351 victims' last descriptor is still attacker-class. 277 of them are family relays that stopped
  publishing on 10-04/10-05.
- **35 relays were still publishing an attacker policy in the final 24 h** (26 near-open, 9 OUR_POLICY;
  listed in `net/victims.csv`, column `last_desc_is_attacker`, with `last_desc` ≥ 2026-10-06 02:18:04).
  Examples:
  - 76959901 TorDotTeitelNet 198.98.51.189, 2026-10-06 16:35:33;
  - 0AE15611 DingBerry 198.98.61.60, 2026-10-07 00:09:38;
  - F2F423F8 HeyBroM 209.141.46.203, 2026-10-07 00:14:42;
  - the devvul relays E2077210, 23259052, 3A78F9C8, 95AA4899 (new keys), 23:16–23:27;
  - 808DED5C relayon9186 (Elxer, OUR_POLICY), 2026-10-06 18:18:53.
- None of the 35 is in the final consensus. In the last vote round in the data (2026-10-07 01:00) each
  was still listed by 1–3 of the 9 authorities (dizum 35, tor26 34, dannenberg 24), below the 5-vote
  majority: excluded from the consensus, not omitted by every authority.
- CollecTor `recent/` to 2026-10-08 03:38: 0 attacker `p` lines in the 2026-10-08 03:00 consensus;
  33 victims still publishing an attacker policy, all excluded (`net/email_current_status.csv`).
- Update to the 2026-10-08 06:00 consensus and votes (`scripts/email_followup_answers.py`,
  `net/email_followup_answers.log`; the votes' `r` lines carry descriptors that CollecTor's descriptor files
  do not have yet): 1 victim listed (9CDB4020); 34 publish an attacker policy, each in only 2-3 of 9
  votes (dizum, tor26, dannenberg), incl. family relay 07DCECDF04BE5D470C615C8E1CCF086F74FC8CA6
  (107.175.218.6), policy near-open, published 2026-10-08 04:35:57, its first descriptor since 10-05
  09:21:42; 19 publish another policy (11 their exact pre-10-01 text, 8 an accept-list); 323 (276 family)
  have no descriptor since 2026-10-06 10:40:07 and are in no vote.
- Of the 100 non-family victims, 67 kept publishing after
  leaving the consensus (strict count: descriptors at or after the first missing consensus), which
  points to authority rejection; 32 went silent; 1 is still listed.
- The one still listed is 9CDB4020 TimberDolphin63 (209.141.51.226). It had carried BadExit+MiddleOnly
  since August and now publishes a different reject-list.

## 2. Identical policy changes across operators

**Method.**
- Every descriptor-level policy-text change is normalized: own-IP /32 lines and tor's private-net lines
  are removed.
- This gives 10,822 changes. 1,199 are identical after normalization (IP changes) and are dropped.
- Changes are grouped by normalized new policy and chained with ≤ 60 min gaps. A group counts when it
  has ≥ 3 relays of ≥ 2 operators (`net/policy_change_groups*.csv`).

**Facts.**
- **Baseline May–September: 4 groups** (May 0, June 0, July 0, August 3, September 1). None is
  attacker-class, and none involves a later victim or a later-victim host:
  - 2026-08-17 20:47:47–20:47:59: 5 relays / 5 contacts → `accept 80,443` (HostPapa, DigitalOcean,
    AS44570, ALEXHOST);
  - 2026-08-19 00:17:32–00:18:06: 10 relays / 10 contacts → `accept 43,53,80,443,1194,1293,9418`
    (ALEXHOST, OVH, Hetzner, FranTech, AS63199, Scaleway). Six of them changed in the same second;
  - 2026-08-25 13:25:15–13:55:07: 4 relays / 2 contacts → `reject 25,135-139,445`;
  - 2026-09-28 08:05:13–08:11:14: 10 relays / 10 contacts → `reject 25,110,143,465,587,993,995` (Vultr
    AS20473 6, AS399629 4).
- **Inference:** the four baseline groups have random-looking or patterned contacts and change in the
  same second across providers. They are most likely undeclared multi-relay operators, which shows that
  "≥ 2 contact strings" overstates the number of independent operators. None of them is a precursor of
  this incident.
- **October: 8 groups**, 6 attacker-class:
  - 10-01 14:49:51–15:39:19, OUR_POLICY, 44 relays / 22 contacts;
  - 10-02 09:27:42–10:21:10, near-open, 312 / 25;
  - 10-03 10:26–10:54, near-open, 15 / 11;
  - 10-03 16:17, near-open, 4 / 4;
  - 10-04 17:49, near-open, 6 / 4;
  - 10-04 22:23–22:44, OUR_POLICY rollback, 9 / 9;
  - 10-04 22:25–22:47, → non-exit, 8 / 7 (rollback);
  - 10-06 09:00:59–09:02:36, 15 relays / 15 gmail contacts → `accept 1-65535` (Vultr/AS399629;
    unrelated to the victims).
- **Precursors:** no attacker-class group before 2026-10-01. The OUR_POLICY rule order, however, was
  built up beforehand on the TorDola relays (§6).

## 3. Directory-authority actions

**Facts** (`net/consensus_counts.csv`, `net/flag_batches.csv`, `net/flag_changes_key.csv`,
`net/victim_flag_timeline.csv`, `net/votes_*.csv`).
- **Baseline:**
  - Consensus BadExit May–September: min 27, median 72, max 96; about 36–38 on 2026-09-30/10-01.
  - MiddleOnly: min 25, median 64, max 91; 31–33.
  - Sybil: 0 throughout. StaleDesc: 3–347.
- **Batches on victims (consensus):**
  - 10-04 21:00: BadExit +62, MiddleOnly +48;
  - 10-05 08:00: MiddleOnly +11;
  - 10-05 10:00: BadExit +81, MiddleOnly +81 (relays back after the family's 10-05 sweep);
  - 10-05 11:00: +86 / +86;
  - **10-05 12:00: 197 victims lose both flags while still listed** (§3.1);
  - 10-05 14:00: −1.
  - Earlier BadExit/MiddleOnly batches of ≥ 3 relays (e.g. 2026-08-17 17:00 BadExit 12; 2026-09-29
    20:00 BadExit 6 + MiddleOnly 6) touch only one later victim: 9CDB4020, flagged on 2026-08-17.
- **Exit and Guard on victims:**
  - All **24 victims that were non-exits before gained the Exit flag**: 10-02 11:00 ×4, 14:00, 16:00,
    **10-03 11:00 ×14**, 10-03 14:00, 17:00 ×4.
  - Exit was lost on 10-04 21:00 (50), 10-05 10:00 (82) and 11:00 (136) as MiddleOnly applied.
  - Guard was lost on 10-04 16:00–21:00 (91) and 10-05 10:00–11:00 (117).
- **Note:** victim 9CDB4020 (TimberDolphin63) carried BadExit+MiddleOnly since 2026-08-17, before it
  published near-open (2026-10-02 10:15:20). It is excluded from the "first flag" times below; with it
  included, the first consensus with a BadExit victim is 2026-10-02 11:00.
- **Votes** (`net/votes_authority_summary.csv`). Nine authorities vote. Only faravahar, gabelmoo,
  longclaw, moria1 and tor26 list BadExit in known-flags; all nine list MiddleOnly.

| authority | first BadExit on a victim | max victims BadExit | first MiddleOnly | max MiddleOnly |
|---|---|---|---|---|
| gabelmoo | 10-04 18:00 | 245 | 10-04 18:00 | 245 |
| moria1 | 10-04 19:00 | 319 | 10-04 19:00 | 319 |
| longclaw | 10-04 21:00 | 245 | 10-04 21:00 | 245 |
| dannenberg | (BadExit not known) | – | 10-04 18:00 | 305 |
| bastet | (BadExit not known) | – | 10-04 20:00 | 245 |
| maatuska | (BadExit not known) | – | 10-05 08:00 | 225 |
| faravahar, tor26 | never (flag known) | 0 | never | 0 |
| dizum | (BadExit not known) | – | never | 0 |

- **Per fingerprint, not per address:**
  - No relay sharing an IP with a victim but without an attacker policy was ever flagged
    (`net/votes_address_test.csv`).
  - New identity keys created on 10-03 at victim hosts were flagged separately, once they published
    attacker policies.
  - The 107.189.8.56 entries (saciperere, GLASNOT, DDR, FOOBS, PERESTROIKA; platform "none") are
    descriptors that never reached a consensus, so they are noise.
- **Rejection by omission** (votes no longer listing victims that still publish):
  - gabelmoo from 10-04 16:00 (~100 victims), bastet 17:00, dannenberg 18:00, moria1 19:00.
  - On 10-05: longclaw and maatuska at 12:00, faravahar at 14:00, gabelmoo at 16:00.
  - Most non-family victims left the consensus on 10-05 16:00–17:00 (54), when the number of
    authorities listing them fell below a majority.
- **Listing needs Running too.** A relay is in the consensus only if ≥ 5 of 9 votes list it and ≥ 5 vote
  it Running. This rule reproduces all 54,665 victim relay-hours of 10-01..10-07 01:00; "≥ 5 votes" alone
  over-predicts 3,769. The family's 10-04 exit was lost reachability, not omission: at 10-04 21:00, 182
  family relays were in all 9 votes with 0 Running votes (263 in ≥ 5 votes, 8 with ≥ 5 Running, 8 listed).

### 3.1 The 10-05 12:00–13:00 gap
**Fact.**
- At 12:00, longclaw and maatuska stopped listing the family relays (and every other victim except
  9CDB4020). For the 157 family relays still in 7 votes:
  - BadExit: 2 (gabelmoo, moria1) of 4 BadExit-knowing listers;
  - MiddleOnly: 4 (bastet, dannenberg, gabelmoo, moria1) of 7;
  - Exit: 3 (dizum, faravahar, tor26) of 7.
  The other 51 listed family relays were in only 5 votes at 11:00 and 12:00 (MiddleOnly 2, BadExit 1) and
  were never flagged. A flag needs > half of the authorities that know it (BadExit 3 of 5, MiddleOnly 5
  of 9), counted over all votes, so omission counts against the flag. 40 non-family victims lost their
  flags at 12:00 the same way.
- Result: **208 (12:00) and 111 (13:00) family relays sat in the consensus with near-open `p` lines and
  neither BadExit, MiddleOnly nor Exit** (`net/votes_consensus_20261005.csv`).
- Exit-flag exposure was then only 13 relays, but the `p` lines still advertised near-open exits.

**Inference.**
- This is a side effect of authorities starting to reject at different hours. Clients that pick exits
  by policy rather than by the Exit flag could in principle have used these relays for 1–2 hours.
- Confirm: tor path-selection code for non-Exit-flag relays with exit policies.

**Exit-weight exposure** (`net/exit_weight_exposure.csv`, share of non-BadExit Exit-flag weight):

| consensus | victims usable as exits | share |
|---|---|---|
| 2026-10-01 15:00 | 3 | 0.22 % |
| 2026-10-01 16:00 | 43 | 2.04 % |
| 2026-10-02 10:00 | 325 | 7.10 % |
| 2026-10-04 01:00 (peak) | 351 | **7.46 %** |
| 2026-10-04 20:00 | 107 | 2.73 % |
| 2026-10-04 21:00 | 12 | 0.77 % |
| 2026-10-05 15:00 | 12 | 0.77 % |
| 2026-10-05 16:00 | 0 | 0 % |

- **Missed victims (Fact):** **14 victims were still usable attacker-policy exits (attacker `p` line,
  Exit, no BadExit) in consensuses from 2026-10-04 21:00 onward**, mostly until 10-05 15:00 (19
  consensuses):
  - the five TorDola relays 15CA183D, 4F72DEF0, 8B2CCF2A, C6AA7656, EEF7AB01, never flagged in any vote;
  - the six FranTech relays re-flipped 10-04 17:49–17:52 (wastedspace 0932F900, knuckledragger
    0CB83F63, ghostdriver 607DD424, pills 67221DF5, JACKofNINES F507D9EE, 2778626253393027 D76D33B4),
    i.e. after the authorities' first BadExit votes at 18:00;
  - mbserver 982FF2DA (from 10-05 00:00);
  - 4715's new key FEDA8542 (created 10-04 22:21:18, OUR_POLICY, 23:00 → 10-05 13:00);
  - Polyphemus13 FF5D90ED (10-04 21:00–23:00).
- 147 victims never carried BadExit or MiddleOnly in any consensus; most of them left (shutdown or
  rejection) before the flags applied (`net/victim_flag_timeline.csv`).
- **All 377 victims were flagged or omitted by at least one authority** at some point
  (`net/votes_victim_first_flag.csv`).

## 4. Restart and reload sweeps spanning several operators

**Method.**
- Per-operator bursts: host events chained with gaps ≤ 20 min (and 60 min), kept when they have ≥ 3
  hosts (`net/operator_bursts_*.csv`).
- Cross-operator coincidences: operator bursts whose time spans overlap (`net/multi_operator_sweeps_*.csv`).
- Key windows: `net/sweeps_key_windows.csv`.
- Event-level synchronisation on later-victim hosts: `net/victimhost_sync_chains.csv`.

**Facts: key windows** (non-family events on later-victim hosts unless stated).

| window | events |
|---|---|
| 10-01 14:30–16:00 | TorDola reloads 14:49:51–14:50:03. Family restarts 14:44:58–14:47:03 (5 hosts) and **15:36:30–15:47:53 (72 hosts / 275 relays)**. **31 non-family later-victim hosts / 23 operators, 15:33:55–15:43:47**: 38 reloads (the OUR_POLICY edits) + 32 restarts. Coincident unrelated bursts: fluffypancakes.dev 15:11–15:39 (19 hosts, no victims), nothingtohide.nl 15:52. |
| 10-02 09:00–10:30 | Family reload run 09:27:42–09:35:18 (73 hosts). Non-family FranTech reload run 09:29:25–09:44:12 (34 hosts / 27 operators), sorted sub-run 09:36:57–09:40:33. Non-exit → near-open reloads 10:15:20–10:21:10 (5 hosts). |
| 10-02 20:30–21:30 | **11 non-exit later-victim relays of 8 operators on 4 providers restarted 20:41:52–20:44:47 with no policy change** (klaxhex 034DC4E8, azadisrvs2 5806A7CE, sh97US104R 7E2FF265, dn3a 144C5DBE, paranoidtorrelay 3B953203, mbserver 982FF2DA, devvulLU/NY/LV/MI, Unnamed 2022BCB3). The same set restarted into near-open on **10-03 10:26:02–10:28:35**. No non-victim FranTech host restarted in 20:35–21:05. |
| 10-03 10:00–17:00 | 10:26–10:28 restarts → near-open (12 hosts / 9 operators). **10:39:20–11:46:10: 8 new identity keys at those hosts**, first descriptors near-open. 10:41–10:54 more (20 hosts / 17 operators). 13:28 and 16:17–16:19 single/four-host flips. |
| all of 10-04 | Family 01:10–05:47 (72 hosts, one restart per host over 4.6 h). TorDola4 created 08:26:36. 17:49–17:56 re-flip of 6 FranTech relays. **22:11:26–22:51:45: 28 later-victim hosts / 27 operators, 34 restarts, including the text-sorted rollback 22:21:18–22:47:33.** |
| 10-05 08:30–11:00 | **Family sweep 08:56:30–10:39:50, 70 hosts, text-sorted** (14 of 2,415 pairs inverted). No non-family attacker-policy events. |
| around 10-05 21:00 | 21:00:59–21:01:02: 6 hosts / 4 contacts restarted (Stan `favorite0ne@proton.me`, wastedspace, knuckledragger, umjallah), all FranTech former victims. No policy change into an attacker class. |

**Facts: baseline May–September.**
- Per-operator bursts of ≥ 5 hosts are common: 485–870 a month (`net/sweep_baseline.csv`).
- Overlapping multi-operator bursts are also common (84–229 a month).
- With ≥ 3 hosts, ≥ 2 operators and ≥ 10 min chaining on the 74 non-family later-victim hosts:
  May 1, July 5, August 3, September 7, October 12.
- The largest pre-October chains:
  - **2026-08-16 21:27:23–21:37:27: 9 hosts / 9 operators.** In 21:15–21:50, 16 FranTech hosts
    restarted: 9 later-victim and 7 non-victim, all in 209.141/205.185.
  - 2026-09-03 04:47:41–05:15:06: 9 hosts / 7 operators, all in 107.189.
- **Inference:** these pre-October chains are consistent with provider maintenance (whole-node VM
  restarts). They hit non-victims too and stay within one address block. By contrast, the 10-02
  20:41, 10-03 10:26 and 10-04 22:11 chains hit only victims, across several blocks and providers.
- Sorted walks are rare in the baseline: per-operator bursts of ≥ 5 hosts with zero text-sort
  inversions occur 10–17 times a month, almost all small runs of one operator.
- Sorted multi-operator walks occur only in October: 10-02 09:36:57, 10-04 22:21:18, and the family's
  10-05 sweep.

**Inference.**
- The 10-02 non-family run, the 10-04 22:21 rollback and the 10-05 08:56 family sweep share one
  signature: hosts walked in text order. The out-of-place hosts fit a sort that ignores dots (e.g.
  107.189.30.x before 107.189.3.11; 107.189.14.4 before 107.189.1.9).
- The family's own routine runs repeat a fixed unsorted order (τ ≈ 0.99), and the family's 10-02 reload
  run is unsorted.
- Confirm: process accounting or shell history on any affected host showing a sorted host list.
  Refute: provider or operator tooling that sorts hosts this way.

## 5. Infrastructure

Details are in `PROVIDER_MEMO.md`; CSVs: `net/as_hit_rates.csv`, `net/provider_profile_*.csv`,
`net/provider_stratified.csv`, `net/multi_provider_operators.csv`, `net/newcomers.csv`.

- **Reference set:** the 9,428 relays of the consensus of 2026-10-01 14:00, the last before the first
  attacker descriptor. 357 later became victims; 20 victims were not present then (new keys or relays,
  or absent that hour).
- **Hit rates per AS (Fact):**

  | AS | family hit | non-family hit |
  |---|---|---|
  | **FranTech AS53667** | 48/48 | **71/101 (70.3 %)**: exits 56/70, non-exits 15/31 |
  | HostPapa | 123/123 | 0/105 |
  | netcup | 39/39 | 0/249 |
  | Contabo Asia | 23/23 | 0/11 |
  | Contabo GmbH | 16/16 | 0/50 |
  | MAXKO | 16/16 | 0/31 |
  | Contabo Inc | 8/8 | 0/6 |
  | Datashield | — | 4/5 (TorDola) |
  | ALEXHOST | — | 4/23 |
  | BSE | — | 2/3 |
  | Snaju | — | 1/6 |
  | DataWagon | — | 1/8 |
  | Constant (Vultr) | — | 1/95 |

  All other ASes: 0. **Inference:** the family was reached through its own infrastructure on every
  provider. Outside the family, FranTech is the most affected provider.
- **Inside FranTech, hit vs not hit (non-family; Fisher two-sided):**
  - Relay level:
    - tor 0.4.9.11: 21/21 hit; 0.5.0.0: 0/5 (p = 0.0018).
    - FreeBSD: 0/4; Linux: 71/97 (p = 0.0067).
    - No family-cert: 58/67 hit; with family-cert: 13/34 (p = 1.3e-6).
    - No IPv6 ORPort: 33/35; with IPv6: 38/66 (p = 7e-5).
    - Exit policy: 56/70; non-exit: 15/31 (p = 0.002).
    - Present since before 2026-05-02: 62/80; newer: 9/21 (p = 0.003).
    - Country LU 48/64 vs US 23/37 (p = 0.18, n.s.).
  - Host level: 56/85 hit; the same direction for IPv6, family-cert, version and OS.
  - Operator level: 44/59 hit; operators without family-cert 36/42 vs with 8/17 (p = 0.006); without
    IPv6 27/29 vs with 17/30 (p = 0.002).
- **Operators on several providers (Fact):** 12 operators were hit on FranTech, and **none of them was
  hit on any other provider**. For example:
  - Brandon Kuschel: FranTech 16/16 hit; GoDaddy 0/5; OVH 0/3.
  - "Satanist": FranTech 2/2; 18 relays on 10 other ASes 0.
  - middelstaedt: FranTech 2/2; Gigahost 0/6.
  - Triangulum1's operator: FranTech 1/1; OVH 0/1 (found by `scripts/email_operator_pattern.py`;
    `net_infra.py` missed it and gave 11).
  - Also Jeff Teitel (OVH 0/1), DoNotDisturb (Comcast 0/1), passmail (IONOS 0/1, Oracle 0/1) and
    others (`net/multi_provider_operators.csv`).
- **Suspicious newcomers (Facts, `net/newcomers.csv`):**
  - BSE Software AS9044:
    - FDBEAC98 `sk4d9f2m8x1q7w3j` (82.220.38.26, contact `diskstats@mailboxly.example`);
    - AE6507A4 `thb8b35d95b69765` (82.220.39.121, `thermalmon@outlook.example`).
    - Both were first published 2026-08-25 15:19–15:38, three days before the known infection. They
      have random nicknames and `.example` contacts, were non-exits, and flipped to near-open on
      **10-02 10:21:10 and 11:51:14**, outside the main family and FranTech runs.
  - TorDola (Datashield AS211720): first published 2026-09-01 23:53, 09-02, 09-29 and 09-30. These are
    the earliest OUR_POLICY publishers; TorDola4 was created 2026-10-04 08:26:36 with OUR_POLICY.
  - ALEXHOST relays MyTorGuardRelay1 54955A17, MDrelay 7BC58F5C and Relay 92A7F611 were first seen
    2026-08-02, non-exits flipped on 10-03 16:17–16:18.
  - Of non-family FranTech relays present on 10-01, only 2 were first published after 2026-09-01, and
    neither was hit.
  - **Inference:** the `.example` relays and TorDola are the strongest "attacker-run relay" candidates:
    relays whose operator set the policy themselves. Timing alone cannot separate that from victims
    with odd contacts. Confirm: provider customer records; whether these hosts show compromise
    artefacts.

## 6. Precursors, May–September

**Facts.**
- **Synchronized cross-operator events on later-victim hosts:** see §4. The largest pre-infection
  chain (2026-08-16 21:27, 9 hosts / 9 operators) also restarted 7 non-victim FranTech hosts in the
  same block. Days around 2026-08-28: 1 chain on 2026-08-31 07:08:54–07:13:43, 5 hosts / 2 operators
  (Brandon Kuschel, torix), restarts only. Nothing on 08-25 to 08-30 (`net/victimhost_sync_chains.csv`,
  column `aug25_31`).
- **Events on later-victim hosts 2026-08-20 → 09-05:** 1,556 (1,418 restarts, 132 descriptor changes,
  4 first-starts, 2 reloads) (`net/victim_host_events_aug.csv`). The 2 reloads and 132 changes are
  routine (family-cert, bandwidth, address). No policy change toward an attacker class.
- **Identity-key changes:**
  - ed25519 master-key changes on the same RSA fingerprint: 1 network-wide (April), none on victims.
  - New RSA identity at the same IP:ORPort within 48 h: 1,840 network-wide (`net/identity_replacements.csv`),
    44 on later-victim hosts.
  - Before October, the later-victim-host cases are: FranTech hosts on 2026-05-03 (DingBerry
    198.98.61.60 16:30:44, Dumbledore 45.61.188.15 16:48:22, HeyBroM 209.141.46.203 17:15:20,
    icestorm → RestoreEU 107.189.6.232 20:09:40); family hosts on 2026-05-10/11, 06-08, 06-17 and
    08-19; and 132.243.175.244 on 2026-08-02.
  - **In October, 10 new identities appeared at victim hosts on 10-03 10:39:20–11:46:10.** Nine have a
    near-open first descriptor: azadisrvs2 91D9FFB5, dn3a 1D9FE06D, Unnamed C9FEFBF4, sh97US104R
    51E61685, mbserver 784F8445, devvulLU E2077210, devvulNY 23259052, devvulMI 3A78F9C8, devvulLV
    95AA4899. The tenth, DicedOnions 190BD23B, has an accept-list.
  - Later: 4715 FEDA8542 on 10-04 22:21:18 (OUR_POLICY), Unnamed 7F75629E on 10-05 16:40:07, ZEYS
    57075066 on 10-06 12:52:15.
- **Policy lineage:**
  - Only two normalized attacker texts exist in the whole window (`net/policy_lineage.csv`): OUR_POLICY
    (12 rules) and near-open (15 rules).
  - **The full OUR_POLICY ordered sequence `25, 465, 587, 110, 143, 993, 995, 3389, 135, 137-139,
    445` first appears at 2026-10-01 14:49:51 (TorDola1 4F72DEF0, Datashield) and nowhere earlier**
    (descriptors 2026-01 → 09; consensus `p` lines 2025-01 → 2026-09; `net/email_history_check.csv`).
    It is contained in 33 policy texts, all OUR_POLICY, on 46 relays (`net/ourpolicy_line_order.csv`).
  - **It was built up in steps on the 4 TorDola relays** (contact `dolas422@…`, AS211720):
    - the first 7 rules in the same order (25, 465, 587, 110, 143, 993, 995) from 2026-09-26 06:10:06
      (all 4 by 09-30 13:46:12; 36 descriptors);
    - 3389 added 2026-10-01 14:44:20–14:44:31;
    - 135, 137-139 and 445 added 14:49:51–14:50:03.
    No other relay used these ordered prefixes (≥ 7 rules) before 10-01 (`scripts/email_timeline_verify.py`).
  - The nearest earlier relative is the mail-only `reject 25,110,143,465,587,993,995`, used in 2025-01,
    2025-09, by TorDola from 2026-09-01 and by 10 new Vultr/AS399629 relays on 2026-09-28 (§2 group 4).
  - **Inference:** the OUR_POLICY text was developed on the TorDola relays before it appeared on 40
    relays of 21 other operators 44 minutes later. Whether TorDola's operator or an intruder on those
    hosts wrote it cannot be told from public data.
  - The near-open text first appears at 2026-10-02 09:27:42 (family).

**Inference.**
- No public precursor to the attack is visible before 2026-10-01 14:49:51, in particular none around
  2026-08-28.
- The 2026-05-03 key changes on four FranTech hosts of three contacts are older than the known infection
  and not obviously linked. They could reflect a provider event (VM restore) or operator actions.
  Confirm with those operators.
- The 10-03 new keys are consistent with tor started with an empty or unreadable DataDirectory, e.g.
  run by hand as a different user. They are also consistent with a deliberate key change to escape
  fingerprint-based flags. The record cannot separate the two.

## 7. Time of day (descriptive only)

`net/time_of_day.csv`.
- Transitions into an attacker policy (381) fall in UTC hour 09 (292), 15 (40), 10 (25), 11 (5),
  14 (5), 17 (6), 16 (4), 13, 18, 22 and 08 (1 each).
- Victim reloads in October: hour 09 312, 15 38.
- Victim restarts in October peak at 15 (311), 10 (158), 09 (136) and 01 (101).
- The same victims' May–September baseline restarts (14,897) peak at 00–03 UTC (931–1,169 an hour) and
  23 UTC (848), with a minimum at 08–09 UTC (299–308).
- The attacker-pattern events thus fall mainly at 09 and 15 UTC, hours that are below average in the
  victims' routine restart profile. No conclusion is drawn from this.

## 8. Red-team pass (attempts to refute)

- **Coincidence against the baseline.** Identical-policy cross-operator groups happen about once a
  month (4 in May–September). Ordered reload runs on 28–34 hosts of 21–27 operators within minutes
  never happen in the baseline. The OUR_POLICY line order is unique in six months. Coincidence is
  rejected for 10-01, 10-02 and 10-04 22:21.
- **Provider maintenance.**
  - It explains the 08-16 and 09-03 restart chains (non-victims restarted too; one block).
  - It cannot explain reloads: a reload is a SIGHUP inside the guest with no new boot.
  - It cannot explain the content changes or a byte-exact per-relay rollback.
- **Operators copying a common config.**
  - near-open is a common one-liner, but nobody used it in May–September. 46 operators would have had
    to adopt it within 17 minutes on 10-02, many by reload.
  - OUR_POLICY's line order is idiosyncratic.
  - Rejected as the main explanation. It cannot be excluded for individual relays: TorDola later
    published a different policy of its own.
- **Directory-authority actions.** Flags and omissions explain the departures and the 10-05 12:00 gap,
  but not the descriptor content.
- **Data artifacts.**
  - Duplicates were removed by digest.
  - Drift was filtered.
  - Missing consensus 2026-10-01 19:00 does not affect descriptor timing.
  - The summarizer was validated against `p` lines.
  - The name-based coverage artefact is documented (§9).
  - Operators counted by contact may overstate independence (see the §2 baseline groups). Even so,
    the 12 multi-provider operators hit only on FranTech is a within-operator contrast that does not
    depend on that count.

## 9. Independent verification

`scripts/verify_independent.py` → `net/verification_independent.txt` uses different code paths: raw
archives, rule-sequence matching instead of summarization, raw `s`-line regex counts, file names, and
IPFire ASNs instead of CAIDA. Results:
- **V1 coverage.**
  - By file name: 3,804 hourly names, 15 hours "missing".
  - Of these, 6 (2026-05-08 21:00 → 05-09 02:00) exist with late file names, e.g.
    `2026-05-09-00-03-03-consensus` = valid-after 2026-05-08 23:00.
  - The content-based count (3,810 consensuses, 9 missing) is correct, and the discrepancy is a naming
    artefact.
- **V2 duplicates.**
  - By file name: 3,006,543 files, 2,769,050 unique names, 237,493 cross-archive duplicates.
  - By signed-content digest (main pipeline): 2,767,399 unique, 239,144 duplicates.
  - The 1,651 difference is descriptors with identical signed content filed under two different file
    names (415 such pairs in Sep–Oct alone, e.g. digest 58bf30ba… under two names). Digest
    de-duplication is the correct one.
- **V3 victims by rule-sequence matching** (no summarizer): **377 relays (331 near-open, 46 OUR_POLICY)**
  in all May–October archives.
  - Earliest OUR_POLICY 2026-10-01 14:49:51 4F72DEF0… TorDola1; earliest near-open 2026-10-02 09:27:42
    F532DA20….
  - Per IPFire AS: FranTech 129, HostPapa 125, netcup 40, Contabo Asia 24, Contabo GmbH 16, MAXKO 16,
    Contabo Inc 8, Datashield 5, ALEXHOST 5, BSE 2, Snaju 2, Redoubt 2, Elxer 1, DataWagon 1, Constant 1.
  - Identical to the CAIDA-based counts.
- **V4 Switzerland2** from the raw archive: 68 lines at 2026-10-01 15:43:20/21; 22 lines at
  2026-10-02 09:34:04 (both). Identical.
- **V5 flags** from raw `s` lines: BadExit 35–243 in October, peak 243 at 2026-10-05 11:00; MiddleOnly
  max 238. 10-04 20:00 36/31; 21:00 98/79; 10-05 10:00 159/154; 12:00 35/30. Identical to
  `consensus_counts.csv`.
- **V6 family**, from the original script's CSVs with an independent restart computation:
  - 277 relays / 73 hosts in October;
  - 10-05 sweep 70 hosts / 253 relays, 08:56:30 → 10:39:50, 14 of 2,415 pairs inverted;
  - 10-01 72 hosts / 275 relays, 15:36:30 → 15:47:53.
  - Identical.
- **V7 FranTech hit rate** with IPFire ASNs and the raw 2026-10-01 14:00 consensus: 71/101 non-family
  inside vs 13/9,054 outside. Identical.
- **Summarizer:** agrees with the authorities' `p` line for **203,044 / 203,044** descriptor/consensus
  pairs (all consensus entries 2026-09-24 → 10-07). 435 referenced digests have no descriptor in the
  archives (published before May or not archived).

## Appendices
- `net/_appendix_victims.md`: all 377 victims.
- `net/_appendix_waves.md`: all waves.
- `net/public_reports_notes.md`: public reports (paraphrased, with URLs).
