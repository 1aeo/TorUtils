# Task: rebuild the public Tor Metrics history of the Quetzalcoatl relay family

## Background

Two of our servers were compromised with the Ebury OpenSSH rootkit. The earliest known infection is **2026-08-28 03:25:11 UTC** (our management server). Known attacker activity on our relay server Switzerland2:

- **2026-10-01 15:35-15:43 UTC**: Tor was SIGHUPed and restarted, and the unused `/etc/tor/torrc` was edited. Published policy unchanged.
- **2026-10-02 09:34:03 UTC**: the instance torrcs were rewritten. At **09:34:04 UTC** both Switzerland2 relays published a near-open exit policy instead of their 68-line accept-list.
- **2026-10-04 13:56 UTC**: the operator stopped Tor on Switzerland2. At **2026-10-05 09:12 UTC** the attacker restarted it from inside the backdoor.
- **2026-10-05 08:56-10:26 UTC**: per Onionoo, relays on 55 family hosts were restarted in one scripted sweep, in text-sorted IP order.

Everything below uses public data from https://collector.torproject.org (Tor Metrics CollecTor). We need the family-wide public record to see:

- which relays changed and when;
- which non-exit relays were turned into exits;
- whether anything matching these patterns happened **before** 2026-08-28. That would point to an earlier compromise.

## Files in this folder

- `collector_family_history.py`: Python 3.8+, standard library only. It downloads the monthly CollecTor archives and streams them without unpacking to disk.
- `family_seed_fingerprints.txt`: the 362 fingerprints from the family's MyFamily line. All 168 relays that Onionoo listed for the family on 2026-10-06 are included. The script also picks up relays whose nickname or contact contains "quetzal", or whose family line lists one of these fingerprints.

## Steps

1. Check network access: `curl -sI https://collector.torproject.org/archive/relay-descriptors/consensuses/ | head -1` should print `HTTP/... 200`. If it doesn't, stop and report that.
2. Check you have about 3 GB of free disk (downloads go to `data/`; outputs are small).
3. Run the script. Downloads take a while; processing takes roughly 10-20 minutes.
   ```
   python3 collector_family_history.py --seed family_seed_fingerprints.txt \
       --start 2026-05 --end 2026-10 --descriptors-start 2026-06 --data data --out out
   ```
   - Consensus archives are small (about 27 MB a month). Always keep `--start 2026-05` so we get the months before the infection.
   - Server-descriptor archives are large (about 500 MB a month). If bandwidth or disk is tight, use `--descriptors-start 2026-08`, and say so in your report.
4. **Sanity check before anything else.** In `out/summary.md`, the section "Switzerland2 descriptors" must show, for both relays (29FEFE36..., 8427937D...):
   - a 68-line policy up to the descriptors published 2026-10-01 15:43:20/21;
   - a 22-line policy from 2026-10-02 09:34:04.

   If that isn't what you see, investigate and report; don't continue on bad data.
5. Analyze the outputs (`summary.md` and the CSVs) and write `out/FINDINGS.md` answering:
   1. **Policy changes since 2026-08-01:**
      - Which family relays changed exit policy, from what, to what, and exactly when? Use the descriptor publication times in `descriptor_changes.csv`; consensus times in `policy_transitions.csv` are only hourly.
      - Which of them were non-exits (`reject 1-65535`) before the change?
      - Give a table with these columns: relay fingerprint, nickname, IP, old policy class, new policy class, published time.
   2. **Clusters:** did changes or restarts happen in bursts, meaning several hosts within an hour or walking the IPs in sorted order? List each burst with its time range and host order. Include the 2026-10-05 sweep and any others (for example around 2026-10-01 15:42 or on 2026-10-04).
   3. **Before 2026-08-28 03:25:11 UTC:** look for anything matching the attacker's patterns in May through August:
      - policy flips, especially to the attacker summary below;
      - restart sweeps;
      - contact, family, platform or address changes;
      - relays joining the family or going missing.

      Say clearly whether you found any. A hit here could mean an earlier victim.
   4. **The Oct-1 "OUR_POLICY" summary:** did any relay ever publish `reject 25,110,135,137-139,143,445,465,587,993,995,3389`? That edit only takes effect on hosts where Tor reads `/etc/tor/torrc`.
   5. **Flags:** when did Exit appear on former non-exits? When did BadExit and MiddleOnly appear? When did relays drop out of the consensus? Separate operator shutdowns from directory-authority rejections where you can.
   6. **Other descriptor changes:** all contact, family, platform/version and nickname changes, so the operators can confirm which were theirs.
   7. **Outsiders:** relays outside the seed list that use the Quetzalcoatl name or contact, or that list our fingerprints in their own family line.

   Keep facts and inferences separate, and cite rows (fingerprint and timestamp) for every claim. Don't speculate about attribution beyond what the timing shows.
6. Return `out/FINDINGS.md`, `out/summary.md` and all CSVs. Zip the `out/` folder; do not include `data/`.

## Reference patterns

| Pattern | Exit-policy summary (consensus `p` line) |
|---|---|
| Attacker's near-open policy (2026-10-02) | `reject 25,119,135-139,445,465,563,587,993,995,1214,4661-4666,6346-6429,6699,6881-6999` |
| Oct-1 attempt in `/etc/tor/torrc` ("OUR_POLICY") | `reject 25,110,135,137-139,143,445,465,587,993,995,3389` |
| Non-exit | `reject 1-65535` |
| Operator's normal exit policy on Switzerland2 | an `accept` list of 60 port ranges (`accept 20-21,43,53,79-81,...`) |

Ports the attacker's policy opened that the operator's policy rejected: 22, 23, 110, 143, 3389 and 6667. Ports it closed: 993 and 995.

Notes:
- All of this is public data; nothing here is secret.
- If you extend the analysis, put the extra code in a separate script and say what it does. Don't change the detection logic in `collector_family_history.py` without saying so.
- Times in CollecTor are UTC.
