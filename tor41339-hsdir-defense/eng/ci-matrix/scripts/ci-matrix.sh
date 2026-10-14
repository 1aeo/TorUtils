#!/bin/bash
# Run the CI matrix: each cell patched then unpatched, sequentially.
for cell in ${CELLS:-minimal hardened distcheck disable-relay disable-dirauth gpl nss docs tracing integration}; do
  for v in patched unpatched; do
    J=${J:-3} /work/scripts/ci-cell.sh $v $cell >/dev/null 2>&1
  done
done
echo MATRIX-DONE >> /work/logs/ci/RESULTS.txt
