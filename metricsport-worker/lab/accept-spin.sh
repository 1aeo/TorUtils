#!/bin/bash
# Usage: accept-spin.sh <tor-binary> [port-base]
# Lowers tor's fd limit to what it has open, so accept() fails with EMFILE,
# leaves a client pending, and prints the CPU time of each thread over 3s.
. "$(dirname "$(readlink -f "$0")")/common.sh"
start_tor "$1" accept-spin-$$ "${2:-30400}"
curl -s -m 2 -o /dev/null "$METRICS"; sleep 1.5
n=$(ls /proc/$PID/fd | wc -l); prlimit --pid "$PID" --nofile=$n:$n
curl -s -m 5 -o /dev/null "$METRICS" & sleep 1
declare -A t0
for t in /proc/$PID/task/*; do t0[$t]=$(awk '{print $14 + $15}' "$t/stat"); done
sleep 3
for t in /proc/$PID/task/*; do
  echo "  tid $(basename "$t"): $(( $(awk '{print $14 + $15}' "$t/stat") - ${t0[$t]:-0} )) clock ticks in 3s"
done
wait; kill -KILL "$PID"
