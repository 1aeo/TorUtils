#!/bin/bash
# Controlled SIGTERM-exit check. tor runs with DisableNetwork 1 (no network
# activity at all). Usage: sigterm-repro.sh <tor-binary> <sandbox 0|1> <trials>
B=$1; SB=$2; N=$3; ok=0; stuck=0
for i in $(seq 1 $N); do
  D=$(mktemp -d "${TMPDIR:-/tmp}/sig.XXXXXX")
  printf 'DataDirectory %s\nDisableNetwork 1\nSocksPort 0\nSandbox %s\nLog notice file %s/notice.log\nRunAsDaemon 0\n' $D $SB $D > $D/torrc
  $B -f $D/torrc >/dev/null 2>&1 &
  P=$!; sleep 3
  blk=$(awk '/^SigBlk/{print $2}' /proc/$P/status 2>/dev/null); sc=$(awk '/^Seccomp:/{print $2}' /proc/$P/status 2>/dev/null)
  kill -TERM $P; for t in $(seq 1 20); do kill -0 $P 2>/dev/null || break; sleep 0.25; done
  if kill -0 $P 2>/dev/null; then stuck=$((stuck+1)); echo "  trial $i STUCK main_SigBlk=$blk Seccomp=$sc ShdPnd=$(awk '/^ShdPnd/{print $2}' /proc/$P/status)"; kill -9 $P; else ok=$((ok+1)); fi
  [ $i = 1 ] && echo "  trial 1 main_SigBlk=$blk Seccomp=$sc"
  rm -rf $D
done
echo "$(basename $(dirname $(dirname $(dirname $B)))) Sandbox=$SB: exited=$ok stuck=$stuck of $N"
