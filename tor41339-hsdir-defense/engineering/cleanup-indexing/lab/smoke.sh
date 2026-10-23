#!/bin/bash
set -uo pipefail
BIN=${1:-/work/lab/bins/tor-S1}
export CHUTNEY_PATH=/opt/chutney CHUTNEY_LISTEN_ADDRESS=127.0.0.1 CHUTNEY_TOR_SANDBOX=0
export PYTHONPATH=/opt/chutney/lib
export CHUTNEY_TOR="$BIN" CHUTNEY_TOR_GENCERT=/work/lab/bins/tor-gencert
export CHUTNEY_DATA_DIR=/tmp/net
cp /work/lab/netdef /opt/chutney/networks/hsflood41339
rm -rf "$CHUTNEY_DATA_DIR"; mkdir -p "$CHUTNEY_DATA_DIR"
cd "$CHUTNEY_PATH"
python3 -m chutney.TorNet init --net hsflood41339 2>&1 | tail -1
python3 -m chutney.TorNet configure 2>&1 | tail -1
CHUTNEY_CONFIG_PHASE=2 python3 -m chutney.TorNet configure 2>&1 | tail -1
python3 -m chutney.TorNet start 2>&1 | tail -1
timeout 300 python3 -m chutney.TorNet wait_for_bootstrap 2>&1 | tail -2
CHUTNEY_LAUNCH_PHASE=2 python3 -m chutney.TorNet start 2>&1 | tail -1
CHUTNEY_LAUNCH_PHASE=2 timeout 300 python3 -m chutney.TorNet wait_for_bootstrap 2>&1 | tail -2
echo "=== nodes ==="; ls "$CHUTNEY_DATA_DIR/nodes" 2>/dev/null
echo "=== metrics sample (first relay 004r) ==="
curl -s 127.0.0.1:19104/metrics 2>/dev/null | grep -E 'tor_relay_streams_total|^# HELP tor_relay_streams' | head
echo SMOKE_DONE
