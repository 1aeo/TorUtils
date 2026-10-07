#!/usr/bin/env python3
"""family_analysis.py - second-resolution analysis of the Quetzalcoatl family (supports out/FINDINGS.md).

Family = the 362 seeds plus every relay whose nickname or contact contains "quetzal"; membership is
then checked against the exact contact string. Uses the network DB (net/netdb.sqlite) built by
build_netdb.py / derive_tables.py and the Onionoo snapshot in onionoo/.

Writes (out/):
  repro_family_members.csv        every family fingerprint: seed?, contact, first/last descriptor, first/last
                                  consensus, hosts, AS, active in October
  repro_policy_changes.csv        every family policy change since 2026-08-01 (descriptor level, seconds),
                                  old/new class, reload vs restart (boot time from published - uptime)
  repro_restarts.csv              family restarts (seconds, drift-filtered) and reloads, with burst ids
  repro_bursts.csv                bursts of host events (20 and 60 min chaining) with host order statistics
                                  and Kendall tau vs the operator's own earlier routine runs
  repro_sweep_20261005.csv        the 2026-10-05 restart sweep host by host, with Onionoo cross-check
  repro_exit_share.csv            per consensus from 2026-09-24: family Exit relays / weight vs network
  repro_port_impact.csv           ports allowed before (accept-list) and after (near-open)
  repro_other_changes.csv         contact / family / platform / nickname / address / ORPort / ipv6 / ed25519
                                  changes of family relays, whole window
  repro_flag_timeline.csv         family Exit/BadExit/MiddleOnly counts and last appearances per consensus
"""
import argparse
import collections
import csv
import glob
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (KNOWN_INFECTION, NEAR_OPEN, chain_bursts, epoch_ts, kendall_tau, order_stats,  # noqa: E402
                    summary_ports, ts_epoch)

FAMILY_CONTACT_PREFIX = "email:Quetzalcoatl_relays[]proton.me"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="net/netdb.sqlite")
    ap.add_argument("--out", default="out")
    ap.add_argument("--seed", default="family_seed_fingerprints.txt")
    args = ap.parse_args()
    db = sqlite3.connect(args.db)
    O = lambda n: os.path.join(args.out, n)  # noqa: E731
    seeds = set()
    for line in open(args.seed):
        t = line.split("#")[0].strip().upper()
        if re.fullmatch(r"[0-9A-F]{40}", t):
            seeds.add(t)
    contact = dict(db.execute("SELECT contact_h, text FROM contact"))
    ipas = {r[0]: r[1:] for r in db.execute("SELECT ip, asn, as_name, org_name FROM ip_as")}
    vas = [r[0] for r in db.execute("SELECT va FROM consensus ORDER BY va")]
    last_va = vas[-1]
    hint = {r[0] for r in db.execute(
        "SELECT DISTINCT d.fp FROM descriptor d LEFT JOIN contact c ON c.contact_h=d.contact_h "
        "WHERE lower(d.nickname) LIKE '%quetzal%' OR lower(c.text) LIKE '%quetzal%'")}
    hint |= {r[0] for r in db.execute("SELECT DISTINCT fp FROM cons_interval WHERE lower(nickname) LIKE '%quetzal%'")}
    cand = seeds | hint
    # ---------------------------------------------------------------- membership by exact contact
    mem = {}
    contacts_seen = collections.Counter()
    for fp in sorted(cand):
        ds = db.execute("SELECT published, nickname, address, contact_h, family_n, platform FROM descriptor "
                        "WHERE fp=? ORDER BY pub_epoch", (fp,)).fetchall()
        ivs = db.execute("SELECT min(start_va), max(end_va), group_concat(DISTINCT ip) FROM cons_interval WHERE fp=?",
                         (fp,)).fetchone()
        cts = collections.Counter(contact.get(d[3], "(none)") for d in ds)
        for c, n in cts.items():
            contacts_seen[c] += 1
        main_c = cts.most_common(1)[0][0] if cts else "(no descriptor in window)"
        fam_contact = main_c.startswith(FAMILY_CONTACT_PREFIX)
        hosts = sorted({d[2] for d in ds} | set((ivs[2] or "").split(",")) - {""})
        mem[fp] = {"seed": fp in seeds, "contact": main_c, "family_contact": fam_contact,
                   "nicknames": " ".join(sorted({d[1] for d in ds})), "first_desc": ds[0][0] if ds else "",
                   "last_desc": ds[-1][0] if ds else "", "first_cons": ivs[0] or "", "last_cons": ivs[1] or "",
                   "hosts": hosts, "active_oct": bool(ivs[1] and ivs[1] >= "2026-10-01"),
                   "last_ip": ds[-1][2] if ds else (hosts[-1] if hosts else "")}
    family = {fp for fp, m in mem.items() if m["seed"] or m["family_contact"]}
    lookalike = cand - family
    with open(O("repro_family_members.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fp", "in_family", "seed", "family_contact_exact", "nicknames", "contact", "first_desc",
                    "last_desc", "first_consensus", "last_consensus", "active_in_october", "last_ip", "asn",
                    "as_name", "all_hosts"])
        for fp in sorted(mem):
            m = mem[fp]
            a = ipas.get(m["last_ip"], ("", "", ""))
            w.writerow([fp, int(fp in family), int(m["seed"]), int(m["family_contact"]), m["nicknames"],
                        m["contact"][:200], m["first_desc"], m["last_desc"], m["first_cons"], m["last_cons"],
                        int(m["active_oct"]), m["last_ip"], a[0], a[2] or a[1], " ".join(m["hosts"])])
    act = {fp for fp in family if mem[fp]["active_oct"]}
    act_hosts = {mem[fp]["last_ip"] for fp in act}
    print("family candidates:", len(cand), "family (seed or exact contact):", len(family),
          "look-alikes:", len(lookalike))
    for fp in sorted(lookalike):
        print("   look-alike", fp, mem[fp]["nicknames"], mem[fp]["contact"][:60], mem[fp]["first_desc"], mem[fp]["last_desc"])
    print("seeds with exact family contact:", sum(1 for fp in seeds if mem[fp]["family_contact"]),
          "; non-seed family:", len(family - seeds))
    print("active in October (any consensus >= 10-01):", len(act), "seeds:", len(act & seeds),
          "non-seeds:", len(act - seeds), "hosts:", len(act_hosts))
    print("   by AS:", collections.Counter((ipas.get(mem[fp]["last_ip"], ("?", "?", "?"))[0],
                                            ipas.get(mem[fp]["last_ip"], ("?", "?", "?"))[2]) for fp in act).most_common())
    print("   hosts by AS:", collections.Counter((ipas.get(h, ("?", "?", "?"))[0]) for h in act_hosts).most_common())
    print("seeds last seen before 10-01:", len(seeds - act), collections.Counter(mem[fp]["last_cons"][:10] for fp in seeds - act).most_common(8))
    print("family present in consensus at 2026-10-01 12:00:",
          db.execute("SELECT count(DISTINCT fp) FROM cons_interval WHERE start_va<='2026-10-01 12:00:00' AND end_va>='2026-10-01 12:00:00' "
                     "AND fp IN (%s)" % ",".join("'%s'" % x for x in family)).fetchone()[0])
    famlist = ",".join("'%s'" % x for x in family)

    # ---------------------------------------------------------------- policy changes since 08-01
    pc = db.execute("""SELECT e.published, e.fp, e.nickname, e.address, e.old_class, e.new_class, e.old_summary,
                         e.new_summary, e.kind, e.prev_published, d.boot_epoch, d.uptime
                       FROM policy_event e JOIN descriptor d ON d.fp=e.fp AND d.published=e.published AND d.policy_h=e.new_h
                       WHERE e.kind!='first' AND e.published>='2026-08-01' AND e.fp IN (%s) ORDER BY e.pub_epoch""" % famlist).fetchall()
    with open(O("repro_policy_changes.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fingerprint", "nickname", "ip", "old_policy_class", "new_policy_class", "published",
                    "reload_or_restart", "boot_time", "uptime_s", "prev_published", "asn", "old_summary", "new_summary"])
        for r in pc:
            w.writerow([r[1], r[2], r[3], r[4], r[5], r[0], r[8], epoch_ts(r[10]) if r[10] else "", r[11], r[9],
                        ipas.get(r[3], ("",))[0], r[6][:80], r[7][:80]])
    cls = collections.Counter((r[4], r[5], r[8]) for r in pc)
    print("family policy changes since 2026-08-01:", len(pc), dict(cls))
    attack = [r for r in pc if r[5] == "near-open"]
    if attack:
        hosts = []
        for r in attack:
            if r[3] not in hosts:
                hosts.append(r[3])
        st = order_stats(hosts)
        print("   near-open changes: %d relays, %d hosts, %s .. %s; boot unchanged (reload) for %d" % (
            len(attack), len(hosts), attack[0][0], attack[-1][0], sum(1 for r in attack if r[8] == "reload")))
        print("   host order: inv str/num/nodot %d/%d/%d of %d; runs %d/%d/%d" % (
            st["inv_str"], st["inv_num"], st["inv_nodot"], st["pairs"], st["run_str"], st["run_num"], st["run_nodot"]))
        boots = collections.Counter(epoch_ts(r[10])[:16] for r in attack if r[10])
        print("   boot times of the near-open descriptors (minute):", boots.most_common(6))
    # ---------------------------------------------------------------- restarts, reloads, bursts
    ev = []
    for fp, be, nick, addr, fiw, ipc, plc, pfc, op, np_ in db.execute(
            "SELECT fp, boot_epoch, nickname, address, first_in_window, ip_change, policy_changed, platform_changed, "
            "old_platform, new_platform FROM restart WHERE fp IN (%s)" % famlist):
        if fiw and be < ts_epoch("2026-05-02 00:00:00"):
            continue
        typ = "start(first-desc)" if fiw else ("restart(ip-change)" if ipc else "restart")
        ev.append([be, addr, fp, typ, nick, (op or "") + ("->" + np_ if pfc else "")])
    for fp, pe, nick, addr, fields in db.execute(
            "SELECT fp, pub_epoch, nickname, address, fields FROM reload WHERE fp IN (%s)" % famlist):
        ev.append([pe, addr, fp, "reload:" + fields, nick, ""])
    ev.sort()
    earlier_runs = []
    brows, rrows = [], []
    for gap in (1200, 3600):
        bursts = chain_bursts(ev, gap, key=lambda e: e[0])
        for bi, b in enumerate(bursts, 1):
            hosts, first = [], {}
            for e in b:
                if e[1] not in first:
                    first[e[1]] = e[0]
                    hosts.append(e[1])
            if gap == 1200:
                for e in b:
                    rrows.append([epoch_ts(e[0]), e[2], e[4], e[1], e[3], e[5], bi])
            if len(hosts) < 5:
                continue
            st = order_stats(hosts)
            types = collections.Counter(e[3].split(":")[0] for e in b)
            taus = []
            if gap == 1200 and len(hosts) >= 10:
                for (ts0, oh) in earlier_runs:
                    tau, n = kendall_tau(hosts, oh)
                    if tau is not None and n >= 10:
                        taus.append((round(tau, 3), n, ts0))
                earlier_runs.append((epoch_ts(b[0][0]), hosts))
            brows.append([gap // 60, bi, epoch_ts(b[0][0]), epoch_ts(b[-1][0]), len(hosts), len({e[2] for e in b}),
                          "; ".join("%s=%d" % kv for kv in types.most_common()), st["inv_str"], st["inv_num"],
                          st["inv_nodot"], st["pairs"], st["run_str"], st["run_num"], st["run_nodot"],
                          int(epoch_ts(b[0][0]) < KNOWN_INFECTION),
                          " ".join("%s:%.2f(n=%d)" % (t[2][:16], t[0], t[1]) for t in taus[-6:]),
                          " ".join(hosts)])
    with open(O("repro_restarts.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_utc", "fingerprint", "nickname", "address", "event", "platform_change", "burst20_id"])
        w.writerows(rrows)
    with open(O("repro_bursts.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["chain_gap_min", "burst", "start", "end", "hosts", "relays", "event_types", "inv_str", "inv_num",
                    "inv_nodot", "pairs", "longest_run_str", "longest_run_num", "longest_run_nodot",
                    "before_known_infection", "kendall_tau_vs_earlier_runs(last 6)", "host_order"])
        w.writerows(brows)
    print("family bursts (>=5 hosts, 20-min chaining) from 2026-08-20:")
    for r in brows:
        if r[0] == 20 and r[2] >= "2026-08-20":
            print("   %s .. %s hosts=%d relays=%d %s inv %d/%d/%d of %d runs %d/%d/%d tau[%s]" % (
                r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11], r[12], r[13], r[15][-120:]))
    n_pre = sum(1 for r in brows if r[0] == 20 and r[14])
    print("bursts (>=5 hosts, 20 min) before known infection:", n_pre)

    # ---------------------------------------------------------------- the 2026-10-05 sweep vs Onionoo
    a, z = ts_epoch("2026-10-05 08:30:00"), ts_epoch("2026-10-05 11:00:00")
    sw = [e for e in ev if a <= e[0] <= z and e[3].startswith(("restart", "start"))]
    on = {}
    for f_ in glob.glob("onionoo/details_family_*.json"):
        for r in json.load(open(f_))["relays"]:
            on[r["fingerprint"]] = r
    on_hosts = {r["or_addresses"][0].rsplit(":", 1)[0] for r in on.values()}
    hosts, first = [], {}
    for e in sw:
        if e[1] not in first:
            first[e[1]] = e
            hosts.append(e[1])
    st = order_stats(hosts)
    with open(O("repro_sweep_20261005.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["order", "host", "first_restart_utc", "relays_restarted_on_host", "asn", "as_name",
                    "in_onionoo_family_view", "onionoo_relays_on_host", "onionoo_last_restarted_min",
                    "seed_relays_on_host", "nonseed_relays_on_host"])
        for i, h in enumerate(hosts, 1):
            rel = [e for e in sw if e[1] == h]
            onr = [r for r in on.values() if r["or_addresses"][0].rsplit(":", 1)[0] == h]
            a_ = ipas.get(h, ("", "", ""))
            w.writerow([i, h, epoch_ts(first[h][0]), len({e[2] for e in rel}), a_[0], a_[2] or a_[1], int(h in on_hosts),
                        len(onr), min((r.get("last_restarted") or "") for r in onr) if onr else "",
                        len({e[2] for e in rel if e[2] in seeds}), len({e[2] for e in rel if e[2] not in seeds})])
    print("2026-10-05 08:30-11:00 sweep: %d hosts, %d relays, %s .. %s; inv str/num/nodot %d/%d/%d of %d; runs %d/%d/%d" % (
        len(hosts), len({e[2] for e in sw}), epoch_ts(sw[0][0]), epoch_ts(sw[-1][0]), st["inv_str"], st["inv_num"],
        st["inv_nodot"], st["pairs"], st["run_str"], st["run_num"], st["run_nodot"]))
    print("   hosts also in Onionoo family view: %d; not in it: %d; Onionoo-view hosts: %d" % (
        len(set(hosts) & on_hosts), len(set(hosts) - on_hosts), len(on_hosts)))
    print("   sweep hosts carrying seed relays: %d; carrying only non-seed relays: %d" % (
        len({e[1] for e in sw if e[2] in seeds}), len({e[1] for e in sw} - {e[1] for e in sw if e[2] in seeds})))
    sw_on = [e for e in sw if e[2] in on]
    print("   restarts of relays in the Onionoo view: %d relays on %d hosts, %s .. %s" % (
        len({e[2] for e in sw_on}), len({e[1] for e in sw_on}), epoch_ts(sw_on[0][0]) if sw_on else "",
        epoch_ts(sw_on[-1][0]) if sw_on else ""))

    # ---------------------------------------------------------------- exit share
    rows = []
    db.execute("CREATE TEMP TABLE fam(fp TEXT PRIMARY KEY)")
    db.executemany("INSERT INTO fam VALUES (?)", [(x,) for x in family])
    q = """SELECT va, sum((' '||flags||' ') LIKE '% Exit %'),
                  sum(CASE WHEN (' '||flags||' ') LIKE '% Exit %' THEN bw ELSE 0 END),
                  sum(CASE WHEN fp IN (SELECT fp FROM fam) AND (' '||flags||' ') LIKE '% Exit %' THEN 1 ELSE 0 END),
                  sum(CASE WHEN fp IN (SELECT fp FROM fam) AND (' '||flags||' ') LIKE '% Exit %' THEN bw ELSE 0 END),
                  sum(CASE WHEN fp IN (SELECT fp FROM fam) THEN 1 ELSE 0 END),
                  sum(CASE WHEN fp IN (SELECT fp FROM fam) AND (' '||flags||' ') LIKE '% Exit %'
                           AND (' '||flags||' ') NOT LIKE '% BadExit %' THEN 1 ELSE 0 END),
                  sum(CASE WHEN fp IN (SELECT fp FROM fam) AND (' '||flags||' ') LIKE '% Exit %'
                           AND (' '||flags||' ') NOT LIKE '% BadExit %' THEN bw ELSE 0 END),
                  sum(CASE WHEN (' '||flags||' ') LIKE '% Exit %' AND (' '||flags||' ') NOT LIKE '% BadExit %'
                           THEN bw ELSE 0 END)
           FROM cons_entry GROUP BY va ORDER BY va"""
    for va, n_exit, bw_exit, n_fam_exit, bw_fam_exit, n_fam, n_fam_usable, bw_fam_usable, bw_exit_usable in db.execute(q):
        rows.append([va, n_fam, n_fam_exit, n_exit, round(100.0 * n_fam_exit / n_exit, 2) if n_exit else 0,
                     bw_fam_exit, bw_exit, round(100.0 * bw_fam_exit / bw_exit, 2) if bw_exit else 0,
                     n_fam_usable, bw_fam_usable, bw_exit_usable,
                     round(100.0 * bw_fam_usable / bw_exit_usable, 2) if bw_exit_usable else 0])
    with open(O("repro_exit_share.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["valid_after", "family_relays", "family_exit_flag", "network_exit_flag", "pct_exit_relays",
                    "family_exit_weight", "network_exit_weight", "pct_exit_weight", "family_usable_exits(no BadExit)",
                    "family_usable_exit_weight", "network_usable_exit_weight", "pct_usable_exit_weight"])
        w.writerows(rows)
    for r in rows:
        if r[0] in ("2026-09-24 12:00:00", "2026-10-01 12:00:00", "2026-10-02 12:00:00", "2026-10-03 12:00:00",
                    "2026-10-04 12:00:00", "2026-10-04 20:00:00", "2026-10-04 21:00:00", "2026-10-05 00:00:00",
                    "2026-10-05 09:00:00", "2026-10-05 12:00:00", "2026-10-06 00:00:00"):
            print("   exit share", r)
    pre = [r for r in rows if "2026-09-24" <= r[0] < "2026-10-01"]
    if pre:
        print("   mean pct exit relays 09-24..09-30: %.2f%%, mean pct exit weight: %.2f%%" % (
            sum(r[4] for r in pre) / len(pre), sum(r[7] for r in pre) / len(pre)))

    # ---------------------------------------------------------------- port impact
    old_sum = db.execute("""SELECT p.summary, count(*) FROM descriptor d JOIN policy p ON p.policy_h=d.policy_h
                            WHERE d.fp IN (%s) AND d.published >= '2026-09-25' AND d.published < '2026-10-02'
                            GROUP BY p.summary ORDER BY 2 DESC""" % famlist).fetchall()
    before = summary_ports(old_sum[0][0])
    after = summary_ports(NEAR_OPEN)
    opened = sorted(after - before)
    closed = sorted(before - after)
    with open(O("repro_port_impact.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item", "value"])
        w.writerow(["operator_summary", old_sum[0][0]])
        w.writerow(["attacker_summary", NEAR_OPEN])
        w.writerow(["ports_allowed_before", len(before)])
        w.writerow(["ports_allowed_after", len(after)])
        w.writerow(["ports_newly_opened", len(opened)])
        w.writerow(["ports_closed", " ".join(map(str, closed))])
        w.writerow(["well_known_<1024_newly_opened", " ".join(map(str, [p for p in opened if p < 1024]))])
        for p in (22, 23, 25, 110, 143, 445, 993, 995, 3389, 5900, 6667, 8080, 3306, 5432, 1433, 27017, 6379, 21, 80, 443):
            w.writerow(["port_%d" % p, "before=%s after=%s" % (p in before, p in after)])
    print("port impact: operator summaries before (count of descriptors):", [(s[:60], n) for s, n in old_sum])
    print("   allowed before %d, after %d, newly opened %d, closed %s" % (len(before), len(after), len(opened), closed))
    print("   newly opened <1024:", len([p for p in opened if p < 1024]))

    # ---------------------------------------------------------------- other descriptor changes
    oc = db.execute("""SELECT published, fp, nickname, address, field, old, new, same_run FROM desc_change
                       WHERE fp IN (%s) AND field IN ('contact','family','platform','nickname','address','or_port',
                       'ipv6_policy','ed25519','dir_port','or_addresses','bw_config')
                       ORDER BY pub_epoch""" % famlist).fetchall()
    with open(O("repro_other_changes.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["published", "fingerprint", "nickname", "address", "field", "old", "new", "without_restart",
                    "before_known_infection", "seed"])
        for r in oc:
            w.writerow(list(r[:5]) + [r[5][:120], r[6][:120], r[7], int(r[0] < KNOWN_INFECTION), int(r[1] in seeds)])
    c = collections.Counter((r[4], r[0][:10]) for r in oc if r[0] >= "2026-08-01")
    print("other family descriptor changes since 08-01 (field, date):", sorted(c.items()))

    # ---------------------------------------------------------------- flag timeline
    ft = []
    for va, n, ex, be, mo, gu, att in db.execute(
            """SELECT ce.va, count(*), sum((' '||flags||' ') LIKE '% Exit %'), sum((' '||flags||' ') LIKE '% BadExit %'),
                      sum((' '||flags||' ') LIKE '% MiddleOnly %'), sum((' '||flags||' ') LIKE '% Guard %'),
                      sum(policy = ?)
               FROM cons_entry ce WHERE fp IN (SELECT fp FROM fam) GROUP BY va ORDER BY va""", (NEAR_OPEN,)):
        ft.append([va, n, ex, be, mo, gu, att])
    have = {r[0] for r in ft}
    for va in vas:
        if va >= "2026-09-24" and va not in have:
            ft.append([va, 0, 0, 0, 0, 0, 0])
    ft.sort()
    with open(O("repro_flag_timeline.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["valid_after", "family_present", "Exit", "BadExit", "MiddleOnly", "Guard", "near_open_pline"])
        w.writerows(ft)
    for r in ft:
        if r[0] >= "2026-10-04 12:00:00" and r[0] <= "2026-10-06 03:00:00":
            print("   flags", r)


if __name__ == "__main__":
    main()
