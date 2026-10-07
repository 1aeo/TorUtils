#!/usr/bin/env python3
"""derive_tables.py - derived per-relay event tables in the network DB (all relays).

Tables written (and CSVs under net/ for the interesting subsets):
  desc_change(fp, published, pub_epoch, prev_published, nickname, address, field, old, new, same_run)
      consecutive-descriptor changes per relay (ordered by publication) in: policy, contact, family set,
      platform, address, or_port, dir_port, nickname, ed25519 key, ipv6-policy, family-cert count,
      or-addresses, configured bandwidth (rate/burst).
  restart(fp, boot_epoch, boot, nickname, address, contact_h, prev_published, first_published, gap_s,
          ip_change, first_in_window, policy_changed, platform_changed, old_platform, new_platform)
      restart time = published - uptime, to the second. A new boot time only counts as a restart when it
      is NOT earlier than the previous descriptor's publication time (otherwise it is uptime drift).
      De-duplicated per relay (each boot counted once). ip_change=1 when the address also changed
      (tor resets uptime on an IP change).
  reload(fp, published, pub_epoch, boot_epoch, nickname, address, contact_h, fields)
      a descriptor whose content changed (policy/contact/family/nickname/ports/ipv6-policy/or-address/
      configured bandwidth) while the boot time did not -> live config reload (SIGHUP / control port).
      family-cert-only changes are excluded (benign).
  absence(fp, after_va, from_va, to_va, before_va, n_consensuses_missing, final, descs_while_absent,
          last_desc_while_absent)
      gaps in consensus presence; descs_while_absent>0 = still publishing (authority rejection or
      reachability failure), 0 = silent (probably stopped). final=1 for absences that run to the last
      consensus scanned (measured against the global last valid-after, not the relay's own last).
  policy_event(fp, published, pub_epoch, prev_published, nickname, address, contact_h, old_h, new_h,
               old_summary, new_summary, old_class, new_class, kind)
      every descriptor-level policy-text change; kind = restart / reload / first.
  victim(fp)  relays that published a descriptor whose policy summarizes to near-open or OUR_POLICY.
"""
import argparse
import bisect
import csv
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import epoch_ts, log, ts_epoch  # noqa: E402

FIELDS = [("policy_h", "policy"), ("contact_h", "contact"), ("family_h", "family"),
          ("platform", "platform"), ("address", "address"), ("or_port", "or_port"),
          ("dir_port", "dir_port"), ("nickname", "nickname"), ("ed25519", "ed25519"),
          ("ipv6_policy", "ipv6_policy"), ("family_cert", "family_cert"),
          ("or_addresses", "or_addresses"), ("bwcfg", "bw_config")]
RELOAD_FIELDS = {"policy", "contact", "family", "nickname", "or_port", "dir_port", "ipv6_policy",
                 "or_addresses", "bw_config", "address"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="net/netdb.sqlite")
    ap.add_argument("--out", default="net")
    args = ap.parse_args()
    db = sqlite3.connect(args.db)
    db.executescript("""
      DROP TABLE IF EXISTS desc_change; DROP TABLE IF EXISTS restart; DROP TABLE IF EXISTS reload;
      DROP TABLE IF EXISTS absence; DROP TABLE IF EXISTS policy_event; DROP TABLE IF EXISTS victim;
      CREATE TABLE desc_change(fp TEXT, published TEXT, pub_epoch INTEGER, prev_published TEXT,
        nickname TEXT, address TEXT, field TEXT, old TEXT, new TEXT, same_run INTEGER);
      CREATE TABLE restart(fp TEXT, boot_epoch INTEGER, boot TEXT, nickname TEXT, address TEXT,
        contact_h TEXT, prev_published TEXT, first_published TEXT, gap_s INTEGER, ip_change INTEGER,
        first_in_window INTEGER, policy_changed INTEGER, platform_changed INTEGER, old_platform TEXT,
        new_platform TEXT);
      CREATE TABLE reload(fp TEXT, published TEXT, pub_epoch INTEGER, boot_epoch INTEGER, nickname TEXT,
        address TEXT, contact_h TEXT, fields TEXT);
      CREATE TABLE absence(fp TEXT, after_va TEXT, from_va TEXT, to_va TEXT, before_va TEXT,
        n_missing INTEGER, final INTEGER, descs_while_absent INTEGER, last_desc_while_absent TEXT);
      CREATE TABLE policy_event(fp TEXT, published TEXT, pub_epoch INTEGER, prev_published TEXT,
        nickname TEXT, address TEXT, contact_h TEXT, old_h TEXT, new_h TEXT, old_summary TEXT,
        new_summary TEXT, old_class TEXT, new_class TEXT, kind TEXT);
      CREATE TABLE victim(fp TEXT PRIMARY KEY);
    """)
    pol = {h: (s, c) for h, s, c in db.execute("SELECT policy_h, summary, class FROM policy")}
    n_drift = 0
    cur_fp, rows = None, []

    def process(fp, rows):
        nonlocal n_drift
        chg, rst, rld, pev = [], [], [], []
        last_boot = None
        prev = None
        for r in rows:
            (dig, published, pe, nick, addr, orp, dirp, ora, plat, up, boot, bwa, bwb, ch, fh, fc, ip6,
             ed, ph) = r
            r_d = {"policy_h": ph, "contact_h": ch, "family_h": fh, "platform": plat, "address": addr,
                   "or_port": orp, "dir_port": dirp, "nickname": nick, "ed25519": ed, "ipv6_policy": ip6,
                   "family_cert": fc, "or_addresses": ora, "bwcfg": "%s/%s" % (bwa, bwb)}
            if prev is None:
                if boot is not None:
                    rst.append((fp, boot, epoch_ts(boot), nick, addr, ch, None, published, None, 0, 1, 0, 0,
                                None, plat))
                    last_boot = boot
                pev.append((fp, published, pe, None, nick, addr, ch, None, ph, None, pol[ph][0], None,
                            pol[ph][1], "first"))
                prev = (r, r_d)
                continue
            pr, pd = prev
            prev_pub_e = pr[2]
            is_restart = False
            if boot is not None:
                if last_boot is None:
                    is_restart = boot >= prev_pub_e
                elif abs(boot - last_boot) <= 2:
                    is_restart = False
                elif boot >= prev_pub_e:
                    is_restart = True
                else:
                    n_drift += 1  # boot moved but is earlier than previous publication: uptime drift
                last_boot = boot
            changed = []
            for k, name in FIELDS:
                if r_d[k] != pd[k]:
                    changed.append(name)
                    chg.append((fp, published, pe, pr[1], nick, addr, name, str(pd[k]), str(r_d[k]),
                                0 if is_restart else 1))
            if is_restart:
                rst.append((fp, boot, epoch_ts(boot), nick, addr, ch, pr[1], published, boot - prev_pub_e,
                            int("address" in changed), 0, int("policy" in changed),
                            int("platform" in changed), pd["platform"], plat))
            else:
                rf = [c for c in changed if c in RELOAD_FIELDS]
                if rf:
                    rld.append((fp, published, pe, boot, nick, addr, ch, " ".join(rf)))
            if ph != pd["policy_h"]:
                pev.append((fp, published, pe, pr[1], nick, addr, ch, pd["policy_h"], ph, pol[pd["policy_h"]][0],
                            pol[ph][0], pol[pd["policy_h"]][1], pol[ph][1], "restart" if is_restart else "reload"))
            prev = (r, r_d)
        db.executemany("INSERT INTO desc_change VALUES (?,?,?,?,?,?,?,?,?,?)", chg)
        db.executemany("INSERT INTO restart VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rst)
        db.executemany("INSERT INTO reload VALUES (?,?,?,?,?,?,?,?)", rld)
        db.executemany("INSERT INTO policy_event VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", pev)

    q = db.execute("""SELECT fp, digest, published, pub_epoch, nickname, address, or_port, dir_port,
                      or_addresses, platform, uptime, boot_epoch, bw_avg, bw_burst, contact_h, family_h,
                      family_cert, ipv6_policy, ed25519, policy_h
                      FROM descriptor ORDER BY fp, pub_epoch, digest""")
    n = 0
    for r in q:
        fp = r[0]
        if fp != cur_fp:
            if cur_fp is not None:
                process(cur_fp, rows)
            cur_fp, rows = fp, []
        rows.append(r[1:])
        n += 1
        if n % 500000 == 0:
            log("  descriptors processed:", n)
    if cur_fp is not None:
        process(cur_fp, rows)
    db.commit()
    log("descriptors: %d; uptime-drift boot shifts discarded: %d" % (n, n_drift))

    # victims
    db.execute("""INSERT INTO victim SELECT DISTINCT d.fp FROM descriptor d JOIN policy p ON p.policy_h=d.policy_h
                  WHERE p.class IN ('near-open','OUR_POLICY')""")
    # absences
    vas = [r[0] for r in db.execute("SELECT va FROM consensus ORDER BY va")]
    idx = {v: i for i, v in enumerate(vas)}
    last_va = vas[-1]
    desc_pub = {}
    for fp, pe in db.execute("SELECT fp, pub_epoch FROM descriptor ORDER BY fp, pub_epoch"):
        desc_pub.setdefault(fp, []).append(pe)
    ab = []
    cur, prev_end = None, None
    for fp, s, e, ag in db.execute("SELECT fp, start_va, end_va, after_gap FROM cons_interval ORDER BY fp, start_va"):
        if fp != cur:
            if cur is not None and prev_end != last_va:
                ab.append(_absence(cur, prev_end, None, vas, idx, desc_pub))
            cur, prev_end = fp, None
        if prev_end is not None and ag:
            ab.append(_absence(fp, prev_end, s, vas, idx, desc_pub))
        prev_end = e
    if cur is not None and prev_end != last_va:
        ab.append(_absence(cur, prev_end, None, vas, idx, desc_pub))
    db.executemany("INSERT INTO absence VALUES (?,?,?,?,?,?,?,?,?)", ab)
    db.executescript("""
      CREATE INDEX IF NOT EXISTS dc_fp ON desc_change(fp, pub_epoch);
      CREATE INDEX IF NOT EXISTS dc_t ON desc_change(pub_epoch);
      CREATE INDEX IF NOT EXISTS rs_t ON restart(boot_epoch);
      CREATE INDEX IF NOT EXISTS rs_fp ON restart(fp);
      CREATE INDEX IF NOT EXISTS rl_t ON reload(pub_epoch);
      CREATE INDEX IF NOT EXISTS pe_t ON policy_event(pub_epoch);
      CREATE INDEX IF NOT EXISTS pe_fp ON policy_event(fp);
      CREATE INDEX IF NOT EXISTS ab_fp ON absence(fp);
    """)
    db.commit()
    for t in ("restart", "reload", "absence", "policy_event", "desc_change", "victim"):
        log(t, db.execute("SELECT count(*) FROM %s" % t).fetchone()[0])


def _absence(fp, prev_end, next_start, vas, idx, desc_pub):
    i = idx[prev_end]
    frm = vas[i + 1] if i + 1 < len(vas) else None
    if next_start is None:
        to = vas[-1]
        n_missing = len(vas) - 1 - i
        final = 1
        hi = ts_epoch(to) + 3600
    else:
        j = idx[next_start]
        to = vas[j - 1]
        n_missing = j - i - 1
        final = 0
        hi = ts_epoch(next_start)
    lo = ts_epoch(frm) - 3600 if frm else ts_epoch(prev_end)
    pubs = desc_pub.get(fp, [])
    a, b = bisect.bisect_left(pubs, lo), bisect.bisect_left(pubs, hi)
    last = epoch_ts(pubs[b - 1]) if b > a else None
    return (fp, prev_end, frm, to, next_start, n_missing, final, b - a, last)


if __name__ == "__main__":
    main()
