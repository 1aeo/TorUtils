#!/bin/bash
# After the main matrix: rerun cells that ran with PYTHONUNBUFFERED=1 inherited.
until grep -q MATRIX-DONE /work/logs/ci/RESULTS.txt; do sleep 30; done
mkdir -p /work/logs/ci/first-pass
for cell in minimal hardened distcheck disable-relay; do for v in patched unpatched; do
  [ -f /work/logs/ci/$v-$cell.log ] && mv /work/logs/ci/$v-$cell.log /work/logs/ci/first-pass/
  J=3 /work/scripts/ci-cell.sh $v $cell >/dev/null 2>&1
done; done
echo RERUN-DONE >> /work/logs/ci/RESULTS.txt
