#!/usr/bin/env python3
"""Closed-lab ticket-41339 HSDir-flood measurement harness (x86, extended).

All activity is loopback-only inside the private chutney net.  "Load" is a
high rate of ordinary, well-formed HSDir descriptor requests (HSFETCH) issued
through the control ports of nodes we own.  No exploit, no malformed cells, no
targeting of the real network.

Measures, at one target HSDir, per cell:
  - requests received (BEGIN_DIR), reused-circuit counter, 0002 refusal
    counter, dir bytes, circuits created/closed, onionskins, CPU% and RSS;
  - the load client's own success rate; a stock (legitimate) client's
    HS-descriptor success rate + latency throughout;
  - network-wide onionskins processed and circuits created across ALL relays
    (to show where cost moves when the attacker adapts to one-per-circuit).

Node identities are DISCOVERED from the nodes dir (robust to flavor size):
metrics port = 19100 + nodenum ; control port = 8000 + nodenum.
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


def discover(nodes_dir):
    """Return (relays, hs, stock_client) nicks discovered from the nodes dir.
    relays = plain relays (tag 'r'); hs = onion services (tag 'h');
    stock_client = first client (tag 'c')."""
    def nicks(tag):
        out = []
        for p in sorted(glob.glob("%s/[0-9]*%s" % (nodes_dir, tag))):
            b = os.path.basename(p)
            if re.fullmatch(r"\d+%s" % tag, b):
                out.append(b)
        return out
    relays = nicks("r")
    hs = nicks("h")
    clients = nicks("c")
    if not relays or not hs or not clients:
        raise SystemExit("discover: relays=%s hs=%s clients=%s" % (relays, hs, clients))
    return relays, hs, clients[0]


def nodenum(nick):
    return int(re.match(r"(\d+)", nick).group(1))


def ctlport(nick):
    return 8000 + nodenum(nick)


def mport(nick):
    return 19100 + nodenum(nick)


def fpr(nodes_dir, nick):
    return open("%s/%s/fingerprint" % (nodes_dir, nick)).read().split()[1]


def onion(nodes_dir, nick):
    hn = glob.glob("%s/%s/**/hostname" % (nodes_dir, nick), recursive=True)
    return open(hn[0]).read().strip().replace(".onion", "")


def pid_of(nodes_dir, nick):
    return int(open("%s/%s/pid" % (nodes_dir, nick)).read().strip())


def proc_cpu_ticks(pid):
    f = open("/proc/%d/stat" % pid).read().split()
    return int(f[13]) + int(f[14])  # utime + stime


def proc_rss_kb(pid):
    for line in open("/proc/%d/status" % pid):
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    return None


HZ = os.sysconf("SC_CLK_TCK")


def choose_target(nodes_dir, stock_ctl_port, stock_cookie, relays=None, hs=None):
    """Return (nick, fpr, onion) for a relay that currently serves an onion
    (is a responsible HSDir this period). Re-probed per cell because the HSDir
    hashring rotates with the consensus."""
    if relays is None or hs is None:
        relays, hs, _ = discover(nodes_dir)
    onions = {n: onion(nodes_dir, n) for n in hs}
    for rn in relays:
        f = fpr(nodes_dir, rn)
        for h, oaddr in onions.items():
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
    from the SAME flooded target HSDir, to show legitimate access is preserved.
    HSFETCH ... SERVER=<fpr> always does a real network fetch (no client-cache
    short-circuit). Records success rate + latency."""
    def __init__(self, ctl_port, cookie, legit_onion, tgt_fpr, interval=1.0):
        super().__init__(daemon=True)
        self.ctl_port, self.cookie = ctl_port, cookie
        self.onion, self.tgt_fpr, self.interval = legit_onion, tgt_fpr, interval
        self.stop_flag = False
        self.attempts = self.ok = 0
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
    """Fetch load: one HSFETCH per fresh circuit (stock isolation). Also the
    'adapted' and 'one-hop' pattern (differ only in the load-client binary)."""
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
    """Reuse load: groups of n descriptor fetches sharing one circuit
    (EVIL_ISO_SESSIONGRP client). The 41339 pattern -- several HSDir requests
    on one circuit. Then rotate to a fresh circuit for the next group."""
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
        fired = 0
        for _ in range(n):
            if time.time() >= end:
                break
            c.cmd(cmdstr)
            issued += 1
            fired += 1
        tally(c.collect_events(max(2.0, fired * 0.2)))
    tally(c.collect_events(2))
    c.close()
    result.update(load_issued=issued, load_recv=recv, load_fail=fail, load_groups=groups)


def scrape_network(nodes_dir, relays, tgt_nick):
    """Sum onionskins processed and circuits created across all relays, and
    separately for the non-target relays (where an adapted attacker's CREATE
    load lands). Returns dict of raw counters."""
    net_onion = net_circs = 0
    nontgt_onion = nontgt_circs = 0
    seen = 0
    for rn in relays:
        try:
            m = scrape(mport(rn))
        except Exception:
            continue
        o = m.get("onionskins_ntor_v3") or 0
        cc = m.get("circs_created") or 0
        net_onion += o
        net_circs += cc
        if rn != tgt_nick:
            nontgt_onion += o
            nontgt_circs += cc
        seen += 1
    return dict(net_onionskins=net_onion, net_circs_created=net_circs,
                nontgt_onionskins=nontgt_onion, nontgt_circs_created=nontgt_circs,
                relays_scraped=seen)


def run_cell(cfg):
    """cfg: mode, load, rep, nodes_dir, target(nick,fpr,onion), legit params,
    load client ctl/cookie, duration, [relays]."""
    nodes_dir = cfg["nodes_dir"]
    tgt_nick, tgt_fpr, tgt_onion = cfg["target"]
    relays = cfg.get("relays")
    if relays is None:
        relays, _, _ = discover(nodes_dir)
    mp = mport(tgt_nick)
    tgt_pid = pid_of(nodes_dir, tgt_nick)

    result = dict(mode=cfg["mode"], load=cfg["load"], rep=cfg["rep"],
                  target_nick=tgt_nick, target_fpr=tgt_fpr,
                  flood_onion=tgt_onion, duration_s=cfg["duration"])

    legit = None
    if cfg.get("legit_ctl"):
        legit = LegitProber(cfg["legit_ctl"], cfg["legit_cookie"],
                            cfg["legit_onion"], tgt_fpr)
        legit.start()

    # snapshot (target + network)
    m0 = scrape(mp)
    net0 = scrape_network(nodes_dir, relays, tgt_nick)
    cpu0 = proc_cpu_ticks(tgt_pid)
    t0 = time.time()

    if cfg["load"] == "none":
        time.sleep(cfg["duration"])
    elif cfg["load"].startswith("reuse"):
        n = int(cfg["load"].split("-")[1])
        load_reuse(cfg["load_ctl"], cfg["load_cookie"], tgt_fpr, tgt_onion,
                  cfg["duration"], n, result)
    else:  # fetch / onehop / adapted -> one request per fresh circuit
        load_fetch(cfg["load_ctl"], cfg["load_cookie"], tgt_fpr, tgt_onion,
                  cfg["duration"], result)

    wall = time.time() - t0
    cpu1 = proc_cpu_ticks(tgt_pid)
    rss = proc_rss_kb(tgt_pid)
    m1 = scrape(mp)
    net1 = scrape_network(nodes_dir, relays, tgt_nick)

    if legit:
        legit.stop_flag = True
        legit.join(timeout=20)
        result.update(legit.result())

    def d(k):
        if m1.get(k) is None or m0.get(k) is None:
            return None
        return m1[k] - m0[k]

    def dn(k):
        return net1.get(k, 0) - net0.get(k, 0)

    result.update(
        begin_dir_recv=d("begin_dir"),
        hsdir_circ_reused=d("hsdir_circ_reused"),
        begindir_hsdir_rejected=d("begindir_hsdir_rejected"),
        hsdir_unknown_prev_hop=d("hsdir_unknown_prev_hop"),
        bytes_written=d("bytes_written"),
        bytes_read=d("bytes_read"),
        circs_created=d("circs_created"),
        circs_closed=d("circs_closed"),
        onionskins_ntor_v3=d("onionskins_ntor_v3"),
        net_onionskins=dn("net_onionskins"),
        net_circs_created=dn("net_circs_created"),
        nontgt_onionskins=dn("nontgt_onionskins"),
        nontgt_circs_created=dn("nontgt_circs_created"),
        target_cpu_pct=round(100.0 * (cpu1 - cpu0) / HZ / wall, 2),
        target_rss_mb=round(rss / 1024.0, 1) if rss else None,
        wall_s=round(wall, 1),
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run_cell(json.loads(sys.argv[1])), indent=2))
