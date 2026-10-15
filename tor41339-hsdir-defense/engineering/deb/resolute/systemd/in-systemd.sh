#!/bin/bash
# Runs inside a booted Ubuntu 26.04 systemd container with NO network
# interface. Two loopback-only tor@ instances (CANARY, SIBLING) pointed at a
# fake loopback authority, both with the fleet's mimalloc 2.0.9 allocator.conf
# preload and Sandbox 1. Follows DEPLOY-AND-MEASURE §1 Path A + §1.1 + §6 on
# CANARY only and checks that SIBLING is never restarted.
# Mount: /debs (the resolute .deb). Stock tor = Ubuntu's archive package.
set -u
DEB=$(ls /debs/tor_*~resolute+1+tor41339.*_amd64.deb)
PRELOAD=/usr/local/lib/mimalloc/libmimalloc-2.0.9.so
say(){ echo; echo "== $*"; }
pid(){ systemctl show -p MainPID --value tor@$1; }
filters(){ awk '/^Seccomp_filters/{print $2}' /proc/$1/status; }
unitstate(){ systemctl show tor@$1 -p Type -p NotifyAccess -p ActiveState -p SubState -p NRestarts -p ExecMainStartTimestampMonotonic -p ActiveEnterTimestampMonotonic | tr '\n' ' '; echo; }
restart_timed(){ local t0=$(date +%s%N); systemctl restart tor@$1; echo "restart tor@$1 took $(( ($(date +%s%N) - t0) / 1000000 )) ms"; }
mimalloc_mapped(){ grep -c "$PRELOAD" /proc/$1/maps; }
mkctl(){ CK=/run/tor-instances/$1/control.authcookie; exec 3<>/dev/tcp/127.0.0.1/$2
  printf 'AUTHENTICATE %s\r\n%s\r\nQUIT\r\n' "$(od -An -tx1 -v $CK | tr -d ' \n')" "$3" >&3; cat <&3 | grep -v '^250 OK\|closing'; exec 3<&-; }

. /etc/os-release; say "host: $PRETTY_NAME, systemd $(systemctl --version | head -1 | awk '{print $2}'), stock tor $(dpkg-query -W -f='${Version}' tor)"
echo "interfaces: $(ls /sys/class/net | tr '\n' ' ')"
echo "mimalloc: $(cat /root/libmimalloc-2.0.9.so.sha256)"

i=0
for N in CANARY SIBLING; do
  tor-instance-create $N >/dev/null 2>&1
  cat > /etc/tor/instances/$N/torrc <<EOF
DirAuthority fake orport=1 no-v2 v3ident=0000000000000000000000000000000000000001 127.0.0.1:2 0000000000000000000000000000000000000002
UseDefaultFallbackDirs 0
Nickname ${N,,}test
ORPort 127.0.0.1:$((5000+i))
AssumeReachable 1
PublishServerDescriptor 0
ExitRelay 0
ControlPort 127.0.0.1:$((9051+i))
MetricsPort 127.0.0.1:$((9035+i))
MetricsPortPolicy accept 127.0.0.1
Sandbox 1
EOF
  mkdir -p /etc/systemd/system/tor@$N.service.d
  printf '[Service]\nEnvironment="LD_PRELOAD=%s"\n' "$PRELOAD" > /etc/systemd/system/tor@$N.service.d/allocator.conf
  i=$((i+1))
done
systemctl daemon-reload
systemctl start tor@CANARY tor@SIBLING; sleep 3
SIB0=$(pid SIBLING); C0=$(pid CANARY)
say "stock start (both Sandbox 1 + mimalloc preload)"
for N in CANARY SIBLING; do P=$(pid $N); echo "$N pid=$P exe=$(readlink /proc/$P/exe) mimalloc_mapped=$(mimalloc_mapped $P) Seccomp_filters=$(filters $P)"; unitstate $N; done

say "§1 Path A: unpack (no maintainer scripts run)"
mkdir -p /opt/tor41339 && dpkg-deb -x "$DEB" /opt/tor41339
echo "$(basename $DEB) sha256 $(sha256sum < $DEB | cut -d' ' -f1)"
echo "/opt/tor41339/usr/bin/tor sha256 $(sha256sum < /opt/tor41339/usr/bin/tor | cut -d' ' -f1)"
/opt/tor41339/usr/bin/tor --version | head -1
echo "counter strings: $(strings /opt/tor41339/usr/bin/tor | grep -c '^hsdir_\(circ_reused\|req_reused\|request_total\|unknown_prev_hop\)$')"

say "§1.1 steps 1-4 on CANARY"
apt-mark hold tor tor-geoipdb >/dev/null && echo "apt hold: $(apt-mark showhold | tr '\n' ' ')"
echo '$nrconf{override_rc}{qr(^tor\@CANARY\.service$)} = 0;' > /etc/needrestart/conf.d/tor41339.conf
echo "effective ExecStart before: $(systemctl cat tor@CANARY | grep '^ExecStart=' | tail -1)"
printf '[Service]\nExecStart=\nExecStart=/opt/tor41339/usr/bin/tor --defaults-torrc /run/tor-instances/%%i.defaults -f /etc/tor/instances/%%i/torrc\n' > /etc/systemd/system/tor@CANARY.service.d/zz-tor41339.conf
systemctl daemon-reload
echo "drop-ins: $(systemctl show tor@CANARY -p DropInPaths --value)"
echo "effective ExecStart after: $(systemctl cat tor@CANARY | grep '^ExecStart=' | tail -1)"
echo "Environment kept: $(systemctl show tor@CANARY -p Environment --value)"
/opt/tor41339/usr/bin/tor --defaults-torrc /run/tor-instances/CANARY.defaults -f /etc/tor/instances/CANARY/torrc --verify-config | tail -1
echo "SIBLING pid after daemon-reload: $(pid SIBLING) (was $SIB0)"

say "§1.1 step 5: the one CANARY restart (Sandbox 1)"
restart_timed CANARY
C1=$(pid CANARY); echo "CANARY pid $C0 -> $C1 exe=$(readlink /proc/$C1/exe) user=$(ps -o user= -p $C1) mimalloc_mapped=$(mimalloc_mapped $C1)"
unitstate CANARY
echo "Type=notify unit reached active => tor sent READY=1 (it is never 'active' before READY for Type=notify)"
journalctl -u tor@CANARY -o cat --since "-90s" | grep -iE 'Started|Bootstrapped|notif|bad syscall' | tail -4
sleep 2
curl -s http://127.0.0.1:9035/metrics | grep 'tor_relay_dos_total{type="hsdir'
mkctl CANARY 9051 "GETCONF HSDirOneRequestPerCircuit HSDirRefuseUnknownPrevHop Sandbox"
echo "SIBLING pid: $(pid SIBLING) (was $SIB0) NRestarts=$(systemctl show tor@SIBLING -p NRestarts --value)"

say "Tor Sandbox vs systemd/container filters on CANARY"
echo "unit SystemCallFilter='$(systemctl show tor@CANARY -p SystemCallFilter --value | cut -c1-60)' NoNewPrivileges=$(systemctl show tor@CANARY -p NoNewPrivileges --value) PrivateDevices=$(systemctl show tor@CANARY -p PrivateDevices --value)"
echo "Sandbox 1: Seccomp_filters=$(filters $C1)"
sed -i 's/^Sandbox 1/Sandbox 0/' /etc/tor/instances/CANARY/torrc; restart_timed CANARY; C2=$(pid CANARY)
echo "Sandbox 0: Seccomp_filters=$(filters $C2) $(mkctl CANARY 9051 'GETCONF Sandbox')"
sed -i 's/^Sandbox 0/Sandbox 1/' /etc/tor/instances/CANARY/torrc; restart_timed CANARY; C3=$(pid CANARY)
echo "Sandbox 1 again: Seccomp_filters=$(filters $C3) $(mkctl CANARY 9051 'GETCONF Sandbox') mimalloc_mapped=$(mimalloc_mapped $C3)"
echo "=> the difference is tor's own filter; the remaining filters come from systemd's unit settings and the container"

say "live controls on CANARY (no restart)"
mkctl CANARY 9051 "SETCONF HSDirOneRequestPerCircuit=1"; mkctl CANARY 9051 "GETCONF HSDirOneRequestPerCircuit"
mkctl CANARY 9051 "SETCONF HSDirOneRequestPerCircuit=0"; mkctl CANARY 9051 "GETCONF HSDirOneRequestPerCircuit"
mkctl CANARY 9051 "SETCONF HSDirRefuseUnknownPrevHop=1"; mkctl CANARY 9051 "GETCONF HSDirRefuseUnknownPrevHop"
mkctl CANARY 9051 "SETCONF HSDirRefuseUnknownPrevHop=0"; mkctl CANARY 9051 "GETCONF HSDirRefuseUnknownPrevHop"
systemctl reload tor@CANARY; sleep 1; echo "after reload tor@CANARY: $(mkctl CANARY 9051 'GETCONF HSDirOneRequestPerCircuit HSDirRefuseUnknownPrevHop' | tr '\r\n' '  ') pid=$(pid CANARY) (was $C3)"
echo "SIBLING pid: $(pid SIBLING) (was $SIB0)"

say "§6 rollback on CANARY"
rm /etc/systemd/system/tor@CANARY.service.d/zz-tor41339.conf && systemctl daemon-reload
restart_timed CANARY; C4=$(pid CANARY)
echo "CANARY exe=$(readlink /proc/$C4/exe) $(systemctl is-active tor@CANARY) mimalloc_mapped=$(mimalloc_mapped $C4)"
apt-mark unhold tor tor-geoipdb >/dev/null && rm -f /etc/needrestart/conf.d/tor41339.conf && echo "unheld: '$(apt-mark showhold | tr '\n' ' ')'"

say "SIBLING across the whole run"
echo "SIBLING pid start=$SIB0 end=$(pid SIBLING) NRestarts=$(systemctl show tor@SIBLING -p NRestarts --value) $(systemctl is-active tor@SIBLING) exe=$(readlink /proc/$(pid SIBLING)/exe)"
echo "bad syscalls in journal: $(journalctl -u 'tor@*' -o cat | grep -c 'Caught a bad syscall')"
