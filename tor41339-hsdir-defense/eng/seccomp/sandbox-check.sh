#!/bin/bash
# Read-only seccomp evidence collector for a lab tor node (observation only).
# Usage: sandbox-check.sh <tor-datadir> [<tor-datadir> ...]
# For each node: torrc Sandbox setting, /proc Seccomp mode of its live tor
# process (2 == seccomp filter active), count of "Caught a bad syscall" in its
# logs, and its hsdir_* DoS metrics if a MetricsPort is configured.
for d in "$@"; do
  sb=$(grep -h '^Sandbox' "$d/torrc" 2>/dev/null | tail -n1)
  pid=$(pgrep -f -- "$d/torrc" | head -n1)
  sc=$([ -n "$pid" ] && grep -E '^Seccomp(_filters)?:' /proc/$pid/status | tr -s '\t\n' '  ')
  bad=$(cat "$d"/*.log 2>/dev/null | grep -c 'Caught a bad syscall')
  mp=$(grep -h '^MetricsPort' "$d/torrc" 2>/dev/null | awk '{print $2}' | head -n1)
  met=$([ -n "$mp" ] && curl -s "http://$mp/metrics" | grep -E 'tor_relay_dos_total\{type="hsdir' | tr '\n' ' ')
  echo "$(basename "$d"): ${sb:-Sandbox ?} pid=${pid:-none} ${sc:-<not running>} bad_syscall=$bad $met"
done
