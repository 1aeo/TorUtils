#!/usr/bin/env python3
"""Closed-lab BEGIN_DIR load + measurement driver for the cleanup-indexing
study. Loopback-only; drives real HS-descriptor BEGIN_DIR streams at a target
HSDir in a private chutney net and measures the target's MAIN-THREAD CPU per
served BEGIN_DIR stream. No connection to the real network.

Usage: load.py <datadir> <target_node> <rate> <seconds> <concurrency>
"""
import binascii, os, socket, sys, threading, time, json, glob, signal

DATA, TARGET, RATE, SECS, CONC = (sys.argv[1], sys.argv[2],
    float(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5]))

def node_dir(n):
    return os.path.join(DATA, "nodes", n)

def read_port(n, fname):
    p = os.path.join(node_dir(n), fname)
    for _ in range(50):
        if os.path.exists(p):
            return int(open(p).read().strip().split(":")[-1])
        time.sleep(0.1)
    raise SystemExit("no %s for %s" % (fname, n))

def control_port(n):
    # chutney writes control ports into the torrc; parse it.
    torrc = os.path.join(node_dir(n), "torrc")
    for line in open(torrc):
        if line.lower().startswith("controlport"):
            return int(line.split()[1])
    raise SystemExit("no controlport for %s" % n)

def fp(n):
    f = os.path.join(node_dir(n), "fingerprint")
    return open(f).read().split()[1].strip()

class Ctl:
    def __init__(self, n):
        self.port = control_port(n)
        self.s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        self.buf = b""
        ck = os.path.join(node_dir(n), "control_auth_cookie")
        self.cmd("AUTHENTICATE " + binascii.hexlify(open(ck,"rb").read()).decode())
    def line(self):
        while b"\r\n" not in self.buf:
            try:
                d = self.s.recv(65536)
            except socket.timeout:
                return None
            if not d: return None
            self.buf += d
        l, self.buf = self.buf.split(b"\r\n",1)
        return l.decode()
    def cmd(self, c):
        try:
            self.s.sendall((c+"\r\n").encode())
        except OSError:
            return []
        out=[]
        while True:
            l=self.line()
            if l is None: break
            if l.startswith("650"): continue
            out.append(l)
            if len(l)>=4 and l[3]==" ": break
        return out

def metrics(n):
    port = read_port(n, "metrics_port") if os.path.exists(os.path.join(node_dir(n),"metrics_port")) else None
    # metrics port is in torrc (MetricsPort 127.0.0.1:191xx)
    if port is None:
        for line in open(os.path.join(node_dir(n),"torrc")):
            if line.lower().startswith("metricsport"):
                port=int(line.split()[1].split(":")[-1]); break
    s=socket.create_connection(("127.0.0.1",port),timeout=8); s.sendall(b"GET /metrics HTTP/1.0\r\n\r\n")
    data=b""
    try:
        while True:
            d=s.recv(65536)
            if not d: break
            data+=d
    except socket.timeout:
        pass
    s.close()
    return data.decode(errors="replace")

def begin_dir_count(n):
    for line in metrics(n).splitlines():
        if line.startswith('tor_relay_streams_total{type="BEGIN_DIR"}'):
            return int(float(line.rsplit(" ",1)[1]))
    return -1

def pid_of(n):
    return int(open(os.path.join(node_dir(n),"pid")).read().strip())

def main_thread_cpu_ticks(pid):
    # main thread tid == pid; utime(14)+stime(15) in clock ticks
    st = open("/proc/%d/task/%d/stat" % (pid,pid)).read()
    rparen = st.rfind(")")
    fields = st[rparen+2:].split()
    # after comm, field index: state is fields[0] (3rd overall). utime=14th
    # overall => fields[11], stime => fields[12].
    return int(fields[11]) + int(fields[12])

def onions():
    out=[]
    for d in sorted(glob.glob(os.path.join(DATA,"nodes","*h"))):
        hs = glob.glob(os.path.join(d,"hidden_service*","hostname"))
        for h in hs:
            out.append(open(h).read().strip().replace(".onion",""))
    return out

TARGET_FP = fp(TARGET)
ONIONS = onions()
if not ONIONS: raise SystemExit("no onion hostnames found")

stop = threading.Event()
counts = {"sent":0, "ok":0, "err":0}
lock = threading.Lock()

def worker(idx):
    # each worker uses one client control port, round-robin across clients
    clients = sorted(glob.glob(os.path.join(DATA,"nodes","*c")))
    cn = os.path.basename(clients[idx % len(clients)])
    c = Ctl(cn)
    c.cmd("SETEVENTS HS_DESC")
    period = CONC / RATE if RATE>0 else 0
    i=0
    while not stop.is_set():
        onion = ONIONS[i % len(ONIONS)]; i+=1
        # Force the BEGIN_DIR to the target HSDir regardless of responsibility.
        r = c.cmd("HSFETCH %s SERVER=%s" % (onion, TARGET_FP))
        with lock:
            counts["sent"]+=1
            if r and r[-1].startswith("250"): counts["ok"]+=1
            else: counts["err"]+=1
        if period: time.sleep(period)

pid = pid_of(TARGET)
bd0 = begin_dir_count(TARGET)
t0 = time.time(); cpu0 = main_thread_cpu_ticks(pid)
threads=[threading.Thread(target=worker,args=(k,),daemon=True) for k in range(CONC)]
for t in threads: t.start()
time.sleep(SECS)
stop.set()
cpu1 = main_thread_cpu_ticks(pid); t1=time.time()
bd1 = begin_dir_count(TARGET)
clk = os.sysconf("SC_CLK_TCK")
cpu_s = (cpu1-cpu0)/clk
bd = bd1-bd0
res = {"target":TARGET,"target_fp":TARGET_FP,"rate":RATE,"concurrency":CONC,
  "seconds":round(t1-t0,2),"hsfetch_sent":counts["sent"],
  "begin_dir_delta":bd,"main_thread_cpu_s":round(cpu_s,4),
  "cpu_us_per_begin_dir": round(cpu_s*1e6/bd,3) if bd>0 else None,
  "begin_dir_per_s": round(bd/(t1-t0),1)}
print(json.dumps(res)); sys.stdout.flush(); os._exit(0)
