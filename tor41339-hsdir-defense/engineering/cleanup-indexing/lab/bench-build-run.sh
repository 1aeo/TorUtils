#!/bin/bash
# Build libtor-testing.a for a dev tree (STATIC symbols + MOCK exported, but
# the cleanup accessors are O(1) in every build), compile+link bench_cleanup.c
# against it with the smartlist --wraps, and run it. Args: TREE LABEL
set -uo pipefail
tree=$1; label=$2
bd=/build/dev-$tree/b
srcdir=/build/dev-$tree/src
(cd "$bd" && make -j16 src/test/libtor-testing.a >/tmp/lib.log 2>&1) || { echo "lib build failed"; tail -8 /tmp/lib.log; exit 1; }
cd "$bd"
WRAPS="-Wl,--wrap=smartlist_remove -Wl,--wrap=smartlist_contains -Wl,--wrap=smartlist_del"
LIBS="-lz -levent -lssl -lcrypto -llzma -lzstd -lm -lpthread -lseccomp -lcap -levent_pthreads"
gcc -DTOR_UNIT_TESTS -I. -I"$srcdir/src" -I"$srcdir/src/ext" \
    -I"$srcdir/src/ext/trunnel" -I"$srcdir/src/trunnel" -I./src/trunnel \
    ${HOSTWORK:-/work}/bench/bench_cleanup.c -o /tmp/bench_cleanup \
    $WRAPS src/test/libtor-testing.a $LIBS 2>/tmp/cc.log
if [ $? -ne 0 ]; then echo "COMPILE/LINK FAILED"; tail -30 /tmp/cc.log; exit 1; fi
/tmp/bench_cleanup "$label"
