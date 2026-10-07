#!/usr/bin/env python3
"""asmap.py - map every relay IPv4 address in the network DB to its origin AS.

Primary source : CAIDA RouteViews prefix-to-AS (routeviews-rv2-20261001-1200.pfx2as.gz),
                 longest-prefix match; multi-origin entries ("a_b") and AS sets ("a,b") kept verbatim,
                 the first AS is used as `asn`.
AS names       : CAIDA AS-to-organization (20261001.as-org2info.txt.gz): aut_name and org_name.
Second source  : IPFire Location database (libloc format v1, location-2026-10-01-03:45.db), read with
                 a small pure-Python reader (big-endian header, binary tree of 12-byte nodes over the
                 IPv6 space with IPv4 at ::ffff:0:0/96, 12-byte network records cc/asn/flags,
                 8-byte AS records number/name-in-string-pool). Gives ASN + country for every IP.

Writes table ip_as into the DB and net/ip_as.csv; prints agreement statistics and unmapped IPs.

Usage: python3 -I scripts/asmap.py --db net/netdb.sqlite --asdata asdata --out net
"""
import argparse
import csv
import gzip
import ipaddress
import os
import sqlite3
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import log  # noqa: E402


class Pfx2AS:
    def __init__(self, path):
        self.by_len = {}
        n = 0
        with gzip.open(path, "rt") as f:
            for line in f:
                p = line.split()
                if len(p) != 3:
                    continue
                try:
                    net = int(ipaddress.IPv4Address(p[0]))
                except ValueError:
                    continue
                ln = int(p[1])
                self.by_len.setdefault(ln, {})[net] = p[2]
                n += 1
        self.lens = sorted(self.by_len, reverse=True)
        log("pfx2as prefixes:", n)

    def lookup(self, ip):
        v = int(ipaddress.IPv4Address(ip))
        for ln in self.lens:
            m = (v >> (32 - ln)) << (32 - ln) if ln else 0
            a = self.by_len[ln].get(m)
            if a is not None:
                return a, "%s/%d" % (ipaddress.IPv4Address(m), ln)
        return None, None


class ASOrg:
    def __init__(self, path):
        self.aut, self.org = {}, {}
        mode = None
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("# format:org_id"):
                    mode = "org"
                    continue
                if line.startswith("# format:aut"):
                    mode = "aut"
                    continue
                if line.startswith("#"):
                    continue
                p = line.rstrip("\n").split("|")
                if mode == "org" and len(p) >= 4:
                    self.org[p[0]] = (p[2], p[3])
                elif mode == "aut" and len(p) >= 4:
                    self.aut[p[0]] = (p[2], p[3])

    def names(self, asn):
        a = self.aut.get(str(asn))
        if not a:
            return "", "", ""
        o = self.org.get(a[1], ("", ""))
        return a[0], o[0], o[1]


class LocDB:
    """Minimal reader for IPFire libloc database format version 1."""

    def __init__(self, path):
        with open(path, "rb") as f:
            self.d = f.read()
        if self.d[:7] != b"LOCDBXX" or self.d[7] != 1:
            raise ValueError("not a libloc v1 database")
        (self.created, vendor, desc, lic, as_off, as_len, net_off, net_len, tree_off, tree_len,
         c_off, c_len, pool_off, pool_len) = struct.unpack(">QIIIIIIIIIIIII", self.d[8:8 + 8 + 13 * 4])
        self.as_off, self.as_len = as_off, as_len
        self.net_off, self.tree_off, self.pool_off = net_off, tree_off, pool_off
        self.asnames = {}
        for i in range(as_len // 8):
            num, name = struct.unpack(">II", self.d[as_off + 8 * i: as_off + 8 * i + 8])
            self.asnames[num] = self._str(name)

    def _str(self, off):
        s = self.pool_off + off
        e = self.d.index(b"\0", s)
        return self.d[s:e].decode("utf-8", "replace")

    def _node(self, i):
        o = self.tree_off + 12 * i
        return struct.unpack(">III", self.d[o:o + 12])

    def _net(self, i):
        o = self.net_off + 12 * i
        cc = self.d[o:o + 2].decode("ascii", "replace")
        asn, flags = struct.unpack(">IH", self.d[o + 4:o + 10])
        return cc, asn, flags

    def lookup(self, ip):
        v6 = int(ipaddress.IPv6Address("::ffff:" + ip))
        node = self._node(0)
        best = None
        if node[2] != 0xFFFFFFFF:
            best = (node[2], 0)
        for level in range(128):
            bit = (v6 >> (127 - level)) & 1
            nxt = node[1] if bit else node[0]
            if nxt == 0:
                break
            node = self._node(nxt)
            if node[2] != 0xFFFFFFFF:
                best = (node[2], level + 1)
        if best is None:
            return None
        cc, asn, flags = self._net(best[0])
        return {"cc": cc, "asn": asn, "flags": flags, "prefix_v6len": best[1],
                "as_name": self.asnames.get(asn, "")}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="net/netdb.sqlite")
    ap.add_argument("--asdata", default="asdata")
    ap.add_argument("--out", default="net")
    args = ap.parse_args()
    pfx = Pfx2AS(os.path.join(args.asdata, "routeviews-rv2-20261001-1200.pfx2as.gz"))
    org = ASOrg(os.path.join(args.asdata, "20261001.as-org2info.txt.gz"))
    loc = LocDB(os.path.join(args.asdata, "location-2026-10-01-03:45.db"))
    db = sqlite3.connect(args.db)
    ips = set(r[0] for r in db.execute("SELECT DISTINCT address FROM descriptor"))
    ips |= set(r[0] for r in db.execute("SELECT DISTINCT ip FROM cons_interval"))
    ips = sorted(i for i in ips if i)
    log("distinct IPv4 addresses:", len(ips))
    db.execute("DROP TABLE IF EXISTS ip_as")
    db.execute("""CREATE TABLE ip_as(ip TEXT PRIMARY KEY, asn TEXT, prefix TEXT, as_name TEXT, org_name TEXT,
                  org_cc TEXT, ipfire_asn TEXT, ipfire_cc TEXT, ipfire_as_name TEXT, agree INTEGER)""")
    rows = []
    unmapped, agree, disagree = [], 0, []
    for ip in ips:
        try:
            a, prefix = pfx.lookup(ip)
        except ValueError:
            a, prefix = None, None
        first = a.replace(",", "_").split("_")[0] if a else ""
        an, on, occ = org.names(first) if first else ("", "", "")
        try:
            l = loc.lookup(ip)
        except ValueError:
            l = None
        la = str(l["asn"]) if l and l["asn"] else ""
        ok = int(bool(a) and la != "" and la in a.replace(",", "_").split("_"))
        if not a:
            unmapped.append(ip)
        elif ok:
            agree += 1
        else:
            disagree.append((ip, a, la))
        rows.append((ip, a or "", prefix or "", an, on, occ, la, l["cc"] if l else "",
                     l["as_name"] if l else "", ok))
    db.executemany("INSERT INTO ip_as VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    db.commit()
    with open(os.path.join(args.out, "ip_as.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ip", "caida_asn", "caida_prefix", "as_name", "org_name", "org_cc", "ipfire_asn",
                    "ipfire_cc", "ipfire_as_name", "caida_ipfire_agree"])
        w.writerows(rows)
    log("mapped by CAIDA: %d / %d; unmapped: %d; CAIDA==IPFire: %d; differ: %d" % (
        len(ips) - len(unmapped), len(ips), len(unmapped), agree, len(disagree)))
    with open(os.path.join(args.out, "ip_as_unmapped.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ip", "ipfire_asn", "ipfire_cc"])
        for ip in unmapped:
            r = [x for x in rows if x[0] == ip][0]
            w.writerow([ip, r[6], r[7]])
    with open(os.path.join(args.out, "ip_as_disagree.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ip", "caida_asn", "ipfire_asn"])
        w.writerows(disagree)


if __name__ == "__main__":
    main()
