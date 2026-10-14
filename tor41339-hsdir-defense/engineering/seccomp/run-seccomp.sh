#!/bin/bash
# Usage: run-seccomp.sh <label> <relay-tor-binary> [relay-extra-torrc]
# Private loopback chutney net (own authorities/consensus). All nodes Sandbox 1.
set -u
LABEL=$1; RELAY_TOR=$2; EXTRA=${3:-}
STOCK=/work/src/tor-unpatched/src/app/tor
OUT=/work/eng/seccomp/out/$LABEL; rm -rf $OUT; mkdir -p $OUT
export CHUTNEY_PATH=/work/src/chutney-ci
export CHUTNEY_DATA_DIR=/work/chutney-net/seccomp-$LABEL; rm -rf $CHUTNEY_DATA_DIR; mkdir -p $CHUTNEY_DATA_DIR
export CHUTNEY_TOR=$RELAY_TOR CHUTNEY_TOR_GENCERT=$(dirname $RELAY_TOR)/../tools/tor-gencert
export STOCK_TOR=$STOCK RELAY_EXTRA="$EXTRA" CHUTNEY_TOR_SANDBOX=1
export CHUTNEY_LISTEN_ADDRESS=127.0.0.1
source /work/venv-ci/bin/activate
NET=/work/eng/seccomp/hs-v3-sandbox
{
echo "### label=$LABEL relay_tor=$RELAY_TOR ($($RELAY_TOR --version | head -1)) stock=$($STOCK --version | head -1)"
echo "### relay extra torrc: ${EXTRA:-<none>}"
date -u
chutney init --net-from-script-path $NET && chutney configure
k=0; for d in $CHUTNEY_DATA_DIR/nodes/*[ar]; do printf 'MetricsPort 127.0.0.1:%d\nMetricsPortPolicy accept 127.0.0.1\n' $((9100+k)) >> $d/torrc; k=$((k+1)); done
chutney start && chutney wait_for_bootstrap && CHUTNEY_LAUNCH_PHASE=2 chutney start && CHUTNEY_LAUNCH_PHASE=2 chutney wait_for_bootstrap
echo "### bootstrap rc=$?"
grep -h "^Sandbox" $CHUTNEY_DATA_DIR/nodes/*/torrc | sort | uniq -c
# Ordinary HS traffic: stock HS uploads (POST), stock client fetches (GET) + connects.
if [ "${STRACE:-0}" = 1 ]; then
  echo "### STRACE=1: attaching strace (failed syscalls only) to every thread of every relay/authority"
  STPIDS=""
  for d in $CHUTNEY_DATA_DIR/nodes/0*[ar]; do
    n=$(basename $d); pid=$(pgrep -f "$(readlink -f $d)/torrc" | head -n1)
    tids=$(ls /proc/$pid/task | sed 's/^/-p /' | tr '\n' ' ')
    strace -f -qq -e status=failed -o $OUT/strace-$n.txt $tids & STPIDS="$STPIDS $!"
  done
  sleep 3
fi
for i in 1 2 3; do chutney verify; echo "### verify $i rc=$?"; done
} > $OUT/transcript.txt 2>&1
echo $CHUTNEY_DATA_DIR > $OUT/datadir
{
echo "### seccomp status of every running tor process (Seccomp: 2 == filter mode)"
for pid in $(pgrep -f "$CHUTNEY_DATA_DIR/nodes"); do echo "pid=$pid $(tr '\0' ' ' < /proc/$pid/cmdline | grep -o 'nodes[^ ]*/[0-9]*[a-z]/torrc' | head -1) $(grep -E '^Seccomp(_filters)?:' /proc/$pid/status | tr '\n' ' ')"; done
ONION=$(cat $CHUTNEY_DATA_DIR/nodes/010h/hidden_service/hostname | sed 's/.onion//')
echo "### 18 ordinary single HSFETCHes, SERVER= round-robin over all 9 HSDirs, from the stock client (one at a time)"
HSDIRS=$(for d in $CHUTNEY_DATA_DIR/nodes/0*[ar]; do awk '{print $2}' $d/fingerprint; done | paste -sd,)
python3 -I /work/eng/tools/hsfetch.py $CHUTNEY_DATA_DIR/nodes/009c/control $ONION 18 $HSDIRS
echo "### DirPort probes against relay 004r (DirPort 7104) and authority 000a (7100)"
python3 -I /work/eng/seccomp/dirport-probes.py 7104
python3 -I /work/eng/seccomp/dirport-probes.py 7100
for p in $(grep -h "^MetricsPort" $CHUTNEY_DATA_DIR/nodes/*/torrc | awk '{print $2}'); do
  echo "### metrics $p"; curl -s http://$p/metrics | grep -E 'tor_relay_dos_total\{type="hsdir' ; done
sleep 5
for i in 4; do chutney verify; echo "### verify $i rc=$?"; done
if [ "${STRACE:-0}" = 1 ]; then
  kill -INT $STPIDS; sleep 3
  echo "### EPERM-returning syscalls per node (syscall + first argument), counts"
  for f in $OUT/strace-*.txt; do echo "== $(basename $f .txt | sed s/strace-//)"; grep "EPERM" $f | sed -E 's/^[0-9]+ +//; s/^([a-z0-9_]+)\(([^,)]*).*/\1(\2, ...)/' | sort | uniq -c | sort -rn; done
fi
chutney stop; echo "### stop rc=$?"; sleep 15
echo "### shutdown check: nodes that logged a shutdown signal, and any survivors"
for d in $CHUTNEY_DATA_DIR/nodes/[0-9]*; do echo "$(basename $d): $(grep -ho 'Catching signal [A-Z]*' $d/notice.log | tail -n1)"; done
for pid in $(pgrep -f "$CHUTNEY_DATA_DIR/nodes"); do echo "SURVIVOR pid=$pid $(tr '\0' ' ' < /proc/$pid/cmdline | grep -o '[0-9]*[a-z]/torrc') main_SigBlk=$(awk '/^SigBlk/{print $2}' /proc/$pid/status) ShdPnd=$(awk '/^ShdPnd/{print $2}' /proc/$pid/status)"; kill -9 $pid; done
echo "### sandbox / bug scan over all node logs"
for d in $CHUTNEY_DATA_DIR/nodes/[0-9]*; do
  n=$(basename $d)
  echo "$n: Sandbox=$(grep -h '^Sandbox' $d/torrc) bad_syscall=$(grep -c 'Caught a bad syscall' $d/notice.log $d/info.log 2>/dev/null | awk -F: '{s+=$2} END{print s}') bug=$(grep -ch '\[bug\]\|Bug:' $d/notice.log | head -1) sandbox_enabled_msgs=$(grep -ch 'sandbox' $d/notice.log | head -1) hs_get=$(grep -c 'hs/3' $d/info.log 2>/dev/null)"
done
grep -h "Caught a bad syscall" -A20 $CHUTNEY_DATA_DIR/nodes/*/notice.log | head -60
} >> $OUT/transcript.txt 2>&1
