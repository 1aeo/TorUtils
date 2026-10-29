#!/bin/bash
# Host driver: check operator/begindir-breakdown.py against one HSDir of a
# private chutney net, in a fresh lab container with NO network interface
# (--network none). The HSDir receives, at once: onion service descriptor
# fetches multiplexed on shared circuits through relays, one-hop fetches
# from an unpublished relay identity, one-hop fetches from a plain client
# (answered 503), and the network's ordinary directory traffic.
# Usage:
#   CHUTNEY=<chutney checkout> LOADCLIENT=<test-only load-client tor> \
#   OUT=<file> [IMAGE=lab24v9] [TOR_BIN=<tor bound over /usr/bin/tor>] \
#   ./run-breakdown-lab.sh
# The default image holds +tor41339.9; IMAGE=lab24v8, lab24v7 or lab24v6
# checks the tool against a +tor41339.8, .7 or .6 relay.
set -u
: "${CHUTNEY:?}" "${LOADCLIENT:?}" "${OUT:?}"
HERE=$(cd "$(dirname "$0")" && pwd)
SIM=$(cd "$HERE/../../simulator/scripts" && pwd)
TOOL=$(cd "$HERE/../../operator" && pwd)
ARGS=(--rm --network none -v "$CHUTNEY":/chutney:ro -v "$SIM":/sim:ro
  -v "$LOADCLIENT":/lc/tor:ro -v "$HERE":/bd:ro -v "$TOOL":/tool:ro)
[ -n "${TOR_BIN:-}" ] && ARGS+=(-v "$TOR_BIN":/usr/bin/tor:ro)
docker run "${ARGS[@]}" "${IMAGE:-lab24v9}" bash /bd/in-lab.sh > "$OUT" 2>&1
