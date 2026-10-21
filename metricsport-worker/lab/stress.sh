#!/bin/bash
# Usage: stress.sh <tor-binary> [seconds] [port-base]
# Four scrapers hit two MetricsPort ports while SIGHUP flips the configured
# port and MetricsPortPolicy every 0.7s, with one 4s main-thread stall; then
# SIGTERM. For a ThreadSanitizer build, reports are counted from tor.out.
. "$(dirname "$(readlink -f "$0")")/common.sh"
SECS=${2:-40} B=${3:-30300}
start_tor "$1" stress-$$ "$B"
cp "$DIR/torrc" "$DIR/torrc.a"
sed -e "s/^MetricsPort .*/MetricsPort 127.0.0.1:$((B + 36))/" \
    -e "s|^MetricsPortPolicy .*|MetricsPortPolicy reject 1.2.3.4, accept 127.0.0.0/8|" \
    "$DIR/torrc.a" > "$DIR/torrc.b"
end=$(( $(date +%s) + SECS ))
for w in 1 2 3 4; do
  ( while [ "$(date +%s)" -lt $end ]; do
      for p in $((B + 35)) $((B + 36)); do
        curl -s -m 3 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:$p/metrics
      done
    done > "$DIR/scrapes.$w" ) &
done
i=0
while [ "$(date +%s)" -lt $end ] && kill -0 "$PID" 2>/dev/null; do
  i=$((i + 1)); cp "$DIR/torrc.$( [ $((i % 2)) = 0 ] && echo a || echo b)" "$DIR/torrc"
  kill -HUP "$PID"; sleep 0.7
  [ $i = 10 ] && python3 -I "$LAB/stall.py" "$PID" 4
done
wait
kill -TERM "$PID" 2>/dev/null
for j in $(seq 1 50); do kill -0 "$PID" 2>/dev/null || break; sleep 0.2; done
kill -0 "$PID" 2>/dev/null && echo "tor still running after SIGTERM" || echo "tor exited"
echo "SIGHUPs: $i"
cat "$DIR"/scrapes.* | sort | uniq -c | sed 's/^/  HTTP status /'
echo "BUG() warnings: $(grep -c 'tor_bug_occurred_' "$DIR/notice.log")"
grep -h "^SUMMARY: ThreadSanitizer" "$DIR/tor.out" | sed 's|^SUMMARY: ThreadSanitizer: ||; s| /[^ ]*/src/| src/|' | sort | uniq -c
grep -E "\[(warn|err)\]" "$DIR/notice.log" | grep -v "running Tor as root" | sed 's/^.*\] //' | sort | uniq -c | head
