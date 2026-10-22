#!/bin/bash
# Host driver: run the live-control validation in a fresh 26.04 lab container
# with NO network interface (--network none). Build the image first from
# the Dockerfile in this directory. Usage:
#   CHUTNEY=<chutney checkout> LOADCLIENT=<test-only load-client tor> OUT=<dir> \
#   [IMAGE=lab26v6] [SANDBOX=1|0] [PHASE_S=40] ./run-controls.sh
set -u
: "${CHUTNEY:?}" "${LOADCLIENT:?}" "${OUT:?}"
HERE=$(cd "$(dirname "$0")" && pwd)
SIM=$(cd "$HERE/../../../../simulator/scripts" && pwd)
mkdir -p "$OUT"
docker run --rm --network none -e SANDBOX="${SANDBOX:-1}" -e PHASE_S="${PHASE_S:-40}" \
  -v "$CHUTNEY":/chutney:ro -v "$SIM":/sim:ro -v "$LOADCLIENT":/lc/tor:ro \
  -v "$HERE":/evidence:ro -v "$OUT":/out "${IMAGE:-lab26v6}" bash /evidence/in-lab.sh 2>&1 | tee "$OUT/controls-transcript.txt"
