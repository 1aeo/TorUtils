#!/bin/bash
# Launch a manual load-client tor joined to the private chutney net (loopback).
# tor-loadclient = v3 series + loadclient-testonly.diff. EVIL_ISO_SESSIONGRP,
# EVIL_ONEHOP and EVIL_EMPTY_BEGINDIR are read from this process's environment
# if exported by caller.
# usage: loadclient_up.sh <net_nodes_dir> <lc_dir> <ctlport> <socksport> <bin> [role:client|onehop]
set -euo pipefail
NET_NODES="$1"; LC_DIR="$2"; CTLPORT="$3"; SOCKSPORT="$4"; BIN="$5"; ROLE="${6:-client}"
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
  echo "ProtocolWarnings 1"
  echo "SafeLogging 0"
  echo "LogTimeGranularity 1"
  echo "Sandbox 0"
  echo "UseMicrodescriptors 1"
  echo "RunAsDaemon 0"
  if [ "$ROLE" = "onehop" ]; then
    # Unpublished relay identity: lets the generator do one-hop HS fetches
    # with a self-minted (not-in-consensus) prev hop -- exactly what 0002
    # targets. Loopback ORPort; never published to the test authorities.
    echo "ORPort 127.0.0.1:$((SOCKSPORT + 2000))"
    echo "PublishServerDescriptor 0"
    echo "AssumeReachable 1"
    echo "ExitRelay 0"
    echo "ClientOnly 0"
  fi
  # Copy the live authority set from the first client node.
  cnode=$(ls -d "$NET_NODES"/[0-9]*c | head -1)
  grep "^DirAuthority " "$cnode/torrc"
} > "$TORRC"
nohup "$BIN" -f "$TORRC" > "$LC_DIR/stdout.log" 2>&1 &
echo "LOADCLIENT_PID=$!"
echo "torrc=$TORRC ctl=$CTLPORT role=$ROLE bin=$BIN EVIL_ISO_SESSIONGRP=${EVIL_ISO_SESSIONGRP:-unset} EVIL_ONEHOP=${EVIL_ONEHOP:-unset}${EVIL_EMPTY_BEGINDIR:+ EVIL_EMPTY_BEGINDIR=$EVIL_EMPTY_BEGINDIR}"
