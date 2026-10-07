#!/usr/bin/env python3
"""
collector_family_history.py - rebuild a Tor relay family's public history from Tor Metrics CollecTor.

Standard library only (Python 3.8+). Downloads the monthly CollecTor archives (consensuses and,
optionally, server descriptors) and streams them without extracting anything to disk.

What it answers, for every relay in the family:
  * when it was in the consensus, with which flags, version, address and exit-policy summary
  * every exit-policy change (published descriptors give the full policy and the exact time)
  * flag changes (Exit, BadExit, MiddleOnly, Guard, Running, ...)
  * restarts (from descriptor uptime) and whether they cluster into scripted sweeps
  * contact / family / platform / address changes
  * which of these happened BEFORE the earliest known infection (2026-08-28 03:25:11 UTC)

Outputs (in --out):
  summary.md                    human-readable findings (start here)
  family_daily.csv              one row per day: family size, flag counts, policy classes
  consensus_intervals.csv       per relay: periods with constant nickname/ip/port/flags/version/policy
  policy_transitions.csv        every exit-policy-summary change per relay, classified
  flag_events.csv               every flag gained/lost per relay
  descriptors.csv               every server descriptor published by a family relay (if enabled)
  descriptor_changes.csv        full-policy / contact / family / platform / address changes
  restart_events.csv            restarts inferred from descriptor uptime, with cluster ids
  switzerland2_descriptors.csv  all descriptors of the two Switzerland2 relays
  policies/<sha1>.txt           the full text of every distinct exit policy seen

Example:
  python3 collector_family_history.py --seed family_seed_fingerprints.txt \
      --start 2026-05 --end 2026-10 --descriptors-start 2026-07 --data data --out out
"""
import argparse
import base64
import collections
import csv
import datetime as dt
import hashlib
import ipaddress
import os
import re
import sys
import tarfile
import urllib.request

BASE = "https://collector.torproject.org/archive/relay-descriptors"
UA = "relay-family-history/1.0 (incident analysis)"

ATTACKER_SUMMARY = ("reject 25,119,135-139,445,465,563,587,993,995,1214,"
                    "4661-4666,6346-6429,6699,6881-6999")
OUR_POLICY_SUMMARY = "reject 25,110,135,137-139,143,445,465,587,993,995,3389"
NONEXIT_SUMMARY = "reject 1-65535"
SENSITIVE_PORTS = [22, 23, 110, 143, 3389, 6667]
TLS_MAIL_PORTS = [993, 995]
KNOWN_INFECTION = dt.datetime(2026, 8, 28, 3, 25, 11)
SWITZERLAND2 = {
    "29FEFE36A5F66A6C93D24775B9D2364A3831B597": "Switzerland2 ORPort 9000",
    "8427937D5A39E15699C850F26FED3CD59C379C48": "Switzerland2 ORPort 9100",
}
NAME_HINT = "quetzal"          # nickname / contact hint for family members not in the seed list
TS_FMT = "%Y-%m-%d %H:%M:%S"


# ----------------------------------------------------------------------------- helpers
def log(*a):
    print(*a, file=sys.stderr, flush=True)


def months(start, end):
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    while (y, m) <= (ey, em):
        yield "%04d-%02d" % (y, m)
        m += 1
        if m == 13:
            y, m = y + 1, 1


def parse_ts(s):
    return dt.datetime.strptime(s, TS_FMT)


def download(url, dest, offline=False):
    """Download url to dest unless an identical-size copy is already there."""
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        if offline:
            return dest
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                size = int(r.headers.get("Content-Length") or 0)
            if size and size == os.path.getsize(dest):
                log("  have", os.path.basename(dest))
                return dest
        except Exception as e:  # keep the local copy if HEAD fails
            log("  HEAD failed for %s (%s); using local copy" % (url, e))
            return dest
    if offline:
        raise FileNotFoundError(dest)
    log("  downloading", url)
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                print("\r    %d%% of %d MB" % (done * 100 // total, total >> 20),
                      end="", file=sys.stderr)
    print(file=sys.stderr)
    os.replace(tmp, dest)
    return dest


def iter_tar(path):
    """Yield (member name, bytes) for every regular file in a .tar.xz, streaming."""
    with tarfile.open(path, mode="r|xz") as tf:
        for m in tf:
            if not m.isfile():
                continue
            f = tf.extractfile(m)
            if f is not None:
                yield m.name, f.read()


def fp_to_b64(fp):
    return base64.b64encode(bytes.fromhex(fp)).decode().rstrip("=")


def b64_to_fp(b):
    return base64.b64decode(b + "=" * (-len(b) % 4)).hex().upper()


def norm_family_token(tok):
    t = tok.lstrip("$").split("=")[0].split("~")[0].upper()
    return t if re.fullmatch(r"[0-9A-F]{40}", t) else None


def parse_portlist(s):
    out = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.append((int(a), int(b)))
        else:
            out.append((int(part), int(part)))
    return out


def port_allowed(summary, port):
    """Exit-policy summary ('accept 80,443' / 'reject 25,119') -> is port allowed?"""
    if not summary:
        return None
    kind, _, plist = summary.partition(" ")
    inside = any(a <= port <= b for a, b in parse_portlist(plist))
    return inside if kind == "accept" else not inside


def classify_summary(s):
    if not s:
        return "none"
    if s == NONEXIT_SUMMARY:
        return "non-exit"
    if s == ATTACKER_SUMMARY:
        return "attacker-near-open"
    if s == OUR_POLICY_SUMMARY:
        return "our-policy-oct1"
    if s.startswith("accept"):
        return "accept-list"
    return "reject-list(open)"


def ip_key(ip):
    try:
        return int(ipaddress.ip_address(ip))
    except ValueError:
        return 0


def inversions(seq):
    return sum(1 for i in range(len(seq)) for j in range(i + 1, len(seq)) if seq[i] > seq[j])


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


# ----------------------------------------------------------------------------- descriptors
FP_RE = re.compile(rb"^fingerprint ((?:[0-9A-F]{4} ?){10})\s*$", re.M)
FAM_RE = re.compile(rb"^family (.*)$", re.M)


def parse_descriptor(data):
    d = {"policy": [], "family": [], "family_cert": 0, "or_addresses": []}
    in_pem = False
    for raw in data.split(b"\n"):
        line = raw.decode("utf-8", "replace").rstrip("\r")
        if line.startswith("-----BEGIN"):
            in_pem = True
            continue
        if line.startswith("-----END"):
            in_pem = False
            continue
        if in_pem:
            continue
        if line.startswith("router "):
            p = line.split()
            d["nickname"] = p[1]
            d["address"] = p[2] if len(p) > 2 else ""
            d["or_port"] = p[3] if len(p) > 3 else ""
            d["dir_port"] = p[5] if len(p) > 5 else ""
        elif line.startswith("published "):
            d["published"] = line[10:].strip()
        elif line.startswith("fingerprint "):
            d["fingerprint"] = line[12:].replace(" ", "").strip().upper()
        elif line.startswith("platform "):
            d["platform"] = line[9:].strip()
        elif line.startswith("uptime "):
            d["uptime"] = line[7:].strip()
        elif line.startswith("bandwidth "):
            d["bandwidth"] = line[10:].strip()
        elif line.startswith("contact "):
            d["contact"] = line[8:].strip()
        elif line.startswith("family "):
            d["family"] = line[7:].split()
        elif line.startswith("family-cert"):
            d["family_cert"] += 1
        elif line.startswith("hibernating "):
            d["hibernating"] = line[12:].strip()
        elif line.startswith("ipv6-policy "):
            d["ipv6_policy"] = line[12:].strip()
        elif line.startswith("or-address "):
            d["or_addresses"].append(line[11:].strip())
        elif line.startswith("accept ") or line.startswith("reject "):
            d["policy"].append(line.strip())
    return d


def scan_descriptors(paths, seeds):
    rows, policies = [], {}
    scanned = 0
    for path in paths:
        log("scanning descriptors:", os.path.basename(path))
        for _, data in iter_tar(path):
            scanned += 1
            m = FP_RE.search(data)
            if not m:
                continue
            fp = m.group(1).replace(b" ", b"").decode()
            low = data.lower()
            hint = NAME_HINT.encode() in low
            fam_hit = False
            fm = FAM_RE.search(data)
            if fm and not (fp in seeds or hint):
                toks = fm.group(1).decode("utf-8", "replace").split()
                fam_hit = any(norm_family_token(t) in seeds for t in toks)
            if not (fp in seeds or hint or fam_hit):
                continue
            d = parse_descriptor(data)
            if "published" not in d:
                continue
            reasons = []
            if fp in seeds:
                reasons.append("seed")
            if NAME_HINT in d.get("nickname", "").lower():
                reasons.append("nickname")
            if NAME_HINT in d.get("contact", "").lower():
                reasons.append("contact")
            fam_fps = [x for x in (norm_family_token(t) for t in d["family"]) if x]
            if any(x in seeds for x in fam_fps):
                reasons.append("family-line")
            if not reasons:
                continue
            ptext = "\n".join(d["policy"])
            phash = hashlib.sha1(ptext.encode()).hexdigest()
            policies[phash] = ptext
            fam_text = " ".join(sorted(fam_fps))
            rows.append({
                "fingerprint": fp, "published": d["published"],
                "nickname": d.get("nickname", ""), "address": d.get("address", ""),
                "or_port": d.get("or_port", ""), "dir_port": d.get("dir_port", ""),
                "or_addresses": " ".join(d["or_addresses"]),
                "platform": d.get("platform", ""), "uptime": d.get("uptime", ""),
                "bandwidth": d.get("bandwidth", ""), "hibernating": d.get("hibernating", ""),
                "contact": d.get("contact", ""),
                "contact_sha1": hashlib.sha1(d.get("contact", "").encode()).hexdigest()[:10],
                "family_count": len(fam_fps),
                "family_sha1": hashlib.sha1(fam_text.encode()).hexdigest()[:10],
                "family_seed_overlap": sum(1 for x in fam_fps if x in seeds),
                "family_cert_lines": d["family_cert"],
                "policy_sha1": phash, "policy_lines": len(d["policy"]),
                "ipv6_policy": d.get("ipv6_policy", ""),
                "reasons": "+".join(reasons),
            })
    rows.sort(key=lambda r: (r["fingerprint"], r["published"]))
    # drop exact duplicates (the same descriptor can appear in two monthly archives)
    dedup, seen = [], set()
    for r in rows:
        k = (r["fingerprint"], r["published"], r["policy_sha1"])
        if k not in seen:
            seen.add(k)
            dedup.append(r)
    log("  descriptors scanned: %d, family descriptors: %d" % (scanned, len(dedup)))
    return dedup, policies, scanned


# ----------------------------------------------------------------------------- consensuses
R_RE = re.compile(rb"^r (\S+) (\S+) \S+ \S+ \S+ (\S+) (\d+) (\d+)", re.M)


def scan_consensus_file(data, target_b64):
    va = None
    m = re.search(rb"^valid-after (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", data, re.M)
    if m:
        va = m.group(1).decode()
    found = []
    starts = [(mm.start(), mm) for mm in R_RE.finditer(data)]
    for i, (pos, mm) in enumerate(starts):
        nick, ident = mm.group(1), mm.group(2)
        if ident not in target_b64 and NAME_HINT.encode() not in nick.lower():
            continue
        end = starts[i + 1][0] if i + 1 < len(starts) else len(data)
        block = data[pos:end]
        e = {"fp": b64_to_fp(ident.decode()), "nickname": nick.decode("utf-8", "replace"),
             "ip": mm.group(3).decode(), "or_port": mm.group(4).decode(),
             "dir_port": mm.group(5).decode(), "flags": "", "version": "", "bw": "",
             "policy": ""}
        for raw in block.split(b"\n")[1:]:
            if raw.startswith(b"s "):
                e["flags"] = " ".join(sorted(raw[2:].decode().split()))
            elif raw.startswith(b"v "):
                e["version"] = raw[2:].decode().strip()
            elif raw.startswith(b"w "):
                bw = re.search(rb"Bandwidth=(\d+)", raw)
                e["bw"] = bw.group(1).decode() if bw else ""
            elif raw.startswith(b"p "):
                e["policy"] = raw[2:].decode().strip()
            elif raw.startswith(b"directory-footer"):
                break
        found.append(e)
    return va, found


def scan_consensuses(paths, targets):
    target_b64 = {fp_to_b64(fp).encode() for fp in targets}
    state, intervals, daily = {}, [], []
    prev_va, n_cons = None, 0
    first_va = last_va = None
    daily_done = set()
    for path in paths:
        log("scanning consensuses:", os.path.basename(path))
        month = []
        for _, data in iter_tar(path):
            va, found = scan_consensus_file(data, target_b64)
            if va:
                month.append((va, found))
        month.sort(key=lambda x: x[0])
        for va, found in month:
            if va == prev_va:
                continue
            n_cons += 1
            first_va = first_va or va
            last_va = va
            for e in found:
                key = (e["nickname"], e["ip"], e["or_port"], e["flags"], e["version"], e["policy"])
                st = state.get(e["fp"])
                if st and st["key"] == key and st["end"] == prev_va:
                    st["end"] = va
                    st["n"] += 1
                    if e["bw"]:
                        st["bw_max"] = max(st["bw_max"], int(e["bw"]))
                else:
                    if st:
                        intervals.append(st)
                    state[e["fp"]] = {"fp": e["fp"], "start": va, "end": va, "n": 1,
                                      "key": key, "bw_max": int(e["bw"] or 0),
                                      "after_gap": bool(st and st["end"] != prev_va)}
            day, hour = va[:10], va[11:13]
            if hour == "12" and day not in daily_done:
                daily_done.add(day)
                c = collections.Counter()
                for e in found:
                    c["present"] += 1
                    flags = set(e["flags"].split())
                    for fl in ("Exit", "BadExit", "MiddleOnly", "Guard", "Stable", "Running"):
                        if fl in flags:
                            c[fl] += 1
                    c["policy:" + classify_summary(e["policy"])] += 1
                    if port_allowed(e["policy"], 22):
                        c["allows22"] += 1
                daily.append((day, c))
            prev_va = va
    for st in state.values():
        intervals.append(st)
    log("  consensuses scanned: %d (%s .. %s)" % (n_cons, first_va, last_va))
    return intervals, daily, n_cons, first_va, last_va


# ----------------------------------------------------------------------------- analysis
def transitions_from_intervals(intervals):
    by_fp = collections.defaultdict(list)
    for iv in intervals:
        by_fp[iv["fp"]].append(iv)
    pol, flg = [], []
    for fp, ivs in by_fp.items():
        ivs.sort(key=lambda x: x["start"])
        prev = None
        for iv in ivs:
            nick, ip, port, flags, ver, policy = iv["key"]
            if prev is None:
                flg.append((iv["start"], fp, nick, ip, "first-seen", flags, ""))
            else:
                pn, pip, pport, pflags, pver, ppol = prev["key"]
                if policy != ppol:
                    pol.append((iv["start"], fp, nick, ip, ppol, policy, iv["after_gap"]))
                a, b = set(pflags.split()), set(flags.split())
                for fl in sorted(b - a):
                    flg.append((iv["start"], fp, nick, ip, "gained", fl, iv["after_gap"]))
                for fl in sorted(a - b):
                    flg.append((iv["start"], fp, nick, ip, "lost", fl, iv["after_gap"]))
            prev = iv
    pol.sort()
    flg.sort()
    return pol, flg


def classify_transition(old, new):
    tags = []
    if new == ATTACKER_SUMMARY:
        tags.append("ATTACKER_POLICY")
    if new == OUR_POLICY_SUMMARY:
        tags.append("OUR_POLICY_OCT1")
    if old == NONEXIT_SUMMARY and new != NONEXIT_SUMMARY:
        tags.append("NONEXIT_TO_EXIT")
    if old.startswith("accept") and new.startswith("reject") and new != NONEXIT_SUMMARY:
        tags.append("ACCEPTLIST_TO_OPEN")
    opened = [p for p in SENSITIVE_PORTS if not port_allowed(old, p) and port_allowed(new, p)]
    if opened:
        tags.append("OPENS_" + "_".join(map(str, opened)))
    closed = [p for p in TLS_MAIL_PORTS if port_allowed(old, p) and not port_allowed(new, p)]
    if closed:
        tags.append("CLOSES_TLS_MAIL_" + "_".join(map(str, closed)))
    if new == NONEXIT_SUMMARY and old != NONEXIT_SUMMARY:
        tags.append("EXIT_TO_NONEXIT")
    return tags


def restart_events(desc_rows, max_uptime=7200):
    ev = []
    for r in desc_rows:
        try:
            up = int(r["uptime"])
        except (TypeError, ValueError):
            continue
        if up > max_uptime:
            continue
        t = parse_ts(r["published"]) - dt.timedelta(seconds=up)
        ev.append((t.replace(second=0), r["fingerprint"], r["nickname"], r["address"]))
    ev.sort()
    dedup, last = [], {}
    for t, fp, nick, addr in ev:
        if fp in last and abs((t - last[fp]).total_seconds()) <= 600:
            continue
        last[fp] = t
        dedup.append([t, fp, nick, addr, None])
    # cluster: consecutive restarts less than 20 minutes apart
    cid, prev_t, clusters = 0, None, collections.defaultdict(list)
    for e in dedup:
        if prev_t is None or (e[0] - prev_t).total_seconds() > 1200:
            cid += 1
        e[4] = cid
        clusters[cid].append(e)
        prev_t = e[0]
    return dedup, clusters


def descriptor_changes(desc_rows):
    out = []
    by_fp = collections.defaultdict(list)
    for r in desc_rows:
        by_fp[r["fingerprint"]].append(r)
    fields = ["policy_sha1", "contact_sha1", "family_sha1", "platform", "address", "or_port",
              "nickname", "ipv6_policy", "hibernating", "family_cert_lines"]
    for fp, rs in by_fp.items():
        rs.sort(key=lambda x: x["published"])
        for a, b in zip(rs, rs[1:]):
            for f in fields:
                if a[f] != b[f]:
                    extra = ""
                    if f == "policy_sha1":
                        extra = "lines %s -> %s" % (a["policy_lines"], b["policy_lines"])
                    out.append((b["published"], fp, b["nickname"], b["address"], f,
                                str(a[f]), str(b[f]), extra))
    out.sort()
    return out


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", required=True, help="file with one 40-hex fingerprint per line (# comments ok)")
    ap.add_argument("--start", default="2026-05", help="first month of consensuses (YYYY-MM)")
    ap.add_argument("--end", default="2026-10", help="last month (YYYY-MM)")
    ap.add_argument("--descriptors-start", default="2026-07",
                    help="first month of server descriptors (each month is ~500 MB); 'none' to skip")
    ap.add_argument("--data", default="data", help="download cache directory")
    ap.add_argument("--out", default="out", help="output directory")
    ap.add_argument("--offline", action="store_true", help="use cached archives only")
    args = ap.parse_args()

    os.makedirs(args.data, exist_ok=True)
    os.makedirs(os.path.join(args.out, "policies"), exist_ok=True)
    seeds = set()
    with open(args.seed, encoding="utf-8") as f:
        for line in f:
            t = line.split("#")[0].strip().upper()
            if re.fullmatch(r"[0-9A-F]{40}", t):
                seeds.add(t)
    seeds |= set(SWITZERLAND2)
    log("seed fingerprints:", len(seeds))

    cons_paths = []
    for mo in months(args.start, args.end):
        name = "consensuses-%s.tar.xz" % mo
        cons_paths.append(download("%s/consensuses/%s" % (BASE, name),
                                   os.path.join(args.data, name), args.offline))
    desc_paths = []
    if args.descriptors_start.lower() != "none":
        for mo in months(args.descriptors_start, args.end):
            name = "server-descriptors-%s.tar.xz" % mo
            desc_paths.append(download("%s/server-descriptors/%s" % (BASE, name),
                                       os.path.join(args.data, name), args.offline))

    desc_rows, policies, n_desc = ([], {}, 0)
    if desc_paths:
        desc_rows, policies, n_desc = scan_descriptors(desc_paths, seeds)
    discovered = {r["fingerprint"] for r in desc_rows} - seeds
    targets = seeds | {r["fingerprint"] for r in desc_rows}

    intervals, daily, n_cons, first_va, last_va = scan_consensuses(cons_paths, targets)
    pol_tr, flag_ev = transitions_from_intervals(intervals)

    # ---------------- write CSVs
    out = args.out
    write_csv(os.path.join(out, "consensus_intervals.csv"),
              ["fingerprint", "nickname", "ip", "or_port", "flags", "version", "policy_summary",
               "policy_class", "start_valid_after", "end_valid_after", "consensuses",
               "max_bandwidth_weight", "after_gap"],
              [(iv["fp"], iv["key"][0], iv["key"][1], iv["key"][2], iv["key"][3], iv["key"][4],
                iv["key"][5], classify_summary(iv["key"][5]), iv["start"], iv["end"], iv["n"],
                iv["bw_max"], iv["after_gap"])
               for iv in sorted(intervals, key=lambda x: (x["fp"], x["start"]))])
    write_csv(os.path.join(out, "policy_transitions.csv"),
              ["first_seen_valid_after", "fingerprint", "nickname", "ip", "old_summary",
               "new_summary", "after_gap", "tags", "before_known_infection"],
              [(t, fp, n, ip, o, nw, g, " ".join(classify_transition(o, nw)),
                parse_ts(t) < KNOWN_INFECTION)
               for t, fp, n, ip, o, nw, g in pol_tr])
    write_csv(os.path.join(out, "flag_events.csv"),
              ["valid_after", "fingerprint", "nickname", "ip", "event", "flag(s)", "after_gap"],
              flag_ev)
    keys = ["present", "Exit", "BadExit", "MiddleOnly", "Guard", "Stable", "Running", "allows22",
            "policy:non-exit", "policy:accept-list", "policy:attacker-near-open",
            "policy:our-policy-oct1", "policy:reject-list(open)", "policy:none"]
    write_csv(os.path.join(out, "family_daily.csv"), ["date_1200utc"] + keys,
              [[d] + [c.get(k, 0) for k in keys] for d, c in daily])
    if desc_rows:
        hdr = list(desc_rows[0].keys())
        write_csv(os.path.join(out, "descriptors.csv"), hdr, [[r[k] for k in hdr] for r in desc_rows])
        write_csv(os.path.join(out, "switzerland2_descriptors.csv"), hdr,
                  [[r[k] for k in hdr] for r in desc_rows if r["fingerprint"] in SWITZERLAND2])
        dchg = descriptor_changes(desc_rows)
        write_csv(os.path.join(out, "descriptor_changes.csv"),
                  ["published", "fingerprint", "nickname", "address", "field", "old", "new", "note"],
                  dchg)
        rst, clusters = restart_events(desc_rows)
        write_csv(os.path.join(out, "restart_events.csv"),
                  ["restart_time_utc", "fingerprint", "nickname", "address", "cluster_id"],
                  [(e[0].strftime(TS_FMT), e[1], e[2], e[3], e[4]) for e in rst])
        for h, text in policies.items():
            with open(os.path.join(out, "policies", h + ".txt"), "w", encoding="utf-8") as f:
                f.write(text + "\n")
    else:
        dchg, rst, clusters = [], [], {}

    # ---------------- summary
    S = []
    w = S.append
    w("# Family history from Tor Metrics CollecTor\n")
    w("Generated %s UTC. Consensus months %s..%s; descriptor months %s..%s.\n" % (
        dt.datetime.now(dt.timezone.utc).strftime(TS_FMT), args.start, args.end,
        args.descriptors_start, args.end))
    w("- Consensuses scanned: %d (%s .. %s)" % (n_cons, first_va, last_va))
    w("- Server descriptors scanned: %d; family descriptors kept: %d" % (n_desc, len(desc_rows)))
    seen_fps = {iv["fp"] for iv in intervals}
    w("- Seed fingerprints: %d; seen in a consensus in the window: %d; never seen: %d" % (
        len(seeds), len(seeds & seen_fps), len(seeds - seen_fps)))
    w("- Relays found that were NOT in the seed list: %d (reasons: nickname/contact = name contains 'quetzal'; "
      "family-line = the relay lists a seed fingerprint in its own family line, a one-sided claim)"
      % len(discovered | (seen_fps - seeds)))
    for fp in sorted(discovered | (seen_fps - seeds)):
        rs = [r for r in desc_rows if r["fingerprint"] == fp]
        why = rs[-1]["reasons"] if rs else "nickname match in consensus"
        nick = rs[-1]["nickname"] if rs else ""
        w("  - %s %s (%s)" % (fp, nick, why))
    w("")

    w("## Exit-policy summary changes (consensus p lines)\n")
    tagc = collections.Counter()
    for t, fp, n, ip, o, nw, g in pol_tr:
        for tag in classify_transition(o, nw):
            tagc[tag.split("_")[0] if tag.startswith(("OPENS", "CLOSES")) else tag] += 1
    w("Counts by tag: " + (", ".join("%s=%d" % kv for kv in sorted(tagc.items())) or "none"))
    w("")
    sus = [(t, fp, n, ip, o, nw, g, classify_transition(o, nw)) for t, fp, n, ip, o, nw, g in pol_tr]
    sus = [x for x in sus if x[7] and x[7] != ["EXIT_TO_NONEXIT"]]
    w("Suspicious transitions (%d), earliest first:\n" % len(sus))
    w("| first seen (consensus) | relay | ip | old -> new | tags |")
    w("|---|---|---|---|---|")
    for t, fp, n, ip, o, nw, g, tags in sus:
        flag = " **BEFORE 2026-08-28 03:25 UTC**" if parse_ts(t) < KNOWN_INFECTION else ""
        w("| %s%s | %s %s | %s | `%s` -> `%s` | %s |" % (t, flag, n, fp[:8], ip, o, nw, " ".join(tags)))
    w("")
    by_hour = collections.Counter(t[:13] for t, *_ in sus)
    w("Hours in which 3 or more relays changed policy suspiciously:")
    for h, c in sorted(by_hour.items()):
        if c >= 3:
            w("- %s:00 UTC: %d relays" % (h, c))
    w("")
    early = [x for x in sus if parse_ts(x[0]) < KNOWN_INFECTION]
    w("Suspicious transitions BEFORE the known infection (2026-08-28 03:25:11 UTC): %d" % len(early))
    w("")

    w("## Flags\n")
    for fl in ("BadExit", "MiddleOnly", "Exit"):
        ev = [e for e in flag_ev if e[4] == "gained" and e[5] == fl]
        w("- %s gained by %d relays; first at %s, last at %s" % (
            fl, len({e[1] for e in ev}), ev[0][0] if ev else "-", ev[-1][0] if ev else "-"))
    w("")

    last_seen = collections.Counter()
    by_fp_end = {}
    for iv in intervals:
        if iv["end"] > by_fp_end.get(iv["fp"], ""):
            by_fp_end[iv["fp"]] = iv["end"]
    for fp, end in by_fp_end.items():
        if end != last_va:
            last_seen[end[:10]] += 1
    w("## Relays whose last consensus appearance falls inside the window (count by date)\n")
    for d, c in sorted(last_seen.items()):
        if d >= "2026-08-01":
            w("- %s: %d" % (d, c))
    w("")

    w("## Daily family snapshot (12:00 UTC consensus), from 2026-08-20\n")
    w("| date | present | Exit | BadExit | MiddleOnly | Guard | non-exit | accept-list | attacker | our-policy | allows 22 |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    for d, c in daily:
        if d >= "2026-08-20" or d.endswith("-01"):
            w("| %s | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d |" % (
                d, c["present"], c["Exit"], c["BadExit"], c["MiddleOnly"], c["Guard"],
                c["policy:non-exit"], c["policy:accept-list"], c["policy:attacker-near-open"],
                c["policy:our-policy-oct1"], c["allows22"]))
    w("")

    if desc_rows:
        w("## Descriptor-level changes\n")
        fc = collections.Counter(x[4] for x in dchg)
        w("Change counts: " + ", ".join("%s=%d" % kv for kv in sorted(fc.items())))
        for f in ("contact_sha1", "family_sha1", "platform", "address", "nickname"):
            rows = [x for x in dchg if x[4] == f]
            if rows:
                w("\n%s changes (first 40):" % f)
                for x in rows[:40]:
                    w("- %s %s %s %s: `%s` -> `%s`" % (x[0], x[2], x[1][:8], x[3], x[5], x[6]))
        w("")
        w("## Restart clusters (5+ hosts within chained 20-minute gaps)\n")
        for cid, evs in sorted(clusters.items()):
            hosts = []
            for e in evs:
                if e[3] not in hosts:
                    hosts.append(e[3])
            if len(hosts) < 5:
                continue
            inv_s = inversions(hosts)
            inv_n = inversions([ip_key(h) for h in hosts])
            pairs = len(hosts) * (len(hosts) - 1) // 2
            w("- cluster %d: %s .. %s UTC, %d hosts, %d relays; order vs text sort: %d/%d inversions, "
              "vs numeric IP sort: %d/%d" % (cid, evs[0][0].strftime(TS_FMT), evs[-1][0].strftime(TS_FMT),
                                             len(hosts), len(evs), inv_s, pairs, inv_n, pairs))
        w("")
        w("## Switzerland2 descriptors (verification)\n")
        sw = [r for r in desc_rows if r["fingerprint"] in SWITZERLAND2]
        w("%d descriptors for the two Switzerland2 relays (%s .. %s)." % (
            len(sw), sw[0]["published"] if sw else "-", sw[-1]["published"] if sw else "-"))
        for fp, label in SWITZERLAND2.items():
            rs = [r for r in sw if r["fingerprint"] == fp]
            seq = []
            for r in rs:
                if not seq or seq[-1][1] != r["policy_sha1"]:
                    seq.append((r["published"], r["policy_sha1"], r["policy_lines"]))
            w("\n%s (%s): policy versions in order:" % (label, fp))
            for pub, h, nl in seq:
                w("- from %s: %s lines, sha1 %s" % (pub, nl, h[:10]))
            if len(seq) >= 2:
                a, b = seq[-2], seq[-1]
                w("\nLast change: %s -> %s at %s." % (a[2], b[2], b[0]))
                w("\nPolicy before:\n```\n%s\n```\nPolicy after:\n```\n%s\n```" % (
                    policies.get(a[1], ""), policies.get(b[1], "")))
        w("")

    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(S) + "\n")
    log("done; see", os.path.join(out, "summary.md"))


if __name__ == "__main__":
    main()
