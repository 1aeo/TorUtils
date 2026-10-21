#!/bin/bash
# Usage: latency.sh <tor-binary> [port-base]
# 20 scrapes while healthy, then 20 while tor's main thread is stopped.
. "$(dirname "$(readlink -f "$0")")/common.sh"
start_tor "$1" latency-$$ "${2:-30000}"
scrape "$METRICS" 20 | python3 -I "$LAB/summarize.py" "healthy"
python3 -I "$LAB/stall.py" "$PID" 90 & sleep 1
scrape "$METRICS" 20 | python3 -I "$LAB/summarize.py" "main thread stopped"
kill -KILL "$PID"; wait 2>/dev/null
