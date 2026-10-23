#!/bin/bash
# One end-to-end lab run inside the container (loopback-only, --network none).
# usage: in-lab.sh <label> <tor-binary> <rate> <seconds> <conc> <target-node>
set -uo pipefail
LABEL=$1; BIN=$2; RATE=$3; SECS=$4; CONC=$5; TARGET=${6:-004r}
OUT=/work/lab/out/$LABEL; mkdir -p "$OUT"
export CHUTNEY_PATH=/opt/chutney PYTHONPATH=/opt/chutney/lib
export CHUTNEY_LISTEN_ADDRESS=127.0.0.1 CHUTNEY_TOR_SANDBOX=0
export CHUTNEY_TOR="$BIN" CHUTNEY_TOR_GENCERT=/work/lab/bins/tor-gencert
export CHUTNEY_DATA_DIR=/tmp/net-$LABEL
cp /work/lab/netdef /opt/chutney/networks/hsflood41339
rm -rf "$CHUTNEY_DATA_DIR"; mkdir -p "$CHUTNEY_DATA_DIR"
cd "$CHUTNEY_PATH"
{
  echo "=== $LABEL bin=$BIN ($($BIN --version|head -1)) rate=$RATE secs=$SECS conc=$CONC target=$TARGET ==="
  python3 -m chutney.TorNet init --net hsflood41339 2>&1 | tail -1
  python3 -m chutney.TorNet configure 2>&1 | tail -1
  CHUTNEY_CONFIG_PHASE=2 python3 -m chutney.TorNet configure 2>&1 | tail -1
  python3 -m chutney.TorNet start 2>&1 | tail -1
  timeout 320 python3 -m chutney.TorNet wait_for_bootstrap 2>&1 | tail -1
  CHUTNEY_LAUNCH_PHASE=2 python3 -m chutney.TorNet start 2>&1 | tail -1
  CHUTNEY_LAUNCH_PHASE=2 timeout 320 python3 -m chutney.TorNet wait_for_bootstrap 2>&1 | tail -1
} | tee "$OUT/netup.txt"

TPID=$(cat "$CHUTNEY_DATA_DIR/nodes/$TARGET/pid")
echo "target $TARGET pid=$TPID" | tee "$OUT/target.txt"
PERF=$(ls /usr/lib/linux-tools-*/perf 2>/dev/null | head -1); [ -z "$PERF" ] && PERF=perf

# warm up load to reach steady state
timeout $((SECS+30)) python3 /work/lab/load.py "$CHUTNEY_DATA_DIR" "$TARGET" "$RATE" 12 "$CONC" >/dev/null 2>&1 || true

# measured window: perf on the target main thread + load.py CPU/stream window
"$PERF" record -F 997 -g --call-graph fp -t "$TPID" -o "$OUT/perf.data" -- sleep "$SECS" >"$OUT/perf-record.log" 2>&1 &
PERFPID=$!
python3 /work/lab/load.py "$CHUTNEY_DATA_DIR" "$TARGET" "$RATE" "$SECS" "$CONC" > "$OUT/measure.json" 2> "$OUT/load.err"
wait $PERFPID 2>/dev/null
"$PERF" report --stdio -i "$OUT/perf.data" > "$OUT/perf-report.txt" 2>/dev/null || true
"$PERF" script -i "$OUT/perf.data" > "$OUT/perf-script.txt" 2>/dev/null || true

echo "=== measure ==="; cat "$OUT/measure.json"; echo
echo "=== perf: cleanup-scan symbols on the main thread ==="
grep -nE 'smartlist_remove|smartlist_contains|connection_free_|connection_unlink|connection_stop_reading_from_linked_conn|add_connection_to_closeable_list|close_closeable_connections' "$OUT/perf-report.txt" | head -25 | tee "$OUT/perf-scan-lines.txt"
echo "=== perf top 15 ==="; grep -E '^\s+[0-9]+\.[0-9]+%' "$OUT/perf-report.txt" | head -15

# normal-client validation: a client does real HS GETs (BEGIN_DIR to the
# responsible HSDir) and we check they are received, with latency.
python3 - "$CHUTNEY_DATA_DIR" > "$OUT/normal-client.json" 2>"$OUT/normal.err" <<'PYV'
import sys,os,glob,socket,binascii,time,json
DATA=sys.argv[1]
def nd(n): return os.path.join(DATA,"nodes",n)
def cport(n):
    for l in open(os.path.join(nd(n),"torrc")):
        if l.lower().startswith("controlport"): return int(l.split()[1])
def onions():
    out=[]
    for d in sorted(glob.glob(os.path.join(DATA,"nodes","*h"))):
        for h in glob.glob(os.path.join(d,"hidden_service*","hostname")):
            out.append(open(h).read().strip().replace(".onion",""))
    return out
cl=sorted(glob.glob(os.path.join(DATA,"nodes","*c")))[0]
n=os.path.basename(cl); s=socket.create_connection(("127.0.0.1",cport(n)))
def line():
    b=b""
    while b"\r\n" not in b: b+=s.recv(65536)
    return b.split(b"\r\n",1)[0].decode(),b
buf=b""
def cmd(c):
    global buf
    s.sendall((c+"\r\n").encode()); out=[]
    while True:
        while b"\r\n" not in buf: buf+=s.recv(65536)
        l,buf=buf.split(b"\r\n",1); l=l.decode()
        if l.startswith("650"): out.append(("EV",l)); continue
        out.append(("R",l))
        if len(l)>=4 and l[3]==" ": break
    return out
ck=os.path.join(nd(n),"control_auth_cookie")
cmd("AUTHENTICATE "+binascii.hexlify(open(ck,"rb").read()).decode())
cmd("SETEVENTS HS_DESC")
res=[]
for onion in onions():
    cmd("HSFETCH %s"%onion)
    t0=time.time(); got=None
    s.settimeout(30)
    while time.time()-t0<30:
        while b"\r\n" not in buf:
            try: buf+=s.recv(65536)
            except socket.timeout: break
        if b"\r\n" not in buf: break
        l,buf=buf.split(b"\r\n",1); l=l.decode()
        if "HS_DESC" in l and ("RECEIVED" in l or "FAILED" in l):
            got=("RECEIVED" in l, round(time.time()-t0,3)); break
    res.append({"onion":onion[:8],"received":got[0] if got else None,
                "latency_s":got[1] if got else None})
print(json.dumps({"client":n,"fetches":res,
  "received":sum(1 for r in res if r["received"]),
  "total":len(res)}))
PYV
echo "=== normal client ==="; cat "$OUT/normal-client.json"; echo
# heartbeat/log warnings for leak/assert signals
grep -hiE 'assert|leaked|BUG|error' "$CHUTNEY_DATA_DIR/nodes/$TARGET/"*.log 2>/dev/null | grep -viE 'MetricsPort|AuthDirTestEd25519|your computer' | head -20 > "$OUT/target-warnings.txt" || true
echo "target warnings: $(wc -l < "$OUT/target-warnings.txt")"
python3 -m chutney.TorNet stop >/dev/null 2>&1 || true
echo "IN_LAB_DONE $LABEL"
