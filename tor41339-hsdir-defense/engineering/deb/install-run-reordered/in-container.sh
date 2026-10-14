#!/bin/bash
# Runs inside a FRESH ubuntu:24.04 container (docker --network host).
# /debs = built packages (ro), /lab = private-net torrc fragment (ro).
set -x
export DEBIAN_FRONTEND=noninteractive
head -2 /etc/os-release
apt-get update -q >/dev/null
# Install ONLY the tor package (tor-geoipdb is just a Recommends).
apt-get install -y -q --no-install-recommends /debs/tor_*_amd64.deb curl procps 2>&1 | tail -n 3
dpkg -l tor tor-geoipdb 2>&1 | tail -n 2
tor --version
tor --verify-config; echo "verify-config(default /etc/tor/torrc) rc=$?"
install -d -o debian-tor -g debian-tor -m 700 /var/lib/tor-lab
cp /lab/torrc-lab /etc/tor/torrc-lab
tor -f /etc/tor/torrc-lab --verify-config; echo "verify-config(lab) rc=$?"
echo "--- enforcement option defaults (expect auto = count-only)"
install -d -m 700 /tmp/dc && printf 'DataDirectory /tmp/dc\nSocksPort 0\nLog notice stdout\n' > /tmp/dc.torrc
tor --defaults-torrc /dev/null -f /tmp/dc.torrc --dump-config full | grep -E '^(HSDirOneRequestPerCircuit|HSDirRefuseUnknownPrevHop|RefuseUnknownExits) '
tor -f /etc/tor/torrc-lab > /var/lib/tor-lab/stdout.log 2>&1 &
TORPID=$!
sleep 20
echo "--- after 20s: Seccomp state of packaged tor (pid $TORPID)"; grep -E '^Seccomp' /proc/$TORPID/status
for i in 1 2 3 4; do
  sleep 25
  echo "--- metrics at +$((20+25*i))s"
  curl -s http://127.0.0.1:9650/metrics | grep -E 'tor_relay_dos_total\{type="hsdir'
done
N=$(curl -s http://127.0.0.1:9650/metrics | grep -cE 'tor_relay_dos_total\{type="hsdir_(circ_reused|req_reused|request_total|unknown_prev_hop)"\}')
echo "HSDIR_COUNTER_SERIES=$N (expect 4)"
echo "--- bootstrap"; grep -E 'Bootstrapped 100%' /var/lib/tor-lab/notice.log | tail -n1
echo "--- enforcement log lines (expect none)"; grep -cE 'Refusing HS directory request|Closing circuit after repeated HS directory request' /var/lib/tor-lab/notice.log
echo "--- notice log"; cat /var/lib/tor-lab/notice.log
kill -TERM $TORPID; sleep 5; echo "SIGTERM exit check: $(kill -0 $TORPID 2>/dev/null && echo STILL-RUNNING || echo exited)"
kill -KILL $TORPID 2>/dev/null
echo "bad syscalls: $(cat /var/lib/tor-lab/notice.log /var/lib/tor-lab/stdout.log | grep -c 'Caught a bad syscall')"
