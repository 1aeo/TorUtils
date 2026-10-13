#!/bin/bash
# Launch a manual load-client tor process joined to the private chutney net.
# This node runs the designated load-generation binary (tor-loadclient =
# v3 series + evil-client-testonly.diff); chutney's own nodes run CHUTNEY_TOR.
# Loopback only. EVIL_ISO_SESSIONGRP / EVIL_ONEHOP are read from this
# process's environment if exported by the caller.
#
# usage: loadclient_up.sh <net_nodes_dir> <lc_data_dir> <ctlport> <socksport> <tor_bin>
set -euo pipefail
NET_NODES="$1"; LC_DIR="$2"; CTLPORT="$3"; SOCKSPORT="$4"; BIN="$5"
rm -rf "$LC_DIR"; mkdir -p "$LC_DIR"; chmod 700 "$LC_DIR"
TORRC="$LC_DIR/torrc"
{
  echo "TestingTorNetwork 1"
  echo "DataDirectory $LC_DIR"
  echo "Nickname loadclient"
  echo "ConnLimit 1000"
  echo "ShutdownWaitLength 2"
  echo "AddressDisableIPv6 1"
  echo "CookieAuthentication 1"
  echo "ControlPort 127.0.0.1:$CTLPORT"
  echo "SocksPort 127.0.0.1:$SOCKSPORT"
  echo "PidFile $LC_DIR/pid"
  echo "Log notice file $LC_DIR/notice.log"
  echo "Log info file $LC_DIR/info.log"
  echo "ProtocolWarnings 1"
  echo "SafeLogging 0"
  echo "LogTimeGranularity 1"
  echo "Sandbox 0"
  echo "UseMicrodescriptors 1"
  echo "RunAsDaemon 0"
  # Copy the live authority set from a chutney client node.
  grep "^DirAuthority " "$NET_NODES/009c/torrc"
} > "$TORRC"
nohup "$BIN" -f "$TORRC" > "$LC_DIR/stdout.log" 2>&1 &
echo "LOADCLIENT_PID=$!"
echo "torrc=$TORRC ctl=$CTLPORT socks=$SOCKSPORT bin=$BIN EVIL_ISO_SESSIONGRP=${EVIL_ISO_SESSIONGRP:-unset} EVIL_ONEHOP=${EVIL_ONEHOP:-unset}"
