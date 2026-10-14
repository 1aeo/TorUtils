#!/bin/bash
# Runs inside a FRESH ubuntu:24.04 container (docker --network host).
# /debs = built packages (ro), /lab = private-net torrc fragment (ro).
set -x
export DEBIAN_FRONTEND=noninteractive
cat /etc/os-release | head -2
apt-get update -q >/dev/null
apt-get install -y -q --no-install-recommends /debs/tor_*_amd64.deb /debs/tor-geoipdb_*_all.deb curl procps 2>&1 | tail -n 5
dpkg -l tor tor-geoipdb | tail -n 2
tor --version
tor --verify-config; echo "verify-config(default /etc/tor/torrc) rc=$?"
# Private-lab relay: unpublished, joined ONLY to the loopback chutney authorities.
install -d -o debian-tor -g debian-tor -m 700 /var/lib/tor-lab
cat > /etc/tor/torrc-lab <<EOT
$(cat /lab/torrc-lab)
EOT
cat /etc/tor/torrc-lab
tor -f /etc/tor/torrc-lab --verify-config; echo "verify-config(lab) rc=$?"
grep -E "^(DirAuthority|TestingTorNetwork|PublishServerDescriptor|MetricsPort|Sandbox)" /etc/tor/torrc-lab
tor -f /etc/tor/torrc-lab > /var/lib/tor-lab/stdout.log 2>&1 &
TORPID=$!
sleep 20
echo "--- after 20s: Seccomp state of packaged tor (pid $TORPID)"; grep -E '^Seccomp' /proc/$TORPID/status
for i in 1 2 3 4; do
  sleep 25
  echo "--- metrics at +$((20+25*i))s"
  curl -s http://127.0.0.1:9650/metrics | grep -E 'tor_relay_dos_total\{type="hsdir|tor_relay_load_tcp_exhaustion|^tor_relay_traffic_bytes' 
done
echo "--- HSDir enforcement options as loaded (expect auto => count-only)"
grep -E "HSDir|hsdir" /var/lib/tor-lab/notice.log | head
echo "--- notice log"; cat /var/lib/tor-lab/notice.log
kill -TERM $TORPID; sleep 5; echo "exit check: $(kill -0 $TORPID 2>/dev/null && echo STILL-RUNNING || echo exited)"
grep -c "Caught a bad syscall" /var/lib/tor-lab/notice.log /var/lib/tor-lab/stdout.log
