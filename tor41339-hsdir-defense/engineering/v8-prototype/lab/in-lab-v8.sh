#!/bin/bash
# Private lab (docker --network none): the v8 metrics prototype under five
# kinds of BEGIN_DIR traffic at one target HSDir.
set -uo pipefail
export CHUTNEY_PATH=/chutney PYTHONPATH=/chutney/lib:/sim
export CHUTNEY_LISTEN_ADDRESS=127.0.0.1 CHUTNEY_DATA_DIR=/work/net
export CHUTNEY_TOR=/usr/bin/tor CHUTNEY_TOR_GENCERT=/usr/bin/tor-gencert CHUTNEY_TOR_SANDBOX=1
. /etc/os-release; echo "os: $PRETTY_NAME; package: $(dpkg-query -W -f='${Version}' tor)"
echo "tor run by every node: $(/usr/bin/tor --version | head -1)"
ip -o link 2>/dev/null | awk '{print "iface:", $2}'
mkdir -p /work "$CHUTNEY_DATA_DIR"; cd /chutney
python3 -m chutney.TorNet init --net hsflood41339 2>&1 | tail -1
python3 -m chutney.TorNet configure 2>&1 | tail -1
CHUTNEY_CONFIG_PHASE=2 python3 -m chutney.TorNet configure 2>&1 | tail -1
python3 -m chutney.TorNet start 2>&1 | tail -1
timeout 320 python3 -m chutney.TorNet wait_for_bootstrap 2>&1 | tail -1
CHUTNEY_LAUNCH_PHASE=2 python3 -m chutney.TorNet start 2>&1 | tail -1
CHUTNEY_LAUNCH_PHASE=2 timeout 320 python3 -m chutney.TorNet wait_for_bootstrap 2>&1 | tail -1
NODES=$(readlink -f "$CHUTNEY_DATA_DIR/nodes")
EVIL_ISO_SESSIONGRP=1 bash /sim/loadclient_up.sh "$NODES" /work/lc-reuse 8020 9020 /lc/tor client | tail -1
EVIL_ONEHOP=1 bash /sim/loadclient_up.sh "$NODES" /work/lc-onehop 8022 9022 /lc/tor onehop | tail -1
EVIL_ONEHOP=1 bash /sim/loadclient_up.sh "$NODES" /work/lc-clientonehop 8024 9024 /lc/tor client | tail -1
EVIL_ISO_SESSIONGRP=1 EVIL_EMPTY_BEGINDIR=2 bash /sim/loadclient_up.sh "$NODES" /work/lc-emptymixed 8026 9026 /lc/tor client | tail -1
EVIL_ISO_SESSIONGRP=1 EVIL_EMPTY_BEGINDIR=1 bash /sim/loadclient_up.sh "$NODES" /work/lc-emptyonly 8028 9028 /lc/tor client | tail -1
python3 /v8/drive-v8.py "$NODES"
echo "--- bad syscalls: $(cat "$NODES"/*/*.log 2>/dev/null | grep -c 'Caught a bad syscall')"
T="$NODES/$(cat /work/target)"
echo "--- [warn] or worse at the target, by message: "
grep -h '\[warn\]\|\[err\]' "$T"/notice.log 2>/dev/null | sed 's/^.*\] //' | sort | uniq -c | sort -rn | head -12
echo "--- protocol warnings at the target, with the info line before each: "
grep -h -B1 'away from origin' "$T"/info.log 2>/dev/null | sed 's/^[A-Z][a-z][a-z] [0-9]* [0-9:.]* //' | head -12
