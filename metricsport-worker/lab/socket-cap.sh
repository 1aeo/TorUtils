#!/bin/bash
# Usage: socket-cap.sh <tor-binary> [port-base]
# Runs tor with a 256 fd limit (so max_sockets = 224), fills its sockets
# with idle SocksPort connections, then scrapes the MetricsPort.
. "$(dirname "$(readlink -f "$0")")/common.sh"
(ulimit -Sn 256; ulimit -Hn 256; start_tor "$1" socket-cap-$$ "${2:-30200}" "ConnLimit 64")
DIR=$WORK/socket-cap-$$; PID=$(cat "$DIR/tor.pid")
METRICS=http://127.0.0.1:$((${2:-30200} + 35))/metrics
python3 -I - $((${2:-30200} + 50)) <<'PY' &
import resource, socket, sys, time
resource.setrlimit(resource.RLIMIT_NOFILE, (4096, 4096))
held = []
for _ in range(400):
    s = socket.socket(); s.settimeout(2)
    try:
        s.connect(("127.0.0.1", int(sys.argv[1]))); held.append(s)
    except OSError:
        break
time.sleep(20)
PY
sleep 8
echo "tor has $(ls /proc/$PID/fd | wc -l) fds open; \"Failing because we have\" warnings: $(grep -c 'Failing because we have' "$DIR/notice.log")"
scrape "$METRICS" 5 | python3 -I "$LAB/summarize.py" "at the socket limit"
kill -KILL "$PID"; wait 2>/dev/null
