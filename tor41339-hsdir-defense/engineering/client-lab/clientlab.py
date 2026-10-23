#!/usr/bin/env python3
"""Private-lab onion-service client-reachability harness for ticket 41339.

Runs entirely on loopback inside a --network none container. It measures
end-to-end reachability of onion services from two real, unmodified client
implementations, a stock C tor client and an Arti client, while a load client
pushes HSDirs over their descriptor-fetch limits, across a data-driven list of
phases (phases.json). Defensive measurement only: every process is a chutney
node, the Arti client or a load client we own, and nothing here can reach any
real network.

For each phase it records, for a loaded onion D and a control onion E, and for
each client kind (ctor, arti), both probing at the same time:
  - requests, successes, latency percentiles (curl through the client's SOCKS
    port, one unique SOCKS username per request);
  - every descriptor fetch attempt the client made for the request: which
    HSDir (mapped to its chutney node name), in what order, and how it ended,
    so failover from one HSDir to another is visible.
      ctor: SIGNAL NEWNYM before each request (purges the client's global
            descriptor cache), HS_DESC events on its control port. A fetch
            whose circuit the HSDir closes has a REQUESTED event and no
            RECEIVED/FAILED event ("no_reply").
      arti: a fresh SOCKS isolation per request (Arti keeps descriptors per
            isolation, so each request fetches again), and Arti's own log
            (tor_hsclient at trace level).
  - per-relay deltas of the shedding metrics (tor_relay_dos_total
    hsdir_fetch_*, tor_relay_hsdir_get_total, tor_relay_streams_total
    BEGIN_DIR), the load the HSDirs actually answered, every relay pid.

Fails closed: if a C tor client node or Arti does not bootstrap, or any
fetch in the baseline phase B0 fails, it stops, writes what it has, prints
"RESULT: FAIL: ..." and exits 2. Otherwise it prints "RESULT: PASS".

usage: clientlab.py <nodes_dir> <out.json> [phase_seconds]
env: PHASES (comma list of set and/or phase names, default dry),
     PHASES_FILE, BUDGET (HSDirFetchBudget for the BUDGET token),
     CLIENTS (default "ctor,arti"), ATTEMPT_TIMEOUT (s), NEWNYM_MIN (s),
     LOAD_CTL / LOAD_COOKIE (load client), ARTI_BIN, ARTI_MKCONF, ARTI_SOCKS,
     ARTI_STATE, PERIOD_GUARD (1/0), LEAD_S, TAIL_S, SETUP_EST_S.
"""
import glob
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.request

sys.path.insert(0, "/sim")
import sim  # noqa: E402
from ctl_lib import Ctl  # noqa: E402

NODES = sys.argv[1]
OUT = sys.argv[2]
PHASE_S = int(sys.argv[3]) if len(sys.argv) > 3 else 60

PHASES_SEL = os.environ.get("PHASES", os.environ.get("PHASES_SET", "dry"))
PHASES_FILE = os.environ.get("PHASES_FILE",
                             os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "phases.json"))
BUDGET_VAL = os.environ.get("BUDGET", "16384 bytes")
CLIENTS = [c for c in os.environ.get("CLIENTS", "ctor,arti").split(",") if c]
ATTEMPT_TIMEOUT = int(os.environ.get("ATTEMPT_TIMEOUT", "20"))
NEWNYM_MIN = float(os.environ.get("NEWNYM_MIN", "11"))
LOAD_CTL = int(os.environ.get("LOAD_CTL", "8090"))
LOAD_COOKIE = os.environ.get("LOAD_COOKIE", "/work/lc-reuse/control_auth_cookie")
ARTI_BIN = os.environ.get("ARTI_BIN", "/arti/bin/arti")
ARTI_MKCONF = os.environ.get("ARTI_MKCONF", "/lab/arti/mkconf.py")
ARTI_SOCKS = int(os.environ.get("ARTI_SOCKS", "9400"))
ARTI_STATE = os.environ.get("ARTI_STATE", "/work/arti")
ARTI_BOOT_S = int(os.environ.get("ARTI_BOOT_S", "180"))
PERIOD_GUARD = os.environ.get("PERIOD_GUARD", "1") == "1"
LEAD_S = float(os.environ.get("LEAD_S", "4"))
TAIL_S = float(os.environ.get("TAIL_S", "4"))
SETUP_EST_S = float(os.environ.get("SETUP_EST_S", "30"))

HS_VIRTPORT = 5858
T_START = time.time()
REUSE_N = 5

# Candidate shedding options; the set actually known to this tor is probed once.
CAND_OPTS = ["HSDirDescriptorFetchLimit", "HSDirDescriptorFetchRate",
             "HSDirDescriptorFetchBurst", "HSDirFetchBudget",
             "HSDirFetchBudgetPercent"]

SERIES = re.compile(
    r'^(tor_relay_(?:dos_total|hsdir_get_total|hsdir_fetch_total|'
    r'streams_total)\{[^}]*\}) (\d+)$', re.M)

_known_opts = None
FP2TAG = {}          # RSA fingerprint (upper hex) -> chutney node dir name
VOTING_S = 20        # V3AuthVotingInterval of the private net (read in main)


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- node helpers
def nicks(tag):
    out = []
    for p in sorted(glob.glob("%s/[0-9]*%s" % (NODES, tag))):
        b = os.path.basename(p)
        if re.fullmatch(r"\d+%s" % tag, b):
            out.append(b)
    return out


def cookie_of(nick):
    return "%s/%s/control_auth_cookie" % (NODES, nick)


def tctl(nick, timeout=30):
    return Ctl(sim.ctlport(nick), cookie_of(nick), timeout=timeout)


def known_opts():
    global _known_opts
    if _known_opts is not None:
        return _known_opts
    relays = nicks("r") + nicks("a")
    c = tctl(relays[0])
    known = set()
    for o in CAND_OPTS:
        ok, _ = c.cmd("GETCONF " + o)
        if ok:
            known.add(o)
    c.close()
    _known_opts = known
    return known


def expand_conf(conf):
    """Expand DEFAULTS / OFF / BUDGET tokens and drop options this tor does not
    know, so the same phases.json runs on the .5 and .6 builds."""
    known = known_opts()
    toks = []
    for t in conf.split():
        if t == "DEFAULTS":
            toks += ["HSDirDescriptorFetchLimit=0", "HSDirDescriptorFetchRate=5",
                     "HSDirDescriptorFetchBurst=20"]
            if "HSDirFetchBudget" in known:
                toks.append("HSDirFetchBudget=0")
        elif t == "OFF":
            toks += ["HSDirDescriptorFetchLimit=0", "HSDirDescriptorFetchRate=5",
                     "HSDirDescriptorFetchBurst=20"]
        elif t == "BUDGET":
            if "HSDirFetchBudget" in known:
                toks.append("HSDirFetchBudget=%s" % BUDGET_VAL.replace(" ", "_"))
        else:
            toks.append(t)
    out = []
    for kv in toks:
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        if k in CAND_OPTS and k not in known:
            continue
        v = v.replace("_", " ")
        out.append('%s="%s"' % (k, v) if " " in v else "%s=%s" % (k, v))
    return " ".join(out)


def setconf(nick, conf):
    exp = expand_conf(conf)
    if not exp:
        return "", []
    c = tctl(nick)
    ok, lines = c.cmd("SETCONF " + exp)
    c.close()
    if not ok:
        raise RuntimeError("SETCONF on %s failed (%s): %s" % (nick, exp, lines))
    return exp, lines


def getconf(nick):
    c = tctl(nick)
    ok, lines = c.cmd("GETCONF " + " ".join(sorted(known_opts())))
    c.close()
    return [l[4:] for l in lines if "=" in l]


def scrape_relay(nick):
    url = "http://127.0.0.1:%d/metrics" % sim.mport(nick)
    txt = urllib.request.urlopen(url, timeout=5).read().decode()
    # +tor41339.7 calls tor_relay_hsdir_get_total tor_relay_hsdir_fetch_total.
    return {k.replace("_hsdir_fetch_total", "_hsdir_get_total"): int(v)
            for k, v in SERIES.findall(txt)}


def scrape_all(relays):
    out = {}
    for n in relays:
        try:
            out[n] = scrape_relay(n)
        except Exception as e:
            out[n] = {"_error": str(e)}
    return out


def delta_all(before, after):
    d = {}
    for n in after:
        if "_error" in after[n] or "_error" in before.get(n, {}):
            continue
        dd = {k: after[n].get(k, 0) - before[n].get(k, 0) for k in after[n]
              if after[n].get(k, 0) != before[n].get(k, 0)}
        if dd:
            d[n] = dd
    return d


def pids_of(relays):
    return {n: sim.pid_of(NODES, n) for n in relays}


def bootstrapped(port, cookie):
    try:
        c = Ctl(port, cookie, timeout=10)
        _, lines = c.cmd("GETINFO status/bootstrap-phase")
        c.close()
        return any("PROGRESS=100" in l for l in lines)
    except Exception:
        return False


def wait_bootstrapped(port, cookie, limit):
    end = time.time() + limit
    while time.time() < end:
        if bootstrapped(port, cookie):
            return True
        time.sleep(3)
    return False


def tag_of(hsdir_field):
    """'$FP~nick' / '$FP' / 'FP' -> chutney node name (or the raw field)."""
    if not hsdir_field:
        return None
    fp = hsdir_field.lstrip("$").split("~")[0].split("=")[0].upper()
    return FP2TAG.get(fp, hsdir_field)


# ------------------------------------------------------------- time periods
def tp_bounds(now):
    """Onion-service time period under TestingTorNetwork: one shared-random
    protocol run (24 voting intervals), offset by 12 voting intervals. C tor
    and Arti (with mkconf's hsdir_interval) both use this."""
    length = 24 * VOTING_S
    off = 12 * VOTING_S
    n = int((now - off) // length)
    start = off + n * length
    return n, start, start + length


def period_guard(est_s):
    """Wait, if needed, so that a phase of about est_s seconds neither starts
    just after nor crosses a time-period boundary: the HSDirs holding each
    descriptor change there, and C tor follows the consensus time, up to a
    voting interval late."""
    if not PERIOD_GUARD:
        return 0.0
    settle = VOTING_S + 25
    now = time.time()
    _, start, end = tp_bounds(now)
    if now < start + settle:
        wait = start + settle - now
    elif now + est_s > end - 5:
        wait = end + settle - now
    else:
        return 0.0
    log("  period guard: waiting %.0f s for a time period to settle" % wait)
    time.sleep(wait)
    return round(wait, 1)


# -------------------------------------------------------- HSDir role discovery
_HSRES = re.compile(r"HS_DESC (RECEIVED|FAILED) (\S+) \S+ \$?([0-9A-Fa-f]{40})")


def serving_hsdirs(onion_addr, relays, probe_client, timeout=20):
    """Relays that currently answer a descriptor fetch for onion_addr (the
    HSDirs holding it this time period). One HSFETCH with every relay as a
    SERVER= through a stock client: a forced fetch from each, no cache."""
    fp = {sim.fpr(NODES, rn).upper(): rn for rn in relays}
    got, failed = set(), set()
    try:
        c = tctl(probe_client, timeout=15)
        c.setevents("HS_DESC")
        c.cmd("HSFETCH %s %s" % (onion_addr, " ".join("SERVER=$" + f for f in fp)))
        end = time.time() + timeout
        while time.time() < end and len(got) + len(failed) < len(fp):
            for _, l in c.collect_events(0.5):
                m = _HSRES.search(l)
                if m and m.group(2) == onion_addr and m.group(3).upper() in fp:
                    (got if m.group(1) == "RECEIVED" else failed).add(fp[m.group(3).upper()])
        c.close()
    except Exception as e:
        log("  serving_hsdirs(%s): %s" % (onion_addr[:8], e))
    return [rn for rn in relays if rn in got]


def measure_desc_bytes(onion_addr, hsdir, probe_client, timeout=15):
    """Size of the descriptor an HSDir serves for onion_addr (the length the
    .6 HSDirFetchBudget accounting counts), from HS_DESC_CONTENT."""
    try:
        c = tctl(probe_client, timeout=15)
        c.setevents("HS_DESC_CONTENT")
        c.cmd("HSFETCH %s SERVER=$%s" % (onion_addr, sim.fpr(NODES, hsdir)))
        end = time.time() + timeout
        inside, size = False, 0
        while time.time() < end:
            line = c._readline(deadline=end)
            if line is None:
                break
            if line.startswith("650+HS_DESC_CONTENT") and onion_addr in line:
                inside, size = True, 0
                continue
            if inside:
                if line == ".":
                    c.close()
                    return size
                size += len(line[1:] if line.startswith("..") else line) + 1
        c.close()
    except Exception as e:
        log("  measure_desc_bytes: %s" % e)
    return None


def client_first_hsdir(onion_addr, probe_client):
    """The HSDir a stock client asks FIRST for onion_addr under normal
    selection (HSFETCH without SERVER=, after NEWNYM so nothing is cached).
    It is in the clients' fetch set, so limiting it is observable."""
    try:
        newnym_gate(probe_client)
        c = tctl(probe_client, timeout=20)
        c.cmd("SIGNAL NEWNYM")
        c.setevents("HS_DESC")
        time.sleep(0.4)
        c.cmd("HSFETCH %s" % onion_addr)
        evs = c.collect_events(10, match="HS_DESC RECEIVED " + onion_addr)
        c.close()
        for a in parse_hs_desc(evs, onion_addr):
            if a["hsdir"] in FP2TAG.values():
                return a["hsdir"]
    except Exception as e:
        log("  client_first_hsdir: %s" % e)
    return None


def resolve_role(role, hs_list):
    if role == "first":
        return hs_list[0]
    if role == "last":
        return hs_list[-1]
    if isinstance(role, int):
        return hs_list[role]
    raise SystemExit("bad role %r" % role)


# ----------------------------------------------------------------- load driver
class LoadThread(threading.Thread):
    """Descriptor fetches through the load client's control port, until
    stop is set. pattern 'reuse': bursts of REUSE_N fetches of onion from ONE
    HSDir (the load client puts them on one circuit), then a pause of at
    least 2 s. pattern 'steady': one HSFETCH naming every target HSDir every
    1/rate s, so each target sees the same steady rate in every second."""
    def __init__(self, onion, hsdirs, pattern, rate, stop):
        super().__init__(daemon=True)
        self.onion, self.hsdirs, self.pattern = onion, hsdirs, pattern
        self.rate, self.stop = rate, stop
        self.r = {"onion": onion[:8], "hsdirs": hsdirs, "pattern": pattern,
                  "rate": rate, "issued": 0, "recv": 0, "fail": 0, "err": None}

    def _tally(self, evs):
        for _, l in evs:
            if "HS_DESC RECEIVED " + self.onion in l:
                self.r["recv"] += 1
            elif "HS_DESC FAILED " + self.onion in l:
                self.r["fail"] += 1

    def run(self):
        try:
            c = Ctl(LOAD_CTL, LOAD_COOKIE, timeout=20)
            c.setevents("HS_DESC")
            servers = " ".join("SERVER=$" + sim.fpr(NODES, h) for h in self.hsdirs)
            cmd = "HSFETCH %s %s" % (self.onion, servers)
            if self.pattern == "steady":
                period = 1.0 / self.rate
                nxt = time.time()
                while not self.stop.is_set():
                    c.cmd(cmd)
                    self.r["issued"] += len(self.hsdirs)
                    nxt += period
                    if nxt < time.time() - 1.0:   # fell behind: do not burst
                        nxt = time.time()
                    self._tally(c.collect_events(max(0.0, nxt - time.time())))
            else:
                while not self.stop.is_set():
                    fired = 0
                    for _ in range(REUSE_N):
                        if self.stop.is_set():
                            break
                        c.cmd(cmd)
                        fired += 1
                    self.r["issued"] += fired
                    self._tally(c.collect_events(max(2.0, fired * 0.2)))
            self._tally(c.collect_events(1.0))
            c.close()
        except Exception as e:
            self.r["err"] = "%s: %s" % (type(e).__name__, e)


# --------------------------------------------------------------- curl helper
def curl_cmd(socks_port, user, onion_addr):
    return ["curl", "-sS", "-o", "/dev/null",
            "-w", "%{http_code} %{time_starttransfer} %{time_total}",
            "--max-time", str(ATTEMPT_TIMEOUT),
            "-x", "socks5h://%s:x@127.0.0.1:%d" % (user, socks_port),
            "http://%s.onion:%d/" % (onion_addr, HS_VIRTPORT)]


def curl_result(rec, proc, t0):
    try:
        raw, err = proc.communicate(timeout=ATTEMPT_TIMEOUT + 5)
    except subprocess.TimeoutExpired:
        proc.kill()
        raw, err = proc.communicate()
    rec["curl_rc"] = proc.returncode
    parts = raw.decode(errors="replace").split()
    if len(parts) == 3:
        rec["http_code"] = parts[0]
        rec["ok"] = parts[0] == "200"
        try:
            rec["ttfb_s"] = round(float(parts[1]), 3)
            rec["total_s"] = round(float(parts[2]), 3)
        except ValueError:
            pass
    if rec["total_s"] is None or not rec["ok"]:
        rec["total_s"] = round(time.time() - t0, 3)
    e = err.decode(errors="replace").strip()
    if e:
        rec["err"] = re.sub(r"[a-z2-7]{56}\.onion", "<onion>", e)[:200]


def new_rec(kind, client, onion_addr, user):
    return {"kind": kind, "client": client, "onion": onion_addr[:8],
            "user": user, "t": None, "ok": False, "http_code": None,
            "curl_rc": None, "ttfb_s": None, "total_s": None, "err": None,
            "hsdir_attempts": [], "n_hsdir_attempts": 0, "n_hsdir_failed": 0,
            "asked": []}


def finish_rec(rec):
    att = rec["hsdir_attempts"]
    rec["n_hsdir_attempts"] = len(att)
    rec["n_hsdir_failed"] = sum(1 for a in att if a["outcome"] != "ok")
    rec["asked"] = [a["hsdir"] for a in att]
    return rec


# --------------------------------------------------------- C tor client probe
_HSDESC = re.compile(r"HS_DESC (REQUESTED|RECEIVED|FAILED) (\S+) \S+ (\S+)"
                     r"(?:.*?REASON=(\S+))?")


def parse_hs_desc(evs, onion_addr):
    """HS_DESC events for one onion -> ordered HSDir fetch attempts. Each
    REQUESTED opens an attempt; RECEIVED closes it ok, FAILED with its
    REASON. A REQUESTED with neither is a fetch whose circuit was closed with
    no reply (how an HSDir refuses one)."""
    out = []
    t_first = evs[0][0] if evs else 0
    for ts, line in evs:
        m = _HSDESC.search(line)
        if not m or m.group(2) != onion_addr:
            continue
        action, hsdir, reason = m.group(1), tag_of(m.group(3)), m.group(4)
        if action == "REQUESTED":
            out.append({"hsdir": hsdir, "t": round(ts - t_first, 3),
                        "outcome": "no_reply", "detail": None})
            continue
        for a in out:
            if a["hsdir"] == hsdir and a["outcome"] == "no_reply":
                a["outcome"] = "ok" if action == "RECEIVED" else (reason or "failed").lower()
                a["detail"] = round(ts - t_first, 3)
                break
    return out


def collect_events_until(c, proc, hard_s, grace=1.0):
    out = []
    if getattr(c, "pending_events", None):
        out.extend(c.pending_events)
        c.pending_events = []
    hard = time.time() + hard_s
    soft = None
    while True:
        now = time.time()
        if now >= hard or (soft is not None and now >= soft):
            break
        if proc.poll() is not None and soft is None:
            soft = now + grace
        line = c._readline(deadline=min(hard, soft or hard, now + 0.3))
        if line and line.startswith("650"):
            out.append((time.time(), line))
    return out


_lastnewnym = {}
_lastnewnym_lock = threading.Lock()


def newnym_gate(nick):
    with _lastnewnym_lock:
        last = _lastnewnym.get(nick, 0.0)
        wait = NEWNYM_MIN - (time.time() - last)
        _lastnewnym[nick] = time.time() + max(0.0, wait)
    if wait > 0:
        time.sleep(wait)


def ctor_attempt(client_nick, onion_addr, user):
    """One stock C tor client request: NEWNYM (purges the client's descriptor
    cache and HSDir-retry memory), then curl over the client's SocksPort with
    a unique SOCKS username, logging HS_DESC fetch events."""
    socks = 9000 + sim.nodenum(client_nick)
    rec = new_rec("ctor", client_nick, onion_addr, user)
    try:
        newnym_gate(client_nick)
        c = tctl(client_nick, timeout=20)
        c.cmd("SIGNAL NEWNYM")
        ok, _ = c.setevents("HS_DESC", "CIRC", "CIRC_MINOR", "STREAM")
        if not ok:
            c.setevents("HS_DESC")
        time.sleep(0.4)
        t0 = time.time()
        rec["t"] = t0
        proc = subprocess.Popen(curl_cmd(socks, user, onion_addr),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        evs = collect_events_until(c, proc, ATTEMPT_TIMEOUT + 3)
        curl_result(rec, proc, t0)
        c.close()
        rec["hsdir_attempts"] = parse_hs_desc(evs, onion_addr)
        if not rec["ok"]:
            # keep the HS_DESC / CIRC / STREAM trail of a failed request
            # (lab node names only)
            rec["events"] = [
                "%+.3f %s" % (ts - t0, re.sub(r"\$([0-9A-F]{40})(?:~[A-Za-z0-9]+)?",
                                               lambda m: tag_of(m.group(1)), l[4:])[:200])
                for ts, l in evs if onion_addr[:20] in l][:60]
    except Exception as e:
        rec["err"] = "%s: %s" % (type(e).__name__, e)
    return finish_rec(rec)


# ------------------------------------------------------------- Arti client
class Arti:
    """One Arti client process inside the container, configured by
    arti/mkconf.py from the running chutney net's node dirs."""
    def __init__(self):
        self.proc = None
        self.log_path = os.path.join(ARTI_STATE, "arti.log")
        self.toml = os.path.join(ARTI_STATE, "arti.toml")
        self.info = {"bin": ARTI_BIN, "socks_port": ARTI_SOCKS}

    def start(self):
        os.makedirs(ARTI_STATE, exist_ok=True)
        if not os.access(ARTI_BIN, os.X_OK):
            return "Arti binary %s missing or not executable" % ARTI_BIN
        h = hashlib.sha256(open(ARTI_BIN, "rb").read()).hexdigest()
        ver = subprocess.run([ARTI_BIN, "--version"], capture_output=True,
                             text=True).stdout.strip().splitlines()
        self.info.update(sha256=h, version=ver[0] if ver else None)
        p = subprocess.run(["python3", "-I", ARTI_MKCONF, NODES, "--state",
                            ARTI_STATE, "--socks-port", str(ARTI_SOCKS),
                            "--out", self.toml], capture_output=True, text=True)
        if p.returncode != 0:
            return "mkconf.py failed: %s" % p.stderr.strip()[:300]
        conf = open(self.toml).read()
        self.info["conf"] = {k: (re.search(r"^%s = (.*)$" % k, conf, re.M) or [None, None])[1]
                             for k in ("hsdir_interval", "cbtmintimeout")}
        out = open(os.path.join(ARTI_STATE, "stdout"), "w")
        t0 = time.time()
        self.proc = subprocess.Popen([ARTI_BIN, "proxy", "-c", self.toml,
                                      "--disable-fs-permission-checks"],
                                     stdout=out, stderr=subprocess.STDOUT)
        while time.time() - t0 < ARTI_BOOT_S:
            if self.proc.poll() is not None:
                return "Arti exited with %s during bootstrap" % self.proc.returncode
            if os.path.exists(self.log_path) and \
                    "Sufficiently bootstrapped" in open(self.log_path, errors="replace").read():
                self.info["bootstrap_s"] = round(time.time() - t0, 1)
                return None
            time.sleep(0.5)
        return "Arti did not bootstrap within %d s" % ARTI_BOOT_S

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.alive():
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def size(self):
        try:
            return os.path.getsize(self.log_path)
        except OSError:
            return 0

    def lines_since(self, off):
        with open(self.log_path, "rb") as f:
            f.seek(off)
            return f.read().decode(errors="replace").splitlines()


ARTI = None

_ATS = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)Z")
_ATRY = re.compile(r"hsdir for (\S+)\.onion, trying [A-Za-z0-9+/=]{43}/\$?([0-9A-Fa-f]{40})")
_AFAIL = re.compile(r"failed hsdir desc fetch for (\S+)\.onion from "
                    r"[A-Za-z0-9+/=]{43}/\$?([0-9A-Fa-f]{40}) error=(.*)$")


def arti_ts(line):
    m = _ATS.match(line)
    if not m:
        return None
    s = m.group(1)
    base = time.strptime(s.split(".")[0], "%Y-%m-%dT%H:%M:%S")
    frac = float("0." + s.split(".")[1]) if "." in s else 0.0
    return time.mktime(base) - time.timezone + frac


def classify_arti_err(msg):
    m = msg.lower()
    if "stream not connected" in m or "circuit closed" in m or "closed" in m:
        return "closed"
    if "timed out" in m or "timeout" in m:
        return "timeout"
    if "404" in m or "not found" in m:
        return "not_found"
    return "other"


def parse_arti(lines, onion_addr):
    """Arti log lines -> (fetch rounds, ordered HSDir attempts, connection
    failure text, descriptor obtained?)."""
    rounds, att, conn_fail, got_desc = 0, [], None, False
    t_first = None
    for l in lines:
        if onion_addr not in l:
            continue
        ts = arti_ts(l)
        if "HS desc fetch for %s.onion" % onion_addr in l:
            rounds += 1
            continue
        m = _ATRY.search(l)
        if m and m.group(1) == onion_addr:
            t_first = t_first if t_first is not None else ts
            att.append({"hsdir": tag_of(m.group(2)), "t": round((ts or 0) - (t_first or 0), 3),
                        "outcome": "pending", "detail": None})
            continue
        m = _AFAIL.search(l)
        if m and m.group(1) == onion_addr:
            tg = tag_of(m.group(2))
            for a in reversed(att):
                if a["hsdir"] == tg and a["outcome"] == "pending":
                    a["outcome"] = classify_arti_err(m.group(3))
                    a["detail"] = re.sub(r"\s+", " ", m.group(3))[:160]
                    break
            continue
        if "HS connection failure for %s.onion" % onion_addr in l:
            conn_fail = re.sub(r"\s+", " ", l.split("error=", 1)[-1])[:200]
            continue
        if "setting up rendezvous point" in l:
            got_desc = True
    # The last pending attempt succeeded iff Arti went on to rendezvous.
    for a in att:
        if a["outcome"] == "pending":
            a["outcome"] = "ok" if got_desc else "no_result"
    return rounds, att, conn_fail, got_desc


def arti_attempt(onion_addr, user):
    rec = new_rec("arti", "arti", onion_addr, user)
    try:
        off = ARTI.size()
        t0 = time.time()
        rec["t"] = t0
        proc = subprocess.Popen(curl_cmd(ARTI_SOCKS, user, onion_addr),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        curl_result(rec, proc, t0)
        time.sleep(0.5)    # let Arti's file logger catch up
        lines = ARTI.lines_since(off)
        rounds, att, conn_fail, got_desc = parse_arti(lines, onion_addr)
        rec["hsdir_attempts"] = att
        rec["desc_fetch_rounds"] = rounds
        rec["desc_obtained"] = got_desc
        if conn_fail:
            rec["arti_conn_failure"] = conn_fail
        if not rec["ok"]:
            # keep Arti's connection trail of a failed request
            rec["events"] = [re.sub(r"\s+", " ", l)[:200] for l in lines
                             if onion_addr in l and "hs conn to" in l][:60]
    except Exception as e:
        rec["err"] = "%s: %s" % (type(e).__name__, e)
    return finish_rec(rec)


# --------------------------------------------------------------- probe driver
def n_attempts(spec, kind, role):
    """probe.attempts: N, {kind: N} or {kind: {role: N}}."""
    a = spec.get("attempts", 6)
    if isinstance(a, dict):
        a = a.get(kind, 0)
    if isinstance(a, dict):
        a = a.get(role, 0)
    return int(a)


def probe_series(kind, role, oaddr, n, w0, w1, client_q, phase, out):
    """n requests from one client kind to one onion, spread evenly over
    [w0, w1]. Kinds and roles are offset within a slot so the four series
    do not start together."""
    recs = []
    out[(kind, role)] = recs
    if n <= 0:
        return
    step = (w1 - w0) / n
    shift = {"ctor": 0.0, "arti": 0.5}[kind] + {"D": 0.0, "E": 0.25}.get(role, 0.0)
    for i in range(n):
        ts = w0 + (i + shift) * step
        now = time.time()
        if ts > now:
            time.sleep(ts - now)
        # Behind schedule (a slow request): catch up back to back. The load
        # keeps running until every series ends, so no request runs without
        # it; only give up on requests that would start long after the plan.
        if time.time() > w1 + ATTEMPT_TIMEOUT + 5:
            recs.append({"kind": kind, "skipped": "phase window over", "ok": False})
            continue
        user = "%s-%s-%s-%d-%d" % (kind, phase, role, i, int(time.time() * 1000) % 1000000)
        if kind == "ctor":
            nick = client_q.get()
            try:
                r = ctor_attempt(nick, oaddr, user)
            finally:
                client_q.put(nick)
        else:
            r = arti_attempt(oaddr, user)
        r["t"] = round(r["t"] - w0, 2) if r.get("t") else None
        recs.append(r)


def pctl(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(len(s) * p))], 3)


def summarize(recs, limited):
    skipped = sum(1 for r in recs if "skipped" in r)
    recs = [r for r in recs if "skipped" not in r]
    n = len(recs)
    ok = [r for r in recs if r["ok"]]
    bad = [r for r in recs if not r["ok"]]
    lat = [r["total_s"] for r in ok if r["total_s"] is not None]
    flat = [r["total_s"] for r in bad if r["total_s"] is not None]
    hit = [r for r in recs if set(r["asked"]) & limited]
    outc, rc = {}, {}
    for r in recs:
        for a in r["hsdir_attempts"]:
            outc[a["outcome"]] = outc.get(a["outcome"], 0) + 1
        rc[str(r["curl_rc"])] = rc.get(str(r["curl_rc"]), 0) + 1

    def mean(xs):
        return round(sum(xs) / len(xs), 2) if xs else None
    return {
        "requests": n, "ok": len(ok),
        "success_rate": round(len(ok) / n, 3) if n else None,
        "lat_p50_s": pctl(lat, 0.5), "lat_p90_s": pctl(lat, 0.9),
        "ttfb_p50_s": pctl([r["ttfb_s"] for r in ok if r["ttfb_s"]], 0.5),
        "fail_lat_p50_s": pctl(flat, 0.5),
        "hsdir_attempts_per_ok": mean([r["n_hsdir_attempts"] for r in ok]),
        "hsdir_attempts_per_fail": mean([r["n_hsdir_attempts"] for r in bad]),
        "max_hsdir_attempts": max([r["n_hsdir_attempts"] for r in recs], default=0),
        "ok_after_failover": sum(1 for r in ok if r["n_hsdir_failed"] > 0),
        # failed although some HSDir served the descriptor: the failure came
        # later (introduction / rendezvous), not from the HSDirs.
        "fail_after_desc": sum(1 for r in bad
                               if any(a["outcome"] == "ok" for a in r["hsdir_attempts"])),
        "skipped_window_over": skipped,
        "ok_without_fetch": sum(1 for r in ok if r["n_hsdir_attempts"] == 0),
        "asked_limited_hsdir": len(hit),
        "ok_when_asked_limited": sum(1 for r in hit if r["ok"]),
        "hsdir_attempt_outcomes": outc,
        "curl_rc": rc,
    }


# ------------------------------------------------------------------- phases
def shed_totals(delta, only=None):
    """Sum the shedding / GET counters across relays (or only those named)."""
    def s(sub):
        return sum(v for n, relay in delta.items() if only is None or n in only
                   for k, v in relay.items() if sub in k)
    return {
        "hsdir_fetch_over_rate": s('type="hsdir_fetch_over_rate"'),
        "hsdir_fetch_pressure": s('type="hsdir_fetch_pressure"'),
        "hsdir_fetch_shed": s('type="hsdir_fetch_shed"'),
        "get_refused": s('action="refused"'),
        "get_success": s('action="success"'),
        "get_not_found": s('action="not_found"'),
        "get_single_hop": s('action="single_hop"'),
        "begin_dir": s('type="BEGIN_DIR"'),
    }


def run_phase(ph, ctx):
    relays, probe_client = ctx["relays"], ctx["probe_client"]
    D, E = ctx["D"], ctx["E"]
    role_addr = {"D": D, "E": E}
    row = {"phase": ph["name"], "desc": ph["desc"]}
    row["period_guard_wait_s"] = period_guard(SETUP_EST_S + PHASE_S + 10)
    t_setup = time.time()
    row["time_period"] = tp_bounds(t_setup)[0]

    # 1. reset relays; find who holds D and E now (before any limit applies).
    for n in relays:
        setconf(n, "DEFAULTS")
    memo = {}

    def holders(oaddr):
        if oaddr not in memo:
            memo[oaddr] = serving_hsdirs(oaddr, relays, probe_client)
        return memo[oaddr]
    row["holders"] = {"D": holders(D), "E": holders(E)}

    # 2. relay selections.
    plans = []
    for rc in ph.get("relays", []):
        sel = rc["set"]
        if sel == "all":
            targets = list(relays)
        elif sel == "none":
            targets = []
        elif ":" in sel:
            how, role = sel.split(":", 1)
            oaddr = role_addr[role]
            if how == "serving":
                targets = holders(oaddr)
            elif how == "serving_one":
                targets = holders(oaddr)[:1]
            elif how == "serving_clientfirst":
                cf = client_first_hsdir(oaddr, probe_client)
                targets = [cf] if cf else holders(oaddr)[:1]
            else:
                raise SystemExit("bad relay set %r" % sel)
        else:
            raise SystemExit("bad relay set %r" % sel)
        plans.append((targets, rc["conf"]))

    # 3. load targets.
    ld = ph.get("load", {"mode": "none"})
    mode, pattern = ld.get("mode", "none"), ld.get("pattern", "reuse")
    load_map, rate = {}, ld.get("rate_per_hsdir", ld.get("rate_per_onion", 10))
    if mode == "concentrated":
        load_map[D] = holders(D)
    elif mode == "spread":
        sp = [sim.onion(NODES, resolve_role(r, ctx["hs"])) for r in ctx["spread_roles"]]
        if ld.get("common_hsdir"):
            count = {}
            for o in sp:
                for h in holders(o):
                    count[h] = count.get(h, 0) + 1
            common = max(sorted(count), key=lambda h: count[h]) if count else None
            for o in sp:
                if common in holders(o):
                    load_map[o] = [common]
        else:
            for o in sp:
                load_map[o] = holders(o)[:1]
    row["load_spec"] = ld
    row["load_targets"] = {o[:8]: v for o, v in load_map.items()}

    # 4. apply relay configs.
    applied, limited = [], set()
    for targets, conf in plans:
        for n in targets:
            exp, _ = setconf(n, conf)
            applied.append({"relay": n, "conf": exp})
            if "HSDirDescriptorFetchLimit=1" in exp:
                limited.add(n)
    row["relay_conf_applied"] = applied
    row["limited_relays"] = sorted(limited)
    row["setup_s"] = round(time.time() - t_setup, 1)

    # 5. snapshot, start load, probe with every client kind at once.
    before = scrape_all(relays)
    pids0 = pids_of(relays)
    stop = threading.Event()
    lths = []
    for oaddr, hs in load_map.items():
        if not hs:
            continue
        if pattern == "steady":
            lths.append(LoadThread(oaddr, hs, "steady", rate, stop))
        else:
            lths += [LoadThread(oaddr, [h], "reuse", None, stop) for h in hs]
    t0 = time.time()
    for t in lths:
        t.start()
    w0, w1 = t0 + LEAD_S, t0 + PHASE_S - TAIL_S
    probe_out = {}
    pths = []
    for kind in CLIENTS:
        for role in ph["probe"]["onions"]:
            th = threading.Thread(target=probe_series, daemon=True, args=(
                kind, role, role_addr[role], n_attempts(ph["probe"], kind, role),
                w0, w1, ctx["client_q"], ph["name"], probe_out))
            pths.append(th)
            th.start()
    for th in pths:
        th.join()
    left = t0 + PHASE_S - time.time()
    if left > 0:
        time.sleep(left)
    stop.set()
    for t in lths:
        t.join(15)
    wall = time.time() - t0
    time.sleep(2)
    after = scrape_all(relays)
    pids1 = pids_of(relays)
    row["holders_at_end"] = {"D": serving_hsdirs(D, relays, probe_client)}
    row["holders_changed"] = sorted(row["holders_at_end"]["D"]) != sorted(row["holders"]["D"])

    delta = delta_all(before, after)
    st = shed_totals(delta)
    lh = sorted({h for hs in load_map.values() for h in hs})
    lst = shed_totals(delta, only=set(lh)) if lh else None
    issued = sum(t.r["issued"] for t in lths)
    row["load"] = {
        "wall_s": round(wall, 1), "issued": issued,
        "issued_per_s": round(issued / wall, 2) if wall else None,
        "recv": sum(t.r["recv"] for t in lths),
        "answered_or_refused_at_targets_per_s": round(
            (lst["get_success"] + lst["get_refused"]) / wall, 2) if lst else 0.0,
        "per_thread": [t.r for t in lths],
    }
    row["metrics_delta"] = delta
    row["totals"] = st
    row["getconf_sample"] = {n: getconf(n) for n in (sorted(limited)[:1] or relays[:1])}
    row["clients"] = {}
    for (kind, role), recs in sorted(probe_out.items()):
        row["clients"].setdefault(kind, {})[role] = {
            "onion": role_addr[role][:8],
            "summary": summarize(recs, limited), "requests": recs}
    row["all_pids_unchanged"] = pids0 == pids1
    row["arti_alive"] = ARTI.alive() if ARTI else None
    for n in relays:
        setconf(n, "DEFAULTS")
    return row


def baseline_failures(row):
    bad = []
    for kind in CLIENTS:
        for role in ("D", "E"):
            s = row["clients"].get(kind, {}).get(role, {}).get("summary")
            if not s or not s["requests"]:
                bad.append("B0 %s %s: no requests" % (kind, role))
            elif s["ok"] < s["requests"]:
                bad.append("B0 %s %s: %d/%d ok" % (kind, role, s["ok"], s["requests"]))
    return bad


def fmt(x):
    return "-" if x is None else str(x)


def print_table(result):
    hdr = ("phase", "client", "onion", "ok/req", "p50_s", "p90_s", "fail_p50",
           "hsdir/ok", "hsdir/fail", "failover_ok", "hit_limited(ok)",
           "fail_after_desc")
    rows = [hdr]
    for p in result["phases"]:
        for kind in CLIENTS:
            for role in ("D", "E"):
                c = p["clients"].get(kind, {}).get(role)
                if not c:
                    continue
                s = c["summary"]
                rows.append((p["phase"], kind, role, "%d/%d" % (s["ok"], s["requests"]),
                             fmt(s["lat_p50_s"]), fmt(s["lat_p90_s"]),
                             fmt(s["fail_lat_p50_s"]), fmt(s["hsdir_attempts_per_ok"]),
                             fmt(s["hsdir_attempts_per_fail"]),
                             str(s["ok_after_failover"]),
                             "%d(%d)" % (s["asked_limited_hsdir"], s["ok_when_asked_limited"]),
                             str(s["fail_after_desc"])))
    w = [max(len(str(r[i])) for r in rows) for i in range(len(hdr))]
    log("\n=== client reachability (per phase x client x onion) ===")
    for r in rows:
        log("  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)))
    hdr2 = ("phase", "load", "load/s", "limited", "refused", "over_rate",
            "pressure", "shed", "begin_dir", "TP", "holders_chg")
    rows = [hdr2]
    for p in result["phases"]:
        st = p["totals"]
        rows.append((p["phase"], "%s/%s" % (p["load_spec"].get("mode"),
                                            p["load_spec"].get("pattern", "-")),
                     fmt(p["load"]["answered_or_refused_at_targets_per_s"]),
                     ",".join(p["limited_relays"]) or "-",
                     str(st["get_refused"]), str(st["hsdir_fetch_over_rate"]),
                     str(st["hsdir_fetch_pressure"]), str(st["hsdir_fetch_shed"]),
                     str(st["begin_dir"]), str(p["time_period"]),
                     str(p["holders_changed"])))
    w = [max(len(str(r[i])) for r in rows) for i in range(len(hdr2))]
    log("\n=== relays (per phase) ===")
    for r in rows:
        log("  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)))


def select_phases(spec):
    want = [w.strip() for w in PHASES_SEL.split(",") if w.strip()]
    sel = [p for p in spec["phases"]
           if p["name"] in want or any(s in want for s in p.get("sets", []))]
    unknown = [w for w in want if w not in {p["name"] for p in spec["phases"]}
               and not any(w in p.get("sets", []) for p in spec["phases"])]
    if unknown:
        raise SystemExit("unknown phase or set name(s): %s" % unknown)
    base = [p for p in spec["phases"] if p.get("baseline")]
    if not base:
        raise SystemExit("phases.json has no baseline phase")
    rest = [p for p in sel if not p.get("baseline")]
    return base[:1] + rest


def main():
    global ARTI, VOTING_S
    relays = sorted(nicks("r") + nicks("a"))
    hs_list = nicks("h")
    clients = nicks("c")
    if not relays or len(hs_list) < 2 or not clients:
        raise SystemExit("discover: relays=%s hs=%s clients=%s" % (relays, hs_list, clients))
    for rn in relays:
        FP2TAG[sim.fpr(NODES, rn).upper()] = rn
    for l in open("%s/%s/torrc" % (NODES, relays[0])):
        m = re.match(r"\s*V3AuthVotingInterval\s+(\d+)", l)
        if m:
            VOTING_S = int(m.group(1))

    spec = json.load(open(PHASES_FILE))
    roles = spec.get("roles", {"D": "first", "E": "last", "spread": ["first", 1, 2]})
    D = sim.onion(NODES, resolve_role(roles["D"], hs_list))
    E = sim.onion(NODES, resolve_role(roles["E"], hs_list))
    phases = select_phases(spec)

    probe_client = clients[0]
    client_q = queue.Queue()
    for c in clients:
        client_q.put(c)

    result = {"phase_seconds": PHASE_S, "phases_selected": PHASES_SEL,
              "clients_kinds": CLIENTS, "budget_token": BUDGET_VAL,
              "D_onion": D, "E_onion": E, "relays": relays,
              "ctor_client_nodes": clients, "voting_interval_s": VOTING_S,
              "time_period_s": 24 * VOTING_S, "phases": [], "fail": []}

    def finish(rc):
        result["result"] = "PASS" if not result["fail"] else "FAIL"
        json.dump(result, open(OUT, "w"), indent=1)
        if result["phases"]:
            print_table(result)
        log("\nwrote %s" % OUT)
        if result["fail"]:
            log("RESULT: FAIL: " + "; ".join(result["fail"]))
            return 2
        log("RESULT: PASS (baseline ok for %s; %d phases measured in %d s)" %
            ("+".join(CLIENTS), len(result["phases"]), time.time() - T_START))
        return rc

    # Readiness: every stock client node, the load client, the descriptors.
    for c in clients:
        if not wait_bootstrapped(sim.ctlport(c), cookie_of(c), 180):
            result["fail"].append("C tor client %s did not bootstrap" % c)
    if any(p["load"]["mode"] != "none" for p in phases) and \
            not wait_bootstrapped(LOAD_CTL, LOAD_COOKIE, 180):
        result["fail"].append("load client did not bootstrap")
    end = time.time() + 180
    while time.time() < end and not (serving_hsdirs(D, relays, probe_client) and
                                     serving_hsdirs(E, relays, probe_client)):
        time.sleep(5)
    if time.time() >= end:
        result["fail"].append("descriptors of D/E not on any HSDir after 180 s")
    result["known_options"] = sorted(known_opts())
    if "arti" in CLIENTS:
        ARTI = Arti()
        err = ARTI.start()
        result["arti"] = ARTI.info
        if err:
            result["fail"].append(err)
        else:
            log("arti: %s, bootstrapped in %s s (hsdir_interval=%s, cbtmintimeout=%s)" % (
                ARTI.info.get("version"), ARTI.info.get("bootstrap_s"),
                ARTI.info["conf"].get("hsdir_interval"), ARTI.info["conf"].get("cbtmintimeout")))
    if result["fail"]:
        return finish(2)

    S = None
    hd = serving_hsdirs(D, relays, probe_client)
    if hd:
        S = measure_desc_bytes(D, hd[0], probe_client)
    result["desc_bytes_D"] = S
    log("known shedding options: %s" % result["known_options"])
    log("D(loaded)=%s... E(control)=%s... relays=%s ctor clients=%s hs=%s" %
        (D[:8], E[:8], relays, clients, hs_list))
    log("descriptor size of D: %s bytes; time period %d s" % (S, 24 * VOTING_S))
    log("phases: %s (PHASE_S=%d, BUDGET token=%s, clients=%s)" %
        ([p["name"] for p in phases], PHASE_S, BUDGET_VAL, CLIENTS))

    ctx = {"relays": relays, "hs": hs_list, "client_q": client_q,
           "probe_client": probe_client, "D": D, "E": E,
           "spread_roles": roles.get("spread", ["first", 1, 2])}
    try:
        for ph in phases:
            log("\n--- phase %s (t+%ds): %s" % (ph["name"], time.time() - T_START, ph["desc"]))
            try:
                row = run_phase(ph, ctx)
            except Exception as e:
                result["fail"].append("phase %s: %s: %s" % (ph["name"], type(e).__name__, e))
                break
            result["phases"].append(row)
            for kind in CLIENTS:
                for role in ("D", "E"):
                    s = row["clients"].get(kind, {}).get(role, {}).get("summary")
                    if s:
                        log("  %-4s %s %2d/%-2d ok  p50=%s s  hsdir/ok=%s  fail_p50=%s s  "
                            "hsdir/fail=%s  hsdir outcomes=%s" % (
                                kind, role, s["ok"], s["requests"], fmt(s["lat_p50_s"]),
                                fmt(s["hsdir_attempts_per_ok"]), fmt(s["fail_lat_p50_s"]),
                                fmt(s["hsdir_attempts_per_fail"]), s["hsdir_attempt_outcomes"]))
            st = row["totals"]
            log("  relays: refused=%d over_rate=%d pressure=%d shed=%d begin_dir=%d "
                "load answered+refused/s=%s limited=%s holders_changed=%s pids_ok=%s arti_alive=%s" % (
                    st["get_refused"], st["hsdir_fetch_over_rate"], st["hsdir_fetch_pressure"],
                    st["hsdir_fetch_shed"], st["begin_dir"],
                    row["load"]["answered_or_refused_at_targets_per_s"], row["limited_relays"],
                    row["holders_changed"], row["all_pids_unchanged"], row["arti_alive"]))
            if ph.get("baseline"):
                bad = baseline_failures(row)
                if bad:
                    result["fail"] += bad
                    break
            if ARTI and not ARTI.alive():
                result["fail"].append("Arti exited during phase %s" % ph["name"])
                break
    finally:
        if ARTI:
            ARTI.stop()
    return finish(0)


if __name__ == "__main__":
    sys.exit(main())
