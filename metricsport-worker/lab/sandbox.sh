#!/bin/bash
# Usage: sandbox.sh <tor-binary> [port-base]
# Runs tor with Sandbox 1, scrapes once, and prints each thread's seccomp
# mode (2 = filtered).
. "$(dirname "$(readlink -f "$0")")/common.sh"
start_tor "$1" sandbox-$$ "${2:-30500}" "Sandbox 1"
scrape "$METRICS" 1 | python3 -I "$LAB/summarize.py" "scrape with Sandbox 1"
for t in /proc/$PID/task/*; do
  echo "  tid $(basename "$t"): $(grep Seccomp: "$t/status" | tr -s '\t ' ' ')"
done
kill -KILL "$PID"
