#!/bin/bash
# Runs INSIDE a lab container started with --network none (loopback only).
# Brings up the hsflood41339 chutney net, serves HTTP behind its onion
# services, starts an Arti client pointed at the net, and runs arti_probe.py.
# Mounts: /chutney (chutney checkout, ro), /sim (simulator scripts, ro),
#         /arti/arti (arti binary, ro), /harness (this dir, ro), /out (rw).
# Env: PROBE_ARGS (extra args for arti_probe.py), NET (default hsflood41339),
#      SANDBOX (chutney nodes' Sandbox, default 0), KEEP_LOGS=1 copies logs.
set -uo pipefail
export CHUTNEY_PATH=/chutney PYTHONPATH=/chutney/lib:/sim
export CHUTNEY_LISTEN_ADDRESS=127.0.0.1 CHUTNEY_DATA_DIR=/work/net
export CHUTNEY_TOR=/usr/bin/tor CHUTNEY_TOR_GENCERT=/usr/bin/tor-gencert
export CHUTNEY_TOR_SANDBOX=${SANDBOX:-0}
NET=${NET:-hsflood41339}
. /etc/os-release
echo "os: $PRETTY_NAME; tor: $(dpkg-query -W -f='${Version}' tor); arti: $(/arti/arti --version | head -1)"
echo "interfaces: $(ls /sys/class/net | tr '\n' ' ')"
mkdir -p /work "$CHUTNEY_DATA_DIR"; cd /chutney
python3 -m chutney.TorNet init --net "$NET" 2>&1 | tail -1
python3 -m chutney.TorNet configure 2>&1 | tail -1
CHUTNEY_CONFIG_PHASE=2 python3 -m chutney.TorNet configure 2>&1 | tail -1
python3 -m chutney.TorNet start 2>&1 | tail -1
timeout 320 python3 -m chutney.TorNet wait_for_bootstrap 2>&1 | tail -1
CHUTNEY_LAUNCH_PHASE=2 python3 -m chutney.TorNet start 2>&1 | tail -1
CHUTNEY_LAUNCH_PHASE=2 timeout 320 python3 -m chutney.TorNet wait_for_bootstrap 2>&1 | tail -1
NODES=$(readlink -f "$CHUTNEY_DATA_DIR/nodes")

# Chutney onion services forward virtual port 5858 to 127.0.0.1:4747.
mkdir -p /work/www && echo "clientlab-ok" > /work/www/index.html
python3 -m http.server 4747 --bind 127.0.0.1 --directory /work/www \
  > /work/www.log 2>&1 &

# Arti client.
A=/work/arti1; mkdir -p "$A"
python3 /harness/mkconf.py "$NODES" --state "$A" --socks-port 9400 \
  --out "$A/arti.toml" || exit 1
/arti/arti proxy -c "$A/arti.toml" --disable-fs-permission-checks \
  > "$A/stdout" 2>&1 &
echo $! > "$A/pid"
for i in $(seq 1 180); do
  grep -q "Sufficiently bootstrapped" "$A/arti.log" 2>/dev/null && break
  sleep 1
done
echo "arti bootstrap: $(grep -m1 -o 'Sufficiently bootstrapped.*' "$A/arti.log" || echo NOT-BOOTSTRAPPED) after ${i}s"

python3 /harness/arti_probe.py --nodes "$NODES" --arti-log "$A/arti.log" \
  --socks 127.0.0.1:9400 --out /out/arti-probe-result.json ${PROBE_ARGS:-}
rc=$?
if [ "${KEEP_LOGS:-1}" = 1 ]; then
  mkdir -p /out/logs
  cp "$A/arti.toml" "$A/arti.log" "$A/stdout" /out/logs/ 2>/dev/null
  for n in "$NODES"/0*; do
    cp "$n/notice.log" "/out/logs/$(basename "$n")-notice.log" 2>/dev/null
  done
fi
kill "$(cat "$A/pid")" 2>/dev/null
python3 -m chutney.TorNet stop 2>&1 | tail -1
exit $rc
