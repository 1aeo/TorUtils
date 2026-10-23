#!/bin/bash
# Three seccomp configurations, sequentially.
P=/work/src/tor-patched/src/app/tor; U=/work/src/tor-unpatched/src/app/tor
timeout 1800 /work/eng/seccomp/run-seccomp.sh patched-default $P ""
timeout 1800 /work/eng/seccomp/run-seccomp.sh patched-enforce $P 'HSDirOneRequestPerCircuit 1\nHSDirRefuseUnknownPrevHop 1'
timeout 1800 /work/eng/seccomp/run-seccomp.sh unpatched-control $U ""
echo ALL-SECCOMP-DONE
