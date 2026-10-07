#!/usr/bin/env python3
"""net_sweeps.py - restart / reload sweeps, per operator and across operators, with sorted-order tests.

Host event = restart (boot = published - uptime, seconds; drift-filtered; see derive_tables.py) or reload
(content change without new boot). Host = IPv4 address; a host's event time inside a burst is its
earliest relay event. Operator = exact contact string (relays without a contact line are treated as
separate unknown operators, never pooled).

1. Per operator, host events are chained into bursts with gaps <= GAP (20 min, and 60 min).
   Bursts with >= 3 hosts are kept: net/operator_bursts_{20,60}min.csv, with inversion counts against
   a text sort, numeric sort and dotless-text sort of the IPs, longest ascending runs, and Kendall tau
   against the same operator's earlier bursts (>= 4 common hosts).
2. Multi-operator sweeps: operator bursts (>= 3 hosts) whose time spans overlap are merged: net/multi_operator_sweeps_{20,60}min.csv.
3. Key windows: every operator burst touching them, plus all victim-host events:
   net/sweeps_key_windows.csv.
4. Baseline: per month, number of operator bursts (>=3, >=5, >=10 hosts) and of multi-operator
   coincidences: net/sweep_baseline.csv.
"""
import argparse
import collections
import csv
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import epoch_ts, kendall_tau, order_stats, ts_epoch  # noqa: E402

KEY_WINDOWS = [("2026-10-01 14:30:00", "2026-10-01 16:00:00"), ("2026-10-02 09:00:00", "2026-10-02 10:30:00"),
               ("2026-10-02 20:30:00", "2026-10-02 21:30:00"), ("2026-10-03 10:00:00", "2026-10-03 17:00:00"),
               ("2026-10-04 00:00:00", "2026-10-05 00:00:00"), ("2026-10-05 08:30:00", "2026-10-05 11:00:00"),
               ("2026-10-05 20:30:00", "2026-10-05 21:30:00")]


def op_of(contact, ch, fp):
    """operator = exact contact string; relays without a contact line are each their own unknown operator"""
    if ch == "-" or ch not in contact or not contact[ch].strip():
        return "(no contact) " + fp[:8]
    return contact[ch]


def load_events(db, window_start_e):
    contact = dict(db.execute("SELECT contact_h, text FROM contact"))
    ev = []
    for fp, be, nick, addr, ch, fiw, ipc in db.execute(
            "SELECT fp, boot_epoch, nickname, address, contact_h, first_in_window, ip_change FROM restart"):
        if fiw and be < window_start_e + 86400:
            continue  # boot before / at the very start of the window: not an observed event
        typ = "start(first-desc)" if fiw else ("restart(ip-change)" if ipc else "restart")
        ev.append((be, addr, fp, op_of(contact, ch, fp), typ, nick))
    for fp, pe, nick, addr, ch, fields in db.execute(
            "SELECT fp, pub_epoch, nickname, address, contact_h, fields FROM reload"):
        ev.append((pe, addr, fp, op_of(contact, ch, fp), "reload:" + fields, nick))
    ev.sort()
    return ev


def operator_bursts(ev, gap):
    by_op = collections.defaultdict(list)
    for e in ev:
        by_op[e[3]].append(e)
    bursts = []
    for op, es in by_op.items():
        cur, prev = [], None
        for e in es:
            if prev is not None and e[0] - prev > gap:
                bursts.append((op, cur))
                cur = []
            cur.append(e)
            prev = e[0]
        if cur:
            bursts.append((op, cur))
    out = []
    for op, es in bursts:
        hosts, first = [], {}
        for e in es:
            if e[1] not in first:
                first[e[1]] = e[0]
                hosts.append(e[1])
        if len(hosts) >= 3:
            out.append({"op": op, "events": es, "hosts": hosts, "start": es[0][0], "end": es[-1][0],
                        "types": collections.Counter(e[4].split(":")[0] for e in es)})
    out.sort(key=lambda b: b["start"])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="net/netdb.sqlite")
    ap.add_argument("--out", default="net")
    args = ap.parse_args()
    db = sqlite3.connect(args.db)
    first_desc = db.execute("SELECT min(pub_epoch) FROM descriptor").fetchone()[0]
    ev = load_events(db, first_desc)
    victims = {r[0] for r in db.execute("SELECT fp FROM victim")}
    vic_hosts = {r[0] for r in db.execute("SELECT DISTINCT address FROM descriptor WHERE fp IN (SELECT fp FROM victim)")}
    ipas = {r[0]: r[1] for r in db.execute("SELECT ip, asn FROM ip_as")}
    base_rows = collections.defaultdict(collections.Counter)
    for gap in (1200, 3600):
        gm = gap // 60
        bursts = operator_bursts(ev, gap)
        hist = collections.defaultdict(list)
        rows = []
        for i, b in enumerate(bursts, 1):
            st = order_stats(b["hosts"])
            taus = []
            if len(b["hosts"]) >= 4:
                for ob in hist[b["op"]]:
                    tau, n = kendall_tau(b["hosts"], ob["hosts"])
                    if tau is not None and n >= 4:
                        taus.append((tau, n, epoch_ts(ob["start"])))
            hist[b["op"]].append(b)
            b["id"] = i
            b["stats"] = st
            b["taus"] = taus
            nv = len(set(b["hosts"]) & vic_hosts)
            rows.append([i, epoch_ts(b["start"]), epoch_ts(b["end"]), round((b["end"] - b["start"]) / 60, 1),
                         b["op"][:160], len(b["hosts"]), len({e[2] for e in b["events"]}), nv,
                         "; ".join("%s=%d" % kv for kv in b["types"].most_common()),
                         "; ".join("AS%s=%d" % kv for kv in collections.Counter(ipas.get(h, "?") for h in b["hosts"]).most_common(4)),
                         st["inv_str"], st["inv_num"], st["inv_nodot"], st["pairs"], st["run_str"], st["run_num"],
                         st["run_nodot"], len(taus),
                         ("%.3f" % max(t[0] for t in taus)) if taus else "",
                         ("%.3f" % (sum(t[0] for t in taus) / len(taus))) if taus else "",
                         " ".join(b["hosts"])])
            m = epoch_ts(b["start"])[:7]
            if gap == 1200:
                base_rows[m]["op_bursts_ge3"] += 1
                if len(b["hosts"]) >= 5:
                    base_rows[m]["op_bursts_ge5"] += 1
                if len(b["hosts"]) >= 10:
                    base_rows[m]["op_bursts_ge10"] += 1
                if st["pairs"] and st["inv_str"] == 0 and len(b["hosts"]) >= 5:
                    base_rows[m]["op_bursts_ge5_perfect_textsort"] += 1
        with open(os.path.join(args.out, "operator_bursts_%dmin.csv" % gm), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["burst", "start", "end", "span_min", "operator", "hosts", "relays", "victim_hosts", "types",
                        "ases", "inv_str", "inv_num", "inv_nodot", "pairs", "run_str", "run_num", "run_nodot",
                        "n_earlier_runs_compared", "max_tau_vs_earlier", "mean_tau_vs_earlier", "host_order"])
            w.writerows(rows)
        # multi-operator merge (operator bursts with >= 3 hosts whose spans overlap)
        multi, cur = [], []
        cur_end = None
        for b in bursts:
            if cur and b["start"] <= cur_end:  # overlapping operator bursts only
                cur.append(b)
                cur_end = max(cur_end, b["end"])
            else:
                if cur:
                    multi.append(cur)
                cur, cur_end = [b], b["end"]
        if cur:
            multi.append(cur)
        mrows = []
        for grp in multi:
            ops = {b["op"] for b in grp}
            if len(ops) < 2:
                continue
            hosts = sum(len(b["hosts"]) for b in grp)
            nv = len(set(h for b in grp for h in b["hosts"]) & vic_hosts)
            mrows.append([epoch_ts(min(b["start"] for b in grp)), epoch_ts(max(b["end"] for b in grp)), len(ops), hosts,
                          nv, " || ".join("%s [%d hosts, inv_str %d/%d]" % (b["op"][:70], len(b["hosts"]),
                                                                         b["stats"]["inv_str"], b["stats"]["pairs"])
                                          for b in grp)])
            if gap == 1200:
                m = mrows[-1][0][:7]
                base_rows[m]["multi_op_coincidences"] += 1
                if nv:
                    base_rows[m]["multi_op_coincidences_touching_victim_hosts"] += 1
        with open(os.path.join(args.out, "multi_operator_sweeps_%dmin.csv" % gm), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["start", "end", "operators", "hosts", "victim_hosts", "operator_bursts"])
            w.writerows(mrows)
        if gap == 1200:
            kw_rows = []
            for ws, we in KEY_WINDOWS:
                a, z = ts_epoch(ws), ts_epoch(we)
                for b in bursts:
                    if b["end"] >= a and b["start"] <= z:
                        st = b["stats"]
                        kw_rows.append(["%s..%s" % (ws, we), "operator-burst", epoch_ts(b["start"]), epoch_ts(b["end"]),
                                        b["op"][:160], len(b["hosts"]), len(set(b["hosts"]) & vic_hosts),
                                        "; ".join("%s=%d" % kv for kv in b["types"].most_common()),
                                        "%d/%d/%d of %d" % (st["inv_str"], st["inv_num"], st["inv_nodot"], st["pairs"]),
                                        "%d/%d/%d" % (st["run_str"], st["run_num"], st["run_nodot"]),
                                        ("%.3f" % max(t[0] for t in b["taus"])) if b["taus"] else "",
                                        " ".join(b["hosts"])])
                for e in ev:
                    if a <= e[0] <= z and (e[2] in victims or e[1] in vic_hosts):
                        kw_rows.append(["%s..%s" % (ws, we), "victim-host-event", epoch_ts(e[0]), "", e[3][:160], 1,
                                        1, e[4], "", "", "", "%s %s %s" % (e[1], e[2], e[5])])
            with open(os.path.join(args.out, "sweeps_key_windows.csv"), "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["window", "row_type", "start", "end", "operator", "hosts", "victim_hosts", "types",
                            "inversions str/num/nodot of pairs", "longest_run str/num/nodot", "max_tau_vs_earlier",
                            "host_order_or_event"])
                w.writerows(kw_rows)
            print("key-window operator bursts (20 min, >=3 hosts):")
            for r in kw_rows:
                if r[1] == "operator-burst":
                    print("  ", r[0][:16], r[2], r[3], "hosts=%d vic=%d" % (r[5], r[6]), r[7], r[8], "tau", r[10], "|", r[4][:70])
        print("multi-operator coincidences (gap %d min): %d" % (gm, len(mrows)))
    with open(os.path.join(args.out, "sweep_baseline.csv"), "w", newline="") as f:
        w = csv.writer(f)
        ks = ["op_bursts_ge3", "op_bursts_ge5", "op_bursts_ge10", "op_bursts_ge5_perfect_textsort",
              "multi_op_coincidences", "multi_op_coincidences_touching_victim_hosts"]
        w.writerow(["month"] + ks)
        for m in sorted(base_rows):
            w.writerow([m] + [base_rows[m][k] for k in ks])
            print("  baseline", m, [base_rows[m][k] for k in ks])


if __name__ == "__main__":
    main()
