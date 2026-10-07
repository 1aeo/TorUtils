"""common.py - shared helpers for the Quetzalcoatl incident reproduction (standard library only).

Contents
  * constants: reference policy summaries, known infection time, Switzerland2 fingerprints
  * iter_tar(): stream (name, bytes) out of a CollecTor .tar.xz without extracting (mode "r|xz")
  * fingerprint <-> base64 conversion
  * parse_policy_line() / summarize_policy(): a re-implementation of tor's IPv4
    policy_summarize() (src/core/or/policies.c):
        - an accept rule only counts when its address mask is /0
        - a reject rule adds 2^(32-maskbits) to the reject count of every port it covers,
          unless its network is exactly one of tor's private nets
          (0.0.0.0/8, 169.254.0.0/16, 127.0.0.0/8, 192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12)
        - a port becomes accepted when an accept rule reaches it while its reject count is
          <= 2^25; once accepted it stays accepted (first-match semantics)
        - output the shorter of the accept / reject port lists (tie -> accept),
          "reject 1-65535" if nothing accepted, "accept 1-65535" if nothing rejected,
          and the 1000-character cap (truncate the accept list at the last comma)
  * classify_summary(): non-exit / near-open / OUR_POLICY / accept-list / other reject-list
  * normalize_policy(): drop own-IP and private-range lines (for identical-policy grouping)
  * order statistics: inversions (string / numeric / dotless), longest ascending run, Kendall tau
"""
import base64
import datetime as dt
import ipaddress
import re
import sys
import tarfile

NEAR_OPEN = ("reject 25,119,135-139,445,465,563,587,993,995,1214,"
             "4661-4666,6346-6429,6699,6881-6999")
OUR_POLICY = "reject 25,110,135,137-139,143,445,465,587,993,995,3389"
NONEXIT = "reject 1-65535"
ATTACKER_SUMMARIES = {NEAR_OPEN: "near-open", OUR_POLICY: "OUR_POLICY"}
KNOWN_INFECTION = "2026-08-28 03:25:11"
SWITZERLAND2 = {
    "29FEFE36A5F66A6C93D24775B9D2364A3831B597": "Switzerland2 ORPort 9000",
    "8427937D5A39E15699C850F26FED3CD59C379C48": "Switzerland2 ORPort 9100",
}
TS_FMT = "%Y-%m-%d %H:%M:%S"
MAX_SUMMARY_LEN = 1000
REJECT_CUTOFF_V4 = 1 << 25

PRIVATE_NETS_V4 = {
    (int(ipaddress.IPv4Address("0.0.0.0")), 8),
    (int(ipaddress.IPv4Address("169.254.0.0")), 16),
    (int(ipaddress.IPv4Address("127.0.0.0")), 8),
    (int(ipaddress.IPv4Address("192.168.0.0")), 16),
    (int(ipaddress.IPv4Address("10.0.0.0")), 8),
    (int(ipaddress.IPv4Address("172.16.0.0")), 12),
}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


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


def b64_to_hex(b):
    return base64.b64decode(b + "=" * (-len(b) % 4)).hex().upper()


def parse_ts(s):
    return dt.datetime.strptime(s, TS_FMT)


def fmt_ts(t):
    return t.strftime(TS_FMT)


def ts_epoch(s):
    return int(parse_ts(s).replace(tzinfo=dt.timezone.utc).timestamp())


def epoch_ts(e):
    return dt.datetime.fromtimestamp(e, dt.timezone.utc).strftime(TS_FMT)


# ----------------------------------------------------------------------------- exit policies
def _parse_mask(m):
    """mask may be a prefix length or a dotted netmask."""
    if "." in m:
        v = int(ipaddress.IPv4Address(m))
        return bin(v).count("1")
    return int(m)


def parse_policy_line(line):
    """'accept 1.2.3.0/24:80-443' -> (kind, net_int, maskbits, pmin, pmax) or None (IPv6/garbage)."""
    try:
        kind, rest = line.split(None, 1)
    except ValueError:
        return None
    if kind not in ("accept", "reject"):
        return None
    rest = rest.strip()
    if rest.startswith("["):
        return None  # IPv6 item (not used in descriptors)
    addr, _, ports = rest.rpartition(":")
    if not addr:
        return None
    if addr == "*":
        net, bits = 0, 0
    else:
        if "/" in addr:
            a, m = addr.split("/", 1)
            bits = _parse_mask(m)
        else:
            a, bits = addr, 32
        try:
            net = int(ipaddress.IPv4Address(a))
        except ValueError:
            return None
    if ports == "*":
        pmin, pmax = 1, 65535
    elif "-" in ports:
        p1, p2 = ports.split("-", 1)
        pmin, pmax = int(p1), int(p2)
    else:
        pmin = pmax = int(ports)
    if pmin == 0:
        pmin = 1  # tor treats port 0 in summaries as 1 (summaries cover 1-65535)
    return kind, net, bits, pmin, pmax


def summarize_policy(lines):
    """Re-implementation of tor's policy_summarize(policy, AF_INET). lines: list of str."""
    # segments: [prt_min, prt_max, accepted, reject_count]
    segs = [[1, 65535, False, 0]]

    def split(pmin, pmax):
        # split so a segment starts at pmin and one ends at pmax; return index of seg starting at pmin
        i = 0
        while segs[i][1] < pmin:
            i += 1
        if segs[i][0] < pmin:
            s = segs[i]
            new = [pmin, s[1], s[2], s[3]]
            s[1] = pmin - 1
            segs.insert(i + 1, new)
            i += 1
        start = i
        j = i
        while segs[j][1] < pmax:
            j += 1
        if segs[j][1] > pmax:
            s = segs[j]
            new = [pmax + 1, s[1], s[2], s[3]]
            s[1] = pmax
            segs.insert(j + 1, new)
        return start

    for line in lines:
        it = parse_policy_line(line)
        if it is None:
            continue
        kind, net, bits, pmin, pmax = it
        if kind == "accept":
            if bits != 0:
                continue
            i = split(pmin, pmax)
            while i < len(segs) and segs[i][1] <= pmax:
                if not segs[i][2] and segs[i][3] <= REJECT_CUTOFF_V4:
                    segs[i][2] = True
                i += 1
        else:
            if (net, bits) in PRIVATE_NETS_V4:
                continue
            count = 1 << (32 - bits)
            i = split(pmin, pmax)
            while i < len(segs) and segs[i][1] <= pmax:
                segs[i][3] += count
                i += 1
    accepts, rejects = [], []
    i, start = 0, 1
    n = len(segs)
    while True:
        last = i == n - 1
        if last or segs[i][2] != segs[i + 1][2]:
            buf = "%d" % start if start == segs[i][1] else "%d-%d" % (start, segs[i][1])
            (accepts if segs[i][2] else rejects).append(buf)
            if last:
                break
            start = segs[i + 1][0]
        i += 1
    if not accepts:
        return "reject 1-65535"
    if not rejects:
        return "accept 1-65535"
    a = ",".join(accepts)
    r = ",".join(rejects)
    if len(r) > MAX_SUMMARY_LEN - len("reject") - 1 and len(a) > MAX_SUMMARY_LEN - len("accept") - 1:
        c = MAX_SUMMARY_LEN - len("accept") - 1
        while c >= 0 and a[c] != ",":
            c -= 1
        return "accept " + a[:c]
    if len(r) < len(a):
        return "reject " + r
    return "accept " + a


def classify_summary(s):
    if s is None or s == "":
        return "none"
    if s == NONEXIT:
        return "non-exit"
    if s == NEAR_OPEN:
        return "near-open"
    if s == OUR_POLICY:
        return "OUR_POLICY"
    if s.startswith("accept"):
        return "accept-list"
    return "other-reject-list"


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


def summary_ports(summary):
    """Set of allowed ports (1..65535) implied by a summary."""
    kind, _, plist = summary.partition(" ")
    rng = parse_portlist(plist)
    inside = set()
    for a, b in rng:
        inside.update(range(a, b + 1))
    if kind == "accept":
        return inside
    return set(range(1, 65536)) - inside


def normalize_policy(lines, own_ips):
    """Drop own-IP '/32' lines and tor's private-net lines; return normalized text."""
    out = []
    for line in lines:
        it = parse_policy_line(line)
        if it is not None:
            kind, net, bits, pmin, pmax = it
            if (net, bits) in PRIVATE_NETS_V4:
                continue
            if bits == 32 and str(ipaddress.IPv4Address(net)) in own_ips:
                continue
        out.append(line)
    return "\n".join(out)


# ----------------------------------------------------------------------------- order statistics
def ip_int(ip):
    try:
        return int(ipaddress.IPv4Address(ip))
    except ValueError:
        return -1


def inversions(seq):
    n = len(seq)
    return sum(1 for i in range(n) for j in range(i + 1, n) if seq[i] > seq[j])


def order_stats(hosts):
    """hosts: list of dotted IPv4 strings in event order. Returns dict of sortedness statistics."""
    n = len(hosts)
    pairs = n * (n - 1) // 2
    keys = {
        "str": list(hosts),
        "num": [ip_int(h) for h in hosts],
        "nodot": [h.replace(".", "") for h in hosts],
    }
    res = {"n_hosts": n, "pairs": pairs}
    for k, seq in keys.items():
        res["inv_" + k] = inversions(seq)
        # longest run of consecutive events in ascending order
        best = cur = 1 if n else 0
        for i in range(1, n):
            cur = cur + 1 if seq[i] > seq[i - 1] else 1
            best = max(best, cur)
        res["run_" + k] = best
    return res


def kendall_tau(order_a, order_b):
    """Kendall tau-a between two orderings of (partly) the same items, on the common items."""
    common = [x for x in order_a if x in set(order_b)]
    pos_b = {x: i for i, x in enumerate(order_b)}
    n = len(common)
    if n < 2:
        return None, n
    conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            if pos_b[common[i]] < pos_b[common[j]]:
                conc += 1
            else:
                disc += 1
    return (conc - disc) / (n * (n - 1) / 2), n


def chain_bursts(events, gap_s, key=lambda e: e[0]):
    """events sorted by time (epoch seconds in key); chain into bursts with gaps <= gap_s."""
    bursts, cur, prev = [], [], None
    for e in events:
        t = key(e)
        if prev is not None and t - prev > gap_s:
            bursts.append(cur)
            cur = []
        cur.append(e)
        prev = t
    if cur:
        bursts.append(cur)
    return bursts


if __name__ == "__main__":
    # self-test of the summarizer on a few hand-checked policies
    tests = [
        (["reject *:*"], "reject 1-65535"),
        (["accept *:*"], "accept 1-65535"),
        (["reject 0.0.0.0/8:*", "reject 127.0.0.0/8:*", "reject 1.2.3.4:*", "reject *:25",
          "accept *:*"], "reject 25"),
        (["accept *:80", "accept *:443", "reject *:*"], "accept 80,443"),
        (["reject 1.0.0.0/7:22", "accept *:*"], "accept 1-65535"),  # 2^25 rejects: still <= cutoff
        (["reject 4.0.0.0/6:22", "accept *:*"], "reject 22"),       # 2^26 rejects: above cutoff
    ]
    for lines, exp in tests:
        got = summarize_policy(lines)
        print("OK " if got == exp else "BAD", got, "| expected", exp)
