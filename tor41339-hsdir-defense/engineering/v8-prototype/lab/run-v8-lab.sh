#!/bin/bash
# Host driver: run the v8 metrics prototype (a tor built from ../prototype.diff
# on +tor41339.7) as every node of a private chutney net, in a fresh lab
# container with NO network interface (--network none), and drive BEGIN_DIR
# traffic at one HSDir: descriptor fetches multiplexed on shared circuits,
# one-hop fetches from an unpublished relay identity and from a plain client,
# and BEGIN_DIR streams that never send a request.
# Usage:
#   CHUTNEY=<chutney checkout> LOADCLIENT=<test-only load-client tor> \
#   OUT=<file> [TOR_BIN=<prototype tor>] [IMAGE=lab24v7] ./run-v8-lab.sh
# Without TOR_BIN, the nodes run the image's +tor41339.7 package: the same
# load as a control.
set -u
: "${CHUTNEY:?}" "${LOADCLIENT:?}" "${OUT:?}"
HERE=$(cd "$(dirname "$0")" && pwd)
SIM=$(cd "$HERE/../../../simulator/scripts" && pwd)
TOOL=$(cd "$HERE/../../../operator" && pwd)
ARGS=(--rm --network none -v "$CHUTNEY":/chutney:ro -v "$SIM":/sim:ro
  -v "$LOADCLIENT":/lc/tor:ro -v "$HERE":/v8:ro -v "$TOOL":/tool:ro)
[ -n "${TOR_BIN:-}" ] && ARGS+=(-v "$TOR_BIN":/usr/bin/tor:ro)
docker run "${ARGS[@]}" "${IMAGE:-lab24v7}" bash /v8/in-lab-v8.sh > "$OUT" 2>&1
