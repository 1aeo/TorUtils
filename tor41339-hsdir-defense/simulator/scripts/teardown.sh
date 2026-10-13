#!/bin/bash
# Stop all chutney nodes and manual load clients for a given net, cleanly.
# usage: teardown.sh <CHUTNEY_DATA_DIR> [lc_dir ...]
set -uo pipefail
DATA="$1"; shift || true
source /root/work/chenv.sh
export CHUTNEY_DATA_DIR="$DATA"
cd /root/work/chutney-main
python3 -m chutney.main stop 2>&1 | tail -3 || true
# kill manual load clients by their pidfile
for lc in "$@"; do
  if [ -f "$lc/pid" ]; then kill -9 "$(cat "$lc/pid")" 2>/dev/null || true; fi
done
# any surviving load clients (exact comm name -- safe for this shell)
for p in $(pgrep -x tor-loadclient); do kill -9 "$p" 2>/dev/null || true; done
sleep 1
echo "teardown done for $DATA"
