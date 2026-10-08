"""email_review_history.py - independent re-scan of the downloaded CollecTor history archives.

Used to re-check the reply draft's claim that neither attacker policy summary (OUR_POLICY,
near-open) appears before 2026-10-01, and the descriptor / consensus counts it quotes.

Usage:  python3 -I scripts/email_review_history.py ARCHIVE.tar.xz OUT_PREFIX

For a consensus archive: counts consensuses ("network-status-version 3" lines), r lines, and
p lines equal to either attacker summary.  For a server-descriptor archive: splits the stream
into descriptors ("router " .. "router-signature"), computes each descriptor's SHA-1 digest
(the same bytes tor hashes), summarizes every distinct IPv4 policy with
common.summarize_policy and counts attacker summaries.  Digests of descriptors published
before 2026-10-01 are written to OUT_PREFIX.digests (hex, one per line) for de-duplication.
The tar stream is read line by line, without extracting files to disk.
Standard library only.
"""
import hashlib
import lzma
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ATT = {common.NEAR_OPEN: "near-open", common.OUR_POLICY: "OUR_POLICY"}


def scan_consensus(path, out):
    n_cons = n_r = 0
    hits = {"near-open": 0, "OUR_POLICY": 0}
    with lzma.open(path, "rb") as f:
        for line in f:
            if line.startswith(b"r "):
                n_r += 1
            elif line.startswith(b"p "):
                s = line[2:].rstrip(b"\n").decode("ascii", "replace")
                k = ATT.get(s)
                if k:
                    hits[k] += 1
            elif b"network-status-version 3" in line and line.rstrip(b"\n").endswith(b"network-status-version 3"):
                n_cons += 1
    with open(out + ".txt", "w") as o:
        o.write("%s consensuses=%d r_lines=%d hits=%s\n" % (os.path.basename(path), n_cons, n_r, hits))


def scan_desc(path, out):
    n = n_before = 0
    cache = {}
    hits = {"near-open": 0, "OUR_POLICY": 0}
    pub_min = pub_max = None
    cur = None
    pol = []
    pub = None
    dig_f = open(out + ".digests", "w")
    with lzma.open(path, "rb") as f:
        for line in f:
            if line.startswith(b"router ") and not line.startswith(b"router-"):
                # tar header garbage can precede "router " only on the same line; take from "router "
                cur = [line[line.index(b"router "):]]
                pol = []
                pub = None
                continue
            if cur is None:
                continue
            cur.append(line)
            if line.startswith(b"accept ") or line.startswith(b"reject "):
                pol.append(line.rstrip(b"\n").decode("ascii", "replace"))
            elif line.startswith(b"published "):
                pub = line[10:29].decode()
            elif line.startswith(b"router-signature"):
                dg = hashlib.sha1(b"".join(cur)).hexdigest().upper()
                n += 1
                key = "\n".join(pol)
                s = cache.get(key)
                if s is None:
                    s = common.summarize_policy(pol)
                    cache[key] = s
                k = ATT.get(s)
                if k:
                    hits[k] += 1
                if pub:
                    pub_min = pub if pub_min is None or pub < pub_min else pub_min
                    pub_max = pub if pub_max is None or pub > pub_max else pub_max
                    if pub < "2026-10-01 00:00:00":
                        n_before += 1
                        dig_f.write(dg + "\n")
                cur = None
    dig_f.close()
    with open(out + ".txt", "w") as o:
        o.write("%s descriptors=%d before_oct1=%d distinct_policies=%d published=%s..%s hits=%s\n"
                % (os.path.basename(path), n, n_before, len(cache), pub_min, pub_max, hits))


def main():
    path, out = sys.argv[1], sys.argv[2]
    if "consensus" in os.path.basename(path):
        scan_consensus(path, out)
    else:
        scan_desc(path, out)


if __name__ == "__main__":
    main()
