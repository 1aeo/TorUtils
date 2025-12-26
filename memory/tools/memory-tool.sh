#!/bin/bash
#
# memory-tool.sh - Tor relay memory analysis tool
#
# Commands:
#   status              Show memory usage for all relays
#   csv                 Output memory data as CSV
#   collect             Collect data to a report directory
#   detail <relay>      Detailed metrics for one relay
#   watch <relay>       Continuous monitoring
#   apply [--dry-run]   Apply memory optimizations (testing only)
#   verify              Check which relays have optimizations

set -euo pipefail

# Load shared functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/common.sh"

REPORTS_DIR="${SCRIPT_DIR}/../reports"

# Get detailed memory metrics for a relay
# Returns: relay,pid,rss_gb,vmsize_gb,hwm_gb,frag_ratio
get_metrics() {
    local relay="$1"
    local pid=$(get_relay_pid "$relay")
    
    [[ -z "$pid" ]] && echo "$relay,,,,,NOT_RUNNING" && return
    
    # Read all metrics in one pass
    PROC_RSS=0 PROC_VSZ=0 PROC_HWM=0
    read_proc_status "$pid"
    
    local rss_gb=$(kb_to_gb "${PROC_RSS:-0}")
    local vsz_gb=$(kb_to_gb "${PROC_VSZ:-0}")
    local hwm_gb=$(kb_to_gb "${PROC_HWM:-0}")
    
    # Calculate fragmentation ratio (requires sudo for smaps)
    local frag="N/A"
    if [[ -r "/proc/$pid/smaps" ]] || [[ $EUID -eq 0 ]]; then
        frag=$(sudo awk '/^(Size|Rss):/{if(NR%2==1)s=$2;else{if(s>1000){ts+=s;tr+=$2}}}END{if(tr>0)printf "%.1f",ts/tr;else print "N/A"}' /proc/$pid/smaps 2>/dev/null || echo "N/A")
    fi
    
    printf "%s,%s,%s,%s,%s,%s\n" "$relay" "$pid" "$rss_gb" "$vsz_gb" "$hwm_gb" "$frag"
}

# Commands
cmd_status() {
    echo "=== Tor Relay Memory Status ==="
    echo "Relay                 PID       RSS (GB)  VmSize    HWM       Frag"
    echo "-------------------- -------- --------- --------- --------- ------"
    local total=0 count=0
    
    for relay in $(list_relays); do
        local data=$(get_metrics "$relay")
        IFS=',' read -r name pid rss vsz hwm frag <<< "$data"
        
        if [[ -n "$rss" && "$rss" != "0" && "$rss" != ".00" ]]; then
            total=$(echo "$total + $rss" | bc)
            count=$((count + 1))
        fi
        
        printf "%-20s %-8s %-9s %-9s %-9s %s\n" "$name" "$pid" "$rss" "$vsz" "$hwm" "$frag"
    done
    
    echo "-------------------- -------- --------- --------- --------- ------"
    local avg=0
    [[ $count -gt 0 ]] && avg=$(echo "scale=2; $total / $count" | bc 2>/dev/null || echo 0)
    printf "TOTAL: %.2f GB across %d relays (avg: %s GB)\n" "$total" "$count" "$avg"
}

cmd_csv() {
    echo "relay,pid,rss_gb,vmsize_gb,hwm_gb,frag_ratio"
    for relay in $(list_relays); do
        get_metrics "$relay"
    done
}

cmd_collect() {
    local output_dir="" auto_dir=""
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --output-dir) output_dir="$2"; shift 2 ;;
            --auto-dir) auto_dir="$2"; shift 2 ;;
            *) shift ;;
        esac
    done
    
    # Determine output directory
    if [[ -n "$auto_dir" ]]; then
        output_dir="${REPORTS_DIR}/$(date_ymd)-$(hostname -s)-${auto_dir}"
    elif [[ -z "$output_dir" ]]; then
        echo "Error: Must specify --output-dir or --auto-dir"
        echo "Usage: $0 collect --output-dir <path>"
        echo "       $0 collect --auto-dir <description>"
        exit 1
    fi
    
    # Create directory structure
    mkdir -p "${output_dir}/charts"
    
    local data_file="${output_dir}/data.csv"
    local timestamp="$(date_ymd) $(time_hms)"
    
    echo "=== Collecting Memory Data ==="
    echo "Output directory: $output_dir"
    echo "Timestamp: $timestamp"
    echo ""
    
    # Write CSV header with metadata
    {
        echo "# Tor Relay Memory Data"
        echo "# Collected: $timestamp"
        echo "# Host: $(hostname)"
        echo "#"
        echo "relay,pid,rss_gb,vmsize_gb,hwm_gb,frag_ratio"
    } > "$data_file"
    
    # Collect data
    local count=0 total_rss=0
    for relay in $(list_relays); do
        local data=$(get_metrics "$relay")
        echo "$data" >> "$data_file"
        IFS=',' read -r name _ rss _ _ _ <<< "$data"
        
        if [[ -n "$rss" && "$rss" != "0" && "$rss" != ".00" ]]; then
            total_rss=$(echo "$total_rss + $rss" | bc)
            count=$((count + 1))
        fi
        printf "  Collected: %s (%s GB)\n" "$name" "$rss"
    done
    
    echo ""
    print_success "✓ Data saved to: ${data_file}"
    echo "  Relays: $count"
    printf "  Total RSS: %.2f GB\n" "$total_rss"
    echo ""
    echo "Next steps:"
    echo "  # Generate charts:"
    echo "  python3 ${SCRIPT_DIR}/generate-charts.py --data ${data_file} --output-dir ${output_dir}/charts/"
}

cmd_detail() {
    local relay="$1"
    local pid=$(get_relay_pid "$relay")
    
    [[ -z "$pid" ]] && echo "Relay $relay not running" && exit 1
    
    echo "=== $relay (PID: $pid) ==="
    grep -E "^(VmRSS|VmSize|VmPeak|VmHWM|VmData|VmStk)" /proc/$pid/status
    echo ""
    
    if [[ -r "/proc/$pid/smaps" ]] || [[ $EUID -eq 0 ]]; then
        local frag=$(sudo awk '/^(Size|Rss):/{if(NR%2==1)s=$2;else{if(s>1000){ts+=s;tr+=$2}}}END{printf "%.2f:1",ts/tr}' /proc/$pid/smaps 2>/dev/null || echo "N/A")
        echo "Fragmentation ratio: $frag"
    fi
    
    echo ""
    echo "Config:"
    grep -E "^(DirCache|MaxMemInQueues)" "${TOR_INSTANCES_DIR}/$relay/torrc" 2>/dev/null || echo "  (no memory optimizations)"
}

cmd_watch() {
    local relay="$1"
    while true; do
        clear
        echo "Watching $relay (Ctrl+C to stop)"
        echo "Time: $(date)"
        cmd_detail "$relay"
        sleep 5
    done
}

cmd_apply() {
    local dry_run=false
    local relays=()
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run) dry_run=true; shift ;;
            *) relays+=("$1"); shift ;;
        esac
    done
    
    [[ ${#relays[@]} -eq 0 ]] && mapfile -t relays < <(list_relays)
    
    echo "=== Apply DirCache 0 (Testing Only) ==="
    print_error "⚠️  WARNING: This will convert guard relays to middle relays!"
    print_warning "   Only use for testing or if middle relay status is acceptable."
    $dry_run && echo "(DRY RUN - no changes will be made)"
    echo ""
    
    local applied=0 skipped=0
    for relay in "${relays[@]}"; do
        local torrc="${TOR_INSTANCES_DIR}/$relay/torrc"
        [[ ! -f "$torrc" ]] && continue
        
        if grep -q "^DirCache 0" "$torrc" 2>/dev/null; then
            print_warning "⏭ $relay: already optimized"
            ((skipped++))
            continue
        fi
        
        if $dry_run; then
            print_success "✓ $relay: would apply DirCache 0 + MaxMemInQueues 2 GB"
        else
            sudo cp "$torrc" "${torrc}.bak.$(date +%Y%m%d%H%M%S)"
            echo -e "\n# Memory optimization ($(date_ymd))\nDirCache 0\nMaxMemInQueues 2 GB" | sudo tee -a "$torrc" >/dev/null
            sudo systemctl restart "tor@$relay" 2>/dev/null && sleep 2
            print_success "✓ $relay: optimized and restarted"
        fi
        ((applied++))
    done
    
    echo ""
    echo "Applied: $applied | Skipped: $skipped"
}

cmd_verify() {
    echo "=== Optimization Status ==="
    local optimized=0 missing=0
    
    for relay in $(list_relays); do
        if grep -q "^DirCache 0" "${TOR_INSTANCES_DIR}/$relay/torrc" 2>/dev/null; then
            print_success "✓ $relay"
            ((optimized++))
        else
            print_error "✗ $relay"
            ((missing++))
        fi
    done
    
    echo ""
    echo "Optimized: $optimized | Missing: $missing"
}

# Main
case "${1:-status}" in
    status) cmd_status ;;
    csv) cmd_csv ;;
    collect) shift; cmd_collect "$@" ;;
    detail) cmd_detail "${2:?Usage: $0 detail <relay>}" ;;
    watch) cmd_watch "${2:?Usage: $0 watch <relay>}" ;;
    apply) shift; cmd_apply "$@" ;;
    verify) cmd_verify ;;
    help|--help|-h)
        cat <<EOF
Usage: $0 <command> [options]

Commands:
  status              Show memory for all relays (default)
  csv                 Output as CSV to stdout
  collect             Collect data to a report directory
  detail <relay>      Detailed metrics for one relay
  watch <relay>       Continuous monitoring
  apply [--dry-run]   Apply DirCache 0 (⚠️ loses guard status)
  verify              Check DirCache 0 status

Collect Options:
  --output-dir <path>   Save data to specific directory
  --auto-dir <desc>     Auto-create: reports/YYYY-MM-DD-hostname-<desc>/

Examples:
  $0                           # Show status
  $0 csv > data.csv            # Export to stdout
  $0 detail 22gz               # Check specific relay
  $0 watch 22gz                # Monitor relay live

  # Collect to auto-named directory:
  $0 collect --auto-dir "baseline"
  # Creates: reports/$(date_ymd)-myserver-baseline/data.csv

  # Collect to specific directory:
  $0 collect --output-dir ../reports/$(date_ymd)-myserver-experiment/

Testing DirCache 0 (not recommended for guard relays):
  $0 apply --dry-run           # Preview changes
  $0 apply relay1              # Apply to test relay

⚠️  DirCache 0 reduces memory (~5GB→0.3GB) but removes guard status.
    For guard relays, investigate alternative allocators (jemalloc, tcmalloc).
EOF
        ;;
    *) echo "Unknown command: $1. Use '$0 help' for usage." ;;
esac
