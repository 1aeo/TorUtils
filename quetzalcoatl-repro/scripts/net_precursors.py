#!/usr/bin/env python3
"""net_precursors.py - May-September precursors: identity-key changes and policy lineage.

Outputs (net/):
  ed25519_key_changes.csv     same RSA fingerprint, new master-key-ed25519 (whole network, whole window)
  identity_replacements.csv   a new RSA fingerprint taking over the same IP:ORPort within 48 h of the old one's
                              last descriptor (key regeneration / redeploy); flagged for victim hosts & family
  policy_lineage.csv          for every distinct attacker-class policy text (normalized: own-IP and private
                              lines removed): first descriptor anywhere with that exact normalized text, line
                              count, how many relays/operators ever used it and when
  ourpolicy_line_order.csv    the OUR_POLICY reject-port line order and where the same ordered port sequence
                              (ignoring the relay-specific lines and the final accept/reject) first appears
  victim_host_events_aug.csv  every restart/reload/descriptor change on later-victim hosts 2026-08-20..09-05
"""
import argparse
import collections
import csv
import hashlib
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import epoch_ts, normalize_policy, parse_policy_line, ts_epoch, KNOWN_INFECTION  # noqa: E402


def core_rules(lines, own):
    """reject/accept rules with own-IP/private lines removed, as (kind, addr, ports) strings."""
    return normalize_policy(lines, own).split("\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="net/netdb.sqlite")
    ap.add_argument("--out", default="net")
    ap.add_argument("--seed", default="family_seed_fingerprints.txt")
    args = ap.parse_args()
    db = sqlite3.connect(args.db)
    contact = dict(db.execute("SELECT contact_h, text FROM contact"))
    contact["-"] = "(no contact line)"
    victims = {r[0] for r in db.execute("SELECT fp FROM victim")}
    vic_hosts = {r[0] for r in db.execute("SELECT DISTINCT address FROM descriptor WHERE fp IN (SELECT fp FROM victim)")}
    seeds = {l.split("#")[0].strip().upper() for l in open(args.seed) if len(l.split("#")[0].strip()) == 40}

    # ---------------- ed25519 key changes
    rows = db.execute("""SELECT published, fp, nickname, address, old, new, same_run FROM desc_change
                         WHERE field='ed25519' ORDER BY pub_epoch""").fetchall()
    with open(os.path.join(args.out, "ed25519_key_changes.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["published", "fp", "nickname", "address", "old_ed25519", "new_ed25519", "same_run",
                    "victim", "family_seed", "victim_host"])
        for r in rows:
            w.writerow(list(r) + [int(r[1] in victims), int(r[1] in seeds), int(r[3] in vic_hosts)])
    print("ed25519 master-key changes (same RSA fp):", len(rows), "; on victims:",
          sum(1 for r in rows if r[1] in victims), "; family:", sum(1 for r in rows if r[1] in seeds))
    by_m = collections.Counter(r[0][:7] for r in rows)
    print("   per month:", sorted(by_m.items()))

    # ---------------- identity replacements at the same IP:ORPort
    span = {}
    for fp, addr, orp, mn, mx, nick, ch in db.execute(
            "SELECT fp, address, or_port, min(pub_epoch), max(pub_epoch), max(nickname), max(contact_h) FROM descriptor GROUP BY fp, address, or_port"):
        span.setdefault((addr, orp), []).append((mn, mx, fp, nick, ch))
    rep = []
    for (addr, orp), lst in span.items():
        lst.sort()
        for i in range(1, len(lst)):
            new = lst[i]
            for old in lst[:i]:
                if old[2] != new[2] and 0 <= new[0] - old[1] <= 48 * 3600 and old[1] < new[0]:
                    rep.append((epoch_ts(new[0]), addr, orp, old[2], old[3], epoch_ts(old[1]), new[2], new[3],
                                contact.get(new[4], new[4])[:100], int(old[2] in victims or new[2] in victims),
                                int(addr in vic_hosts), int(old[2] in seeds or new[2] in seeds)))
    rep.sort()
    with open(os.path.join(args.out, "identity_replacements.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["new_first_published", "address", "or_port", "old_fp", "old_nick", "old_last_published",
                    "new_fp", "new_nick", "new_contact", "victim_involved", "victim_host", "family_seed_involved"])
        w.writerows(rep)
    print("identity replacements at same IP:ORPort (<=48h):", len(rep), "; on victim hosts:",
          sum(r[10] for r in rep), "; family:", sum(r[11] for r in rep))
    for r in rep:
        if r[10] or r[11]:
            print("   ", r[:9])

    # ---------------- policy lineage
    att = db.execute("""SELECT p.policy_h, p.text, p.class FROM policy p WHERE p.class IN ('near-open','OUR_POLICY')""").fetchall()
    # normalized attacker texts (normalize each descriptor with its own IPs)
    norm_first = {}
    users = collections.defaultdict(lambda: {"fps": set(), "ops": set(), "first": None, "last": None, "class": None,
                                             "n_lines": 0, "text": ""})
    ath = {h: (t, c) for h, t, c in att}
    q = db.execute("""SELECT d.policy_h, d.published, d.fp, d.address, d.or_addresses, d.contact_h FROM descriptor d
                      WHERE d.policy_h IN (SELECT policy_h FROM policy WHERE class IN ('near-open','OUR_POLICY'))
                      ORDER BY d.pub_epoch""")
    for h, pub, fp, addr, ora, ch in q:
        own = {addr} | {x.rsplit(":", 1)[0] for x in (ora or "").split() if not x.startswith("[")}
        nt = normalize_policy(ath[h][0].split("\n"), own)
        nh = hashlib.sha1(nt.encode()).hexdigest()[:12]
        u = users[nh]
        u["fps"].add(fp)
        u["ops"].add(contact.get(ch, ch))
        u["first"] = u["first"] or (pub, fp)
        u["last"] = (pub, fp)
        u["class"] = ath[h][1]
        u["text"] = nt
        u["n_lines"] = nt.count("\n") + 1
    with open(os.path.join(args.out, "policy_lineage.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["norm_policy", "class", "n_lines", "first_published", "first_fp", "last_published", "relays",
                    "operators", "before_known_infection", "operator_list", "normalized_text"])
        for nh, u in sorted(users.items(), key=lambda kv: kv[1]["first"][0]):
            w.writerow([nh, u["class"], u["n_lines"], u["first"][0], u["first"][1], u["last"][0], len(u["fps"]),
                        len(u["ops"]), int(u["first"][0] < KNOWN_INFECTION),
                        " || ".join(sorted(o[:70] for o in u["ops"])), u["text"].replace("\n", " ; ")])
    print("distinct normalized attacker-class policy texts:", len(users))
    for nh, u in sorted(users.items(), key=lambda kv: kv[1]["first"][0]):
        print("   %s %-10s lines=%3d first=%s %s relays=%d ops=%d" % (nh, u["class"], u["n_lines"], u["first"][0],
                                                                    u["first"][1][:8], len(u["fps"]), len(u["ops"])))

    # ---------------- OUR_POLICY port order: search all policies for the same ordered reject sequence
    ourp = [(h, t) for h, t, c in att if c == "OUR_POLICY"]
    seqs = collections.Counter()
    for h, t in ourp:
        seq = tuple(l for l in t.split("\n") if l.startswith("reject *:"))
        seqs[seq] += 1
    print("OUR_POLICY 'reject *:' sequences (distinct):", len(seqs))
    for s, n in seqs.most_common(5):
        print("   %d texts: %s" % (n, " ; ".join(s)))
    rows = []
    for seq, n in seqs.most_common():
        if not seq:
            continue
        hits = []
        for h, t in db.execute("SELECT policy_h, text FROM policy"):
            lines = t.split("\n")
            r = [l for l in lines if l.startswith("reject *:")]
            # contains the sequence as a contiguous run
            k = len(seq)
            if any(tuple(r[i:i + k]) == seq for i in range(0, len(r) - k + 1)):
                hits.append(h)
        if not hits:
            continue
        first = db.execute("SELECT min(d.published), count(DISTINCT d.fp) FROM descriptor d WHERE d.policy_h IN (%s)"
                           % ",".join("?" * len(hits)), hits).fetchone()
        fd = db.execute("SELECT d.published, d.fp, d.nickname, d.address, d.contact_h, p.class FROM descriptor d "
                        "JOIN policy p ON p.policy_h=d.policy_h WHERE d.policy_h IN (%s) ORDER BY d.pub_epoch LIMIT 1"
                        % ",".join("?" * len(hits)), hits).fetchone()
        classes = collections.Counter(c for (c,) in db.execute(
            "SELECT class FROM policy WHERE policy_h IN (%s)" % ",".join("?" * len(hits)), hits))
        rows.append([" ; ".join(seq), n, len(hits), first[1], fd[0], fd[1], fd[2], fd[3],
                     contact.get(fd[4], fd[4])[:100], fd[5], dict(classes)])
    with open(os.path.join(args.out, "ourpolicy_line_order.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["reject_sequence", "ourpolicy_texts_with_it", "policies_containing_sequence",
                    "relays_using_them", "first_published", "first_fp", "first_nick", "first_ip",
                    "first_contact", "first_class", "classes_of_containing_policies"])
        w.writerows(rows)
    for r in rows:
        print("   sequence used by %d policies / %d relays; first %s %s %s %s class=%s classes=%s" % (
            r[2], r[3], r[4], r[5][:8], r[6], r[7], r[9], r[10]))

    # ---------------- events on later-victim hosts around the known infection
    a, z = ts_epoch("2026-08-20 00:00:00"), ts_epoch("2026-09-05 00:00:00")
    hv = []
    for fp, be, nick, addr, ch, fiw, ipc in db.execute(
            "SELECT fp, boot_epoch, nickname, address, contact_h, first_in_window, ip_change FROM restart "
            "WHERE boot_epoch BETWEEN ? AND ?", (a, z)):
        if addr in vic_hosts:
            hv.append((epoch_ts(be), "restart" + ("(first)" if fiw else ""), fp, nick, addr, contact.get(ch, ch)[:80], ""))
    for fp, pe, nick, addr, ch, fields in db.execute(
            "SELECT fp, pub_epoch, nickname, address, contact_h, fields FROM reload WHERE pub_epoch BETWEEN ? AND ?", (a, z)):
        if addr in vic_hosts:
            hv.append((epoch_ts(pe), "reload", fp, nick, addr, contact.get(ch, ch)[:80], fields))
    for pub, fp, nick, addr, field, old, new in db.execute(
            "SELECT published, fp, nickname, address, field, old, new FROM desc_change WHERE pub_epoch BETWEEN ? AND ? "
            "AND field NOT IN ('family_cert')", (a, z)):
        if addr in vic_hosts:
            hv.append((pub, "change:" + field, fp, nick, addr, "", (old[:40] + " -> " + new[:40])))
    hv.sort()
    with open(os.path.join(args.out, "victim_host_events_aug.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "event", "fp", "nickname", "address", "operator", "detail"])
        w.writerows(hv)
    print("events on later-victim hosts 2026-08-20..09-05:", len(hv),
          collections.Counter(h[1].split(":")[0] for h in hv))


if __name__ == "__main__":
    main()
