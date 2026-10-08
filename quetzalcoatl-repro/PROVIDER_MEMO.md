# Provider corroboration memo: why FranTech (AS53667)?

Prepared 2026-10-07 from public data only: CollecTor consensuses, descriptors and October votes;
CAIDA/IPFire AS data; public web pages. All times are UTC. **Facts** cite fingerprint, timestamp and
table (`net/…`); **Inferences** are labelled. No attribution is made beyond what the timing shows.

## Bottom line

- **Fact:**
  - Outside the Quetzalcoatl family, attacker exit policies (near-open / OUR_POLICY) hit
    **71 of 101 non-family FranTech relays (70.3 %)** in the reference consensus (2026-10-01 14:00).
  - On every other AS combined they hit **13 of 9,054 (0.14 %)**.
  - **11 operators hit on FranTech also ran relays on other providers, and none of those was hit.**
- **Fact:**
  - Most edits were **in-guest live reloads**: 38 of 40 on 10-01, 311 of 316 on 10-02.
  - Several waves **crossed providers**: 10-01 FranTech + Elxer; 10-03 FranTech + Redoubt + Snaju +
    ALEXHOST; the 10-04 22:21 rollback FranTech + ALEXHOST + DataWagon + Vultr.
- **Inference:**
  - Something specific to FranTech-hosted machines, or to how they are reached, explains most
    non-family victims. Relay profile does not explain it.
  - The edits themselves needed an in-guest root shell, not only hypervisor or panel access.
  - The best-supported hypotheses are:
    1. credential or session theft that clusters on FranTech customers (an SSH-credential-stealing
       backdoor seen from a shared vantage point);
    2. FranTech-specific in-guest access.
  - A FranTech-only mechanism cannot explain the cross-provider victims.

## 1. Profile test: is the concentration explained by relay profile?

`net/as_hit_rates.csv`, `net/provider_profile_tests.csv`, `net/provider_stratified.csv`;
script `scripts/net_infra.py`.

**Facts.**
- **Reference population:** the 9,428 relays of the consensus valid at 2026-10-01 14:00, the last
  before the first attacker-class descriptor at 14:49:51. The 764-fingerprint family is excluded
  because the family's own management server reached all its hosts (100 % hit on all 7 family ASes).
- **Stratified test.** Strata are exit/non-exit × tor version × OS × family-cert × IPv6.
  - Mantel–Haenszel OR ≈ 3.6×10³, CMH χ² = 1,358, p ≈ 1e-297.
  - Stratified on exit status alone: OR ≈ 1.5×10³.
  - In every stratum that has FranTech relays, the FranTech hit rate (33–100 %) exceeds the non-FranTech
    rate (0–1.25 %). Examples:
    - non-exit / 0.4.9.1x / Linux / no family-cert / no IPv6: inside 11/13 vs outside 4/1,794;
    - exit / 0.4.9.1x / Linux / no family-cert / IPv6: inside 26/29 vs outside 1/444.
- **Operator level:**
  - Operators with ≥ 1 FranTech relay: 44 of 59 hit.
  - Operators only elsewhere: 10 of 3,604 hit (Fisher p ≈ 5e-79).
  - Those 10 include the TorDola operator (Datashield), the BSE `.example` relays and operators on
    ALEXHOST, DataWagon, Snaju, Redoubt and Vultr. The count covers operators present in the
    reference consensus only.
- **Inside FranTech, hit vs not hit (relay level).** These differences are real but cannot explain the
  provider effect, because the same profiles are almost never hit elsewhere.

| attribute | hit / not | p (Fisher) |
|---|---|---|
| tor 0.4.9.11 | 21 / 0 | 0.0003 |
| tor 0.5.0.0 (alpha) | 0 / 5 | 0.002 |
| OS Linux / FreeBSD | 71 / 26 vs 0 / 4 | 0.007 |
| family-cert line absent / present | 58 / 9 vs 13 / 21 | 1e-6 |
| IPv6 ORPort absent / present | 33 / 2 vs 38 / 28 | 7e-5 |
| exit policy / non-exit | 56 / 14 vs 15 / 16 | 0.002 |
| first seen before 2026-05-02 | 62 / 18 vs 9 / 12 | 0.003 |
| location LU (107.189.x) / US | 48 / 16 vs 23 / 14 | 0.18 (n.s.) |

- Host level: 56 of 85 FranTech hosts hit, in the same directions. Operator level: 44 of 59, with
  family-cert (p = 0.006) and IPv6 (p = 0.002) the strongest negatives.

**Inference.**
- FranTech hosts that run FreeBSD, the 0.5.0.0 alpha, family-cert (Happy Family) or IPv6 were less often
  hit. These attributes mark more recently maintained setups.
- This fits an access path that depends on the host's age or maintenance state, e.g. stale credentials
  or old images. It also fits a Linux-only tool (FreeBSD 0/4).
- It does not explain why the effect is confined to FranTech.

## 2. Access-path evidence

**Facts.**
- **In-guest reloads.** A reload is a new descriptor with changed content and an unchanged boot time,
  which means SIGHUP or a control-port command inside the guest.
  - 10-01 15:33:55–15:39:19: 38 of 40 OUR_POLICY changes were reloads.
  - 10-02: 311 of 316 near-open changes were reloads, including all 39 non-family FranTech ones.
  - 10-02 10:15–11:51: non-exit → near-open by reload on FranTech and BSE.
  - Later waves (10-03, 10-04) were restarts.
  - Switzerland2's own 10-02 09:34:04 change was a reload: the boot stayed 10-01 15:43:18.
- **Single-instance edits on multi-relay hosts** (`net/attacker_transitions.csv`):
  - 107.189.5.249: on 10-01 only `2mpe4` 5957F8B3 changed (15:36:49 → OUR_POLICY). Its siblings `2mpe4b`
    0D8826A5 and `2mpe4c` BC7A5E91 changed only on 10-02 at 09:29:25/26, and 2mpe4 changed again at
    09:38:20.
  - 198.251.89.96: on 10-02 only `Polyphemus` 0CABED91 moved OUR_POLICY → near-open (09:44:12). Its
    three siblings stayed OUR_POLICY. On 10-01 all 16 Polyphemus relays on 4 hosts had changed in the
    same second, 15:37:16.
  - **Inference:** the edits touched particular torrc files, not "all tor instances". That matches the
    operator's account for Switzerland2: on 10-01 the generic `/etc/tor/torrc` was edited, and on 10-02
    the instance torrcs.
- **Ordering.**
  - The non-family FranTech reload run of 10-02 09:36:57–09:40:33 (31 hosts) was walked in near text
    order: 7.1 % of pairs inverted against a dot-ignoring sort, 31 % against a numeric sort.
  - So was the 10-04 22:21:18–22:47:33 rollback (23 hosts, 4 providers): 2 % inverted.
  - So was the family's 10-05 sweep (70 hosts, 4 providers): 0.4–0.6 % inverted.
  - **Inference:** one walker over a host list sorted as text, used across operators and providers.
- **Waves crossing providers:**
  - 10-01: FranTech ×39 + Elxer AS133255 (relayon9186 808DED5C, 103.39.237.147, India).
  - 10-02 10:21:10: BSE AS9044.
  - 10-02 20:41:52–20:44:47: no-change restarts on FranTech, Redoubt AS400304, Snaju AS399646 and
    ALEXHOST AS200019, followed by the same set flipping on 10-03 10:26.
  - 10-03 16:17: ALEXHOST ×3.
  - 10-04 22:21 rollback: FranTech 18, ALEXHOST 3, DataWagon 1, Vultr 1.
  - None of these non-FranTech operators is the Quetzalcoatl family.
- **Provider-wide events.**
  - The only pre-attack synchronized restarts on later-victim FranTech hosts (2026-08-16 21:27, 9
    hosts) also restarted 7 non-victim FranTech hosts in the same address blocks (209.141/205.185).
  - The October chains (10-02 20:41, 10-04 22:11) touched only victims, across several blocks.
- **Public status pages:** no FranTech or BuyVM security notice found. Their status page could not be
  fetched (503) during this research (`net/public_reports_notes.md`).

**Inference.**
- A provider control panel or hypervisor alone could change disk contents and reboot VMs. It would not
  naturally produce SIGHUP reloads, one-step byte-exact rollbacks, or edits on Elxer, ALEXHOST,
  Redoubt, Snaju, DataWagon and Vultr hosts.
- The pattern fits an actor with **root shells on individual hosts across several providers**, most of
  them FranTech customers. That actor walked sorted host lists, edited specific torrc files, reloaded,
  and later restored backups.

## 3. Directory-authority votes (votes-2026-10.tar.xz)

`net/votes_authority_summary.csv`, `net/votes_victim_flags_hourly.csv`, `net/votes_victim_first_flag.csv`,
`net/votes_address_test.csv`, `net/votes_consensus_20261005.csv`; scripts `votes_parse.py` and
`votes_analysis.py`.

**Facts.**
- 1,301 votes from 9 authorities. BadExit is a known flag for faravahar, gabelmoo, longclaw, moria1 and
  tor26. MiddleOnly is known to all nine.

| authority | BadExit for victims, from | MiddleOnly for victims, from | started omitting listed victims |
|---|---|---|---|
| gabelmoo | 2026-10-04 18:00 (231 → 245) | 10-04 18:00 | 10-04 16:00 (~100); 10-05 16:00 (all) |
| moria1 | 10-04 19:00 (319) | 10-04 19:00 | 10-04 19:00 (~26) |
| longclaw | 10-04 21:00 (245) | 10-04 21:00 | 10-05 12:00 (all family) |
| dannenberg | – (flag unknown) | 10-04 18:00 (305) | 10-04 18:00 (~26) |
| bastet | – (flag unknown) | 10-04 20:00 (245) | 10-04 17:00 (~100) |
| maatuska | – (flag unknown) | 10-05 08:00 (225) | 10-05 12:00 (all family) |
| faravahar | never (flag known) | never | 10-05 14:00 |
| tor26 | never (flag known) | never | – |
| dizum | – (flag unknown) | never | – |

- **Per fingerprint, not per address.** No relay sharing an IP with a victim but without an attacker
  policy was flagged. The new identity keys that appeared at victim hosts on 10-03 were flagged under
  their own fingerprints.
- **Consensus effect.**
  - BadExit reached a majority of BadExit-knowing listers at 2026-10-04 21:00, when longclaw joined.
  - When longclaw and maatuska stopped listing the family at 2026-10-05 12:00, the remaining listers no
    longer had a BadExit majority (2 of 4) or a MiddleOnly majority (4 of 7).
  - So 208 (12:00) and 111 (13:00) family relays appeared with near-open `p` lines and neither flag.
- **Missed:**
  - The 5 TorDola relays (OUR_POLICY since 10-01 14:49) were never flagged by any authority and stayed
    in the consensus as usable exits until 10-05 15:00.
  - 6 FranTech relays re-flipped at 10-04 17:49–17:52, after the BadExit list was drawn up at about
    18:00, also escaped flagging until they were removed.
  - In all, 14 victims were usable attacker-policy exits after 10-04 21:00 (`../NETWORK_FINDINGS.md` §3).

## 4. Public reports (paraphrased; URLs in `net/public_reports_notes.md`)

- **Tor Project, tor-relays list, 2026-10-05**, "Security incident affecting some relay operators" (hiro):
  - attackers gained root on Linux relay hosts and rewrote torrc to turn non-exits into exits for SSH
    interception;
  - Network Health flagged the relays and the authorities reject them;
  - indicators to check include NAT redirects of port 22, modified tor binaries, rogue keys and cron
    jobs, and a fake upper-case "CRON" daemon.
  - It names no provider and no count.
  - https://lists.torproject.org/mailman3/hyperkitty/list/tor-relays@lists.torproject.org/thread/WOHPLKCSHYXFTBRZXDENDKJZMBMPLMG5/
  - Spot-checked by direct fetch.
- **tor-relays, 2026-10-07**, "Ebury 1.8.3 on two Quetzalcoatl relay servers…" (apparently the family
  operator):
  - Contabo management VPS and FranTech VPS "Switzerland2";
  - attacker login 08-28 03:19 with the operator's password, Ebury installed 03:25–03:43 and on
    Switzerland2 at 04:38;
  - 10-01 /etc/tor/torrc edit; 10-02 instance torrcs; 10-04 05:46 kernel upgrade and reboot; 13:56 the
    network-health team contacted the operator;
  - 10-05 sweep of 55 hosts.
  - Not independent of the operator.
  - https://lists.torproject.org/mailman3/hyperkitty/list/tor-relays@lists.torproject.org/thread/QHRD6YOX6RZRDR7NCHNDO7GLCEA6VFM6/
  - Spot-checked.
  - The public data corroborates its times: Switzerland2 restart boot 10-01 15:43:18; reload at
    10-02 09:34:04; 10-04 05:47:26 restart (uptime 2); 10-05 09:12:22 restart.
- **forum.torproject.org 2026-08-31**, "Man-in-the-Middle Attack SSH in Tor": a user reports an SSH
  host-key mismatch over Tor. No relay is identified.
- **Ebury research.** ESET, "Ebury is alive but unseen", 2024-05-14:
  - Ebury is an OpenSSH credential-stealing backdoor that spreads with stolen credentials and has
    compromised hosting providers;
  - ESET reports its operators targeting Tor exit relays by redirecting SSH (iptables/ARP) to harvest
    credentials;
  - https://www.welivesecurity.com/en/eset-research/ebury-alive-unseen-400k-linux-servers-compromised-cryptotheft-financial-gain/
- **Providers.** No security incident was found on the status pages of Contabo, Hetzner, netcup,
  DigitalOcean, Linode, Scaleway, Hostinger or OVH for 2026-08-20 → 10-07. FranTech/BuyVM status could
  not be fetched.
- **Unrelated industry event:** the Virtualizor update hijack of 2026-08-28 20:57 → 08-30 06:10 starts
  17.5 h after the known infection.

## 5. Ranked hypotheses

Ranked by fit to the public record. Each entry gives evidence for and against, and what would confirm
or refute it.

### 1. Credential or session theft clustered on FranTech customers, by an actor with in-guest root (e.g. an SSH backdoor harvesting credentials) — **best fit**
- **For:**
  - in-guest reloads and byte-exact rollbacks;
  - specific torrc files edited;
  - cross-provider waves whose victims are mostly FranTech customers;
  - 11 multi-provider operators hit only on FranTech;
  - a known Ebury infection on a FranTech VPS (Switzerland2) since 2026-08-28;
  - Ebury's documented behaviour of spreading via harvested SSH credentials and targeting Tor exits;
  - FreeBSD hosts never hit.
- **Against:**
  - the public record shows no FranTech host compromised before 10-01;
  - why would credentials of many unrelated FranTech customers be exposed? A shared jump host, a
    provider-side SSH console or rescue system, or customers reusing keys are all speculative.
- **Confirm:** Ebury indicators (libkeyutils, abstract socket, sshd changes) on other victims' hosts;
  shared login sources in their auth logs at 10-01 15:33–15:39 and 10-02 09:29–09:44.
- **Refute:** clean victim hosts with no shell access in those windows.

### 2. Provider-specific access (FranTech panel, hypervisor, rescue system, guest agent)
- **For:** 70 % hit rate on FranTech versus 0.14 % elsewhere; the profile cannot explain it; the
  within-operator contrast.
- **Against:**
  - reloads require in-guest signalling;
  - edits and rollbacks are per-file and per-relay;
  - victims on Elxer, ALEXHOST, Redoubt, Snaju, DataWagon, Vultr and BSE;
  - pre-attack FranTech-wide events (08-16) look like ordinary maintenance.
- **Confirm:** a provider-side incident notice; panel or API logs of console or guest-agent commands
  at the wave times.
- **Refute:** victims' hosts showing interactive SSH root sessions as the cause.

### 3. Compromise of the Quetzalcoatl management server
- **For, as the explanation for the 277 family relays: strong.**
  - 100 % of family relays on 7 providers hit;
  - one 7.6-minute reload run on 73 hosts;
  - a family-wide restart 10-01 15:42–15:47 during the known Switzerland2 session;
  - known Ebury on the management server since 08-28.
- **Against, as the explanation for non-family victims:** no evidence that the family's server could
  reach other operators' hosts.
- **Confirm:** management-server logs of fan-out at 10-01 15:3x and 10-02 09:27–09:35.

### 4. Per-operator credential theft (independent compromises)
- **For:** non-family operators were hit on their FranTech hosts only.
- **Against:** 21–27 operators changed within minutes, in one sorted walk, with one shared rule order.
  That needs one actor holding all of their access, which turns this into hypothesis 1.

### 5. A common setup weakness (e.g. one install script, image or management tool)
- **For:**
  - older, unmaintained setups were hit more (0.4.9.11 21/21; no family-cert; no IPv6);
  - FreeBSD was never hit.
- **Against:** the weakness would have to be FranTech-specific (same profiles elsewhere are ~0 % hit).
- **Confirm:** the victims share a provisioning method, e.g. a BuyVM template or a third-party installer.

### 6. Attacker-run relays
- **For:**
  - TorDola, 4+1 relays on Datashield first seen 09-01 → 09-30, published the unique OUR_POLICY order
    first (14:49:51, 45 min before the FranTech wave). The order was built up on them in steps from
    2026-09-26 (7 rules), with 3389 added at 14:44:20 and the last 3 rules at 14:49:51.
    TorDola4 was created on 10-04 with OUR_POLICY. No authority flagged them.
  - `sk4d9f2m8x1q7w3j` / `thb8b35d95b69765` (BSE, `.example` contacts, created 2026-08-25).
- **Against:**
  - TorDola reverted to a new accept-list on 10-06 09:14 (restarts), which could be an operator fixing
    a victim.
  - Timing alone cannot separate "attacker-run" from "early victim".
- **Confirm:** provider customer records; whether TorDola hosts show compromise.
- **Refute:** TorDola's operator shows the same compromise artefacts.

### 7. A tor exploit
- **For:** none specific. 0.4.9.12 and 0.4.9.13 were security releases on 09-08 and 09-23.
- **Against:**
  - victims ran 0.4.9.6 → 0.4.9.13, and the changes are torrc edits plus SIGHUP or restart, which
    require local access;
  - the network-wide 0.5.0.0 and FreeBSD hosts were not hit;
  - nothing in descriptors suggests remote code execution.
- **Refute:** host forensics showing torrc writes by a non-tor process.

### 8. Earlier compromise (before 2026-08-28)
- **For (weak):**
  - the `.example` relays appeared 2026-08-25;
  - a 9-operator synchronized restart on FranTech on 2026-08-16;
  - FranTech identity replacements on 2026-05-03.
- **Against:**
  - no attacker-pattern descriptor anywhere before 2026-10-01 14:49:51;
  - the 08-16 restart also hit non-victims (maintenance-like);
  - the OUR_POLICY order is unseen before 10-01.
- **Confirm:** Ebury artefacts dated before 08-28 on any victim host. **Refute:** clean timelines.

## 6. What the operators and providers could check, from public data

- **FranTech victims:** auth logs and process accounting around:
  - 10-01 15:33:55–15:39:19 (OUR_POLICY reloads);
  - 10-02 09:29:25–09:44:12 (near-open reloads);
  - 10-02 20:41:52–20:44:47 (no-change restarts);
  - 10-03 10:26–11:46 (restarts and new keys);
  - 10-04 22:21:18–22:47:33 (rollback restarts).
- **The family:** the management server's sessions at 10-01 15:36–15:47, 10-02 09:27:42–09:35:18 and
  10-05 08:56:30–10:39:50.
