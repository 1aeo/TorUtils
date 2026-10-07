# Quetzalcoatl incident: independent reproduction from public Tor Metrics data

A blind, from-scratch reproduction of the incident analysis covering the Quetzalcoatl relay family and
the wider Tor network, May–October 2026. It uses public data only: CollecTor archives, CAIDA and IPFire
AS data, and public web pages.

## Deliverables
- `out/FINDINGS.md`: family findings (PROMPT.md questions 1–7 and the extra questions), with appendices
  `out/_appendix_*.md` and CSVs `out/repro_*.csv`. The original script's outputs (`summary.md`, CSVs,
  `policies/`) are in the same folder. Zipped as `collector-results-repro.zip`.
- `NETWORK_FINDINGS.md`: network-wide findings (victims, waves, identical policy changes, authority
  actions, sweeps, infrastructure, precursors, time of day, red team, independent verification).
- `PROVIDER_MEMO.md`: provider corroboration memo (profile test, access path, votes, public reports,
  ranked hypotheses).
- `net/*.csv`: derived network tables. `net/public_reports_notes.md` holds the public reports with URLs.
  Zipped, with all scripts, as `network-results-repro.zip`. Databases over 100 MB are excluded.

## Inputs (as given)
- `PROMPT.md`
- `family_seed_fingerprints.txt` (362 seeds)
- `collector_family_history.py` (unmodified)

## How to reproduce
```
python3 collector_family_history.py --seed family_seed_fingerprints.txt --start 2026-05 --end 2026-10 \
    --descriptors-start 2026-05 --data data --out out             # ~3 GB download, ~20 min
python3 -I scripts/build_netdb.py --data data --db net/netdb.sqlite --workers 3   # ~10 min, 3.8 GB DB
python3 -I scripts/derive_tables.py
python3 -I scripts/asmap.py          # needs asdata/: CAIDA pfx2as 20261001-1200, as-org 20261001, IPFire location-2026-10-01
python3 -I scripts/net_victims.py
python3 -I scripts/net_dirauth.py
python3 -I scripts/net_policy_groups.py
python3 -I scripts/net_precursors.py
python3 -I scripts/net_sweeps.py
python3 -I scripts/net_timeofday.py
python3 -I scripts/votes_parse.py    # needs data/votes-2026-10.tar.xz
python3 -I scripts/votes_analysis.py
python3 -I scripts/net_infra.py
python3 -I scripts/net_wave_order.py
python3 -I scripts/net_rollback_check.py
python3 -I scripts/net_victimhost_sync.py
python3 -I scripts/family_analysis.py
python3 -I scripts/onionoo_extract.py   # needs onionoo/ snapshot (live Onionoo, cross-check only)
python3 -I scripts/make_tables.py
python3 -I scripts/verify_independent.py   # independent re-derivation, raw archives
```
Every script starts with a docstring describing what it does. `scripts/common.py` holds the
re-implementation of tor's `policy_summarize()`; it is validated against the consensus `p` lines
(203,044 / 203,044 agree).

Large local data is not committed: `data/` (CollecTor archives), `asdata/` (CAIDA/IPFire), `onionoo/`
(raw JSON) and `net/netdb.sqlite` / `net/tmp/`.
