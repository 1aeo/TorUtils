#!/usr/bin/env python3
"""Closed-lab ticket-41339 HSDir-flood measurement harness.

All activity is loopback-only inside the private chutney net.  "Load" is a
high rate of ordinary, well-formed HSDir descriptor requests (HSFETCH) issued
through the control ports of nodes we own.  No exploit, no malformed cells, no
targeting of the real network.

Measures, at one target HSDir, per cell:
  - requests received (BEGIN_DIR), reused-circuit counter, dir bytes,
    circuits created/closed, onionskins, target CPU% and RSS;
  - the attacking load client's own success rate + latency;
  - a stock (legitimate) client's HS-descriptor success rate + latency,
    sampled throughout, to show the defense preserves legitimate access.
"""
import glob
import json
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ctl_lib import Ctl
from metrics import scrape

RELAYS = ["004r", "005r", "006r", "007r", "008r"]
HS = ["011h", "012h", "013h"]
# nodenum -> metrics port is 19100 + nodenum ; control port is 8000 + nodenum
RELAY_NODENUM = {"004r": 4, "005r": 5, "006r": 6, "007r": 7, "008r": 8}


def fpr(nodes_dir, nick):
    return open("%s/%s/fingerprint" % (nodes_dir, nick)).read().split()[1]


def onion(nodes_dir, nick):
    hn = glob.glob("%s/%s/**/hostname" % (nodes_dir, nick), recursive=True)
    return open(hn[0]).read().strip().replace(".onion", "")


def pid_of(nodes_dir, nick):
    p = "%s/%s/pid" % (nodes_dir, nick)
    return int(open(p).read().strip())


def proc_cpu_ticks(pid):
    f = open("/proc/%d/stat" % pid).read().split()
    # fields 14 (utime) and 15 (stime), 1-indexed after comm
    return int(f[13]) + int(f[14])


def proc_rss_kb(pid):
    for line in open("/proc/%d/status" % pid):
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    return None


HZ = os.sysconf("SC_CLK_TCK")


def choose_target(nodes_dir, stock_ctl_port, stock_cookie):
    """Return (nick, fpr, onion) for a relay that currently serves an onion
    (is a responsible HSDir this time period).  Re-probed per cell because the
    HSDir hashring rotates with the consensus."""
    onions = {n: onion(nodes_dir, n) for n in HS}
    for rn in RELAYS:
        f = fpr(nodes_dir, rn)
        for hs, oaddr in onions.items():
            c = Ctl(stock_ctl_port, stock_cookie)
            c.setevents("HS_DESC")
            c.cmd("HSFETCH %s SERVER=$%s" % (oaddr, f))
            evs = c.collect_events(10, match="HS_DESC RECEIVED " + oaddr)
            ok = any(("HS_DESC RECEIVED " + oaddr) in l for _, l in evs)
            c.close()
            if ok:
                return rn, f, oaddr
    raise SystemExit("no responsible HSDir found this period")


class LegitProber(threading.Thread):
    """Stock client (one request per circuit) repeatedly fetches a descriptor
    from the SAME flooded target HSDir, to show a legitimate user's access to
    the flooded HSDir is preserved.  HSFETCH ... SERVER=<fpr> always does a
    real network fetch (no client-cache short-circuit), so every probe is a
    genuine request.  Records success rate + latency."""
    def __init__(self, ctl_port, cookie, legit_onion, tgt_fpr, interval=1.0):
        super().__init__(daemon=True)
        self.ctl_port, self.cookie = ctl_port, cookie
        self.onion, self.tgt_fpr, self.interval = legit_onion, tgt_fpr, interval
        self.stop_flag = False
        self.attempts = 0
        self.ok = 0
        self.latencies = []

    def run(self):
        while not self.stop_flag:
            t0 = time.time()
            try:
                c = Ctl(self.ctl_port, self.cookie, timeout=20)
                c.setevents("HS_DESC")
                c.cmd("HSFETCH %s SERVER=$%s" % (self.onion, self.tgt_fpr))
                evs = c.collect_events(15, match="HS_DESC RECEIVED " + self.onion)
                got = any(("HS_DESC RECEIVED " + self.onion) in l for _, l in evs)
                c.close()
                self.attempts += 1
                if got:
                    self.ok += 1
                    self.latencies.append(time.time() - t0)
            except Exception:
                self.attempts += 1
            dt = self.interval - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)

    def result(self):
        lat = sorted(self.latencies)
        mean = sum(lat) / len(lat) if lat else None
        p95 = lat[int(len(lat) * 0.95)] if lat else None
        return {
            "legit_attempts": self.attempts,
            "legit_ok": self.ok,
            "legit_success_rate": (self.ok / self.attempts) if self.attempts else None,
            "legit_mean_latency_s": round(mean, 3) if mean else None,
            "legit_p95_latency_s": round(p95, 3) if p95 else None,
        }


def load_fetch(ctl_port, cookie, tgt_fpr, oaddr, duration, result):
    """Fetch load: one HSFETCH per fresh circuit (stock isolation)."""
    c = Ctl(ctl_port, cookie, timeout=20)
    c.setevents("HS_DESC")
    issued = recv = fail = 0
    end = time.time() + duration
    while time.time() < end:
        c.cmd("HSFETCH %s SERVER=$%s" % (oaddr, tgt_fpr))
        issued += 1
        evs = c.collect_events(2.0)
        for _, l in evs:
            if "HS_DESC RECEIVED " + oaddr in l:
                recv += 1
            elif "HS_DESC FAILED " + oaddr in l:
                fail += 1
    c.collect_events(2)
    c.close()
    result.update(load_issued=issued, load_recv=recv, load_fail=fail)


def load_reuse(ctl_port, cookie, tgt_fpr, oaddr, duration, n, result):
    """Reuse load: groups of n descriptor fetches that share one circuit
    (EVIL_ISO_SESSIONGRP client).  Per group: one establishing fetch (waited,
    so its circuit is open), then n-1 fetches fired back-to-back that reuse
    that open circuit.  This is the 41339 pattern -- several HSDir requests on
    one circuit.  Then rotate to a fresh circuit for the next group."""
    c = Ctl(ctl_port, cookie, timeout=20)
    c.setevents("HS_DESC")
    issued = recv = fail = groups = 0
    end = time.time() + duration
    cmdstr = "HSFETCH %s SERVER=$%s" % (oaddr, tgt_fpr)

    def tally(evs):
        nonlocal recv, fail
        for _, l in evs:
            if "HS_DESC RECEIVED " + oaddr in l:
                recv += 1
            elif "HS_DESC FAILED " + oaddr in l:
                fail += 1

    while time.time() < end:
        groups += 1
        # Fire n fetches back-to-back (wait only for each 250 OK, no event
        # drain between) so they pile onto one in-flight circuit; the EVIL_ISO
        # client lets the anonymized dir requests share that circuit.
        fired = 0
        for _ in range(n):
            if time.time() >= end:
                break
            c.cmd(cmdstr)
            issued += 1
            fired += 1
        # drain all responses for the group (RESOURCELIMIT-closed -> FAILED)
        tally(c.collect_events(max(2.0, fired * 0.2)))
    tally(c.collect_events(2))
    c.close()
    result.update(load_issued=issued, load_recv=recv, load_fail=fail, load_groups=groups)


def run_cell(cfg):
    """cfg: dict with mode, load, rep, nodes_dir, target(nick,fpr,onion),
    legit params, load client ctl/cookie, duration."""
    nodes_dir = cfg["nodes_dir"]
    tgt_nick, tgt_fpr, tgt_onion = cfg["target"]
    mp = 19100 + RELAY_NODENUM[tgt_nick]
    tgt_pid = pid_of(nodes_dir, tgt_nick)

    result = dict(mode=cfg["mode"], load=cfg["load"], rep=cfg["rep"],
                  target_nick=tgt_nick, target_fpr=tgt_fpr,
                  flood_onion=tgt_onion, duration_s=cfg["duration"])

    # start legit prober (stock client, different onion if possible)
    legit = None
    if cfg.get("legit_ctl"):
        legit = LegitProber(cfg["legit_ctl"], cfg["legit_cookie"],
                            cfg["legit_onion"], tgt_fpr)
        legit.start()

    # snapshot
    m0 = scrape(mp)
    cpu0 = proc_cpu_ticks(tgt_pid)
    t0 = time.time()

    # run the load
    if cfg["load"] == "none":
        time.sleep(cfg["duration"])
    elif cfg["load"] == "fetch":
        load_fetch(cfg["load_ctl"], cfg["load_cookie"], tgt_fpr, tgt_onion,
                  cfg["duration"], result)
    elif cfg["load"].startswith("reuse"):
        n = int(cfg["load"].split("-")[1])
        load_reuse(cfg["load_ctl"], cfg["load_cookie"], tgt_fpr, tgt_onion,
                  cfg["duration"], n, result)

    wall = time.time() - t0
    cpu1 = proc_cpu_ticks(tgt_pid)
    rss = proc_rss_kb(tgt_pid)
    m1 = scrape(mp)

    if legit:
        legit.stop_flag = True
        legit.join(timeout=20)
        result.update(legit.result())

    def d(k):
        if m1.get(k) is None or m0.get(k) is None:
            return None
        return m1[k] - m0[k]

    result.update(
        begin_dir_recv=d("begin_dir"),
        hsdir_circ_reused=d("hsdir_circ_reused"),
        hsdir_unknown_prev_hop=d("hsdir_unknown_prev_hop"),
        bytes_written=d("bytes_written"),
        bytes_read=d("bytes_read"),
        circs_created=d("circs_created"),
        circs_closed=d("circs_closed"),
        onionskins_ntor_v3=d("onionskins_ntor_v3"),
        target_cpu_pct=round(100.0 * (cpu1 - cpu0) / HZ / wall, 2),
        target_rss_mb=round(rss / 1024.0, 1) if rss else None,
        wall_s=round(wall, 1),
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run_cell(json.loads(sys.argv[1])), indent=2))
