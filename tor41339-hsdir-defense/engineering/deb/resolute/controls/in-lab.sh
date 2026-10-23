#!/bin/bash
# Runs inside the lab26 image (Ubuntu 26.04 + the resolute .deb + chutney's
# Python deps) started with --network none: loopback only, no route anywhere.
# Mounts: /chutney (chutney checkout, ro), /sim (simulator scripts, ro),
#         /lc/tor (test-only load-client binary, ro), /evidence (this dir), /out.
# SANDBOX=1|0 sets Sandbox for every chutney node (default 1).
set -uo pipefail
export CHUTNEY_PATH=/chutney PYTHONPATH=/chutney/lib:/sim
export CHUTNEY_LISTEN_ADDRESS=127.0.0.1 CHUTNEY_DATA_DIR=/work/net
export CHUTNEY_TOR=/usr/bin/tor CHUTNEY_TOR_GENCERT=/usr/bin/tor-gencert
export CHUTNEY_TOR_SANDBOX=${SANDBOX:-1}
. /etc/os-release; echo "os: $PRETTY_NAME; tor: $(dpkg-query -W -f='${Version}' tor); Sandbox=$CHUTNEY_TOR_SANDBOX"
ip -o link 2>/dev/null | awk '{print "iface:", $2}' || cat /proc/net/dev | tail -n +3 | awk '{print "iface:", $1}'
mkdir -p /work "$CHUTNEY_DATA_DIR"; cd /chutney
python3 -m chutney.TorNet init --net hsflood41339 2>&1 | tail -1
python3 -m chutney.TorNet configure 2>&1 | tail -1
CHUTNEY_CONFIG_PHASE=2 python3 -m chutney.TorNet configure 2>&1 | tail -1
python3 -m chutney.TorNet start 2>&1 | tail -1
timeout 320 python3 -m chutney.TorNet wait_for_bootstrap 2>&1 | tail -1
CHUTNEY_LAUNCH_PHASE=2 python3 -m chutney.TorNet start 2>&1 | tail -1
CHUTNEY_LAUNCH_PHASE=2 timeout 320 python3 -m chutney.TorNet wait_for_bootstrap 2>&1 | tail -1
NODES=$(readlink -f "$CHUTNEY_DATA_DIR/nodes")
EVIL_ISO_SESSIONGRP=1 bash /sim/loadclient_up.sh "$NODES" /work/lc-reuse 8020 9020 /lc/tor client | tail -1
EVIL_ONEHOP=1 bash /sim/loadclient_up.sh "$NODES" /work/lc-onehop 8022 9022 /lc/tor onehop | tail -1
python3 /evidence/controls.py "$NODES" /out/controls-result.json "${PHASE_S:-40}"
echo "--- bad syscalls across all node logs: $(cat "$NODES"/*/*.log 2>/dev/null | grep -c 'Caught a bad syscall')"
echo "--- defense log lines (need ProtocolWarnings; chutney sets it):"
grep -hE 'Closing a circuit that (made more than one|fetched an) onion service|Refusing an onion service directory request' "$NODES"/*/*.log 2>/dev/null | sed -E 's/^.*\] //; s/relay .*\./relay <peer>./' | sort | uniq -c | head
echo "--- heartbeat DoS lines at the end (target relays):"
for f in "$NODES"/00[4-9]r/notice.log; do grep -h 'DoS mitigation since startup' "$f" | tail -n1 | sed 's/^.*\] //'; done | sort | uniq -c
for f in "$NODES"/0*r; do printf '%s Sandbox=%s %s\n' "$(basename $f)" "$(grep -i '^Sandbox' $f/torrc | awk '{print $2}')" "$(grep -E '^Seccomp_filters' /proc/$(cat $f/pid)/status | tr -s '\t' ' ')"; done
