#!/bin/bash
# Bring up the private loopback-only chutney net with modern chutney (3338f5c).
# usage: netup.sh <patched|unpatched>
set -uo pipefail
BASE="${1:?usage: netup.sh patched|unpatched}"
PY=/root/work/chutney-venv/bin/python3
export CHUTNEY_PATH=/root/work/chutney-main
export CHUTNEY_LISTEN_ADDRESS=127.0.0.1
export CHUTNEY_TOR_SANDBOX=0
export CHUTNEY_TOR_GENCERT=/root/bins/tor-gencert
case "$BASE" in
  patched)   export CHUTNEY_TOR=/root/bins/tor-patched;   export CHUTNEY_DATA_DIR=/root/work/net-patched;;
  unpatched) export CHUTNEY_TOR=/root/bins/tor-unpatched; export CHUTNEY_DATA_DIR=/root/work/net-unpatched;;
  *) echo "usage: netup.sh patched|unpatched"; exit 2;;
esac
cd "$CHUTNEY_PATH"
rm -rf "$CHUTNEY_DATA_DIR"; mkdir -p "$CHUTNEY_DATA_DIR"
echo "=== init ($BASE, tor=$CHUTNEY_TOR) ==="
$PY -m chutney.TorNet init --net hsflood41339 2>&1 | tail -1
$PY -m chutney.TorNet configure 2>&1 | tail -1
CHUTNEY_CONFIG_PHASE=2 $PY -m chutney.TorNet configure 2>&1 | tail -1
echo "=== start phase 1 (auth+relays) ==="
$PY -m chutney.TorNet start 2>&1 | tail -1
timeout 320 $PY -m chutney.TorNet wait_for_bootstrap 2>&1 | tail -2
echo "=== start phase 2 (clients+onions) ==="
CHUTNEY_LAUNCH_PHASE=2 $PY -m chutney.TorNet start 2>&1 | tail -1
CHUTNEY_LAUNCH_PHASE=2 timeout 320 $PY -m chutney.TorNet wait_for_bootstrap 2>&1 | tail -2
echo "NETUP_DONE $BASE"
