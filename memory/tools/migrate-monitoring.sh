#!/bin/bash
#
# migrate-monitoring.sh - Convert legacy monitoring data to unified format
#
# Converts memory_stats.csv from the old monitor.sh format to the new
# unified format used by collect.sh.
#
# Note: Historical data will only have aggregate rows since per-relay
# detail wasn't collected by the old format.
#
# Usage:
#   ./migrate-monitoring.sh <input_csv> <output_csv>
#   ./migrate-monitoring.sh <input_csv>              # Output to stdout
#   ./migrate-monitoring.sh --server gatedopen <input_csv> <output_csv>
#
# Legacy format (input):
#   date,time,num_relays,total_mb,avg_mb,min_mb,max_mb,total_kb,avg_kb,min_kb,max_kb
#
# New format (output):
#   timestamp,server,type,fingerprint,nickname,rss_kb,vmsize_kb,hwm_kb,frag_ratio,count,total_kb,avg_kb,min_kb,max_kb

set -euo pipefail

# Load shared functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/common.sh"

# Defaults
INPUT_FILE=""
OUTPUT_FILE=""
SERVER_NAME=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --server|-s) SERVER_NAME="$2"; shift 2 ;;
        --help|-h)
            cat <<EOF
Usage: $0 [options] <input_csv> [output_csv]

Convert legacy memory_stats.csv to unified format.

Arguments:
  input_csv     Path to legacy memory_stats.csv
  output_csv    Path to output file (optional, defaults to stdout)

Options:
  --server, -s <name>   Server name (default: extracted from path or 'unknown')
  --help, -h            Show this help

Legacy format (input):
  date,time,num_relays,total_mb,avg_mb,min_mb,max_mb,total_kb,avg_kb,min_kb,max_kb

New format (output):
  timestamp,server,type,fingerprint,nickname,rss_kb,vmsize_kb,hwm_kb,frag_ratio,count,total_kb,avg_kb,min_kb,max_kb

Note: Migrated data will only contain aggregate rows. Per-relay detail
was not collected by the legacy format.

Examples:
  $0 /var/log/tor/memory_stats.csv /var/log/tor/memory.csv
  $0 --server gatedopen old_stats.csv new_stats.csv
  $0 old_stats.csv > new_stats.csv
EOF
            exit 0
            ;;
        -*)
            echo "Unknown option: $1"
            exit 1
            ;;
        *)
            if [[ -z "$INPUT_FILE" ]]; then
                INPUT_FILE="$1"
            elif [[ -z "$OUTPUT_FILE" ]]; then
                OUTPUT_FILE="$1"
            else
                echo "Too many arguments"
                exit 1
            fi
            shift
            ;;
    esac
done

# Validate input
if [[ -z "$INPUT_FILE" ]]; then
    print_error "Error: Input file required"
    echo "Usage: $0 <input_csv> [output_csv]"
    exit 1
fi

if [[ ! -f "$INPUT_FILE" ]]; then
    print_error "Error: Input file not found: $INPUT_FILE"
    exit 1
fi

# Try to extract server name from path if not provided
if [[ -z "$SERVER_NAME" ]]; then
    # Try to extract from path like /path/to/monitoring/gatedopen/memory_stats.csv
    parent_dir=$(dirname "$INPUT_FILE")
    parent_name=$(basename "$parent_dir")
    if [[ "$parent_name" != "." && "$parent_name" != "/" ]]; then
        SERVER_NAME="$parent_name"
    else
        SERVER_NAME="unknown"
    fi
fi

# Migration function
migrate_data() {
    local input="$1"
    
    # Output header
    echo "$CSV_HEADER"
    
    # Process each line (skip header)
    local line_num=0
    while IFS=',' read -r date time num_relays total_mb avg_mb min_mb max_mb total_kb avg_kb min_kb max_kb; do
        ((line_num++)) || true
        
        # Skip header line
        if [[ "$line_num" -eq 1 && "$date" == "date" ]]; then
            continue
        fi
        
        # Convert date + time to ISO 8601 timestamp
        timestamp="${date}T${time}"
        
        # Output aggregate row
        # Empty columns: fingerprint, nickname, rss_kb, vmsize_kb, hwm_kb, frag_ratio
        echo "${timestamp},${SERVER_NAME},aggregate,,,,,,,${num_relays},${total_kb},${avg_kb},${min_kb},${max_kb}"
        
    done < "$input"
}

# Run migration
if [[ -n "$OUTPUT_FILE" ]]; then
    mkdir -p "$(dirname "$OUTPUT_FILE")"
    migrate_data "$INPUT_FILE" > "$OUTPUT_FILE"
    
    # Count lines
    input_lines=$(wc -l < "$INPUT_FILE")
    output_lines=$(wc -l < "$OUTPUT_FILE")
    
    print_success "Migration complete:"
    echo "  Input:  $INPUT_FILE ($((input_lines - 1)) records)"
    echo "  Output: $OUTPUT_FILE ($((output_lines - 1)) aggregate rows)"
    echo "  Server: $SERVER_NAME"
    echo ""
    echo "Note: Historical data contains aggregate rows only."
    echo "New collections with collect.sh will include per-relay detail."
else
    # Output to stdout
    migrate_data "$INPUT_FILE"
fi

