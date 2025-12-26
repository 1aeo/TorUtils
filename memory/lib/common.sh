#!/bin/bash
#
# common.sh - Shared functions for Tor memory tools
#
# Source this file in other scripts:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "${SCRIPT_DIR}/../lib/common.sh"

# Colors for output
COLOR_RED='\033[0;31m'
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_RESET='\033[0m'

# Tor instances directory
TOR_INSTANCES_DIR="/etc/tor/instances"

# Get PID for a relay by name
# Usage: pid=$(get_relay_pid "relay_name")
get_relay_pid() {
    local relay="$1"
    pgrep -f "tor.*instances/${relay}" | head -1
}

# List all relay names
# Usage: for relay in $(list_relays); do ...; done
list_relays() {
    ls "${TOR_INSTANCES_DIR}/" 2>/dev/null | sort
}

# Count running relays
# Usage: count=$(count_running_relays)
count_running_relays() {
    local count=0
    for relay in $(list_relays); do
        [[ -n "$(get_relay_pid "$relay")" ]] && ((count++)) || true
    done
    echo "$count"
}

# Get memory stats from /proc/PID/status (reads file once)
# Usage: read_proc_status "$pid"
# Sets variables: PROC_RSS, PROC_VSZ, PROC_PEAK, PROC_HWM (in KB)
read_proc_status() {
    local pid="$1"
    local status_file="/proc/${pid}/status"
    
    [[ ! -f "$status_file" ]] && return 1
    
    # Reset values
    PROC_RSS=0 PROC_VSZ=0 PROC_PEAK=0 PROC_HWM=0
    
    # Parse with awk for reliable handling of tabs and spaces
    eval "$(awk '
        /^VmRSS:/  { printf "PROC_RSS=%d\n", $2 }
        /^VmSize:/ { printf "PROC_VSZ=%d\n", $2 }
        /^VmPeak:/ { printf "PROC_PEAK=%d\n", $2 }
        /^VmHWM:/  { printf "PROC_HWM=%d\n", $2 }
    ' "$status_file")"
    
    return 0
}

# Get RSS memory for a relay (in KB)
# Usage: rss=$(get_relay_rss "relay_name")
get_relay_rss() {
    local relay="$1"
    local pid=$(get_relay_pid "$relay")
    
    [[ -z "$pid" ]] && echo "0" && return 1
    
    PROC_RSS=0
    read_proc_status "$pid"
    echo "${PROC_RSS:-0}"
}

# Collect aggregate memory stats for all relays
# Returns: count,total_kb,avg_kb,min_kb,max_kb
collect_aggregate_stats() {
    local total_kb=0
    local min_kb=999999999
    local max_kb=0
    local count=0
    
    for relay in $(list_relays); do
        local pid=$(get_relay_pid "$relay")
        [[ -z "$pid" ]] && continue
        
        PROC_RSS=0
        read_proc_status "$pid" || continue
        local rss_kb="${PROC_RSS:-0}"
        
        [[ "$rss_kb" -eq 0 ]] && continue
        
        total_kb=$((total_kb + rss_kb))
        ((count++)) || true
        
        [[ $rss_kb -lt $min_kb ]] && min_kb=$rss_kb
        [[ $rss_kb -gt $max_kb ]] && max_kb=$rss_kb
    done
    
    [[ $count -eq 0 ]] && echo "0,0,0,0,0" && return 1
    
    local avg_kb=$((total_kb / count))
    echo "${count},${total_kb},${avg_kb},${min_kb},${max_kb}"
}

# Convert KB to MB
kb_to_mb() { echo $(($1 / 1024)); }

# Convert KB to GB (with 2 decimal places)
# Falls back to awk if bc is not available
kb_to_gb() {
    if command -v bc &>/dev/null; then
        echo "scale=2; $1 / 1048576" | bc
    else
        awk "BEGIN {printf \"%.2f\", $1 / 1048576}"
    fi
}

# Get current date in YYYY-MM-DD format
date_ymd() { date +%Y-%m-%d; }

# Get current time in HH:MM:SS format
time_hms() { date +%H:%M:%S; }

# Print colored message
print_success() { echo -e "${COLOR_GREEN}$1${COLOR_RESET}"; }
print_warning() { echo -e "${COLOR_YELLOW}$1${COLOR_RESET}"; }
print_error() { echo -e "${COLOR_RED}$1${COLOR_RESET}"; }

# Get relay fingerprint from fingerprint file
# Usage: fp=$(get_relay_fingerprint "relay_name")
# Returns: 40-character hex fingerprint or empty string
# Checks multiple locations: config dir, data dir, common systemd paths
# Note: May require sudo to read fingerprint files (owned by _tor-* users)
get_relay_fingerprint() {
    local relay="$1"
    local fp_file=""
    local fp_content=""
    
    # Check possible fingerprint file locations
    for path in \
        "/var/lib/tor-instances/${relay}/fingerprint" \
        "${TOR_INSTANCES_DIR}/${relay}/fingerprint" \
        "/var/lib/tor/${relay}/fingerprint" \
        "/home/tor/${relay}/fingerprint"
    do
        if [[ -f "$path" ]]; then
            fp_file="$path"
            break
        fi
    done
    
    [[ -z "$fp_file" ]] && echo "" && return
    
    # Try to read the file - may need sudo for tor-owned files
    if [[ -r "$fp_file" ]]; then
        fp_content=$(cat "$fp_file" 2>/dev/null)
    elif [[ $EUID -eq 0 ]]; then
        fp_content=$(cat "$fp_file" 2>/dev/null)
    elif command -v sudo &>/dev/null && sudo -n true 2>/dev/null; then
        # User has passwordless sudo
        fp_content=$(sudo cat "$fp_file" 2>/dev/null)
    fi
    
    # Fingerprint file format: "nickname FINGERPRINT"
    if [[ -n "$fp_content" ]]; then
        echo "$fp_content" | awk '{print $2}' | tr -d ' '
    else
        echo ""
    fi
}

# Get relay nickname from torrc
# Usage: nick=$(get_relay_nickname "relay_name")
# Returns: Nickname from torrc or the relay directory name
get_relay_nickname() {
    local relay="$1"
    local torrc="${TOR_INSTANCES_DIR}/${relay}/torrc"
    
    if [[ -f "$torrc" ]]; then
        local nick=$(grep -E "^Nickname " "$torrc" 2>/dev/null | awk '{print $2}')
        echo "${nick:-$relay}"
    else
        echo "$relay"
    fi
}

# Get ISO 8601 timestamp
# Usage: ts=$(timestamp_iso)
timestamp_iso() {
    date +%Y-%m-%dT%H:%M:%S
}

# CSV header for unified format
CSV_HEADER="timestamp,server,type,fingerprint,nickname,rss_kb,vmsize_kb,hwm_kb,frag_ratio,count,total_kb,avg_kb,min_kb,max_kb"

# CSV header for unified format with group (Phase 2)
CSV_HEADER_WITH_GROUP="timestamp,server,type,fingerprint,nickname,group,rss_kb,vmsize_kb,hwm_kb,frag_ratio,count,total_kb,avg_kb,min_kb,max_kb"

