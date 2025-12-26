#!/bin/bash
#
# diagnostics.sh - Tor relay system diagnostics for memory troubleshooting
#
# Collects system-level information to help compare memory behavior across servers.
# Can output as human-readable text or JSON for programmatic use.
#
# Usage:
#   ./diagnostics.sh                    # Human-readable output
#   ./diagnostics.sh --json             # JSON output
#   ./diagnostics.sh --csv              # CSV header + values (for logging)
#   ./diagnostics.sh --append FILE      # Append diagnostics to CSV file

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/common.sh"

OUTPUT_FORMAT="text"
APPEND_FILE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --json) OUTPUT_FORMAT="json"; shift ;;
        --csv) OUTPUT_FORMAT="csv"; shift ;;
        --append) APPEND_FILE="$2"; OUTPUT_FORMAT="csv"; shift 2 ;;
        --help|-h)
            cat <<EOF
Usage: $0 [options]

Collect system diagnostics for Tor relay memory troubleshooting.

Options:
  --json           Output as JSON
  --csv            Output as CSV (header + values)
  --append FILE    Append to CSV file (creates if doesn't exist)
  --help, -h       Show this help

Diagnostics collected:
  - Hostname, date/time
  - Tor version and build info
  - OS release and kernel version
  - Memory allocator in use (glibc/jemalloc/tcmalloc)
  - System memory (total, free, cached, swap)
  - TCP connection count
  - File descriptor limits
  - Number of relays and total memory

Examples:
  $0                           # Human-readable report
  $0 --json                    # JSON for scripting
  $0 --append /var/log/tor_diagnostics.csv  # Log to CSV
EOF
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Collect diagnostics
collect_diagnostics() {
    local hostname=$(hostname -s)
    local date_str=$(date_ymd)
    local time_str=$(time_hms)
    
    # Tor version
    local tor_version=$(tor --version 2>/dev/null | head -1 | sed 's/Tor version //' || echo "unknown")
    
    # OS info
    local os_release=$(grep -E "^(PRETTY_NAME|VERSION_ID)" /etc/os-release 2>/dev/null | head -1 | cut -d= -f2 | tr -d '"' || echo "unknown")
    local kernel=$(uname -r)
    
    # Memory allocator
    local allocator="glibc"
    local tor_bin=$(which tor 2>/dev/null || echo "/usr/bin/tor")
    if ldd "$tor_bin" 2>/dev/null | grep -q jemalloc; then
        allocator="jemalloc"
    elif ldd "$tor_bin" 2>/dev/null | grep -q tcmalloc; then
        allocator="tcmalloc"
    fi
    
    # System memory (in MB)
    local mem_total=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)
    local mem_free=$(awk '/MemFree/ {printf "%d", $2/1024}' /proc/meminfo)
    local mem_cached=$(awk '/^Cached/ {printf "%d", $2/1024}' /proc/meminfo)
    local mem_available=$(awk '/MemAvailable/ {printf "%d", $2/1024}' /proc/meminfo)
    local swap_total=$(awk '/SwapTotal/ {printf "%d", $2/1024}' /proc/meminfo)
    local swap_free=$(awk '/SwapFree/ {printf "%d", $2/1024}' /proc/meminfo)
    
    # TCP connections
    local tcp_established=$(ss -t state established 2>/dev/null | wc -l)
    local tcp_total=$(ss -t 2>/dev/null | wc -l)
    
    # File descriptor limit (first relay)
    local fd_limit="unknown"
    local first_pid=$(pgrep -f "tor.*instances" | head -1)
    if [[ -n "$first_pid" ]]; then
        fd_limit=$(grep "Max open files" /proc/$first_pid/limits 2>/dev/null | awk '{print $4}' || echo "unknown")
    fi
    
    # Relay stats
    local relay_count=$(count_running_relays)
    local stats=$(collect_aggregate_stats)
    IFS=',' read -r _ total_kb avg_kb min_kb max_kb <<< "$stats"
    local total_mb=$((total_kb / 1024))
    local avg_mb=$((avg_kb / 1024))
    
    # Output based on format
    case "$OUTPUT_FORMAT" in
        json)
            cat <<EOF
{
  "hostname": "$hostname",
  "timestamp": "${date_str}T${time_str}",
  "tor_version": "$tor_version",
  "os_release": "$os_release",
  "kernel": "$kernel",
  "allocator": "$allocator",
  "memory": {
    "total_mb": $mem_total,
    "free_mb": $mem_free,
    "available_mb": $mem_available,
    "cached_mb": $mem_cached,
    "swap_total_mb": $swap_total,
    "swap_free_mb": $swap_free
  },
  "network": {
    "tcp_established": $tcp_established,
    "tcp_total": $tcp_total
  },
  "fd_limit": "$fd_limit",
  "relays": {
    "count": $relay_count,
    "total_mb": $total_mb,
    "avg_mb": $avg_mb
  }
}
EOF
            ;;
        csv)
            local header="date,time,hostname,tor_version,os_release,kernel,allocator,mem_total_mb,mem_free_mb,mem_available_mb,mem_cached_mb,swap_total_mb,swap_free_mb,tcp_established,tcp_total,fd_limit,relay_count,relay_total_mb,relay_avg_mb"
            local values="$date_str,$time_str,$hostname,$tor_version,$os_release,$kernel,$allocator,$mem_total,$mem_free,$mem_available,$mem_cached,$swap_total,$swap_free,$tcp_established,$tcp_total,$fd_limit,$relay_count,$total_mb,$avg_mb"
            
            if [[ -n "$APPEND_FILE" ]]; then
                if [[ ! -f "$APPEND_FILE" ]]; then
                    mkdir -p "$(dirname "$APPEND_FILE")"
                    echo "$header" > "$APPEND_FILE"
                fi
                echo "$values" >> "$APPEND_FILE"
                echo "Appended to: $APPEND_FILE"
            else
                echo "$header"
                echo "$values"
            fi
            ;;
        text|*)
            cat <<EOF
╔══════════════════════════════════════════════════════════════╗
║           Tor Relay System Diagnostics                       ║
╚══════════════════════════════════════════════════════════════╝

Host:        $hostname
Date:        $date_str $time_str

── Tor ─────────────────────────────────────────────────────────
Version:     $tor_version
Allocator:   $allocator
Relays:      $relay_count running
Memory:      ${total_mb} MB total (avg ${avg_mb} MB/relay)

── System ──────────────────────────────────────────────────────
OS:          $os_release
Kernel:      $kernel
FD Limit:    $fd_limit (per process)

── Memory ──────────────────────────────────────────────────────
Total:       ${mem_total} MB
Free:        ${mem_free} MB
Available:   ${mem_available} MB
Cached:      ${mem_cached} MB
Swap Total:  ${swap_total} MB
Swap Free:   ${swap_free} MB

── Network ─────────────────────────────────────────────────────
TCP Established: $tcp_established
TCP Total:       $tcp_total

EOF
            ;;
    esac
}

collect_diagnostics

