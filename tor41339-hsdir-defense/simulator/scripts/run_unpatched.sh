#!/bin/bash
# Tear down the patched net, bring up a fresh unpatched net (base upstream
# main, no patches), attach the load clients, and run the no-defense baseline
# matrix.  Unpatched has no enforcement option and no reuse metric, so it runs
# enforce=0 only; those metric columns record NA.
set -uo pipefail
S=.
source /root/work/chenv.sh

echo "=== teardown patched net + load clients ==="
bash $S/teardown.sh /root/work/net-patched /root/work/lc-reuse /root/work/lc-fetch

echo "=== bring up unpatched net ==="
export CHUTNEY_TOR=/root/bins/tor-unpatched
export CHUTNEY_DATA_DIR=/root/work/net-unpatched
rm -rf $CHUTNEY_DATA_DIR; mkdir -p $CHUTNEY_DATA_DIR
cd /root/work/chutney-main
python3 -m chutney.main init --net hsflood41339 --tor /root/bins/tor-unpatched \
  --tor-gencert /root/bins/tor-gencert --tor-sandbox 0 2>&1 | tail -2
python3 -m chutney.main configure 2>&1 | tail -2
python3 -m chutney.main start 2>&1 | tail -1
timeout 240 python3 -m chutney.main wait_for_bootstrap 2>&1 | tail -2
python3 -m chutney.main start --launch-phase 2 2>&1 | tail -1
timeout 200 python3 -m chutney.main wait_for_bootstrap --launch-phase 2 2>&1 | tail -2

echo "=== launch load clients against unpatched net ==="
EVIL_ISO_SESSIONGRP=1 bash $S/loadclient_up.sh /root/work/net-unpatched/nodes /root/work/lc-reuse 8020 9020 /root/bins/tor-loadclient
bash $S/loadclient_up.sh /root/work/net-unpatched/nodes /root/work/lc-fetch 8021 9021 /root/bins/tor-loadclient
# wait for load clients to bootstrap
for i in $(seq 1 40); do
  r=$(grep -h "Bootstrapped 100%" /root/work/lc-reuse/notice.log 2>/dev/null | tail -1)
  f=$(grep -h "Bootstrapped 100%" /root/work/lc-fetch/notice.log 2>/dev/null | tail -1)
  [ -n "$r" ] && [ -n "$f" ] && { echo "load clients bootstrapped"; break; }
  sleep 3
done

echo "=== run unpatched matrix ==="
python3 $S/run_matrix.py unpatched /root/work/net-unpatched/nodes 0 2 60
echo ALL_UNPATCHED_DONE
