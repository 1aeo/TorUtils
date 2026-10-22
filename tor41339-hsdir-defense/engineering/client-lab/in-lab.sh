#!/bin/bash
# Container entrypoint for the client-reachability lab. Runs inside the lab
# image (Ubuntu + the packaged tor + chutney's Python deps + curl), started
# with --network none: loopback only, no route anywhere. Brings up the private
# clientlab41339 chutney net, one small HTTP server every onion forwards to,
# one load client, and runs the harness (which also starts the Arti client).
#
# Mounts: /chutney (chutney checkout, ro), /sim (simulator scripts, ro),
#         /lc/tor (test-only load-client binary, ro), /lab (this dir, ro),
#         /arti/bin/arti (Arti binary, ro; absent when CLIENTS=ctor),
#         /out (results).
# Env: PHASES, PHASE_S, BUDGET, CLIENTS, SANDBOX (relays' Sandbox, default 1),
#      TOR_BIN, KEEP_LOGS (default 1).
set -uo pipefail
fail() { echo "RESULT: FAIL: $*"; exit 2; }

# Isolation check: the only interface must be loopback.
IFACES=$(ls /sys/class/net 2>/dev/null | tr '\n' ' ')
echo "interfaces: $IFACES"
for i in $IFACES; do [ "$i" = lo ] || fail "non-loopback interface $i present"; done

export CHUTNEY_PATH=/chutney PYTHONPATH=/chutney/lib:/sim
export CHUTNEY_LISTEN_ADDRESS=127.0.0.1 CHUTNEY_DATA_DIR=/work/net
export CHUTNEY_TOR=${TOR_BIN:-/usr/bin/tor} CHUTNEY_TOR_GENCERT=/usr/bin/tor-gencert
export CHUTNEY_TOR_SANDBOX=${SANDBOX:-1}
. /etc/os-release
echo "os: $PRETTY_NAME; tor: $(dpkg-query -W -f='${Version}' tor 2>/dev/null); $($CHUTNEY_TOR --version | head -1); Sandbox=$CHUTNEY_TOR_SANDBOX"
[ -x /arti/bin/arti ] && echo "arti: $(/arti/bin/arti --version | head -1)"

mkdir -p /work "$CHUTNEY_DATA_DIR"; cd /chutney
python3 -m chutney.TorNet init --net-from-script-path /lab/clientlab41339 2>&1 | tail -1
python3 -m chutney.TorNet configure 2>&1 | tail -1
CHUTNEY_CONFIG_PHASE=2 python3 -m chutney.TorNet configure 2>&1 | tail -1
python3 -m chutney.TorNet start 2>&1 | tail -1
timeout 320 python3 -m chutney.TorNet wait_for_bootstrap 2>&1 | tail -1
CHUTNEY_LAUNCH_PHASE=2 python3 -m chutney.TorNet start 2>&1 | tail -1
CHUTNEY_LAUNCH_PHASE=2 timeout 320 python3 -m chutney.TorNet wait_for_bootstrap 2>&1 | tail -1
NODES=$(readlink -f "$CHUTNEY_DATA_DIR/nodes")
[ -d "$NODES" ] || fail "chutney net did not come up"

# One small HTTP server on the shared onion target port (5858 -> 127.0.0.1:4747).
python3 -I /lab/httpd.py 4747 & HTTPD=$!
sleep 1

# One load client (joins the net on loopback; issues descriptor fetches).
EVIL_ISO_SESSIONGRP=1 bash /sim/loadclient_up.sh "$NODES" /work/lc-reuse 8090 9090 /lc/tor client | tail -1

LOAD_CTL=8090 PHASES="${PHASES:-dry}" BUDGET="${BUDGET:-16384 bytes}" \
  CLIENTS="${CLIENTS:-ctor,arti}" ARTI_BIN=/arti/bin/arti ARTI_MKCONF=/lab/arti/mkconf.py \
  python3 /lab/clientlab.py "$NODES" /out/client-lab-result.json "${PHASE_S:-60}"
RC=$?

kill "$HTTPD" 2>/dev/null
echo "--- bad syscalls across all node logs: $(cat "$NODES"/*/*.log 2>/dev/null | grep -c 'Caught a bad syscall')"
echo "--- shedding / refusal log lines:"
grep -hE 'Closing a circuit that fetched an onion service|Refusing an onion service directory request|over its onion service descriptor' "$NODES"/*/*.log 2>/dev/null | sed -E 's/^.*\] //' | sort | uniq -c | head
echo "--- per-relay Sandbox / seccomp:"
for f in "$NODES"/0*[ar]; do [ -f "$f/pid" ] || continue; printf '%s Sandbox=%s %s\n' "$(basename $f)" "$(grep -i '^Sandbox' $f/torrc | awk '{print $2}')" "$(grep -E '^Seccomp_filters' /proc/$(cat $f/pid)/status 2>/dev/null | tr -s '\t' ' ')"; done
if [ "${KEEP_LOGS:-1}" = 1 ]; then
  mkdir -p /out/logs
  cp /work/arti/arti.toml /work/arti/arti.log /out/logs/ 2>/dev/null
  cp /work/arti/stdout /out/logs/arti-stdout.log 2>/dev/null
  cp /work/lc-reuse/notice.log /out/logs/loadclient-notice.log 2>/dev/null
  for n in "$NODES"/0*; do cp "$n/notice.log" "/out/logs/$(basename "$n")-notice.log" 2>/dev/null; done
  gzip -f /out/logs/*.log 2>/dev/null
fi
exit $RC
