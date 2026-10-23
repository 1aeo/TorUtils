#!/usr/bin/env python3
"""Summarize each ci-driver.sh cell (patched vs unpatched) and flag regressions.
A regression = an item that passes unpatched but fails patched.
Usage: ci-diff.py <logdir> > table.md"""
import os, re, sys

D = sys.argv[1]
CELLS = ["minimal", "hardened", "distcheck", "disable-relay", "disable-dirauth", "gpl",
         "nss", "docs", "tracing", "integration"]
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def parse(path):
    if not os.path.exists(path):
        return None
    txt = ANSI.sub("", open(path, errors="replace").read())
    r = {}
    r["fatal"] = ("FATAL ERROR" in txt) or bool(re.search(r"^ERROR: command '.*' has failed", txt, re.M))
    r["fails"] = sorted(set(re.findall(r"^FAIL: (\S+)", txt, re.M)))
    r["chutney"] = {m.group(2): m.group(1) for m in
                    re.finditer(r"^(PASS|FAIL|SKIP|ERROR) ([a-z0-9+.-]+) \(exit status", txt, re.M)}
    r["stem_ran"] = "run_tests.py" in txt
    r["stem_failed"] = bool(re.search(r"^ERROR: command 'timelimit[^\n]*run_tests\.py[^\n]*' has failed", txt, re.M))
    r["distcheck_ok"] = bool(re.search(r"archives ready for distribution", txt))
    r["build_errors"] = len(re.findall(r"error:", txt)) if "ERROR: command 'make" in txt and "all' has failed" in txt else 0
    r["unit_failed_cases"] = sorted(set(re.findall(r"\[([a-z0-9_]+) FAILED\]", txt)))
    r["practracker_only"] = r["fails"] == ["scripts/maint/practracker/test_practracker.sh"]
    return r


def items(r):
    """Set of (kind, name) -> 'pass'/'fail' for comparison."""
    out = {}
    if r is None:
        return out
    for f in r["fails"]:
        out[("test", f)] = "fail"
    for c in r["unit_failed_cases"]:
        out[("unit-case", c)] = "fail"
    for k, v in r["chutney"].items():
        out[("chutney", k)] = v.lower()
    if r["stem_ran"]:
        out[("stem", "integ")] = "fail" if r["stem_failed"] else "pass"
    return out


print("| Cell | Unpatched | Patched | Regression? |")
print("|---|---|---|---|")
regressions = []
for cell in CELLS:
    u = parse(os.path.join(D, f"unpatched-{cell}.log"))
    p = parse(os.path.join(D, f"patched-{cell}.log"))
    def desc(r):
        if r is None:
            return "not run"
        bits = []
        if not r["fatal"]:
            bits.append("green")
        if r["fails"]:
            bits.append("FAIL: " + ", ".join(os.path.basename(f) for f in r["fails"]))
        if r["unit_failed_cases"]:
            bits.append("failed cases: " + ", ".join(r["unit_failed_cases"]))
        if r["chutney"]:
            ok = sorted(k for k, v in r["chutney"].items() if v == "PASS")
            bad = sorted(k for k, v in r["chutney"].items() if v != "PASS")
            bits.append(f"chutney PASS {len(ok)} ({', '.join(ok)}); FAIL {len(bad)} ({', '.join(bad)})")
        if r["stem_failed"]:
            bits.append("stem: tor failed to start (cannot bind [::]; no IPv6 in container)")
        return "; ".join(bits) if bits else "green"
    iu, ip = items(u), items(p)
    reg = sorted(k for k, v in ip.items() if v == "fail" and iu.get(k, "pass") != "fail" and u is not None)
    if reg:
        regressions.append((cell, reg))
    print(f"| {cell} | {desc(u)} | {desc(p)} | {'**YES: ' + ', '.join(n for _, n in reg) + '**' if reg else 'no'} |")
print()
print("Regressions (pass unpatched, fail patched):", "none" if not regressions else regressions)
