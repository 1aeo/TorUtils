#!/usr/bin/env python3
"""Live-control validation of a packaged tor in a private chutney net.

Runs inside an Ubuntu container with NO network interface (loopback only);
every chutney node runs the packaged /usr/bin/tor. Uses the closed-lab
simulator's helpers (../../../../simulator/scripts). Nothing here can reach
the real Tor network.

It runs these phases, each with the same two loads running at once (a
reuse load: groups of N fetches on one circuit; and a one-hop load from an
unpublished relay identity) and a stock client fetching throughout:

  P0 default          every defense off (auto / 0)
  P1 explicit off     every option set to its off value
  then, for each defense, "on" and then "off live" on the same target:
  0011 reuse          HSDirOneRequestPerCircuit=1
  0011 prev hop       HSDirRefuseUnknownPrevHop=1
  0012                DoSBeginDirLimitEnabled=1 with DoSBeginDirMaxStreams=2
  0013                HSDirDescriptorFetchLimit=1 with rate 1 and burst 2

The HSDir hashring rotates quickly in a test network, so the target (an
HSDir that serves the onion right now) is chosen again before P0 and before
each pair, and reset to the defaults after it.

For each phase it records the deltas of the new MetricsPort series and of
tor_relay_streams_total{type="BEGIN_DIR"} at the target, each load's
issued/received/failed fetches, and the stock client's success rate.
"""
import json
import re
import sys
import threading
import time
import urllib.request

sys.path.insert(0, "/sim")
import sim  # noqa: E402
from ctl_lib import Ctl  # noqa: E402

NODES = sys.argv[1]
OUT = sys.argv[2]
PHASE_S = int(sys.argv[3]) if len(sys.argv) > 3 else 40
REUSE_N = 5
REUSE_LC = (8020, "/work/lc-reuse/control_auth_cookie")
ONEHOP_LC = (8022, "/work/lc-onehop/control_auth_cookie")
SERIES = re.compile(r'^(tor_relay_(?:dos_total|hsdir_get_total|hsdir_post_total|'
                    r'dir_requests_total|dir_responses_total|dir_server_conns|'
                    r'streams_total)\{[^}]*\}) (\d+)$', re.M)
OPTS = ["HSDirOneRequestPerCircuit", "HSDirRefuseUnknownPrevHop",
        "DoSBeginDirLimitEnabled", "DoSBeginDirMaxStreams",
        "HSDirDescriptorFetchLimit", "HSDirDescriptorFetchRate",
        "HSDirDescriptorFetchBurst"]
OFF = ("HSDirOneRequestPerCircuit=0 HSDirRefuseUnknownPrevHop=0 "
       "DoSBeginDirLimitEnabled=0 DoSBeginDirMaxStreams=0 "
       "HSDirDescriptorFetchLimit=0 HSDirDescriptorFetchRate=5 "
       "HSDirDescriptorFetchBurst=20")
DEFAULTS = OFF.replace("Circuit=0", "Circuit=auto").replace(
    "PrevHop=0", "PrevHop=auto").replace("LimitEnabled=0", "LimitEnabled=auto")

PAIRS = [
    ("0011 reuse", "HSDirOneRequestPerCircuit=1"),
    ("0011 prev-hop", "HSDirRefuseUnknownPrevHop=1"),
    ("0012 BEGIN_DIR limit", "DoSBeginDirLimitEnabled=1 DoSBeginDirMaxStreams=2"),
    ("0013 fetch limit", "HSDirDescriptorFetchLimit=1 HSDirDescriptorFetchRate=1 "
                         "HSDirDescriptorFetchBurst=2"),
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
    ok, lines = c.cmd("GETCONF " + " ".join(OPTS) + " Sandbox")
    c.close()
    return [l[4:] for l in lines if "=" in l]


def counters(nick):
    url = "http://127.0.0.1:%d/metrics" % sim.mport(nick)
    txt = urllib.request.urlopen(url, timeout=5).read().decode()
    return {k: int(v) for k, v in SERIES.findall(txt)}


def reconcile(d):
    """Every tunneled BEGIN_DIR stream should land in exactly one bucket."""
    def tot(prefix):
        return sum(v for k, v in d.items() if k.startswith(prefix))
    streams = d.get('tor_relay_streams_total{type="BEGIN_DIR"}', 0)
    buckets = (tot("tor_relay_hsdir_get_total") + tot("tor_relay_hsdir_post_total") +
               tot("tor_relay_dir_requests_total") +
               d.get('tor_relay_dir_server_conns{state="command_wait"}', 0))
    return {"begindir_streams": streams, "buckets": buckets,
            "unbucketed": streams - buckets}


def setconf(nick, conf):
    c = tctl(NODES, nick)
    ok, lines = c.cmd("SETCONF " + conf)
    c.close()
    if not ok:
        raise SystemExit("SETCONF failed: %s" % lines)


def run_phase(target, name, conf, stock, stock_ck):
    tnick, tfpr, toni = target
    if conf:
        setconf(tnick, conf)
    getc = getconf(NODES, tnick)
    pid = sim.pid_of(NODES, tnick)
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
    delta = {k: after.get(k, 0) - before.get(k, 0) for k in after
             if after.get(k, 0) != before.get(k, 0)}
    row = {"phase": name, "target": tnick, "setconf": conf or "(none: defaults)",
           "getconf": getc, "counter_delta": delta, "reconcile": reconcile(delta),
           "reuse_load": reuse, "onehop_load": onehop, "legit": prober.result(),
           "target_pid_unchanged": sim.pid_of(NODES, tnick) == pid}
    print(json.dumps(row), flush=True)
    return row


def main():
    relays, hs, stock = sim.discover(NODES)
    stock_ck = "%s/%s/control_auth_cookie" % (NODES, stock)
    for port, ck in (REUSE_LC, ONEHOP_LC):
        if not wait_bootstrap(port, ck):
            raise SystemExit("load client on %d did not bootstrap" % port)
    result = {"phase_seconds": PHASE_S, "reuse_n": REUSE_N, "phases": []}

    def target():
        t = sim.choose_target(NODES, sim.ctlport(stock), stock_ck, relays, hs)
        print("target HSDir %s serves onion %s..." % (t[0], t[2][:8]), flush=True)
        return t

    t = target()
    result["phases"].append(run_phase(t, "P0 default", None, stock, stock_ck))
    result["phases"].append(run_phase(t, "P1 explicit off", OFF, stock, stock_ck))
    setconf(t[0], DEFAULTS)
    for name, on in PAIRS:
        t = target()
        conf = dict(kv.split("=") for kv in (OFF + " " + on).split())
        result["phases"].append(run_phase(
            t, name + " on", " ".join("%s=%s" % kv for kv in conf.items()),
            stock, stock_ck))
        result["phases"].append(run_phase(t, name + " off live", OFF,
                                          stock, stock_ck))
        setconf(t[0], DEFAULTS)

    result["final_getconf"] = {n: getconf(NODES, n) for n in relays}
    json.dump(result, open(OUT, "w"), indent=1)
    print("final:", result["final_getconf"], flush=True)


if __name__ == "__main__":
    main()
