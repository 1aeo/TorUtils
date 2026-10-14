#!/bin/bash
# Read-only seccomp evidence collector for a lab tor node (observation only).
# Usage: sandbox-check.sh <tor-datadir> [<tor-datadir> ...]
# NOTE: the tor sandbox default action is EPERM, not SIGSYS, so a 0 count of
# "Caught a bad syscall" alone does not prove no syscall was denied. Pair it
# with the strace EPERM audit: set STRACE_SECS=<n> (needs strace, root/ptrace).
# For each node: torrc Sandbox setting, /proc Seccomp mode of its live tor
# process (2 == seccomp filter active), count of "Caught a bad syscall" in its
# logs, and its hsdir_* DoS metrics if a MetricsPort is configured.
for d in "$@"; do
  d=$(readlink -f "$d")   # chutney nodes/ is a symlink to nodes.<ts>/; tor argv has the real path
  sb=$(grep -h '^Sandbox' "$d/torrc" 2>/dev/null | tail -n1)
  pid=$(pgrep -f -- "$d/torrc" | head -n1)
  sc=$([ -n "$pid" ] && grep -E '^Seccomp(_filters)?:' /proc/$pid/status | tr -s '\t\n' '  ')
  bad=$(cat "$d"/*.log 2>/dev/null | grep -c 'Caught a bad syscall')
  mp=$(grep -h '^MetricsPort' "$d/torrc" 2>/dev/null | awk '{print $2}' | head -n1)
  met=$([ -n "$mp" ] && curl -s "http://$mp/metrics" | grep -E 'tor_relay_dos_total\{type="hsdir' | tr '\n' ' ')
  echo "$(basename "$d"): ${sb:-Sandbox ?} pid=${pid:-none} ${sc:-<not running>} bad_syscall=$bad $met"
  # Optional EPERM audit: STRACE_SECS=<n> attaches strace (failed syscalls only)
  # to every thread of the live process for n seconds while traffic runs, then
  # lists syscalls that returned EPERM. Under tor's filter (default action
  # EPERM), a stock build shows only rt_sigprocmask(SIG_BLOCK, ...) here,
  # from glibc pthread_create (upstream tor#41060). Anything else = denied.
  if [ -n "${STRACE_SECS:-}" ] && [ -n "$pid" ]; then
    tf=$(mktemp); tids=$(ls /proc/$pid/task | sed 's/^/-p /' | tr '\n' ' ')
    timeout -s INT "$STRACE_SECS" strace -f -qq -e status=failed -o "$tf" $tids 2>/dev/null
    echo "  EPERM syscalls over ${STRACE_SECS}s:"
    grep EPERM "$tf" | sed -E 's/^[0-9]+ +//; s/^([a-z0-9_]+)\(([^,)]*).*/\1(\2, ...)/' | sort | uniq -c | sed 's/^/   /'
    rm -f "$tf"
  fi
done
