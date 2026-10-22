#!/bin/bash
# Host driver for the onion-service client-reachability lab (ticket 41339).
#
# Starts ONE fresh lab container with NO network interface (--network none):
# a private chutney net (own authorities, loopback only), an HTTP server
# behind its onion services, a test-only load client, a stock C tor client
# probe and an Arti client probe. Nothing can reach any real network. Every
# input is mounted read-only; results go to $OUT.
#
# Usage:
#   CHUTNEY=<chutney checkout> LOADCLIENT=<test-only load-client tor binary> \
#   OUT=<results dir> [IMAGE=lab24v5] [ARTI=<arti binary>|none] \
#   [PHASES=dry|full|B0,C0,...] [PHASE_S=60] [BUDGET="<n> bytes"] \
#   [TOR_BIN=<tor binary bound over /usr/bin/tor>] [SIM=<simulator scripts>] \
#   [SANDBOX=1|0] ./run-client-lab.sh
#
# Exit status 0 and a last line "RESULT: PASS" only if every client
# bootstrapped and every baseline (B0) fetch succeeded; otherwise nonzero
# and "RESULT: FAIL: <reason>".
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
: "${CHUTNEY:?set CHUTNEY to the chutney checkout}"
: "${LOADCLIENT:?set LOADCLIENT to the test-only load-client tor binary}"
: "${OUT:?set OUT to an output directory}"
IMAGE=${IMAGE:-lab24v6}
: "${ARTI:?set ARTI to an Arti binary, or ARTI=none for the C tor client only}"
SIM=${SIM:-${SIM_DIR:-$HERE/../../simulator/scripts}}
PHASES=${PHASES:-dry}
PHASE_S=${PHASE_S:-60}
mkdir -p "$OUT" || { echo "RESULT: FAIL: cannot create OUT=$OUT"; exit 1; }
LOG="$OUT/client-lab-transcript.txt"
fail() { echo "RESULT: FAIL: $*" | tee -a "$LOG"; exit 1; }
: > "$LOG"

docker image inspect "$IMAGE" >/dev/null 2>&1 || fail "docker image $IMAGE not found"
[ -d "$CHUTNEY/lib/chutney" ] || fail "CHUTNEY=$CHUTNEY is not a chutney checkout"
[ -x "$LOADCLIENT" ] || fail "LOADCLIENT=$LOADCLIENT is not executable"
[ -f "$SIM/sim.py" ] && [ -f "$SIM/ctl_lib.py" ] || fail "SIM=$SIM lacks sim.py/ctl_lib.py"
[ -f "$HERE/arti/mkconf.py" ] || fail "$HERE/arti/mkconf.py missing"

ARGS=(--rm --network none --name "clientlab-$$"
  -e PHASES="$PHASES" -e PHASE_S="$PHASE_S" -e BUDGET="${BUDGET:-16384 bytes}"
  -e SANDBOX="${SANDBOX:-1}" -e KEEP_LOGS="${KEEP_LOGS:-1}"
  -v "$CHUTNEY":/chutney:ro -v "$SIM":/sim:ro -v "$LOADCLIENT":/lc/tor:ro
  -v "$HERE":/lab:ro -v "$OUT":/out)
if [ "$ARTI" = none ]; then
  ARGS+=(-e CLIENTS=ctor)
else
  [ -x "$ARTI" ] || fail "ARTI=$ARTI is not an executable Arti binary (ARTI=none skips Arti)"
  ARGS+=(-e CLIENTS=ctor,arti -v "$ARTI":/arti/bin/arti:ro)
fi
if [ -n "${TOR_BIN:-}" ]; then
  [ -x "$TOR_BIN" ] || fail "TOR_BIN=$TOR_BIN is not executable"
  ARGS+=(-e TOR_BIN=/usr/bin/tor -v "$TOR_BIN":/usr/bin/tor:ro)
fi
[ -n "${DOCKER_CPUS:-}" ] && ARGS+=(--cpus "$DOCKER_CPUS")

trap 'docker kill "clientlab-$$" >/dev/null 2>&1; fail "interrupted"' INT TERM
echo "client lab: image=$IMAGE phases=$PHASES phase_s=$PHASE_S arti=$( [ "$ARTI" = none ] && echo none || basename "$ARTI") out=$(basename "$OUT")" | tee -a "$LOG"
docker run "${ARGS[@]}" "$IMAGE" bash /lab/in-lab.sh 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
echo "client lab: wall time ${SECONDS} s" | tee -a "$LOG"

if [ "$RC" -eq 0 ] && grep -q '^RESULT: PASS' "$LOG" && [ -s "$OUT/client-lab-result.json" ]; then
  PASSLINE=$(grep -m1 '^RESULT: PASS' "$LOG"); echo "$PASSLINE" | tee -a "$LOG"
  exit 0
fi
grep -q '^RESULT: FAIL' "$LOG" || echo "RESULT: FAIL: container exited $RC without a PASS result" | tee -a "$LOG"
exit $(( RC == 0 ? 1 : RC ))
