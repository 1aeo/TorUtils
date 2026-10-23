#!/bin/bash
# Private lab (docker --network none): check begindir-breakdown.py against a
# target HSDir under four kinds of BEGIN_DIR traffic.
set -uo pipefail
export CHUTNEY_PATH=/chutney PYTHONPATH=/chutney/lib:/sim
export CHUTNEY_LISTEN_ADDRESS=127.0.0.1 CHUTNEY_DATA_DIR=/work/net
export CHUTNEY_TOR=/usr/bin/tor CHUTNEY_TOR_GENCERT=/usr/bin/tor-gencert CHUTNEY_TOR_SANDBOX=1
. /etc/os-release; echo "os: $PRETTY_NAME; tor: $(dpkg-query -W -f='${Version}' tor)"
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
python3 /bd/drive.py "$NODES"
echo "--- bad syscalls: $(cat "$NODES"/*/*.log 2>/dev/null | grep -c 'Caught a bad syscall')"
