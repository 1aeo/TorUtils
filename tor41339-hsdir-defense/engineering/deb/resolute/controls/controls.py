#!/usr/bin/env python3
"""Live-control validation of the 26.04 package in a private chutney net.

Runs inside an Ubuntu 26.04 container with NO network interface (loopback
only); every chutney node runs the packaged /usr/bin/tor. Uses the closed-lab
simulator's helpers (../../../../simulator/scripts). Nothing here can reach
the real Tor network.

At one target HSDir it walks through these phases, each with the same two
loads running at once (a reuse load: groups of N fetches on one circuit; and
a one-hop load from an unpublished relay identity) and a stock client
fetching throughout:

  P0 default         both options auto (count-only)
  P1 explicit off    both =0
  P2 0002 on         HSDirOneRequestPerCircuit=1, HSDirRefuseUnknownPrevHop=0
  P3 0002 off live   both =0
  P4 0001 on         HSDirRefuseUnknownPrevHop=1, HSDirOneRequestPerCircuit=0
  P5 0001 off live   both =0
  then both back to auto.

For each phase it records the four counter deltas at the target, each load's
issued/received/failed fetches, and the stock client's success rate.
"""
import json
import sys
import threading
import time

sys.path.insert(0, "/sim")
import sim  # noqa: E402
from ctl_lib import Ctl  # noqa: E402
from metrics import scrape  # noqa: E402

NODES = sys.argv[1]
OUT = sys.argv[2]
PHASE_S = int(sys.argv[3]) if len(sys.argv) > 3 else 40
REUSE_N = 5
REUSE_LC = (8020, "/work/lc-reuse/control_auth_cookie")
ONEHOP_LC = (8022, "/work/lc-onehop/control_auth_cookie")
KEYS = ["hsdir_request_total", "hsdir_req_reused", "hsdir_circ_reused",
        "hsdir_unknown_prev_hop"]

PHASES = [
    ("P0 default (auto)", None),
    ("P1 explicit off", "HSDirOneRequestPerCircuit=0 HSDirRefuseUnknownPrevHop=0"),
    ("P2 0002 on", "HSDirOneRequestPerCircuit=1 HSDirRefuseUnknownPrevHop=0"),
    ("P3 0002 off live", "HSDirOneRequestPerCircuit=0 HSDirRefuseUnknownPrevHop=0"),
    ("P4 0001 on", "HSDirOneRequestPerCircuit=0 HSDirRefuseUnknownPrevHop=1"),
    ("P5 0001 off live", "HSDirOneRequestPerCircuit=0 HSDirRefuseUnknownPrevHop=0"),
]


def wait_bootstrap(port, cookie, limit=300):
    end = time.time() + limit
    while time.time() < end:
        try:
            c = Ctl(port, cookie, timeout=10)
            ok, lines = c.cmd("GETINFO status/bootstrap-phase")
            c.close()
            if any("PROGRESS=100" in l for l in lines):
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


def tctl(nodes, nick):
    return Ctl(sim.ctlport(nick), "%s/%s/control_auth_cookie" % (nodes, nick))


def getconf(nodes, nick):
    c = tctl(nodes, nick)
    ok, lines = c.cmd("GETCONF HSDirOneRequestPerCircuit HSDirRefuseUnknownPrevHop Sandbox")
    c.close()
    return [l[4:] for l in lines if "=" in l]


def counters(nick):
    m = scrape(sim.mport(nick))
    return {k: m.get(k) for k in KEYS}


def main():
    relays, hs, stock = sim.discover(NODES)
    stock_ck = "%s/%s/control_auth_cookie" % (NODES, stock)
    for port, ck in (REUSE_LC, ONEHOP_LC):
        if not wait_bootstrap(port, ck):
            raise SystemExit("load client on %d did not bootstrap" % port)
    tnick, tfpr, toni = sim.choose_target(NODES, sim.ctlport(stock), stock_ck, relays, hs)
    print("target HSDir %s serves onion %s..." % (tnick, toni[:8]), flush=True)
    result = {"target": tnick, "phase_seconds": PHASE_S, "reuse_n": REUSE_N,
              "target_pid": sim.pid_of(NODES, tnick), "phases": []}

    for name, setconf in PHASES:
        if setconf:
            c = tctl(NODES, tnick)
            ok, lines = c.cmd("SETCONF " + setconf)
            c.close()
            if not ok:
                raise SystemExit("SETCONF failed: %s" % lines)
        conf = getconf(NODES, tnick)
        before = counters(tnick)
        prober = sim.LegitProber(sim.ctlport(stock), stock_ck, toni, tfpr, interval=1.0)
        reuse, onehop = {}, {}
        th = [threading.Thread(target=sim.load_reuse,
                               args=(REUSE_LC[0], REUSE_LC[1], tfpr, toni, PHASE_S, REUSE_N, reuse)),
              threading.Thread(target=sim.load_fetch,
                               args=(ONEHOP_LC[0], ONEHOP_LC[1], tfpr, toni, PHASE_S, onehop))]
        prober.start()
        for t in th:
            t.start()
        for t in th:
            t.join()
        prober.stop_flag = True
        prober.join(30)
        time.sleep(3)
        after = counters(tnick)
        delta = {k: (after[k] - before[k]) if None not in (after[k], before[k]) else None for k in KEYS}
        row = {"phase": name, "setconf": setconf or "(none: defaults)", "getconf": conf,
               "counter_delta": delta, "reuse_load": reuse, "onehop_load": onehop,
               "legit": prober.result(),
               "target_pid_unchanged": sim.pid_of(NODES, tnick) == result["target_pid"]}
        result["phases"].append(row)
        print(json.dumps(row), flush=True)

    c = tctl(NODES, tnick)
    c.cmd("SETCONF HSDirOneRequestPerCircuit=auto HSDirRefuseUnknownPrevHop=auto")
    c.close()
    result["final_getconf"] = getconf(NODES, tnick)
    result["target_status"] = open("/proc/%d/status" % result["target_pid"]).read()
    json.dump(result, open(OUT, "w"), indent=1)
    print("final:", result["final_getconf"], flush=True)


if __name__ == "__main__":
    main()
