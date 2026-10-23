#!/bin/bash
# Stop all chutney nodes + manual load clients for a net. Modern chutney.
# usage: teardown.sh <CHUTNEY_DATA_DIR> [lc_dir ...]
set -uo pipefail
DATA="$1"; shift || true
PY=/root/work/chutney-venv/bin/python3
export CHUTNEY_PATH=/root/work/chutney-main
export CHUTNEY_DATA_DIR="$DATA"
cd /root/work/chutney-main
[ -e "$DATA/nodes" ] && $PY -m chutney.TorNet stop 2>&1 | tail -2 || true
for lc in "$@"; do [ -f "$lc/pid" ] && kill -9 "$(cat "$lc/pid")" 2>/dev/null || true; done
for p in $(pgrep -x tor-loadclient); do kill -9 "$p" 2>/dev/null || true; done
sleep 1; echo "teardown done for $DATA"
