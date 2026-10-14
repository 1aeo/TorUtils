#!/usr/bin/env python3
"""Off-vs-on analysis with a net-health gate. A rep is INVALID (lab transient,
not a defense effect) if its legit prober got < 30 attempts in the ~60s cell
(healthy cells ~47-64; choked ~5). We report valid-rep medians + how many reps
were dropped per cell, and never silently hide a dropped rep."""
import csv, statistics, sys
rows=list(csv.DictReader(open(sys.argv[1] if len(sys.argv)>1 else "results/results.csv")))
def f(x):
    try: return float(x)
    except: return None
GATE=30
def valid(r):
    la=f(r.get("legit_attempts"))
    # 'none' baseline has no load; gate on legit attempts only
    return la is not None and la>=GATE
groups={}
for r in rows:
    if r.get("error"): continue
    groups.setdefault((r["mode"],r["load"]),[]).append(r)
MODES=["unpatched","patched-observe","patched-0001","patched-0002","patched-both"]
LOADS=["none","fetch","reuse-5","reuse-22","onehop","adapted"]
def med(rs,k):
    v=[f(r.get(k)) for r in rs]; v=[x for x in v if x is not None]
    return statistics.median(v) if v else None
print(f"{'mode':16} {'load':9} {'n_ok/n':6} {'served':7} {'legit':6} {'bytes_w':10} {'begin':6} {'reused':7} {'unkhop':7} {'net_onion':9} {'cpu%':5}")
for m in MODES:
    for ld in LOADS:
        allr=groups.get((m,ld),[])
        if not allr: continue
        ok=[r for r in allr if valid(r)]
        tag=f"{len(ok)}/{len(allr)}"
        if not ok:
            print(f"{m:16} {ld:9} {tag:6}  ALL REPS CHOKED (lab transient) - no valid measurement"); continue
        iss=med(ok,"load_issued"); rcv=med(ok,"load_recv")
        served=(rcv/iss) if (iss and rcv is not None and iss>0) else None
        la=med(ok,"legit_attempts"); lo=med(ok,"legit_ok")
        lr=(lo/la) if (la and lo is not None and la>0) else None
        def s(k,fmt="%.0f"):
            v=med(ok,k); return (fmt%v) if v is not None else "-"
        print(f"{m:16} {ld:9} {tag:6} {('%.2f'%served) if served is not None else '-':>7} "
              f"{('%.3f'%lr) if lr is not None else '-':>6} {s('bytes_written'):>10} {s('begin_dir_recv'):>6} "
              f"{s('hsdir_circ_reused','%.0f'):>7} {s('hsdir_unknown_prev_hop','%.0f'):>7} {s('net_onionskins'):>9} {s('target_cpu_pct','%.2f'):>5}")
# flake accounting
dropped=[(m,ld,len([r for r in rs if not valid(r)]),len(rs)) for (m,ld),rs in groups.items() if any(not valid(r) for r in rs)]
print("\nDropped (choked) reps:", sum(d[2] for d in dropped), "of", sum(len(rs) for rs in groups.values()), "total")
for m,ld,nd,nt in sorted(dropped): print(f"  {m} {ld}: {nd}/{nt} reps choked")
