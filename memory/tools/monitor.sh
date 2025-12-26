#!/bin/bash
#
# monitor.sh - Tor relay memory time-series monitoring
#
# ⚠️  DEPRECATED: This tool is replaced by collect.sh
#     collect.sh provides the same functionality plus per-relay detail.
#     Use: ./collect.sh --output /var/log/tor/memory.csv
#
# Collects aggregate memory statistics and appends to a CSV file.
# Designed to run via cron for continuous monitoring.
#
# Usage:
#   ./monitor.sh                          # Append to default file
#   ./monitor.sh --output stats.csv       # Append to specific file
#   ./monitor.sh --init                   # Create new CSV with header
#
# Cron example (daily at 2am):
#   0 2 * * * /path/to/monitor.sh --output /var/log/tor_memory_stats.csv

set -euo pipefail

# Deprecation warning
echo "⚠️  DEPRECATED: monitor.sh is replaced by collect.sh" >&2
echo "   Use: ./collect.sh --output <file>" >&2
echo "   See README.md for details." >&2
echo "" >&2

# Load shared functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/common.sh"

# Defaults
OUTPUT_FILE="${PWD}/memory_stats.csv"
INIT_MODE=false
WITH_DIAGNOSTICS=false
DIAGNOSTICS_FILE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --output|-o) OUTPUT_FILE="$2"; shift 2 ;;
        --init) INIT_MODE=true; shift ;;
        --with-diagnostics) WITH_DIAGNOSTICS=true; shift ;;
        --diagnostics-file) DIAGNOSTICS_FILE="$2"; shift 2 ;;
        --help|-h)
            cat <<EOF
Usage: $0 [options]

Collect aggregate memory stats for all Tor relays and append to CSV.

Options:
  --output, -o <file>     Output CSV file (default: ./memory_stats.csv)
  --init                  Create new CSV with header (overwrites existing)
  --with-diagnostics      Also collect system diagnostics
  --diagnostics-file FILE Diagnostics output file (default: same dir as output)
  --help, -h              Show this help

Output CSV columns:
  date, time, num_relays, total_mb, avg_mb, min_mb, max_mb,
  total_kb, avg_kb, min_kb, max_kb

Examples:
  $0                                    # Append to ./memory_stats.csv
  $0 --init --output /var/log/tor.csv   # Create new file
  $0 --output /var/log/tor.csv          # Append to existing file
  $0 --output stats.csv --with-diagnostics  # Also log system diagnostics

Cron setup (daily at 2am with diagnostics):
  0 2 * * * $0 --output /var/log/tor_memory_stats.csv --with-diagnostics
EOF
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Create directory if needed
mkdir -p "$(dirname "$OUTPUT_FILE")"

# Initialize CSV if requested or file doesn't exist
if $INIT_MODE || [[ ! -f "$OUTPUT_FILE" ]]; then
    echo "date,time,num_relays,total_mb,avg_mb,min_mb,max_mb,total_kb,avg_kb,min_kb,max_kb" > "$OUTPUT_FILE"
    echo "Created: $OUTPUT_FILE"
fi

# Collect stats using shared function
stats=$(collect_aggregate_stats)
IFS=',' read -r count total_kb avg_kb min_kb max_kb <<< "$stats"

if [[ "$count" -eq 0 ]]; then
    print_error "No running relays found"
    exit 1
fi

# Convert to MB
total_mb=$(kb_to_mb "$total_kb")
avg_mb=$(kb_to_mb "$avg_kb")
min_mb=$(kb_to_mb "$min_kb")
max_mb=$(kb_to_mb "$max_kb")

# Format output
date_str=$(date_ymd)
time_str=$(time_hms)
csv_line="$date_str,$time_str,$count,$total_mb,$avg_mb,$min_mb,$max_mb,$total_kb,$avg_kb,$min_kb,$max_kb"

# Append to file
echo "$csv_line" >> "$OUTPUT_FILE"

# Output summary
echo "[$date_str $time_str] $count relays: total=${total_mb}MB avg=${avg_mb}MB min=${min_mb}MB max=${max_mb}MB"
echo "Appended to: $OUTPUT_FILE"

# Collect diagnostics if requested
if $WITH_DIAGNOSTICS; then
    if [[ -z "$DIAGNOSTICS_FILE" ]]; then
        DIAGNOSTICS_FILE="$(dirname "$OUTPUT_FILE")/diagnostics.csv"
    fi
    "${SCRIPT_DIR}/diagnostics.sh" --append "$DIAGNOSTICS_FILE"
fi
