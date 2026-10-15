#!/bin/bash
# Install-and-run check for the noble or resolute .deb. Private loopback lab ONLY:
#  1. bring up a private chutney net (its own authorities and consensus);
#  2. a FRESH $IMAGE container (default ubuntu:24.04; ubuntu:26.04 for the
#     resolute build) installs ONLY the `tor` .deb and runs an
#     unpublished relay joined to that net (Sandbox 1, MetricsPort on loopback).
# Nothing here talks to the real Tor network.
# Usage: DEBDIR=<dir with tor_*_amd64.deb> OUT=<out dir> CHUTNEY_PATH=<chutney>
#        CHUTNEY_TOR=<tor for the lab's own nodes> CHUTNEY_TOR_GENCERT=<tor-gencert>
#        VENV=<python venv with chutney> [IMAGE=ubuntu:26.04] ./run-deb-test.sh
set -u
: "${DEBDIR:?}" "${OUT:?}" "${CHUTNEY_PATH:?}" "${CHUTNEY_TOR:?}" "${CHUTNEY_TOR_GENCERT:?}" "${VENV:?}"
HERE=$(cd "$(dirname "$0")" && pwd)
IMAGE=${IMAGE:-ubuntu:24.04}
export CHUTNEY_PATH CHUTNEY_TOR CHUTNEY_TOR_GENCERT PYTHONPATH="$CHUTNEY_PATH:${PYTHONPATH:-}"
export CHUTNEY_DATA_DIR=${CHUTNEY_DATA_DIR:-/tmp/chutney-debtest} CHUTNEY_LISTEN_ADDRESS=127.0.0.1
rm -rf "$OUT" "$CHUTNEY_DATA_DIR"; mkdir -p "$OUT" "$CHUTNEY_DATA_DIR"
. "$VENV/bin/activate"
{ chutney init --net-from-script-path "$HERE/lab-net" && chutney bootstrap; echo "lab net bootstrap rc=$?"; } > "$OUT/labnet.log" 2>&1
C=$(ls -d "$CHUTNEY_DATA_DIR"/nodes/*c | head -n1)
{
grep -E "^(DirAuthority|TestingTorNetwork)" "$C/torrc"
cat <<EOT
DataDirectory /var/lib/tor-lab
User debian-tor
Nickname deblab
Address 127.0.0.1
ORPort 127.0.0.1:5650
PublishServerDescriptor 0
AssumeReachable 1
ExitRelay 0
SocksPort 0
MetricsPort 127.0.0.1:9650
MetricsPortPolicy accept 127.0.0.1
Sandbox ${DEB_SANDBOX:-1}
Log notice file /var/lib/tor-lab/notice.log
EOT
} > "$OUT/torrc-lab"
docker run --rm --network host -v "$DEBDIR":/debs:ro -v "$OUT":/lab:ro \
  -v "$HERE/in-container.sh":/run.sh:ro "$IMAGE" bash /run.sh > "$OUT/install-run-transcript.txt" 2>&1
echo "container rc=$?" >> "$OUT/install-run-transcript.txt"
chutney stop >> "$OUT/labnet.log" 2>&1
