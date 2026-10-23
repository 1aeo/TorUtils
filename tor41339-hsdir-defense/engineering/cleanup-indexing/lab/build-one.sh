#!/bin/bash
# Build one exported source tree out of tree and run its checks.
# Runs inside the tor41350-build:2404 container (network disabled).
# usage: build-one.sh NAME MODE -- CONFIGURE_ARGS...
#   MODE: check   = make, make check, check-best-practices
#         build   = make only
set -uo pipefail
name=$1; mode=$2; shift 2; [ "${1:-}" = "--" ] && shift
src=/work/build/src/$name
obj=/build/$name
logs=/work/logs/$name
J=${J:-8}
mkdir -p "$logs"
rm -rf "$obj"; mkdir -p "$obj"
cp -a "$src" "$obj/src"
{
  echo "name=$name mode=$mode date=$(date -u +%FT%TZ)"
  echo "configure_args=$*"
  echo "CFLAGS=${CFLAGS:-} CPPFLAGS=${CPPFLAGS:-} LDFLAGS=${LDFLAGS:-}"
  gcc --version | head -1; ld --version | head -1
  dpkg-query -W -f='${Package} ${Version}\n' libevent-dev libssl-dev zlib1g-dev liblzma-dev libzstd-dev libseccomp-dev libcap-dev python3 perl 2>/dev/null
  uname -r; nproc
  cat "$src/.source-id" 2>/dev/null
} > "$logs/env.txt" 2>&1
cd "$obj/src" && ./autogen.sh > "$logs/autogen.log" 2>&1 || { echo "autogen failed rc=$?" > "$logs/RESULT"; exit 1; }
mkdir -p "$obj/b" && cd "$obj/b"
../src/configure "$@" > "$logs/configure.log" 2>&1; rc=$?
[ $rc -ne 0 ] && { echo "configure failed rc=$rc" > "$logs/RESULT"; exit 1; }
make -j"$J" > "$logs/make.log" 2>&1; rc=$?
echo "make rc=$rc" > "$logs/RESULT"
[ $rc -ne 0 ] && exit 1
if [ "$mode" = check ]; then
  make -j"$J" check > "$logs/check.log" 2>&1; rc=$?
  echo "check rc=$rc" >> "$logs/RESULT"
  cp -f test-suite.log "$logs/" 2>/dev/null
  for f in src/test/*.log; do cp -f "$f" "$logs/" 2>/dev/null; done
  make check-best-practices > "$logs/practracker.log" 2>&1; rc2=$?
  echo "practracker rc=$rc2" >> "$logs/RESULT"
  make check-spaces > "$logs/check-spaces.log" 2>&1; echo "check-spaces rc=$?" >> "$logs/RESULT"
fi
cat "$logs/RESULT"
