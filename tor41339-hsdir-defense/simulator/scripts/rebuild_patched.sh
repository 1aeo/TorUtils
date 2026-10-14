#!/bin/bash
# Rebuild the patched net with a long V3AuthVotingInterval so the consensus
# (and therefore the HSDir responsible-set / hashring) is stable for the whole
# matrix.  Then relaunch the load clients and confirm ring stability.
set -uo pipefail
S=.
source /root/work/chenv.sh

echo "=== teardown old patched net + load clients ==="
bash $S/teardown.sh /root/work/net-patched /root/work/lc-reuse /root/work/lc-fetch
sleep 2

echo "=== re-init patched net (voting interval 1800s) ==="
export CHUTNEY_TOR=/root/bins/tor-patched
export CHUTNEY_DATA_DIR=/root/work/net-patched
rm -rf $CHUTNEY_DATA_DIR; mkdir -p $CHUTNEY_DATA_DIR
cd /root/work/chutney-main
python3 -m chutney.main init --net hsflood41339 --tor /root/bins/tor-patched \
  --tor-gencert /root/bins/tor-gencert --tor-sandbox 0 \
  --v3-auth-voting-interval-seconds 1800 2>&1 | tail -2
python3 -m chutney.main configure 2>&1 | tail -2
python3 -m chutney.main start 2>&1 | tail -1
timeout 300 python3 -m chutney.main wait_for_bootstrap 2>&1 | tail -2
python3 -m chutney.main start --launch-phase 2 2>&1 | tail -1
timeout 240 python3 -m chutney.main wait_for_bootstrap --launch-phase 2 2>&1 | tail -2

echo "=== launch load clients ==="
EVIL_ISO_SESSIONGRP=1 bash $S/loadclient_up.sh /root/work/net-patched/nodes /root/work/lc-reuse 8020 9020 /root/bins/tor-loadclient
bash $S/loadclient_up.sh /root/work/net-patched/nodes /root/work/lc-fetch 8021 9021 /root/bins/tor-loadclient
for i in $(seq 1 40); do
  r=$(grep -h "Bootstrapped 100%" /root/work/lc-reuse/notice.log 2>/dev/null | tail -1)
  f=$(grep -h "Bootstrapped 100%" /root/work/lc-fetch/notice.log 2>/dev/null | tail -1)
  [ -n "$r" ] && [ -n "$f" ] && { echo "load clients bootstrapped"; break; }
  sleep 3
done
echo REBUILD_PATCHED_DONE
