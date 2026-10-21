#!/bin/bash
# Runs inside a FRESH ubuntu:24.04 or ubuntu:26.04 container (docker --network host).
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
echo "--- package version (expect suffix +tor41339.${REV:-4})"
V=$(dpkg-query -W -f='${Version}' tor); echo "$V"
case "$V" in *+tor41339."${REV:-4}") echo "VERSION_OK=1";; *) echo "VERSION_OK=0";; esac
echo "--- new option defaults (expect every defense off: auto with no consensus parameter, or 0)"
install -d -m 700 /tmp/dc && printf 'DataDirectory /tmp/dc\nSocksPort 0\nLog notice stdout\n' > /tmp/dc.torrc
OPTS='HSDirOneRequestPerCircuit|HSDirRefuseUnknownPrevHop|DoSBeginDirLimitEnabled|DoSBeginDirMaxStreams|HSDirDescriptorFetchLimit|HSDirDescriptorFetchRate|HSDirDescriptorFetchBurst'
tor --defaults-torrc /dev/null -f /tmp/dc.torrc --dump-config full | grep -E "^($OPTS|RefuseUnknownExits) "
echo "NEW_OPTIONS=$(tor --list-torrc-options | grep -cxE "$OPTS") (expect 7)"
# The new series: 6 tor_relay_dos_total types, 3 + 5 HSDir GET/POST
# outcomes, 2 + 2 tunneled dir request/response types, 4 connection states.
SERIES='tor_relay_dos_total\{type="(hsdir_(request_total|req_reused|circ_reused|unknown_prev_hop|fetch_over_rate)|begindir_over_max)"\}'
SERIES="$SERIES"'|tor_relay_hsdir_get_total\{action="(success|not_found|single_hop)"\}'
SERIES="$SERIES"'|tor_relay_hsdir_post_total\{action="(success|bad_url|invalid|not_newer|single_hop)"\}'
SERIES="$SERIES"'|tor_relay_dir_requests_total\{type="(non_hs|unparsed)"\}'
SERIES="$SERIES"'|tor_relay_dir_responses_total\{type="(hs_descriptor|other)"\}'
SERIES="$SERIES"'|tor_relay_dir_server_conns\{state="(command_wait|writing_hs_descriptor|writing_other|draining)"\}'
tor -f /etc/tor/torrc-lab > /var/lib/tor-lab/stdout.log 2>&1 &
TORPID=$!
sleep 20
echo "--- after 20s: Seccomp state of packaged tor (pid $TORPID)"; grep -E '^Seccomp' /proc/$TORPID/status
for i in 1 2 3 4; do
  sleep 25
  echo "--- metrics at +$((20+25*i))s"
  curl -s http://127.0.0.1:9650/metrics | grep -E "^($SERIES) "
done
N=$(curl -s http://127.0.0.1:9650/metrics | grep -cE "^($SERIES) ")
echo "NEW_METRIC_SERIES=$N (expect 22)"
curl -s http://127.0.0.1:9650/metrics | grep -E '^# TYPE tor_relay_(hsdir|dir)_'
echo "--- bootstrap"; grep -E 'Bootstrapped 100%' /var/lib/tor-lab/notice.log | tail -n1
echo "--- notice log"; cat /var/lib/tor-lab/notice.log
kill -TERM $TORPID; sleep 5; echo "SIGTERM exit check: $(kill -0 $TORPID 2>/dev/null && echo STILL-RUNNING || echo exited)"
kill -KILL $TORPID 2>/dev/null
echo "bad syscalls: $(cat /var/lib/tor-lab/notice.log /var/lib/tor-lab/stdout.log | grep -c 'Caught a bad syscall')"
