#!/bin/bash
# Shared helpers for the MetricsPort lab scripts. Source, don't run.
LAB=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
WORK=${LAB_DIR:-/tmp/metricsport-lab}

# start_tor <tor-binary> <name> <port-base> [extra torrc lines...]
# Starts a throwaway relay that publishes nothing, with MetricsPort on
# 127.0.0.1:<port-base + 35>. Sets $PID, $DIR and $METRICS.
start_tor() {
  local bin=$1 name=$2 base=$3; shift 3
  DIR=$WORK/$name; METRICS=http://127.0.0.1:$((base + 35))/metrics
  rm -rf "$DIR"; mkdir -p "$DIR/data"; chmod 700 "$DIR/data"
  {
    echo "DataDirectory $DIR/data"
    echo "PidFile $DIR/tor.pid"
    echo "Log notice file $DIR/notice.log"
    echo "SocksPort 127.0.0.1:$((base + 50))"
    echo "ORPort 127.0.0.1:$((base + 1))"
    echo "AssumeReachable 1"
    echo "PublishServerDescriptor 0"
    echo "ExitRelay 0"
    echo "Nickname lab$base"
    echo "ContactInfo metricsport-lab"
    echo "MetricsPort 127.0.0.1:$((base + 35))"
    echo "MetricsPortPolicy accept 127.0.0.1"
    local l; for l in "$@"; do echo "$l"; done
  } > "$DIR/torrc"
  (cd "$DIR" && nohup "$bin" -f torrc > tor.out 2>&1 &)
  local i; for i in $(seq 1 50); do [ -s "$DIR/tor.pid" ] && break; sleep 0.2; done
  PID=$(cat "$DIR/tor.pid"); sleep 3
}

# scrape <url> <count> [curl timeout]: print "<http code> <seconds>" lines.
scrape() {
  local i; for i in $(seq 1 "$2"); do
    curl -s -m "${3:-3}" -o /dev/null -w "%{http_code} %{time_total}\n" "$1"
    sleep 0.2
  done
}
