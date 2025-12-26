#!/bin/bash
#
# collect.sh - Unified Tor relay memory data collection
#
# Collects both aggregate and per-relay memory statistics in a single CSV.
# This tool replaces both monitor.sh and memory-tool.sh collect.
#
# Usage:
#   ./collect.sh --output /var/log/tor/memory.csv     # Append data
#   ./collect.sh --init --output /var/log/tor/memory.csv  # Initialize new file
#   ./collect.sh --stdout                              # Output to stdout only
#   ./collect.sh --config relay_config.csv            # With experiment group assignments
#
# Output format:
#   - 1 aggregate row with summary statistics
#   - N relay rows with per-relay detail
#
# See docs/schema.md for full format documentation.

set -euo pipefail

# Load shared functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/common.sh"

# Defaults
OUTPUT_FILE=""
INIT_MODE=false
STDOUT_MODE=false
WITH_DIAGNOSTICS=false
DIAGNOSTICS_FILE=""
CONFIG_FILE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --output|-o) OUTPUT_FILE="$2"; shift 2 ;;
        --init) INIT_MODE=true; shift ;;
        --stdout) STDOUT_MODE=true; shift ;;
        --config|-c) CONFIG_FILE="$2"; shift 2 ;;
        --with-diagnostics) WITH_DIAGNOSTICS=true; shift ;;
        --diagnostics-file) DIAGNOSTICS_FILE="$2"; shift 2 ;;
        --help|-h)
            cat <<EOF
Usage: $0 [options]

Collect unified memory statistics (aggregate + per-relay) for all Tor relays.

Options:
  --output, -o <file>     Output CSV file (required unless --stdout)
  --init                  Create new CSV with header (overwrites existing)
  --stdout                Output to stdout only (no file)
  --config, -c <file>     Relay config CSV for group assignments (experiments)
  --with-diagnostics      Also collect system diagnostics
  --diagnostics-file FILE Diagnostics output file (default: same dir as output)
  --help, -h              Show this help

Output Format:
  Each collection appends:
    - 1 aggregate row (type=aggregate) with totals
    - N relay rows (type=relay) with per-relay detail

  Standard columns:
    timestamp, server, type, fingerprint, nickname, rss_kb, vmsize_kb,
    hwm_kb, frag_ratio, count, total_kb, avg_kb, min_kb, max_kb

  With --config (adds group column):
    timestamp, server, type, fingerprint, nickname, group, rss_kb, vmsize_kb,
    hwm_kb, frag_ratio, count, total_kb, avg_kb, min_kb, max_kb

Relay Config Format (relay_config.csv):
  fingerprint,nickname,group,dircache,maxmem,notes
  A1B2C3...,relay1,A,0,2GB,Test relay
  B2C3D4...,relay2,B,default,default,Control

Examples:
  $0 --init --output /var/log/tor/memory.csv   # Initialize new file
  $0 --output /var/log/tor/memory.csv          # Append to existing
  $0 --stdout                                   # Quick check, no file
  $0 --output stats.csv --with-diagnostics     # With system info
  $0 --output exp.csv --config relay_config.csv  # With group assignments

Cron setup (daily at 2am):
  0 2 * * * $0 --output /var/log/tor/memory.csv

See docs/schema.md for format documentation.
EOF
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Validate arguments
if [[ "$STDOUT_MODE" == "false" && -z "$OUTPUT_FILE" ]]; then
    print_error "Error: Must specify --output <file> or --stdout"
    exit 1
fi

# Load relay config if provided
declare -A RELAY_GROUPS
declare -A NICKNAME_GROUPS  # Fallback lookup by nickname
if [[ -n "$CONFIG_FILE" ]]; then
    if [[ ! -f "$CONFIG_FILE" ]]; then
        print_error "Error: Config file not found: $CONFIG_FILE"
        exit 1
    fi
    
    # Parse config file (fingerprint -> group mapping)
    while IFS=',' read -r fp nickname group rest; do
        # Skip header, empty lines, and comments
        [[ "$fp" == "fingerprint" || -z "$fp" || "$fp" == \#* ]] && continue
        [[ -n "$fp" ]] && RELAY_GROUPS["$fp"]="$group"
        [[ -n "$nickname" ]] && NICKNAME_GROUPS["$nickname"]="$group"
    done < "$CONFIG_FILE"
    
    echo "Loaded ${#RELAY_GROUPS[@]} relay group assignments from config"
fi

# Determine which header to use
if [[ -n "$CONFIG_FILE" ]]; then
    HEADER="$CSV_HEADER_WITH_GROUP"
else
    HEADER="$CSV_HEADER"
fi

# Initialize file if needed
if [[ -n "$OUTPUT_FILE" ]]; then
    mkdir -p "$(dirname "$OUTPUT_FILE")"
    
    if $INIT_MODE || [[ ! -f "$OUTPUT_FILE" ]]; then
        echo "$HEADER" > "$OUTPUT_FILE"
        print_success "Created: $OUTPUT_FILE"
    fi
fi

# Collect data
timestamp=$(timestamp_iso)
server=$(hostname -s)

# Arrays to store per-relay data
declare -a relay_lines=()
total_kb=0
min_kb=999999999
max_kb=0
count=0

# Collect per-relay data
for relay in $(list_relays); do
    pid=$(get_relay_pid "$relay")
    [[ -z "$pid" ]] && continue
    
    # Get memory metrics
    PROC_RSS=0 PROC_VSZ=0 PROC_HWM=0
    read_proc_status "$pid" || continue
    
    rss_kb="${PROC_RSS:-0}"
    vmsize_kb="${PROC_VSZ:-0}"
    hwm_kb="${PROC_HWM:-0}"
    
    [[ "$rss_kb" -eq 0 ]] && continue
    
    # Get relay identity
    fingerprint=$(get_relay_fingerprint "$relay")
    nickname=$(get_relay_nickname "$relay")
    
    # Get group from config (if available) - try fingerprint first, then nickname
    group=""
    if [[ -n "$CONFIG_FILE" ]]; then
        if [[ -n "$fingerprint" && -n "${RELAY_GROUPS[$fingerprint]:-}" ]]; then
            group="${RELAY_GROUPS[$fingerprint]}"
        elif [[ -n "${NICKNAME_GROUPS[$nickname]:-}" ]]; then
            group="${NICKNAME_GROUPS[$nickname]}"
        fi
    fi
    
    # Calculate fragmentation ratio (VmSize / VmRSS)
    # Uses already-retrieved values - no extra disk read needed
    frag_ratio=""
    if [[ "$rss_kb" -gt 0 && "$vmsize_kb" -gt 0 ]]; then
        frag_ratio=$(awk "BEGIN {printf \"%.2f\", $vmsize_kb / $rss_kb}")
    fi
    
    # Build relay line (group column only if config provided)
    relay_group_col=""
    [[ -n "$CONFIG_FILE" ]] && relay_group_col="${group},"
    relay_lines+=("${timestamp},${server},relay,${fingerprint},${nickname},${relay_group_col}${rss_kb},${vmsize_kb},${hwm_kb},${frag_ratio},,,,,")

    
    # Update aggregate stats
    total_kb=$((total_kb + rss_kb))
    ((count++)) || true
    [[ $rss_kb -lt $min_kb ]] && min_kb=$rss_kb
    [[ $rss_kb -gt $max_kb ]] && max_kb=$rss_kb
done

# Check if any relays found
if [[ $count -eq 0 ]]; then
    print_error "No running relays found"
    exit 1
fi

# Calculate averages
avg_kb=$((total_kb / count))

# Build aggregate line (extra empty field for group column if config provided)
agg_group_col=""
[[ -n "$CONFIG_FILE" ]] && agg_group_col=","
aggregate_line="${timestamp},${server},aggregate,,,${agg_group_col},,,,${count},${total_kb},${avg_kb},${min_kb},${max_kb}"

# Output data
output_lines() {
    echo "$aggregate_line"
    for line in "${relay_lines[@]}"; do
        echo "$line"
    done
}

if $STDOUT_MODE; then
    echo "$HEADER"
    output_lines
else
    output_lines >> "$OUTPUT_FILE"
    
    # Summary to stderr
    total_mb=$((total_kb / 1024))
    avg_mb=$((avg_kb / 1024))
    echo "[$timestamp] $count relays: total=${total_mb}MB avg=${avg_mb}MB"
    echo "Appended $((count + 1)) rows to: $OUTPUT_FILE"
fi

# Collect diagnostics if requested
if $WITH_DIAGNOSTICS; then
    if [[ -z "$DIAGNOSTICS_FILE" && -n "$OUTPUT_FILE" ]]; then
        DIAGNOSTICS_FILE="$(dirname "$OUTPUT_FILE")/diagnostics.csv"
    fi
    if [[ -n "$DIAGNOSTICS_FILE" ]]; then
        "${SCRIPT_DIR}/diagnostics.sh" --append "$DIAGNOSTICS_FILE"
    fi
fi
