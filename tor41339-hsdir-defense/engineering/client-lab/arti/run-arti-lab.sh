#!/bin/bash
# Host driver: run the Arti onion-service client probes in a fresh lab
# container with NO network interface (--network none): a private chutney
# net (own authorities, loopback only), an HTTP server behind its onion
# services, and an Arti client configured by mkconf.py.
# Usage:
#   ARTI=<arti binary> CHUTNEY=<chutney checkout> SIM=<simulator scripts dir> \
#   OUT=<dir> [IMAGE=lab24v5] [PROBE_ARGS="--only proof,isolation"] ./run-arti-lab.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
: "${ARTI:?set ARTI to an Arti binary}"
: "${CHUTNEY:?set CHUTNEY to a chutney checkout}" "${SIM:?set SIM to the simulator scripts dir}"
: "${OUT:=$HERE/results/run-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$OUT"
docker run --rm --network none -e PROBE_ARGS="${PROBE_ARGS:-}" -e NET="${NET:-hsflood41339}" \
  -e SANDBOX="${SANDBOX:-0}" \
  -v "$CHUTNEY":/chutney:ro -v "$SIM":/sim:ro -v "$ARTI":/arti/arti:ro \
  -v "$HERE":/harness:ro -v "$OUT":/out "${IMAGE:-lab24v5}" \
  bash /harness/in-lab-arti.sh 2>&1 | tee "$OUT/transcript.txt"
