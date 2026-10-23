#!/bin/bash
# Runs inside a FRESH ubuntu:24.04 or ubuntu:26.04 container (docker --network host).
# /debs = built packages (ro), /lab = private-net torrc fragment (ro).
# Exits nonzero if any check fails. REV is the expected +tor41339.N suffix.
set -xuo pipefail
: "${REV:?}"
fail=0
check() { "$@" || { echo "FAIL: $*"; fail=1; }; }
export DEBIAN_FRONTEND=noninteractive
head -2 /etc/os-release
apt-get update -q >/dev/null
# Install ONLY the tor package (tor-geoipdb is just a Recommends).
apt-get install -y -q --no-install-recommends /debs/tor_*_amd64.deb curl procps > /tmp/apt.log 2>&1 || { tail -n 20 /tmp/apt.log; exit 1; }
dpkg -l tor tor-geoipdb 2>&1 | tail -n 2
tor --version
tor --verify-config; rc=$?; echo "verify-config(default /etc/tor/torrc) rc=$rc"; check [ $rc -eq 0 ]
install -d -o debian-tor -g debian-tor -m 700 /var/lib/tor-lab
cp /lab/torrc-lab /etc/tor/torrc-lab
tor -f /etc/tor/torrc-lab --verify-config; rc=$?; echo "verify-config(lab) rc=$rc"; check [ $rc -eq 0 ]
echo "--- package version (expect suffix +tor41339.$REV)"
V=$(dpkg-query -W -f='${Version}' tor); echo "$V"
check [ "${V##*+tor41339.}" = "$REV" ]
echo "--- new option defaults (expect every defense off: auto with no consensus parameter, or 0)"
install -d -m 700 /tmp/dc && printf 'DataDirectory /tmp/dc\nSocksPort 0\nLog notice stdout\n' > /tmp/dc.torrc
OPTS='HSDirOneRequestPerCircuit|HSDirRefuseUnknownPrevHop|DoSBeginDirLimitEnabled|DoSBeginDirMaxStreams|HSDirDescriptorFetchRate|HSDirDescriptorFetchBurst|HSDirFetchShedding|HSDirFetchBudget'
tor --defaults-torrc /dev/null -f /tmp/dc.torrc --dump-config full | grep -E "^($OPTS|RefuseUnknownExits) "
NO=$(tor --list-torrc-options | grep -cxE "$OPTS"); echo "NEW_OPTIONS=$NO (expect 8)"; check [ "$NO" -eq 8 ]
echo "--- the +tor41339.6 name of HSDirFetchShedding still works, with a warning (Debian-only patch)"
printf 'HSDirDescriptorFetchLimit 1\n' | cat /tmp/dc.torrc - > /tmp/dc-old.torrc
OLDOPT=$(tor --defaults-torrc /dev/null -f /tmp/dc-old.torrc --verify-config 2>&1)
echo "$OLDOPT" | grep -E 'deprecated|Configuration was valid'
check grep -q "The configuration option 'HSDirDescriptorFetchLimit' is deprecated; use 'HSDirFetchShedding' instead." <<< "$OLDOPT"
check grep -q 'Configuration was valid' <<< "$OLDOPT"
OLDV=$(tor --defaults-torrc /dev/null -f /tmp/dc-old.torrc --dump-config short 2>/dev/null | grep -E '^HSDirFetchShedding ')
echo "$OLDV (expect HSDirFetchShedding 1)"; check [ "$OLDV" = "HSDirFetchShedding 1" ]
# The new series, by family: the exact labels tor writes (keys, values and
# order) and how many series there must be. The 11 new tor_relay_dos_total
# types and every series of each new family, 132 in all: no unset previous
# hop, no misspelled label, nothing missing.
HOP='prev_hop="(client|known_relay|unknown_relay)"'
TYPE='type="(hs_get|hs_post|consensus|microdesc|descriptor|other_get|other_post|unparsed|no_request)"'
BAND='nth="(1|2_10|11_100|101_1000|1001_plus)"'
EXPECT="tor_relay_dos_total type=\"(hsdir_(req_reused|circ_reused|unknown_prev_hop|descriptor_only_prev_hop|fetch_over_rate|fetch_pressure|fetch_shed)|begindir_over_(max|stream_rate)|circuit_(over_rate|untracked))\" 11
tor_relay_hsdir_fetch_total action=\"(success|not_found|single_hop|circuit_dead|refused)\" 5
tor_relay_hsdir_upload_total action=\"(success|bad_url|invalid|not_newer|single_hop|circuit_dead|refused)\" 7
tor_relay_hsdir_fetch_descriptor_total lookup=\"(found|not_found)\",$BAND 10
tor_relay_begindir_request_total $TYPE,$HOP 27
tor_relay_begindir_request_over_max_total $TYPE 9
tor_relay_begindir_response_total type=\"(hs_descriptor|other)\" 2
tor_relay_begindir_response_bytes_total $TYPE 9
tor_relay_begindir_connections state=\"(command_wait|writing_hs_descriptor|writing_other|draining)\" 4
tor_relay_begindir_cell_total $HOP,$BAND 15
tor_relay_begindir_cell_source_total $HOP,$BAND 15
tor_relay_create_cell_total $HOP 3
tor_relay_create_cell_source_total $HOP,$BAND 15"
SERIES=$(while read -r f l n; do printf '|%s\\{%s\\}' "$f" "$l"; done <<< "$EXPECT")
SERIES=${SERIES#|}
tor -f /etc/tor/torrc-lab > /var/lib/tor-lab/stdout.log 2>&1 &
TORPID=$!
sleep 20
check kill -0 $TORPID
echo "--- after 20s: Seccomp state of packaged tor (pid $TORPID)"; grep -E '^Seccomp' /proc/$TORPID/status
for i in 1 2 3 4; do
  sleep 25
  echo "--- +$((20+25*i))s: $(curl -s http://127.0.0.1:9650/metrics | grep -cE "^($SERIES) ") new series"
done
curl -s http://127.0.0.1:9650/metrics > /tmp/metrics.txt
N=$(grep -E "^($SERIES) " /tmp/metrics.txt | cut -d' ' -f1 | sort -u | wc -l)
echo "NEW_METRIC_SERIES=$N (expect 132)"; check [ "$N" -eq 132 ]
while read -r f l n; do
  e=$(grep -E "^$f\{$l\} " /tmp/metrics.txt | cut -d' ' -f1 | sort -u | wc -l)
  echo "$f: $e (expect $n)"; check [ "$e" -eq "$n" ]
  # Nothing else in a new family; tor_relay_dos_total also has stock types.
  if [ "$f" != tor_relay_dos_total ]; then
    a=$(grep -cE "^$f\{" /tmp/metrics.txt); check [ "$a" -eq "$n" ]
  fi
done <<< "$EXPECT"
# Names that +tor41339.7 replaced: none of their series may remain.
GONE=$(grep -cE '^tor_relay_(dir_requests_total|dir_responses_total|dir_server_conns|begindir_streams_total|begindir_requests_total|begindir_over_max_requests_total|hsdir_get_total|hsdir_post_total|hsdir_fetch_target_total)\{|^tor_relay_dos_total\{type="hsdir_request(_total)?"\}|lookup="missing"' /tmp/metrics.txt)
echo "replaced names: $GONE series (expect 0)"; check [ "$GONE" -eq 0 ]
grep -E "^($SERIES) " /tmp/metrics.txt
grep -E '^# TYPE tor_relay_(hsdir|create|begindir)_' /tmp/metrics.txt
echo "--- bootstrap"; check grep -qE 'Bootstrapped 100%' /var/lib/tor-lab/notice.log
echo "--- notice log"; cat /var/lib/tor-lab/notice.log
kill -TERM $TORPID; sleep 5; echo "SIGTERM exit check: $(kill -0 $TORPID 2>/dev/null && echo STILL-RUNNING || echo exited)"
kill -KILL $TORPID 2>/dev/null
BAD=$(cat /var/lib/tor-lab/notice.log /var/lib/tor-lab/stdout.log | grep -c 'Caught a bad syscall'); echo "bad syscalls: $BAD"; check [ "$BAD" -eq 0 ]
echo "RESULT: $([ $fail -eq 0 ] && echo PASS || echo FAIL)"
exit $fail
