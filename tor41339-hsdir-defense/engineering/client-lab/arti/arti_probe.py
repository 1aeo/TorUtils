#!/usr/bin/env python3
"""Arti onion-service client probes for the private chutney lab.

Runs inside a --network none lab container next to a chutney net and an
Arti client (see in-lab-arti.sh). Loopback only.

Experiments (each selectable with --only):
  proof      fetch http://<onion>:5858/ through Arti's SOCKS port.
  isolation  repeat fetches with the same / different SOCKS credentials and
             count the onion-service descriptor GETs the HSDirs answered,
             to show whether a new SOCKS isolation forces a new fetch.
  retry      make some or all of the onion's responsible HSDirs refuse
             fetches (HSDirDescriptorFetchLimit=1 with rate 1, burst 1 and a
             background C tor client that keeps those buckets empty), then
             record each Arti descriptor-fetch attempt: which HSDir, how it
             ended, and the time between attempts. Modes: retry-partial,
             retry-all (fresh isolation per request), retry-sameiso (one
             isolation reused after each failure).
  prober     ArtiProber for --prober-duration s: one fetch per
             --prober-interval s, each with a fresh SOCKS isolation.

Counters come from each relay's MetricsPort: tor_relay_hsdir_get_total
{action=success|not_found|single_hop|refused}. Arti attempts come from its
log file (tor_hsclient at trace level).
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

sys.path.insert(0, "/sim")
from ctl_lib import Ctl  # noqa: E402

HS_VIRTPORT = 5858


# ---------------------------------------------------------------- discovery
def torrc_opts(path):
    out = {}
    for line in open(path):
        line = line.split("#", 1)[0].strip()
        if line:
            k, _, v = line.partition(" ")
            out.setdefault(k.lower(), []).append(v.strip())
    return out


def discover(nodes_dir):
    nodes = []
    for d in sorted(glob.glob(os.path.join(nodes_dir, "[0-9]*"))):
        if not re.fullmatch(r"\d+[a-z]+", os.path.basename(d)):
            continue
        o = torrc_opts(os.path.join(d, "torrc"))
        n = {"tag": os.path.basename(d), "dir": d,
             "nick": o.get("nickname", [os.path.basename(d)])[0]}
        if "controlport" in o:
            n["ctl"] = int(o["controlport"][0].split(":")[-1])
        if "metricsport" in o:
            n["metrics"] = int(o["metricsport"][0].split(":")[-1])
        orp = [v for v in o.get("orport", []) if v not in ("0",)]
        n["relay"] = bool(orp)
        fp = os.path.join(d, "fingerprint")
        if os.path.exists(fp):
            n["fp"] = open(fp).read().split()[1]
        fp_ed = os.path.join(d, "fingerprint-ed25519")
        if os.path.exists(fp_ed):
            n["ed"] = open(fp_ed).read().split()[1]
        hn = glob.glob(os.path.join(d, "**", "hostname"), recursive=True)
        if hn:
            n["onion"] = open(hn[0]).read().strip().replace(".onion", "")
        n["client"] = n["tag"].endswith("c")
        nodes.append(n)
    return nodes


def ctl(n):
    return Ctl(n["ctl"], os.path.join(n["dir"], "control_auth_cookie"))


# ---------------------------------------------------------------- metrics
MPAT = re.compile(r'^(tor_relay_hsdir_get_total|tor_relay_hsdir_fetch_total|'
                  r'tor_relay_dos_total|tor_relay_streams_total)'
                  r'\{([^}]*)\}\s+([0-9.e+]+)$', re.M)


def scrape(n):
    try:
        txt = urllib.request.urlopen("http://127.0.0.1:%d/metrics" % n["metrics"],
                                     timeout=5).read().decode()
    except Exception:
        return {}
    # +tor41339.7 calls tor_relay_hsdir_get_total tor_relay_hsdir_fetch_total.
    return {"%s{%s}" % (m.group(1).replace("_hsdir_fetch_total",
                                           "_hsdir_get_total"), m.group(2)):
            int(float(m.group(3))) for m in MPAT.finditer(txt)}


def scrape_all(relays):
    return {n["nick"]: scrape(n) for n in relays}


def delta(before, after, keep=("tor_relay_hsdir_get_total",
                               'tor_relay_dos_total{type="hsdir_fetch')):
    per, tot = {}, {}
    for nick, a in after.items():
        b = before.get(nick, {})
        d = {k: v - b.get(k, 0) for k, v in a.items()
             if v - b.get(k, 0) and k.startswith(keep)}
        if d:
            per[nick] = d
        for k, v in d.items():
            tot[k] = tot.get(k, 0) + v
    return tot, per


# ---------------------------------------------------------------- arti log
class ArtiLog:
    def __init__(self, path):
        self.path = path
        self.off = os.path.getsize(path) if os.path.exists(path) else 0

    def mark(self):
        self.off = os.path.getsize(self.path)

    def since(self):
        with open(self.path, "rb") as f:
            f.seek(self.off)
            data = f.read().decode(errors="replace")
        return data.splitlines()


TS = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)Z")


def ts_of(line):
    m = TS.match(line)
    if not m:
        return None
    t = time.strptime(m.group(1).split(".")[0], "%Y-%m-%dT%H:%M:%S")
    frac = float("0." + m.group(1).split(".")[1]) if "." in m.group(1) else 0
    return time.mktime(t) - time.timezone + frac


def parse_attempts(lines, onion):
    """Pull Arti's descriptor-fetch events for one onion out of log lines."""
    ev = []
    for l in lines:
        if onion not in l and "hsdir" not in l.lower():
            continue
        kind = None
        if "HS desc fetch for" in l:
            kind = "start"
        elif "hsdir for" in l and "trying" in l:
            kind = "attempt"
        elif "failed hsdir desc fetch" in l or \
                "Suspicious failure while downloading hsdesc" in l:
            kind = "attempt_failed"
        elif "all hsdirs are rate-limited" in l:
            kind = "all_rate_limited"
        elif "HS connection failure" in l:
            kind = "connection_failed"
        if kind:
            m = re.search(r"trying ([A-Za-z0-9+/=]{43})/\$?([0-9A-Fa-f]{40})", l)
            ev.append({"t": ts_of(l), "kind": kind,
                       "hsdir_ed": m.group(1) if m else None,
                       "hsdir_rsa": m.group(2).upper() if m else None,
                       "line": re.sub(r"\s+", " ", l)[:600]})
    return ev


# ---------------------------------------------------------------- client
def fetch(socks, onion, user=None, pw="x", max_time=120):
    proxy = "socks5h://%s%s" % (("%s:%s@" % (user, pw)) if user else "", socks)
    t0 = time.time()
    p = subprocess.run(["curl", "-sS", "-x", proxy, "--max-time", str(max_time),
                        "-o", "-", "-w", "\n%{http_code}",
                        "http://%s.onion:%d/" % (onion, HS_VIRTPORT)],
                       capture_output=True, text=True)
    out = p.stdout.rsplit("\n", 1)
    return {"user": user, "rc": p.returncode,
            "http": out[-1] if out else "", "body": out[0].strip()[:80],
            "stderr": p.stderr.strip()[:300], "secs": round(time.time() - t0, 3)}


# ---------------------------------------------------------------- C tor helpers
def responsible_hsdirs(client, relays, onion, timeout=25):
    """Ask the C tor client to fetch the descriptor from every relay; the
    ones that return it are the responsible HSDirs right now."""
    c = ctl(client)
    c.setevents("HS_DESC")
    c.cmd("HSFETCH %s %s" % (onion, " ".join("SERVER=$" + n["fp"] for n in relays)))
    got, failed = set(), set()
    end = time.time() + timeout
    while time.time() < end and len(got) + len(failed) < len(relays):
        for _, l in c.collect_events(1.0):
            m = re.search(r"HS_DESC (RECEIVED|FAILED) %s \S+ \$?([0-9A-F]{40})" % onion, l)
            if m:
                (got if m.group(1) == "RECEIVED" else failed).add(m.group(2))
    c.close()
    return [n for n in relays if n["fp"] in got]


def setconf(n, conf):
    c = ctl(n)
    ok, lines = c.cmd("SETCONF " + conf)
    c.close()
    if not ok:
        raise SystemExit("SETCONF on %s failed: %s" % (n["nick"], lines))


class Drainer(threading.Thread):
    """Keeps the per-descriptor fetch buckets of the given HSDirs empty by
    fetching the descriptor from them via a C tor client every `period` s."""
    def __init__(self, client, hsdirs, onion, period):
        super().__init__(daemon=True)
        self.client, self.hsdirs, self.onion, self.period = client, hsdirs, onion, period
        self.stop_flag = False
        self.issued = self.recv = self.fail = 0

    def run(self):
        c = ctl(self.client)
        c.setevents("HS_DESC")
        cmd = "HSFETCH %s %s" % (self.onion,
                                 " ".join("SERVER=$" + n["fp"] for n in self.hsdirs))
        while not self.stop_flag:
            t0 = time.time()
            c.cmd(cmd)
            self.issued += len(self.hsdirs)
            for _, l in c.collect_events(max(0.0, self.period - (time.time() - t0))):
                if "HS_DESC RECEIVED " + self.onion in l:
                    self.recv += 1
                elif "HS_DESC FAILED " + self.onion in l:
                    self.fail += 1
        c.close()


class ArtiProber(threading.Thread):
    """Legitimate Arti client load for a measurement phase: every `interval`
    seconds, fetch http://<onion>:5858/ with a FRESH SOCKS isolation, which
    makes Arti fetch the descriptor again (its descriptor cache is per
    isolation). Records success, latency and Arti's HSDir attempts per
    request. Import it from a phase driver, or use --only prober."""
    def __init__(self, socks, onion, log, interval=1.0, max_time=120, tag="probe"):
        super().__init__(daemon=True)
        self.socks, self.onion, self.log = socks, onion, log
        self.interval, self.max_time, self.tag = interval, max_time, tag
        self.stop_flag = False
        self.rows = []

    def run(self):
        k = 0
        while not self.stop_flag:
            t0 = time.time()
            off = os.path.getsize(self.log.path)
            r = fetch(self.socks, self.onion, user="%s-%d-%d" % (self.tag, k, int(t0)),
                      max_time=self.max_time)
            with open(self.log.path, "rb") as f:
                f.seek(off)
                lines = f.read().decode(errors="replace").splitlines()
            ev = parse_attempts(lines, self.onion)
            self.rows.append({"t": round(t0, 3), "ok": r["rc"] == 0 and r["http"] == "200",
                              "secs": r["secs"],
                              "attempts": sum(1 for e in ev if e["kind"] == "attempt"),
                              "failed_attempts": sum(1 for e in ev
                                                     if e["kind"] == "attempt_failed")})
            k += 1
            dt = self.interval - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)

    def result(self):
        n = len(self.rows)
        ok = [r for r in self.rows if r["ok"]]
        lat = sorted(r["secs"] for r in ok)
        hist = {}
        for r in self.rows:
            hist[r["attempts"]] = hist.get(r["attempts"], 0) + 1
        return {"arti_requests": n, "arti_ok": len(ok),
                "arti_success_rate": round(len(ok) / n, 4) if n else None,
                "arti_mean_latency_s": round(sum(lat) / len(lat), 3) if lat else None,
                "arti_p95_latency_s": lat[int(len(lat) * 0.95)] if lat else None,
                "arti_desc_attempts_hist": {str(k): v for k, v in sorted(hist.items())},
                "arti_failed_desc_attempts": sum(r["failed_attempts"] for r in self.rows)}


# ---------------------------------------------------------------- experiments
def exp_proof(a, onions, log):
    res = []
    for onion in onions:
        r = None
        for i in range(a.proof_tries):
            log.mark()
            r = fetch(a.socks, onion, user="proof", max_time=a.max_time)
            r["attempts"] = [e for e in parse_attempts(log.since(), onion)
                             if e["kind"] != "start"]
            r["try"] = i + 1
            print("proof %s: rc=%s http=%s body=%r %.1fs (desc attempts %d)"
                  % (onion[:16], r["rc"], r["http"], r["body"], r["secs"],
                     sum(1 for e in r["attempts"] if e["kind"] == "attempt")),
                  flush=True)
            if r["rc"] == 0 and r["http"] == "200":
                break
            time.sleep(5)
        res.append({"onion": onion, **r})
    return res


def exp_isolation(a, relays, onion, log):
    steps = [("A", "first fetch, credentials A"),
             ("A", "same credentials A again"),
             ("B", "new credentials B"),
             (None, "no SOCKS auth"),
             ("A", "credentials A once more"),
             ("C", "new credentials C")]
    out = []
    for user, label in steps:
        before = scrape_all(relays)
        log.mark()
        r = fetch(a.socks, onion, user=user, max_time=a.max_time)
        time.sleep(1.5)
        tot, per = delta(before, scrape_all(relays))
        ev = parse_attempts(log.since(), onion)
        row = {"step": label, "user": user, "rc": r["rc"], "http": r["http"],
               "secs": r["secs"],
               "arti_desc_fetch_started": sum(1 for e in ev if e["kind"] == "start"),
               "arti_desc_attempts": sum(1 for e in ev if e["kind"] == "attempt"),
               "hsdir_get_delta": tot, "per_relay": per}
        print("isolation %-28s rc=%s http=%s arti_attempts=%d relay GET delta=%s"
              % (label, r["rc"], r["http"], row["arti_desc_attempts"], tot), flush=True)
        out.append(row)
    return out


def exp_retry(a, relays, client, onion, log, mode):
    """mode: partial (half the holders refuse), all (every holder refuses,
    fresh SOCKS isolation per request), sameiso (every holder refuses, one
    SOCKS isolation reused for every request)."""
    hsdirs = responsible_hsdirs(client, relays, onion)
    if not hsdirs:
        return {"error": "no responsible HSDirs found"}
    drained = hsdirs if mode != "partial" else hsdirs[:max(1, len(hsdirs) // 2)]
    print("retry[%s]: responsible HSDirs %s; refusing at %s" %
          (mode, [n["nick"] for n in hsdirs], [n["nick"] for n in drained]), flush=True)
    for n in drained:
        setconf(n, "HSDirDescriptorFetchLimit=1 HSDirDescriptorFetchRate=1 "
                   "HSDirDescriptorFetchBurst=1")
    dr = Drainer(client, drained, onion, a.drain_period)
    dr.start()
    time.sleep(3)
    reqs = []
    gen, t_start = 0, int(time.time())
    try:
        for k in range(a.retry_requests):
            before = scrape_all(relays)
            log.mark()
            # sameiso: keep one SOCKS isolation while requests fail, and only
            # move to a new one after a success (its descriptor is cached).
            user = ("retry-sameiso-%d-%d" % (gen, t_start) if mode == "sameiso"
                    else "retry-%s-%d-%d" % (mode, k, int(time.time())))
            r = fetch(a.socks, onion, user=user, max_time=a.max_time)
            if r["rc"] == 0:
                gen += 1
            time.sleep(1.5)
            tot, per = delta(before, scrape_all(relays))
            ev = parse_attempts(log.since(), onion)
            att = [e for e in ev if e["kind"] == "attempt"]
            gaps = [round(att[i + 1]["t"] - att[i]["t"], 3)
                    for i in range(len(att) - 1) if att[i]["t"] and att[i + 1]["t"]]
            nick = {n["fp"]: n["nick"] for n in relays}
            row = {"request": k, "user": user, "rc": r["rc"], "http": r["http"], "secs": r["secs"],
                   "curl_err": r["stderr"],
                   "attempt_hsdirs": [nick.get(e["hsdir_rsa"], e["hsdir_rsa"]) for e in att],
                   "attempt_gaps_s": gaps,
                   "attempt_failures": [e["line"] for e in ev if e["kind"] == "attempt_failed"],
                   "drained": [n["nick"] for n in drained],
                   "hsdir_get_delta": tot, "per_relay": per}
            print("retry[%s] req %d: rc=%s http=%s %.1fs attempts=%s gaps=%s refused=%s"
                  % (mode, k, r["rc"], r["http"], r["secs"], row["attempt_hsdirs"], gaps,
                     tot.get('tor_relay_hsdir_get_total{action="refused"}', 0)), flush=True)
            reqs.append(row)
            time.sleep(a.retry_gap)
    finally:
        dr.stop_flag = True
        dr.join(10)
        for n in drained:
            setconf(n, "HSDirDescriptorFetchLimit=0 HSDirDescriptorFetchRate=5 "
                       "HSDirDescriptorFetchBurst=20")
    return {"mode": mode, "responsible": [n["nick"] for n in hsdirs],
            "drained": [n["nick"] for n in drained],
            "drainer": {"issued": dr.issued, "recv": dr.recv, "fail": dr.fail,
                        "period_s": a.drain_period},
            "requests": reqs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", required=True)
    ap.add_argument("--arti-log", required=True)
    ap.add_argument("--socks", default="127.0.0.1:9400")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="proof,isolation,retry-partial,retry-all,"
                    "retry-sameiso,prober")
    ap.add_argument("--max-time", type=int, default=120)
    ap.add_argument("--proof-tries", type=int, default=6)
    ap.add_argument("--retry-requests", type=int, default=6)
    ap.add_argument("--drain-period", type=float, default=0.25)
    ap.add_argument("--retry-gap", type=float, default=1.0,
                    help="pause between retry-experiment requests (s)")
    ap.add_argument("--prober-duration", type=float, default=30)
    ap.add_argument("--prober-interval", type=float, default=1.0)
    a = ap.parse_args()

    nodes = discover(a.nodes)
    relays = [n for n in nodes if n["relay"] and "metrics" in n]
    onions = [n["onion"] for n in nodes if "onion" in n]
    clients = [n for n in nodes if n["client"] and "ctl" in n]
    log = ArtiLog(a.arti_log)
    only = a.only.split(",")
    res = {"relays": [n["nick"] for n in relays], "onions": onions,
           "arti_version": subprocess.run(["/arti/arti", "--version"], capture_output=True,
                                          text=True).stdout.strip().splitlines()[:1]}
    if "proof" in only:
        res["proof"] = exp_proof(a, onions, log)
    if "isolation" in only:
        res["isolation"] = exp_isolation(a, relays, onions[0], log)
    for i, mode in enumerate(("partial", "all", "sameiso")):
        if "retry-" + mode in only:
            res["retry_" + mode] = exp_retry(a, relays, clients[0],
                                             onions[(1 + i) % len(onions)], log, mode)
    if "prober" in only:
        p = ArtiProber(a.socks, onions[0], log, interval=a.prober_interval,
                       max_time=a.max_time)
        before = scrape_all(relays)
        p.start()
        time.sleep(a.prober_duration)
        p.stop_flag = True
        p.join(a.max_time + 5)
        tot, _ = delta(before, scrape_all(relays))
        res["prober"] = {**p.result(), "hsdir_get_delta": tot}
        print("prober:", json.dumps(res["prober"]), flush=True)
    with open(a.out, "w") as f:
        json.dump(res, f, indent=1)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
