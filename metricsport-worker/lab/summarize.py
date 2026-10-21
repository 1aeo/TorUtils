"""Summarize "<http code> <seconds>" lines (curl -w) read from stdin.

Usage: ... | python3 summarize.py <label>
"""
import collections, statistics, sys

rows = [line.split() for line in sys.stdin if line.strip()]
codes = collections.Counter(code for code, _ in rows)
ok = sorted(float(t) * 1000 for code, t in rows if code == "200")
out = ", ".join("%s x%d" % kv for kv in sorted(codes.items()))
if ok:
    out += " | median %.2f ms, max %.2f ms" % (statistics.median(ok), ok[-1])
print("%s: %s" % (sys.argv[1], out))
