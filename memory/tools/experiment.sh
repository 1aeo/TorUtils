#!/bin/bash
#
# experiment.sh - Tor relay memory experiment management
#
# Commands:
#   init    Create a new experiment directory with scaffolding
#   status  Show experiment status and data summary
#   list    List all experiments
#
# Usage:
#   ./experiment.sh init --name "dircache-test" --groups A,B,C
#   ./experiment.sh status --experiment reports/2025-12-25-server-dircache-test/
#   ./experiment.sh list

set -euo pipefail

# Load shared functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/common.sh"

REPORTS_DIR="${SCRIPT_DIR}/../reports"
TEMPLATES_DIR="${SCRIPT_DIR}/../templates"

# Initialize a new experiment
cmd_init() {
    local name=""
    local groups=""
    local output_dir=""
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --name|-n) name="$2"; shift 2 ;;
            --groups|-g) groups="$2"; shift 2 ;;
            --output-dir|-o) output_dir="$2"; shift 2 ;;
            *) shift ;;
        esac
    done
    
    # Validate
    if [[ -z "$name" ]]; then
        print_error "Error: --name is required"
        echo "Usage: $0 init --name <description> [--groups A,B,C]"
        exit 1
    fi
    
    # Generate directory name
    local date_prefix=$(date_ymd)
    local server=$(hostname -s)
    local safe_name=$(echo "$name" | tr ' ' '-' | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-')
    
    if [[ -z "$output_dir" ]]; then
        output_dir="${REPORTS_DIR}/${date_prefix}-${server}-${safe_name}"
    fi
    
    # Check if exists
    if [[ -d "$output_dir" ]]; then
        print_error "Error: Experiment directory already exists: $output_dir"
        exit 1
    fi
    
    echo "=== Creating New Experiment ==="
    echo "Name: $name"
    echo "Directory: $output_dir"
    [[ -n "$groups" ]] && echo "Groups: $groups"
    echo ""
    
    # Create directory structure
    mkdir -p "${output_dir}/charts"
    
    # Create experiment.json
    local groups_json="{}"
    if [[ -n "$groups" ]]; then
        # Parse comma-separated groups into JSON
        groups_json="{"
        local first=true
        IFS=',' read -ra GROUP_ARRAY <<< "$groups"
        for g in "${GROUP_ARRAY[@]}"; do
            g=$(echo "$g" | tr -d ' ')
            if $first; then
                first=false
            else
                groups_json+=","
            fi
            groups_json+="\"$g\": {\"name\": \"Group $g\", \"config\": {}}"
        done
        groups_json+="}"
    fi
    
    cat > "${output_dir}/experiment.json" <<EOF
{
  "id": "${date_prefix}-${server}-${safe_name}",
  "name": "${name}",
  "server": "${server}",
  "start_date": "${date_prefix}",
  "end_date": "",
  "hypothesis": "",
  "description": "",
  "groups": ${groups_json},
  "tor_version": "$(tor --version 2>/dev/null | head -1 | sed 's/Tor version //' || echo 'unknown')",
  "allocator": "glibc"
}
EOF
    print_success "✓ Created: experiment.json"
    
    # Create relay_config.csv
    cat > "${output_dir}/relay_config.csv" <<EOF
fingerprint,nickname,group,dircache,maxmem,notes
# Add relay configurations below
# Example:
# A1B2C3D4E5F67890A1B2C3D4E5F67890A1B2C3D4,relay1,A,0,2GB,Test relay
# B2C3D4E5F67890A1B2C3D4E5F67890A1B2C3D4E5,relay2,B,default,default,Control
EOF
    print_success "✓ Created: relay_config.csv"
    
    # Create measurements.csv with header (with group column)
    echo "$CSV_HEADER_WITH_GROUP" > "${output_dir}/measurements.csv"
    print_success "✓ Created: measurements.csv"
    
    # Copy REPORT.md template if exists
    if [[ -f "${TEMPLATES_DIR}/REPORT.md" ]]; then
        cp "${TEMPLATES_DIR}/REPORT.md" "${output_dir}/REPORT.md"
        # Replace placeholders
        sed -i "s/\[Experiment Title\]/${name}/g" "${output_dir}/REPORT.md"
        sed -i "s/\[hostname\]/${server}/g" "${output_dir}/REPORT.md"
        sed -i "s/\[start\]/${date_prefix}/g" "${output_dir}/REPORT.md"
        print_success "✓ Created: REPORT.md (from template)"
    else
        # Create minimal README
        cat > "${output_dir}/README.md" <<EOF
# ${name}

**Server:** ${server}  
**Started:** ${date_prefix}  
**Status:** In Progress

## Overview

[Add experiment description]

## Files

- \`experiment.json\` - Experiment metadata and group definitions
- \`relay_config.csv\` - Relay-to-group assignments
- \`measurements.csv\` - Collected data
- \`charts/\` - Generated visualizations
- \`REPORT.md\` - Full analysis report (after completion)

## Data Collection

\`\`\`bash
# Collect data (run daily)
cd tools
./collect.sh --output ${output_dir}/measurements.csv --config ${output_dir}/relay_config.csv
\`\`\`

## Generate Report

\`\`\`bash
./generate-report.py --experiment ${output_dir}/
\`\`\`
EOF
        print_success "✓ Created: README.md"
    fi
    
    echo ""
    print_success "Experiment initialized!"
    echo ""
    echo "Next steps:"
    echo "  1. Edit relay_config.csv to assign relays to groups"
    echo "  2. Apply configurations to relays (edit torrc files)"
    echo "  3. Collect data:"
    echo "     ./collect.sh --output ${output_dir}/measurements.csv --config ${output_dir}/relay_config.csv"
    echo "  4. Generate report when done:"
    echo "     ./generate-report.py --experiment ${output_dir}/"
}

# Show experiment status
cmd_status() {
    local exp_dir=""
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --experiment|-e) exp_dir="$2"; shift 2 ;;
            *) exp_dir="$1"; shift ;;
        esac
    done
    
    if [[ -z "$exp_dir" ]]; then
        print_error "Error: Experiment directory required"
        echo "Usage: $0 status --experiment <directory>"
        exit 1
    fi
    
    if [[ ! -d "$exp_dir" ]]; then
        print_error "Error: Directory not found: $exp_dir"
        exit 1
    fi
    
    echo "=== Experiment Status ==="
    echo "Directory: $exp_dir"
    echo ""
    
    # Read experiment.json if exists
    if [[ -f "${exp_dir}/experiment.json" ]]; then
        echo "Metadata:"
        # Use grep/sed for basic JSON parsing (no jq dependency)
        grep -E '"(name|start_date|end_date|hypothesis)"' "${exp_dir}/experiment.json" | \
            sed 's/[",]//g' | sed 's/^[[:space:]]*/  /'
        echo ""
    fi
    
    # Count relays in config
    if [[ -f "${exp_dir}/relay_config.csv" ]]; then
        local relay_count
        relay_count=$(grep -v '^#' "${exp_dir}/relay_config.csv" | grep -v '^fingerprint' | grep -c ',' 2>/dev/null) || relay_count=0
        echo "Relay config: ${relay_count} relays configured"
    fi
    
    # Count measurements
    if [[ -f "${exp_dir}/measurements.csv" ]]; then
        local total_rows=$(wc -l < "${exp_dir}/measurements.csv" | tr -d ' ')
        # grep -c outputs count even on no match (exits 1), so capture output regardless
        local agg_rows
        agg_rows=$(grep -c ',aggregate,' "${exp_dir}/measurements.csv" 2>/dev/null) || agg_rows=0
        local relay_rows
        relay_rows=$(grep -c ',relay,' "${exp_dir}/measurements.csv" 2>/dev/null) || relay_rows=0
        
        echo "Measurements: $((total_rows - 1)) rows total"
        echo "  - $agg_rows aggregate rows (data points)"
        echo "  - $relay_rows relay rows"
        
        # Date range
        if [[ "$agg_rows" -gt 0 ]]; then
            local first_date=$(grep ',aggregate,' "${exp_dir}/measurements.csv" | head -1 | cut -d',' -f1)
            local last_date=$(grep ',aggregate,' "${exp_dir}/measurements.csv" | tail -1 | cut -d',' -f1)
            echo "  - Period: $first_date to $last_date"
        fi
    fi
    
    # Check for charts
    if [[ -d "${exp_dir}/charts" ]]; then
        local chart_count=0
        for f in "${exp_dir}/charts"/*.png; do
            [[ -f "$f" ]] && ((chart_count++)) || true
        done
        echo "Charts: $chart_count generated"
    fi
    
    # Check for report
    if [[ -f "${exp_dir}/REPORT.md" ]]; then
        print_success "Report: REPORT.md exists"
    else
        echo "Report: Not yet created"
    fi
}

# List all experiments
cmd_list() {
    echo "=== Experiments ==="
    echo ""
    
    if [[ ! -d "$REPORTS_DIR" ]]; then
        echo "No experiments found (reports directory doesn't exist)"
        return
    fi
    
    local count=0
    for exp_dir in "${REPORTS_DIR}"/*/; do
        [[ ! -d "$exp_dir" ]] && continue
        
        local name=$(basename "$exp_dir")
        local has_data=""
        local has_report=""
        
        [[ -f "${exp_dir}measurements.csv" ]] && has_data="✓ data"
        [[ -f "${exp_dir}REPORT.md" ]] && has_report="✓ report"
        
        echo "  $name  $has_data $has_report"
        ((count++)) || true
    done
    
    echo ""
    echo "Total: $count experiments"
}

# Help
cmd_help() {
    cat <<EOF
Usage: $0 <command> [options]

Commands:
  init     Create a new experiment directory
  status   Show experiment status and data summary
  list     List all experiments
  help     Show this help

Init Options:
  --name, -n <name>       Experiment name/description (required)
  --groups, -g <A,B,C>    Comma-separated group names
  --output-dir, -o <dir>  Custom output directory

Status Options:
  --experiment, -e <dir>  Experiment directory

Examples:
  $0 init --name "DirCache Test" --groups A,B,C
  $0 init --name "Allocator Comparison" --groups control,jemalloc,tcmalloc
  $0 status reports/2025-12-25-server-dircache-test/
  $0 list

Workflow:
  1. Initialize:  $0 init --name "my-experiment" --groups A,B
  2. Configure:   Edit relay_config.csv to assign relays to groups
  3. Apply:       Update torrc files based on group configs
  4. Collect:     ./collect.sh --output .../measurements.csv --config .../relay_config.csv
  5. Report:      ./generate-report.py --experiment .../

See docs/experiments.md for detailed documentation.
EOF
}

# Main
case "${1:-help}" in
    init) shift; cmd_init "$@" ;;
    status) shift; cmd_status "$@" ;;
    list) cmd_list ;;
    help|--help|-h) cmd_help ;;
    *) echo "Unknown command: $1. Use '$0 help' for usage." ;;
esac

