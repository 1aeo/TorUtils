#!/bin/bash
# Host driver: private chutney net up -> fresh ubuntu:24.04 container installs the
# .deb and runs an unpublished relay joined only to that net -> transcript.
set -u
OUT=${OUT:-/work/eng/deb/run/out}; DEBDIR=${DEBDIR:-/work/eng/deb/out}; rm -rf $OUT; mkdir -p $OUT
export CHUTNEY_PATH=/work/src/chutney-ci CHUTNEY_DATA_DIR=/work/chutney-net/debtest
export CHUTNEY_TOR=/work/src/tor-unpatched/src/app/tor CHUTNEY_TOR_GENCERT=/work/src/tor-unpatched/src/tools/tor-gencert
rm -rf $CHUTNEY_DATA_DIR; mkdir -p $CHUTNEY_DATA_DIR
source /work/venv-ci/bin/activate
{ chutney init --net-from-script-path /work/eng/deb/run/lab-net && chutney bootstrap; echo "lab net bootstrap rc=$?"; } > $OUT/labnet.log 2>&1
C=$(ls -d $CHUTNEY_DATA_DIR/nodes/*c | head -n1)
{
grep -E "^(DirAuthority|TestingTorNetwork)" $C/torrc
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
Log info file /var/lib/tor-lab/info.log
EOT
} > $OUT/torrc-lab
docker run --rm --network host -v $DEBDIR:/debs:ro -v $OUT:/lab:ro \
  -v /work/eng/deb/run/in-container.sh:/run.sh:ro ubuntu:24.04 bash /run.sh > $OUT/install-run-transcript.txt 2>&1
echo "container rc=$?" >> $OUT/install-run-transcript.txt
chutney stop >> $OUT/labnet.log 2>&1
