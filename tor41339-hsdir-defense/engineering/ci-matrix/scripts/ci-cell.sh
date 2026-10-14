#!/bin/bash
# Usage: ci-cell.sh <variant: patched|unpatched> <cell>
# Runs one upstream CI matrix cell via scripts/ci/ci-driver.sh in a fresh worktree.
set -u
V=$1; CELL=$2
BASE=8dbbbe6e86
PATCHES="${PATCHES:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../patches" && pwd)}"
WT=/work/ci/$V-$CELL
LOG=/work/logs/ci/$V-$CELL.log
mkdir -p /work/ci /work/logs/ci
rm -rf "$WT"; git -C /work/src/tor worktree prune
git -C /work/src/tor worktree add -q --detach "$WT" $BASE
if [ "$V" = patched ]; then
  git -C "$WT" -c user.email=ci@x -c user.name=ci am -q $PATCHES/000*.patch || { echo "AM FAILED" > $LOG; exit 2; }
fi
envs=(ON_GITLAB=no COLOR_CI=no DEBUG_CI=no MAKE_J_OPT=-j${J:-4} CI_SRCDIR="$WT" CI_BUILDDIR="$WT/build")
case $CELL in
  minimal) ;;
  hardened) envs+=(ALL_BUGS_ARE_FATAL=yes HARDENING=yes CC=clang) ;;
  distcheck) envs+=(DISTCHECK=yes CHECK=no) ;;
  docs) envs+=(DOXYGEN=yes ASCIIDOC=yes CHECK=no RUN_STAGE_BUILD=no) ;;
  integration) envs+=(CHECK=no CHUTNEY=yes CHUTNEY_MAKE_TARGET=test-network-all STEM=yes ALL_BUGS_ARE_FATAL=yes CHUTNEY_PATH=/work/src/chutney-ci STEM_PATH=/work/src/stem) ;;
  tracing) envs+=(TRACING=yes CHECK=no DISTCHECK=yes) ;;
  disable-dirauth) envs+=(DISABLE_DIRAUTH=yes) ;;
  disable-relay) envs+=(DISABLE_RELAY=yes) ;;
  gpl) envs+=(GPL=yes) ;;
  nss) envs+=(NSS=yes) ;;
  *) echo bad cell; exit 3;;
esac
cd "$WT"
start=$(date +%s)
if [ "$CELL" = integration ]; then
  source /work/venv-ci/bin/activate
  # chutney uses fixed port bases: never overlap with another lab net on this host
  while pgrep -f "[c]hutney-net/" >/dev/null; do sleep 30; done
fi
env -u PYTHONUNBUFFERED "${envs[@]}" ./scripts/ci/ci-driver.sh > "$LOG" 2>&1
rc=$?
end=$(date +%s)
# keep test logs
mkdir -p /work/logs/ci/$V-$CELL.artifacts
cp "$WT"/build/test-suite.log /work/logs/ci/$V-$CELL.artifacts/ 2>/dev/null
find "$WT/build" -maxdepth 3 -name 'test-suite.log' -path '*_build*' -exec cp {} /work/logs/ci/$V-$CELL.artifacts/distdir-test-suite.log \; 2>/dev/null
cp "$WT"/build/config.log /work/logs/ci/$V-$CELL.artifacts/ 2>/dev/null
echo "$V $CELL rc=$rc secs=$((end-start)) head=$(git -C $WT rev-parse --short HEAD)" | tee -a /work/logs/ci/RESULTS.txt
[ "${KEEP:-0}" = 1 ] || { cd /; git -C /work/src/tor worktree remove --force "$WT"; }
exit $rc
