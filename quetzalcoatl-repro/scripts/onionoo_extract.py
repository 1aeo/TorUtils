#!/usr/bin/env python3
"""onionoo_extract.py - flatten the live Onionoo family snapshot (onionoo/details_family_29FEFE36....json,
fetched 2026-10-07, relays_published 2026-10-07 13:00) into out/onionoo_family_view.csv: fingerprint,
nickname, IPv4 host, running, last_seen, last_restarted, AS, flags, exit-policy summary. Cross-check only;
Onionoo is live data and drops relays offline for more than 7 days.
"""
import csv
import json

d = json.load(open("onionoo/details_family_29FEFE36A5F66A6C93D24775B9D2364A3831B597.json"))
with open("out/onionoo_family_view.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["relays_published", "fingerprint", "nickname", "host", "running", "last_seen", "last_restarted",
                "as", "as_name", "flags", "exit_policy_summary"])
    for r in sorted(d["relays"], key=lambda r: r["or_addresses"][0]):
        w.writerow([d["relays_published"], r["fingerprint"], r["nickname"], r["or_addresses"][0].rsplit(":", 1)[0],
                    r.get("running"), r.get("last_seen"), r.get("last_restarted"), r.get("as"), r.get("as_name"),
                    " ".join(r.get("flags", [])), json.dumps(r.get("exit_policy_summary"))])
print("rows:", len(d["relays"]))
