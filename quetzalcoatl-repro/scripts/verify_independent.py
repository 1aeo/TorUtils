#!/usr/bin/env python3
"""verify_independent.py - re-derive the key numbers by different methods, straight from the raw archives.

It does NOT use net/netdb.sqlite, scripts/common.py's summarizer or derive_tables.py. Checks:
  V1  archive coverage: consensus valid-after hours from tar MEMBER NAMES (not file contents); missing hours
  V2  duplicate server descriptors across monthly archives, counted by member file name (sha256 names)
  V3  attacker-policy relays from the raw May-October descriptors by RULE MATCHING (ordered "*"-rules
      equal to the near-open / OUR_POLICY rule sequences, ignoring private / /32 lines), not by summarization:
      victim count, earliest descriptor per class, per-AS counts (IPFire ASN instead of CAIDA)
  V4  Switzerland2: policy line counts around the change, from the raw October archive
  V5  BadExit / MiddleOnly per consensus from raw October consensus "s" lines (regex count)
  V6  family October hosts and the 2026-10-05 sweep from the ORIGINAL family script outputs
      (out/consensus_intervals.csv, out/descriptors.csv) with an independent restart computation
  V7  FranTech hit rate using IPFire ASNs for the reference consensus 2026-10-01 14:00 read from the raw archive
Writes net/verification_independent.txt.
"""
import collections
import csv
import datetime as dt
import ipaddress
import os
import re
import sys
import tarfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asmap import LocDB  # noqa: E402  (IPFire reader only)

DATA = "data"
NEAR = ["25", "465", "587", "993", "995", "119", "135-139", "445", "563", "1214", "4661-4666", "6346-6429", "6699",
        "6881-6999"]
OURP = ["25", "465", "587", "110", "143", "993", "995", "3389", "135", "137-139", "445"]
OUT = []


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    OUT.append(s)


def members(path):
    with tarfile.open(path, "r|xz") as tf:
        for m in tf:
            if m.isfile():
                yield m, tf.extractfile(m)


def star_rules(text):
    """ordered list of ports of 'reject *:PORT' lines up to the first 'accept *:*'; None if structure differs."""
    rej = []
    acc_all = False
    for line in text.split("\n"):
        if line.startswith("reject *:"):
            rej.append(line[9:].strip())
        elif line.startswith("accept *:*"):
            acc_all = True
            break
        elif line.startswith("accept"):
            return None
    return rej if acc_all else None


def main():
    # V1
    hours = set()
    for mo in ("05", "06", "07", "08", "09", "10"):
        with tarfile.open(os.path.join(DATA, "consensuses-2026-%s.tar.xz" % mo), "r|xz") as tf:
            for m in tf:
                mm = re.search(r"(\d{4}-\d\d-\d\d-\d\d)-00-00-consensus$", m.name)
                if mm:
                    hours.add(mm.group(1))
    hs = sorted(hours)
    t = dt.datetime.strptime(hs[0], "%Y-%m-%d-%H")
    end = dt.datetime.strptime(hs[-1], "%Y-%m-%d-%H")
    missing = []
    while t <= end:
        if t.strftime("%Y-%m-%d-%H") not in hours:
            missing.append(t.strftime("%Y-%m-%d %H:00"))
        t += dt.timedelta(hours=1)
    say("V1 consensus files by name:", len(hs), hs[0], "..", hs[-1], "missing:", len(missing), missing)
    # V2 + V3 + V4
    names = collections.Counter()
    loc = LocDB("asdata/location-2026-10-01-03:45.db")
    att = {}
    sw = []
    total = 0
    for mo in ("05", "06", "07", "08", "09", "10"):
        for m, f in members(os.path.join(DATA, "server-descriptors-2026-%s.tar.xz" % mo)):
            total += 1
            base = m.name.rsplit("/", 1)[-1]
            names[base] += 1
            data = f.read().decode("utf-8", "replace")
            fp = re.search(r"^fingerprint (.+)$", data, re.M)
            pub = re.search(r"^published (.+)$", data, re.M)
            rt = re.search(r"^router (\S+) (\S+)", data, re.M)
            if not (fp and pub and rt):
                continue
            fp = fp.group(1).replace(" ", "")
            pol = "\n".join(l for l in data.split("\n") if l.startswith(("accept ", "reject ")))
            if fp in ("29FEFE36A5F66A6C93D24775B9D2364A3831B597", "8427937D5A39E15699C850F26FED3CD59C379C48") and \
                    "2026-10-01" <= pub.group(1) <= "2026-10-03":
                sw.append((pub.group(1), fp[:8], pol.count("\n") + 1))
            sr = star_rules(pol)
            cls = "near-open" if sr == NEAR else ("OUR_POLICY" if sr == OURP else None)
            if cls:
                a = att.setdefault(fp, {"first": pub.group(1), "cls": cls, "ip": rt.group(2), "nick": rt.group(1)})
                if pub.group(1) < a["first"]:
                    a.update(first=pub.group(1), cls=cls, ip=rt.group(2))
    dup = sum(n - 1 for n in names.values() if n > 1)
    say("V2 descriptor files scanned:", total, "unique names:", len(names), "duplicates across archives:", dup)
    say("V3 relays with an attacker rule sequence (all May-Oct archives):", len(att),
        collections.Counter(a["cls"] for a in att.values()))
    for c in ("OUR_POLICY", "near-open"):
        e = min((a["first"], fp, a["nick"], a["ip"]) for fp, a in att.items() if a["cls"] == c)
        say("   earliest", c, e)
    by_as = collections.Counter()
    for a in att.values():
        r = loc.lookup(a["ip"])
        by_as["AS%s %s" % (r["asn"], r["as_name"][:25]) if r else "?"] += 1
    say("   by IPFire AS:", by_as.most_common())
    say("V4 Switzerland2 descriptors 10-01..10-02 (published, fp, policy lines):", sorted(sw))
    # V5
    rows = []
    with tarfile.open(os.path.join(DATA, "consensuses-2026-10.tar.xz"), "r|xz") as tf:
        for m in tf:
            if not m.isfile():
                continue
            d = tf.extractfile(m).read()
            va = re.search(rb"^valid-after (.+)$", d, re.M).group(1).decode()
            s_lines = re.findall(rb"^s (.*)$", d, re.M)
            rows.append((va, len(s_lines), sum(1 for s in s_lines if b" BadExit" in b" " + s),
                         sum(1 for s in s_lines if b" MiddleOnly" in b" " + s),
                         sum(1 for s in s_lines if re.search(rb"(^| )Exit( |$)", s))))
    rows.sort()
    pk = max(rows, key=lambda r: r[2])
    say("V5 October consensuses:", len(rows), "; BadExit min/max:", min(r[2] for r in rows), max(r[2] for r in rows),
        "peak at", pk[0], "; MiddleOnly max:", max(r[3] for r in rows))
    for r in rows:
        if r[0] in ("2026-10-04 20:00:00", "2026-10-04 21:00:00", "2026-10-05 10:00:00", "2026-10-05 11:00:00",
                    "2026-10-05 12:00:00"):
            say("   ", r)
    # V6 family from the original script outputs
    iv = list(csv.DictReader(open("out/consensus_intervals.csv")))
    lastend = collections.defaultdict(str)
    ip_oct = collections.defaultdict(set)
    for r in iv:
        lastend[r["fingerprint"]] = max(lastend[r["fingerprint"]], r["end_valid_after"])
        if r["end_valid_after"] >= "2026-10-01" and r["nickname"].startswith("Quetzalcoatl") and r["nickname"] in ("Quetzalcoatl",):
            ip_oct[r["fingerprint"]].add(r["ip"])
    act = [fp for fp in ip_oct]
    say("V6 family relays (nickname Quetzalcoatl) present in a consensus >= 10-01:", len(act),
        "hosts:", len({ip for s in ip_oct.values() for ip in s}))
    ds = list(csv.DictReader(open("out/descriptors.csv")))
    by = collections.defaultdict(list)
    for r in ds:
        by[r["fingerprint"]].append(r)
    restarts = []
    for fp, rs in by.items():
        rs.sort(key=lambda r: r["published"])
        prev = None
        for r in rs:
            if not r["uptime"].isdigit():
                continue
            pub = dt.datetime.strptime(r["published"], "%Y-%m-%d %H:%M:%S")
            boot = pub - dt.timedelta(seconds=int(r["uptime"]))
            if prev is not None and boot >= prev[0] and abs((boot - prev[1]).total_seconds()) > 2:
                restarts.append((boot, r["address"], fp))
            prev = (pub, boot)
    win = sorted(x for x in restarts if dt.datetime(2026, 10, 5, 8, 30) <= x[0] <= dt.datetime(2026, 10, 5, 11, 0))
    hosts = []
    for b, ip, fp in win:
        if ip not in hosts:
            hosts.append(ip)
    inv_s = sum(1 for i in range(len(hosts)) for j in range(i + 1, len(hosts)) if hosts[i] > hosts[j])
    say("V6 10-05 sweep from out/descriptors.csv: hosts", len(hosts), "relays", len({x[2] for x in win}),
        "first", win[0][0], "last", win[-1][0], "text-sort inversions", inv_s, "of", len(hosts) * (len(hosts) - 1) // 2)
    w1 = sorted(x for x in restarts if dt.datetime(2026, 10, 1, 15, 30) <= x[0] <= dt.datetime(2026, 10, 1, 16, 0))
    say("V6 10-01 15:30-16:00 restarts: hosts", len({x[1] for x in w1}), "relays", len({x[2] for x in w1}),
        w1[0][0] if w1 else "", w1[-1][0] if w1 else "")
    # V7 FranTech hit rate with IPFire ASNs, reference consensus from raw archive
    ref = None
    with tarfile.open(os.path.join(DATA, "consensuses-2026-10.tar.xz"), "r|xz") as tf:
        for m in tf:
            if m.name.endswith("2026-10-01-14-00-00-consensus"):
                ref = tf.extractfile(m).read().decode()
                break
    import base64
    present = []
    for mm in re.finditer(r"^r (\S+) (\S+) \S+ \S+ \S+ (\S+) ", ref, re.M):
        fp = base64.b64decode(mm.group(2) + "=" * (-len(mm.group(2)) % 4)).hex().upper()
        present.append((fp, mm.group(3), mm.group(1)))
    fam_contact = {r["fingerprint"] for r in ds if r["contact"].startswith("email:Quetzalcoatl_relays[]proton.me")}
    inside = [p for p in present if (loc.lookup(p[1]) or {}).get("asn") == 53667]
    ins_nf = [p for p in inside if p[0] not in fam_contact]
    out_nf = [p for p in present if p not in inside and p[0] not in fam_contact]
    hit_in = sum(1 for p in ins_nf if p[0] in att)
    hit_out = sum(1 for p in out_nf if p[0] in att)
    say("V7 reference consensus 2026-10-01 14:00 relays:", len(present), "; IPFire AS53667 non-family:", len(ins_nf),
        "hit", hit_in, "; outside non-family:", len(out_nf), "hit", hit_out)
    with open("net/verification_independent.txt", "w") as f:
        f.write("\n".join(OUT) + "\n")


if __name__ == "__main__":
    main()
