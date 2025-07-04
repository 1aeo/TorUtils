#!/bin/bash

# tor_migration.sh - Comprehensive Tor Relay Migration Tool
# 
# This script orchestrates the complete Tor relay migration process,
# including creating input files, migrating relays, managing services,
# and generating reports.

set -euo pipefail

# Script version and configuration
VERSION="1.0.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output (only if terminal supports it)
if [[ "${TERM:-}" != "dumb" ]] && [[ "${TERM:-}" =~ color ]] && command -v tput >/dev/null 2>&1; then
    RED=$'\033[0;31m'
    GREEN=$'\033[0;32m'
    YELLOW=$'\033[1;33m'
    BLUE=$'\033[0;34m'
    CYAN=$'\033[0;36m'
    NC=$'\033[0m' # No Color
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    CYAN=''
    NC=''
fi

# Default file names
BATCH_FILE="batch_migration.txt"
IP_FILE="ipv4_addresses.txt"
INPUT_RELAYS_DIR="instances"
OUTPUT_RELAYS="relay_names_output.txt"
MASTER_LIST="master_relay_list.txt"

# Source directories (dynamic based on current user)
SOURCE_KEYS_DIR="${HOME}/tor-instances"
SOURCE_TORRC_DIR="${HOME}/instances"

# Default port starting numbers
CONTROL_PORT_START=47100
METRICS_PORT_START=31000

# Function to print colored output
print_header() { echo -e "${CYAN}=== $1 ===${NC}"; }
print_success() { echo -e "${GREEN}✓${NC} $1"; }
print_warning() { echo -e "${YELLOW}⚠${NC} $1"; }
print_error() { echo -e "${RED}✗${NC} $1" >&2; }
print_info() { echo -e "${BLUE}ℹ${NC} $1"; }

# Function to show main help
show_help() {
    cat << EOF
${CYAN}Tor Relay Migration Tool v${VERSION}${NC}

${YELLOW}USAGE:${NC}
    $0 <command> [options]

${YELLOW}COMMANDS:${NC}
    ${GREEN}create-inputs${NC}       Create migration input files (batch_migration.txt, ipv4_addresses.txt)
    ${GREEN}create-new${NC}          Create new relays with fresh keys (auto-increments ports)
    ${GREEN}migrate${NC}             Perform complete relay migration (instances + torrc)
    ${GREEN}migrate-instances${NC}   Migrate relay instances and keys only
    ${GREEN}migrate-torrc${NC}       Migrate and update torrc files only
    ${GREEN}manage${NC}              Relay management (start, stop, restart, status, etc.)
    ${GREEN}list${NC}                Generate master list of relays (nickname, fingerprint, IP)
    ${GREEN}inventory${NC}           Inventory currently deployed relays from /etc/tor/instances/
    ${GREEN}verify${NC}              Verify migration was successful
    ${GREEN}status${NC}              Show overall migration status
    ${GREEN}cleanup${NC}             Clean up temporary files
    ${GREEN}fix-ownership${NC}        Fix ownership of existing Tor relay instances

${YELLOW}GLOBAL OPTIONS:${NC}
    --help, -h           Show this help message
    --version, -v        Show version information
    --verbose            Enable verbose output
    --dry-run            Show what would be done without executing
    --batch-file FILE    Use custom batch migration file (default: ${BATCH_FILE})
    --ip-file FILE       Use custom IP addresses file (default: ${IP_FILE})
    --control-port-start NUM  Starting ControlPort number (default: ${CONTROL_PORT_START})
    --metrics-port-start NUM  Starting MetricsPort number (default: ${METRICS_PORT_START})

${YELLOW}EXAMPLES:${NC}
    # Complete migration workflow
    $0 create-inputs
    $0 migrate --verbose
    $0 manage start --parallel
    $0 list
    
    # Create new relays with fresh keys
    $0 create-new --nicknames new_relays.txt --ip-file new_ips.txt --verbose
    
    # Individual operations
    $0 migrate-instances --dry-run
    $0 manage status
    $0 inventory --verbose
    $0 verify

${YELLOW}DETAILED COMMAND HELP:${NC}
    $0 <command> --help     Show detailed help for specific command

${YELLOW}FILES USED:${NC}
    ${BATCH_FILE}    - Old→new relay name mappings
    ${IP_FILE}        - IPv4 addresses for new relays
    ${INPUT_RELAYS_DIR}/      - Source torrc files directory
    ${SOURCE_KEYS_DIR}/ - Source keys directory  
    ${OUTPUT_RELAYS}        - Target relay names file
    ${MASTER_LIST}      - Generated master relay list

${YELLOW}WORKFLOW:${NC}
    1. Create input files with relay names and IP addresses
    2. Migrate relay instances (keys, fingerprints)
    3. Update torrc configurations with new settings
    4. Start/manage relay services
    5. Generate master list for monitoring
    6. Verify everything is working correctly

EOF
}

# Function to show command-specific help
show_command_help() {
    local command="$1"
    case "$command" in
        create-inputs)
            cat << EOF
${CYAN}CREATE-INPUTS Command${NC}

Create migration input files from source data.

${YELLOW}USAGE:${NC}
    $0 create-inputs [options]

${YELLOW}OPTIONS:${NC}
    --input-dir DIR      Source torrc files directory (default: ${INPUT_RELAYS_DIR})
    --output-file FILE   Target relay names file (default: ${OUTPUT_RELAYS})
    --network CIDR       IPv4 network for new relays (e.g., 64.65.1.0/24)
    --octets LIST        Comma-separated list of last octets (e.g., 1,2,3,4)
    --control-port-start NUM  Starting ControlPort number (default: ${CONTROL_PORT_START})
    --metrics-port-start NUM  Starting MetricsPort number (default: ${METRICS_PORT_START})
    --help              Show this help

${YELLOW}EXAMPLES:${NC}
    $0 create-inputs --network 64.65.1.0/24 --octets 1,2,3,4,5
    $0 create-inputs --input-dir old_names_dir/ --output-file new_names.txt

EOF
            ;;
        create-new)
            cat << EOF
${CYAN}CREATE-NEW Command${NC}

Create new Tor relays with fresh keys, automatically finding next available ports.

${YELLOW}USAGE:${NC}
    $0 create-new [options]

${YELLOW}OPTIONS:${NC}
    --nicknames FILE    File containing new relay nicknames (one per line)
    --ip-file FILE      File containing IP addresses for new relays (default: ${IP_FILE})
    --verbose           Show detailed output
    --dry-run           Show what would be done without executing
    --help              Show this help

${YELLOW}DESCRIPTION:${NC}
This command creates entirely new Tor relays with fresh keys. It automatically:
- Scans existing relays in /etc/tor/instances/ to find highest port numbers
- Increments ControlPort and MetricsPort by 1 for each new relay
- Creates new relay instances with tor-instance-create
- Generates torrc configurations with appropriate settings

${YELLOW}INPUT FILES:${NC}
- Nicknames file: One relay nickname per line (underscores not allowed)
- IP file: One IPv4 address per line matching the number of nicknames

${YELLOW}EXAMPLES:${NC}
    $0 create-new --nicknames new_relays.txt --ip-file new_ips.txt --verbose
    $0 create-new --nicknames new_relays.txt --dry-run

EOF
            ;;
        migrate)
            cat << EOF
${CYAN}MIGRATE Command${NC}

Perform complete relay migration (instances + torrc files).

${YELLOW}USAGE:${NC}
    $0 migrate [options]

${YELLOW}OPTIONS:${NC}
    --instances-only    Migrate instances only (skip torrc)
    --torrc-only       Migrate torrc only (skip instances)
    --parallel         Use parallel processing (up to 20 concurrent jobs)
    --control-port-start NUM  Starting ControlPort number (default: ${CONTROL_PORT_START})
    --metrics-port-start NUM  Starting MetricsPort number (default: ${METRICS_PORT_START})
    --help             Show this help

${YELLOW}FEATURES:${NC}
    - Auto-truncates nicknames to 19 characters (Tor's limit)
    - Shows warnings for truncated nicknames with --verbose

${YELLOW}EXAMPLES:${NC}
    $0 migrate --verbose --parallel
    $0 migrate --instances-only --dry-run --parallel
    $0 migrate --torrc-only --parallel --control-port-start 47200 --metrics-port-start 31088

EOF
            ;;
        manage)
            cat << EOF
${CYAN}MANAGE Command${NC}

Manage Tor relay services (start, stop, restart, reload, etc.).

${YELLOW}USAGE:${NC}
    $0 manage <action> [options]

${YELLOW}ACTIONS:${NC}
    start       Start relay services
    stop        Stop all relay services
    restart     Restart all relay services
    reload      Reload all relay services (apply config changes)
    status      Show status of all relays
    enable      Enable relays for boot
    disable     Disable relays from boot
    list        List all relay instances
    count       Count total relays

${YELLOW}START OPTIONS:${NC}
    --all           Start all relay instances (default)
    --migrated-only Start only recently migrated relays
    --new-only      Start only relays that are not currently running
    --parallel      Use parallel processing
    --verbose       Show detailed output including specific error messages

${YELLOW}OTHER OPTIONS:${NC}
    --parallel    Use parallel processing (for stop/restart/etc.)
    --verbose     Show detailed output
    --help        Show this help

${YELLOW}EXAMPLES:${NC}
    $0 manage start --all --parallel --verbose
    $0 manage start --migrated-only --verbose
    $0 manage status
    $0 manage restart --verbose
    $0 manage reload --parallel --verbose

EOF
            ;;
        list)
            cat << EOF
${CYAN}LIST Command${NC}

Generate master list of relays with nickname, fingerprint, and IP address.

${YELLOW}USAGE:${NC}
    $0 list [options]

${YELLOW}OPTIONS:${NC}
    --output FILE       Output file (default: ${MASTER_LIST})
    --format FORMAT     Output format: txt, csv, json (default: txt)
    --sort FIELD        Sort by: nickname, ip, fingerprint (default: nickname)
    --verbose           Show detailed output
    --help              Show this help

${YELLOW}EXAMPLES:${NC}
    $0 list --format csv --output relays.csv
    $0 list --sort ip
    $0 list --format json

EOF
            ;;
        verify)
            cat << EOF
${CYAN}VERIFY Command${NC}

Verify that migration was successful.

${YELLOW}USAGE:${NC}
    $0 verify [options]

${YELLOW}OPTIONS:${NC}
    --check-services    Check if services are running
    --check-configs     Validate torrc configurations
    --check-ports       Verify port bindings
    --all               Run all verification checks
    --help              Show this help

${YELLOW}EXAMPLES:${NC}
    $0 verify --all
    $0 verify --check-services
    $0 verify --check-ports

EOF
            ;;
        fix-ownership)
            cat << EOF
${CYAN}FIX-OWNERSHIP Command${NC}

Fix ownership of existing Tor relay instances.

${YELLOW}USAGE:${NC}
    $0 fix-ownership [options]

${YELLOW}OPTIONS:${NC}
    --verbose      Show detailed output
    --dry-run      Show what would be done without executing
    --help         Show this help

${YELLOW}DESCRIPTION:${NC}
This command fixes the ownership of files in /var/lib/tor-instances/ to use
the correct _tor-{relayname} user instead of the generic debian-tor user.

${YELLOW}EXAMPLES:${NC}
    $0 fix-ownership --verbose
    $0 fix-ownership --dry-run

EOF
            ;;
        *)
            print_error "Unknown command: $command"
            print_info "Use '$0 --help' for available commands"
            exit 1
            ;;
    esac
}

# Function to check prerequisites
check_prerequisites() {
    local missing=()
    
    # Check for required commands
    for cmd in systemctl sudo ss grep awk sort; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            missing+=("$cmd")
        fi
    done
    
    # Check for our helper scripts
    for script in manage_tor_relays.sh; do
        if [ ! -f "$SCRIPT_DIR/$script" ] || [ ! -x "$SCRIPT_DIR/$script" ]; then
            missing+=("$script (not found or not executable)")
        fi
    done
    
    if [ ${#missing[@]} -gt 0 ]; then
        print_error "Missing prerequisites:"
        for item in "${missing[@]}"; do
            echo "  - $item"
        done
        return 1
    fi
    
    return 0
}

# Function to create input files
create_inputs() {
    local input_dir="$INPUT_RELAYS_DIR"
    local output_file="$OUTPUT_RELAYS"
    local network=""
    local octets=""
    local control_port_start="$CONTROL_PORT_START"
    local metrics_port_start="$METRICS_PORT_START"
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --input-dir)
                input_dir="$2"
                shift 2
                ;;
            --output-file)
                output_file="$2"
                shift 2
                ;;
            --network)
                network="$2"
                shift 2
                ;;
            --octets)
                octets="$2"
                shift 2
                ;;
            --control-port-start)
                control_port_start="$2"
                shift 2
                ;;
            --metrics-port-start)
                metrics_port_start="$2"
                shift 2
                ;;
            --help)
                show_command_help "create-inputs"
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    print_header "Creating Migration Input Files"
    
    # Check if source directory exists
    if [ ! -d "$input_dir" ]; then
        print_error "Input directory not found: $input_dir"
        exit 1
    fi
    
    # Check if there are any files or directories in the directory
    if [ ! "$(ls -A "$input_dir" 2>/dev/null)" ]; then
        print_error "Input directory is empty: $input_dir"
        exit 1
    fi
    
    if [ ! -f "$output_file" ]; then
        print_error "Output file not found: $output_file"
        exit 1
    fi
    
    # Create temporary input file from directory contents
    local temp_input_file=$(mktemp)
    trap "rm -f $temp_input_file" EXIT
    
    print_info "Reading relay names from directory $input_dir..."
    
    # List all files and directories in the directory and use their names (without path) as relay names
    for item in "$input_dir"/*; do
        if [ -f "$item" ] || [ -d "$item" ]; then
            basename "$item"
        fi
    done | sort > "$temp_input_file"
    
    local input_count=$(wc -l < "$temp_input_file")
    print_info "Found $input_count relay names in directory"
    
    # Validate relay names for underscores (not allowed in Tor relay names)
    print_info "Validating relay names..."
    local invalid_names=()
    while IFS= read -r relay_name; do
        if [[ "$relay_name" == *"_"* ]]; then
            invalid_names+=("$relay_name")
        fi
    done < "$temp_input_file"
    
    if [ ${#invalid_names[@]} -gt 0 ]; then
        print_error "Invalid relay names found - underscores are not allowed in Tor relay names:"
        for name in "${invalid_names[@]}"; do
            echo "  - $name"
        done
        print_info "Please rename these directories/files to remove underscores before running migration"
        exit 1
    fi
    
    print_success "All relay names are valid (no underscores)"
    
    # Validate new relay names in output file for underscores  
    print_info "Validating new relay names from $output_file..."
    local invalid_new_names=()
    while IFS= read -r new_relay_name; do
        # Skip empty lines and comments
        if [[ -n "$new_relay_name" && ! "$new_relay_name" =~ ^[[:space:]]*# ]]; then
            if [[ "$new_relay_name" == *"_"* ]]; then
                invalid_new_names+=("$new_relay_name")
            fi
        fi
    done < "$output_file"
    
    if [ ${#invalid_new_names[@]} -gt 0 ]; then
        print_error "Invalid new relay names found in $output_file - underscores are not allowed in Tor relay names:"
        for name in "${invalid_new_names[@]}"; do
            echo "  - $name"
        done
        print_info "Please update $output_file to remove underscores from relay names before running migration"
        exit 1
    fi
    
    print_success "All new relay names are valid (no underscores)"
    
    # Create batch migration file
    print_info "Creating batch migration file from directory $input_dir and $output_file..."
    if paste "$temp_input_file" "$output_file" | sed 's/\t/ /' > "$BATCH_FILE"; then
        print_success "Created $BATCH_FILE"
    else
        print_error "Failed to create $BATCH_FILE"
        exit 1
    fi
    
    # Create IP addresses file if network and octets provided
    if [ -n "$network" ] && [ -n "$octets" ]; then
        print_info "Creating IP addresses file for network $network..."
        local base_ip=$(echo "$network" | cut -d'/' -f1 | cut -d'.' -f1-3)
        echo "# IPv4 addresses for new relay instances" > "$IP_FILE"
        echo "# Network: $network" >> "$IP_FILE"
        echo "# One IP per line" >> "$IP_FILE"
        
        IFS=',' read -ra OCTET_ARRAY <<< "$octets"
        for octet in "${OCTET_ARRAY[@]}"; do
            echo "${base_ip}.${octet}" >> "$IP_FILE"
        done
        
        print_success "Created $IP_FILE with ${#OCTET_ARRAY[@]} addresses"
    fi
    
    print_success "Input files created successfully"
}

# Function to migrate instances
migrate_instances() {
    local batch_file="$BATCH_FILE"
    local verbose=false
    local dry_run=false
    local parallel=false
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --batch-file)
                batch_file="$2"
                shift 2
                ;;
            --verbose)
                verbose=true
                shift
                ;;
            --dry-run)
                dry_run=true
                shift
                ;;
            --parallel)
                parallel=true
                shift
                ;;
            *)
                shift
                ;;
        esac
    done
    
    if [ ! -f "$batch_file" ]; then
        print_error "Batch file not found: $batch_file"
        return 1
    fi
    
    local total_relays=$(grep -c '^[^#]' "$batch_file")
    local processed=0
    local success=0
    local errors=0
    
    # Function to process a single relay
    process_relay() {
        local old_name="$1"
        local new_name="$2"
        local relay_num="$3"
        local total="$4"
        
        if [ "$verbose" = true ]; then
            echo "Processing ($relay_num/$total): $old_name -> $new_name"
        fi
        
        # Check if old instance exists in source directory (for keys)
        local source_keys_dir="$SOURCE_KEYS_DIR/$old_name"
        if [ ! -d "$source_keys_dir" ]; then
            if [ "$verbose" = true ]; then
                print_warning "Source keys directory not found: $source_keys_dir"
            fi
            return 1
        fi
        
        # Create new instance
        if [ "$dry_run" = false ]; then
            if sudo tor-instance-create "$new_name" >/dev/null 2>&1; then
                if [ "$verbose" = true ]; then
                    print_success "Created instance: $new_name"
                fi
            else
                print_error "Failed to create instance: $new_name"
                return 1
            fi
            
            # Copy all keys and important files from source directory
            if [ -d "$source_keys_dir/keys" ]; then
                # Ensure keys directory exists in destination
                sudo mkdir -p "/var/lib/tor-instances/$new_name/keys/"
                sudo cp -r "$source_keys_dir/keys/"* "/var/lib/tor-instances/$new_name/keys/"
            fi
            
            if [ -f "$source_keys_dir/fingerprint" ]; then
                sudo cp "$source_keys_dir/fingerprint" "/var/lib/tor-instances/$new_name/"
            fi
            
            if [ -f "$source_keys_dir/fingerprint-ed25519" ]; then
                sudo cp "$source_keys_dir/fingerprint-ed25519" "/var/lib/tor-instances/$new_name/"
            fi
            
            # Set ownership to _tor-{relayname}
            sudo chown -R "_tor-$new_name:_tor-$new_name" "/var/lib/tor-instances/$new_name/"
        else
            if [ "$verbose" = true ]; then
                echo "  [DRY-RUN] Would create instance: $new_name"
                echo "  [DRY-RUN] Would copy keys from: $source_keys_dir"
            fi
        fi
        
        return 0
    }
    
    if [ "$parallel" = true ]; then
        # Parallel processing
        local pids=()
        local relay_num=0
        
        while read -r old_name new_name; do
            # Skip comments and empty lines
            if [[ -z "$old_name" || "$old_name" =~ ^[[:space:]]*# ]]; then
                continue
            fi
            
            ((relay_num++))
            ((processed++))
            
            # Process relay in background
            process_relay "$old_name" "$new_name" "$relay_num" "$total_relays" &
            pids+=($!)
            
            # Limit concurrent jobs to avoid overloading the system
            if [ ${#pids[@]} -ge 20 ]; then
                for pid in "${pids[@]}"; do
                    if wait "$pid"; then
                        ((success++))
                    else
                        ((errors++))
                    fi
                done
                pids=()
            fi
        done < "$batch_file"
        
        # Wait for remaining background jobs
        for pid in "${pids[@]}"; do
            if wait "$pid"; then
                ((success++))
            else
                ((errors++))
            fi
        done
    else
        # Sequential processing
        while read -r old_name new_name; do
            # Skip comments and empty lines
            if [[ -z "$old_name" || "$old_name" =~ ^[[:space:]]*# ]]; then
                continue
            fi
            
            ((processed++))
            
            if process_relay "$old_name" "$new_name" "$processed" "$total_relays"; then
                ((success++))
            else
                ((errors++))
            fi
        done < "$batch_file"
    fi
    
    if [ "$verbose" = true ]; then
        echo ""
        print_info "Migration Summary:"
        echo "  Total relays: $total_relays"
        echo "  Processed: $processed"
        echo "  Successful: $success"
        echo "  Errors: $errors"
    fi
    
    return $errors
}

# Function to migrate torrc files
migrate_torrc() {
    local batch_file="$BATCH_FILE"
    local ip_file="$IP_FILE"
    local verbose=false
    local dry_run=false
    local parallel=false
    local control_port_start="$CONTROL_PORT_START"
    local metrics_port_start="$METRICS_PORT_START"
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --batch-file)
                batch_file="$2"
                shift 2
                ;;
            --ip-file)
                ip_file="$2"
                shift 2
                ;;
            --control-port-start)
                control_port_start="$2"
                shift 2
                ;;
            --metrics-port-start)
                metrics_port_start="$2"
                shift 2
                ;;
            --verbose)
                verbose=true
                shift
                ;;
            --dry-run)
                dry_run=true
                shift
                ;;
            --parallel)
                parallel=true
                shift
                ;;
            *)
                shift
                ;;
        esac
    done
    
    if [ ! -f "$batch_file" ]; then
        print_error "Batch file not found: $batch_file"
        return 1
    fi
    
    if [ ! -f "$ip_file" ]; then
        print_error "IP file not found: $ip_file"
        return 1
    fi
    
    # Read IP addresses into array (skip comments)
    mapfile -t ip_addresses < <(grep -v '^[[:space:]]*#' "$ip_file" | grep -v '^[[:space:]]*$')
    
    local total_relays=$(grep -c '^[^#]' "$batch_file")
    local processed=0
    local success=0
    local errors=0
    
    # Scan existing relays to find highest port numbers
    print_info "Scanning existing relays to find highest port numbers..."
    local max_control_port=0
    local max_metrics_port=0
    local existing_count=0
    
    # Temporarily disable strict error checking for this section
    set +e
    
    if [ -d "/etc/tor/instances" ]; then
        if [ "$verbose" = true ]; then
            print_info "/etc/tor/instances directory found, scanning torrc files..."
        fi
        
        # Find all torrc files and process them
        local torrc_files
        torrc_files=$(find /etc/tor/instances -name "torrc" -type f 2>/dev/null)
        
        if [ -n "$torrc_files" ]; then
            while IFS= read -r torrc_file; do
                if [ ! -f "$torrc_file" ]; then
                    continue
                fi
                
                existing_count=$((existing_count + 1))
                local relay_name=$(basename "$(dirname "$torrc_file")")
                
                if [ "$verbose" = true ]; then
                    print_info "Scanning $relay_name/torrc (count: $existing_count)"
                fi
                
                # Extract ControlPort number
                local control_line
                control_line=$(sudo grep "^ControlPort" "$torrc_file" 2>/dev/null | head -1)
                if [ -n "$control_line" ]; then
                    local extracted_port
                    extracted_port=$(echo "$control_line" | sed 's/.*:\([0-9][0-9]*\).*/\1/')
                    if [[ "$extracted_port" =~ ^[0-9]+$ ]] && [ "$extracted_port" -gt "$max_control_port" ]; then
                        max_control_port="$extracted_port"
                        if [ "$verbose" = true ]; then
                            print_info "New max ControlPort: $max_control_port from $relay_name"
                        fi
                    fi
                fi
                
                # Extract MetricsPort number
                local metrics_line
                metrics_line=$(sudo grep "^MetricsPort" "$torrc_file" 2>/dev/null | head -1)
                if [ -n "$metrics_line" ]; then
                    local extracted_port
                    extracted_port=$(echo "$metrics_line" | sed 's/.*:\([0-9][0-9]*\).*/\1/')
                    if [[ "$extracted_port" =~ ^[0-9]+$ ]] && [ "$extracted_port" -gt "$max_metrics_port" ]; then
                        max_metrics_port="$extracted_port"
                        if [ "$verbose" = true ]; then
                            print_info "New max MetricsPort: $max_metrics_port from $relay_name"
                        fi
                    fi
                fi
            done <<< "$torrc_files"
        else
            if [ "$verbose" = true ]; then
                print_info "No torrc files found in /etc/tor/instances/"
            fi
        fi
    else
        if [ "$verbose" = true ]; then
            print_info "/etc/tor/instances/ directory does not exist"
        fi
    fi
    
    # Re-enable strict error checking
    set -e
    
    # Set starting ports (next available)
    local next_control_port=$((max_control_port + 1))
    local next_metrics_port=$((max_metrics_port + 1))
    
    # If no existing relays, use defaults
    if [ "$max_control_port" -eq 0 ]; then
        next_control_port="$control_port_start"
    fi
    if [ "$max_metrics_port" -eq 0 ]; then
        next_metrics_port="$metrics_port_start"
    fi
    
    print_info "Found $existing_count existing relay configurations"
    print_info "Highest ControlPort: $max_control_port, starting new relays at: $next_control_port"
    print_info "Highest MetricsPort: $max_metrics_port, starting new relays at: $next_metrics_port"
    
    # Function to process a single torrc
    process_torrc() {
        local old_name="$1"
        local new_name="$2"
        local relay_num="$3"
        local total="$4"
        local ip_index="$5"
        
        if [ "$verbose" = true ]; then
            echo "Processing ($relay_num/$total): $old_name -> $new_name"
        fi
        
        # Get IP address
        local new_ip
        if [ "$ip_index" -lt "${#ip_addresses[@]}" ]; then
            new_ip="${ip_addresses[$ip_index]}"
        else
            print_error "Not enough IP addresses for relay: $new_name"
            return 1
        fi
        
        # Calculate ports using dynamically found highest ports
        local control_port=$((next_control_port + ip_index))
        local metrics_port=$((next_metrics_port + ip_index))
        
        # Source and destination paths
        local source_torrc="$SOURCE_TORRC_DIR/$old_name/torrc"
        local dest_torrc="/etc/tor/instances/$new_name/torrc"
        
        if [ "$dry_run" = false ]; then
            # Check source exists
            if [ ! -f "$source_torrc" ]; then
                if [ "$verbose" = true ]; then
                    print_warning "Source torrc not found: $source_torrc"
                fi
                return 1
            fi
            
            # Create destination directory
            sudo mkdir -p "$(dirname "$dest_torrc")"
            
            # Process torrc file
            local temp_torrc=$(mktemp)
            
            # Update torrc configuration with flags to prevent duplication
            local controlport_set=false
            local orport_set=false
            local address_set=false
            local outboundbind_set=false
            local nickname_set=false
            local metricsport_set=false
            
            while IFS= read -r line; do
                # Update ControlPort (bind to 127.0.0.1 and prevent duplicates)
                if [[ "$line" =~ ^[[:space:]]*ControlPort[[:space:]] ]]; then
                    if [ "$controlport_set" = false ]; then
                        echo "ControlPort 127.0.0.1:$control_port"
                        controlport_set=true
                    fi
                # Update ORPort (prevent duplicates)
                elif [[ "$line" =~ ^[[:space:]]*ORPort[[:space:]] ]]; then
                    if [ "$orport_set" = false ]; then
                        echo "ORPort $new_ip:443"
                        orport_set=true
                    fi
                # Update Address (prevent duplicates)
                elif [[ "$line" =~ ^[[:space:]]*Address[[:space:]] ]]; then
                    if [ "$address_set" = false ]; then
                        echo "Address $new_ip"
                        address_set=true
                    fi
                # Update OutboundBindAddress (prevent duplicates)
                elif [[ "$line" =~ ^[[:space:]]*OutboundBindAddress[[:space:]] ]]; then
                    if [ "$outboundbind_set" = false ]; then
                        echo "OutboundBindAddress $new_ip"
                        outboundbind_set=true
                    fi
                # Update Nickname (auto-truncate to 19 characters if needed, prevent duplicates)
                elif [[ "$line" =~ ^[[:space:]]*Nickname[[:space:]] ]]; then
                    if [ "$nickname_set" = false ]; then
                        local truncated_name="$new_name"
                        if [ ${#new_name} -gt 19 ]; then
                            truncated_name="${new_name:0:19}"
                            if [ "$verbose" = true ]; then
                                print_warning "Nickname '$new_name' (${#new_name} chars) truncated to '$truncated_name' (19 chars limit)"
                            fi
                        fi
                        echo "Nickname $truncated_name"
                        nickname_set=true
                    fi
                # Update MetricsPort (bind to 127.0.0.1 and prevent duplicates)
                elif [[ "$line" =~ ^[[:space:]]*MetricsPort[[:space:]] ]]; then
                    if [ "$metricsport_set" = false ]; then
                        echo "MetricsPort 127.0.0.1:$metrics_port"
                        metricsport_set=true
                    fi
                # Update comments referencing old name (use truncated name if applicable)
                elif [[ "$line" =~ ^[[:space:]]*#.*$old_name ]]; then
                    local comment_name="$new_name"
                    if [ ${#new_name} -gt 19 ]; then
                        comment_name="${new_name:0:19}"
                    fi
                    echo "$line" | sed "s/$old_name/$comment_name/g"
                else
                    echo "$line"
                fi
            done < "$source_torrc" > "$temp_torrc"
            
            # Copy to destination
            if sudo cp "$temp_torrc" "$dest_torrc"; then
                sudo chown "_tor-$new_name:_tor-$new_name" "$dest_torrc"
                if [ "$verbose" = true ]; then
                    print_success "Created torrc: $dest_torrc"
                fi
                rm -f "$temp_torrc"
                return 0
            else
                print_error "Failed to create torrc: $dest_torrc"
                rm -f "$temp_torrc"
                return 1
            fi
        else
            if [ "$verbose" = true ]; then
                echo "  [DRY-RUN] Would create: $dest_torrc"
                echo "  [DRY-RUN] IP: $new_ip, ControlPort: 127.0.0.1:$control_port, MetricsPort: 127.0.0.1:$metrics_port"
            fi
            return 0
        fi
    }
    
    if [ "$parallel" = true ]; then
        # Parallel processing
        local pids=()
        local relay_num=0
        local ip_index=0
        
        while read -r old_name new_name; do
            # Skip comments and empty lines
            if [[ -z "$old_name" || "$old_name" =~ ^[[:space:]]*# ]]; then
                continue
            fi
            
            ((relay_num++))
            ((processed++))
            
            # Process torrc in background
            process_torrc "$old_name" "$new_name" "$relay_num" "$total_relays" "$ip_index" &
            pids+=($!)
            
            # Limit concurrent jobs to avoid overloading the system
            if [ ${#pids[@]} -ge 20 ]; then
                for pid in "${pids[@]}"; do
                    if wait "$pid"; then
                        ((success++))
                    else
                        ((errors++))
                    fi
                done
                pids=()
            fi
            
            ((ip_index++))
        done < "$batch_file"
        
        # Wait for remaining background jobs
        for pid in "${pids[@]}"; do
            if wait "$pid"; then
                ((success++))
            else
                ((errors++))
            fi
        done
    else
        # Sequential processing
        local ip_index=0
        
        while read -r old_name new_name; do
            # Skip comments and empty lines
            if [[ -z "$old_name" || "$old_name" =~ ^[[:space:]]*# ]]; then
                continue
            fi
            
            ((processed++))
            
            if process_torrc "$old_name" "$new_name" "$processed" "$total_relays" "$ip_index"; then
                ((success++))
            else
                ((errors++))
            fi
            
            ((ip_index++))
        done < "$batch_file"
    fi
    
    if [ "$verbose" = true ]; then
        echo ""
        print_info "Torrc Migration Summary:"
        echo "  Total relays: $total_relays"
        echo "  Processed: $processed"
        echo "  Successful: $success"
        echo "  Errors: $errors"
    fi
    
    return $errors
}

# Function to perform migration
migrate_relays() {
    local instances_only=false
    local torrc_only=false
    local parallel_flag=""
    local verbose_flag=""
    local dry_run_flag=""
    local control_port_start="$CONTROL_PORT_START"
    local metrics_port_start="$METRICS_PORT_START"
    

    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --instances-only)
                instances_only=true
                shift
                ;;
            --torrc-only)
                torrc_only=true
                shift
                ;;
            --parallel)
                parallel_flag="--parallel"
                shift
                ;;
            --verbose)
                verbose_flag="--verbose"
                shift
                ;;
            --dry-run)
                dry_run_flag="--dry-run"
                shift
                ;;
            --control-port-start)
                control_port_start="$2"
                CONTROL_PORT_START="$2"  # Update global variable too
                shift 2
                ;;
            --metrics-port-start)
                metrics_port_start="$2"
                METRICS_PORT_START="$2"  # Update global variable too
                shift 2
                ;;
            --help)
                show_command_help "migrate"
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    print_header "Starting Tor Relay Migration"
    
    # Check required files
    if [ ! -f "$BATCH_FILE" ]; then
        print_error "Batch migration file not found: $BATCH_FILE"
        print_info "Run '$0 create-inputs' first"
        exit 1
    fi
    
    # Migrate instances
    if [ "$torrc_only" = false ]; then
        print_info "Migrating relay instances..."
        if migrate_instances --batch-file "$BATCH_FILE" $verbose_flag $dry_run_flag $parallel_flag; then
            print_success "Instance migration completed"
        else
            print_error "Instance migration failed"
            exit 1
        fi
    fi
    
    # Migrate torrc files
    if [ "$instances_only" = false ]; then
        if [ ! -f "$IP_FILE" ]; then
            print_error "IP addresses file not found: $IP_FILE"
            print_info "Run '$0 create-inputs' first"
            exit 1
        fi
        
        print_info "Migrating torrc configurations..."
        if migrate_torrc --batch-file "$BATCH_FILE" --ip-file "$IP_FILE" --control-port-start "$control_port_start" --metrics-port-start "$metrics_port_start" $verbose_flag $dry_run_flag $parallel_flag; then
            print_success "Torrc migration completed"
        else
            print_error "Torrc migration failed"
            exit 1
        fi
    fi
    
    print_success "Migration completed successfully"
}

# Function to start migrated relays with error reporting
start_migrated_relays() {
    local verbose=false
    local parallel=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --verbose)
                verbose=true
                shift
                ;;
            --parallel)
                parallel=true
                shift
                ;;
            *)
                shift
                ;;
        esac
    done
    
    if [ ! -f "$BATCH_FILE" ]; then
        print_error "Batch migration file not found: $BATCH_FILE"
        print_info "Run migration first or use --all to start all relays"
        return 1
    fi
    
    # Read the migrated relay names
    mapfile -t new_relays < <(awk '{if($0 !~ /^[[:space:]]*#/ && $0 !~ /^[[:space:]]*$/) print $2}' "$BATCH_FILE")
    
    print_info "Found ${#new_relays[@]} migrated relays to start"
    
    if [ "$verbose" = true ]; then
        print_info "Relay list: ${new_relays[*]}"
    fi
    
    local success_count=0
    local error_count=0
    local already_running=0
    
    # Function to start a single relay
    start_single_relay() {
        local relay="$1"
        local relay_num="$2"
        local total="$3"
        
        if [ -z "$relay" ]; then
            return 1
        fi
        
        # Check if torrc exists
        if [ ! -f "/etc/tor/instances/$relay/torrc" ]; then
            if [ "$verbose" = true ]; then
                print_warning "Torrc not found for $relay, skipping"
            fi
            return 1
        fi
        
        # Check if data directory exists (use sudo for permission)
        if ! sudo test -d "/var/lib/tor-instances/$relay"; then
            if [ "$verbose" = true ]; then
                print_warning "Data directory not found for $relay, skipping"
            fi
            return 1
        fi
        
        # Check if already running first
        if sudo systemctl is-active "tor@$relay" >/dev/null 2>&1; then
            if [ "$verbose" = true ]; then
                print_info "$relay is already running"
            fi
            return 2  # Special return code for "already running"
        fi
        
        if [ "$verbose" = true ]; then
            print_info "Starting $relay ($relay_num/$total)..."
        fi
        
        # Start the service
        if sudo systemctl start "tor@$relay" >/dev/null 2>&1; then
            if [ "$verbose" = true ]; then
                print_success "Started $relay"
            fi
            return 0
        else
            print_error "Failed to start $relay"
            return 1
        fi
    }
    
    if [ "$verbose" = true ]; then
        print_info "Starting processing (parallel=$parallel)"
    fi
    
    if [ "$parallel" = true ]; then
        if [ "$verbose" = true ]; then
            print_info "Using parallel processing mode"
        fi
        # Simplified parallel processing - start all at once, then wait
        local pids=()
        local relay_num=0
        local temp_files=()
        
        # Start all relays in background - simplified approach
        for relay in "${new_relays[@]}"; do
            relay_num=$((relay_num + 1))
            
            # Disable strict error handling for background jobs
            set +e
            start_single_relay "$relay" "$relay_num" "${#new_relays[@]}" &
            pids+=($!)
            set -e
            
            # Small delay to prevent overwhelming the system
            if [ $((relay_num % 5)) -eq 0 ]; then
                sleep 0.2
            fi
        done
        
        # Wait for all jobs to complete
        for pid in "${pids[@]}"; do
            local ret_code
            wait "$pid"
            ret_code=$?
            
            if [ $ret_code -eq 0 ]; then
                success_count=$((success_count + 1))
            elif [ $ret_code -eq 2 ]; then
                already_running=$((already_running + 1))
            else
                error_count=$((error_count + 1))
            fi
        done
    else
        if [ "$verbose" = true ]; then
            print_info "Using sequential processing mode"
        fi
        # Sequential processing
        local relay_num=0

        for relay in "${new_relays[@]}"; do
            relay_num=$((relay_num + 1))
            
            if [ "$verbose" = true ]; then
                print_info "Processing relay $relay_num: $relay"
            fi
            
            # Temporarily disable strict error handling for this function
            set +e
            local ret_code
            start_single_relay "$relay" "$relay_num" "${#new_relays[@]}"
            ret_code=$?
            set -e
            
            if [ "$verbose" = true ]; then
                print_info "Relay $relay returned code: $ret_code"
            fi
            
            if [ $ret_code -eq 0 ]; then
                success_count=$((success_count + 1))
            elif [ $ret_code -eq 2 ]; then
                already_running=$((already_running + 1))
            else
                error_count=$((error_count + 1))
            fi
        done
    fi
    
    echo ""
    print_info "Start Summary:"
    echo "  Total relays: ${#new_relays[@]}"
    echo "  Successfully started: $success_count"
    echo "  Already running: $already_running"
    echo "  Failed: $error_count"
    
    if [ $error_count -gt 0 ] && [ "$verbose" = true ]; then
        echo ""
        print_info "To check logs for failed relays:"
        echo "  sudo journalctl -u tor@<relay_name> -f"
    fi
    
    local total_active=$((success_count + already_running))
    if [ $error_count -eq 0 ]; then
        print_success "All $total_active migrated relays are now running!"
        return 0
    else
        print_warning "$total_active relays running, $error_count failed"
        return 1
    fi
}

# Function to start a single relay (for start_all_relays)
start_single_relay_all() {
    local relay="$1"
    local relay_num="$2"
    local total="$3"
    local verbose="$4"
    
    # Disable strict error checking for this function
    set +e
    
    if [ "$verbose" = "true" ]; then
        echo "ℹ Starting $relay ($relay_num/$total)..."
    fi
    
    # Check if already running first
    local is_active
    is_active=$(sudo systemctl is-active "tor@$relay" 2>/dev/null)
    if [ "$is_active" = "active" ]; then
        if [ "$verbose" = "true" ]; then
            echo "ℹ $relay is already running"
        fi
        return 2  # Special return code for "already running"
    fi
    
    # Check if service exists
    if ! sudo systemctl list-unit-files | grep -q "tor@$relay.service"; then
        if [ "$verbose" = "true" ]; then
            echo "✗ Service tor@$relay.service not found" >&2
        fi
        return 1
    fi
    
    # Try to start the service
    local error_output
    error_output=$(sudo systemctl start "tor@$relay" 2>&1)
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        # Wait a moment and verify it actually started
        sleep 1
        local final_status
        final_status=$(sudo systemctl is-active "tor@$relay" 2>/dev/null)
        if [ "$final_status" = "active" ]; then
            if [ "$verbose" = "true" ]; then
                echo "✓ Started $relay successfully"
            fi
            return 0
        else
            if [ "$verbose" = "true" ]; then
                echo "✗ $relay started but then failed - check logs" >&2
            fi
            return 1
        fi
    else
        # Analyze the error
        local error_msg="Unknown error"
        if [[ "$error_output" =~ "Job for tor@$relay.service failed" ]]; then
            # Get more detailed error from journalctl
            local journal_error
            journal_error=$(sudo journalctl -u "tor@$relay" --no-pager -n 5 --since "1 minute ago" 2>/dev/null | tail -1 || echo "")
            if [[ "$journal_error" =~ "Address already in use" ]]; then
                error_msg="Port/address already in use"
            elif [[ "$journal_error" =~ "Permission denied" ]]; then
                error_msg="Permission denied"
            elif [[ "$journal_error" =~ "No such file or directory" ]]; then
                error_msg="Configuration file missing"
            elif [[ "$journal_error" =~ "User _tor-$relay" ]]; then
                error_msg="User _tor-$relay does not exist"
            else
                error_msg="Service failed to start (check: sudo journalctl -u tor@$relay)"
            fi
        elif [[ "$error_output" =~ "not found" ]]; then
            error_msg="Service not found"
        elif [[ "$error_output" =~ "Failed to start" ]]; then
            error_msg="Failed to start: $error_output"
        fi
        
        if [ "$verbose" = "true" ]; then
            echo "✗ Failed to start $relay: $error_msg" >&2
        fi
        return 1
    fi
}

# Function to start only relays that are not currently running
start_new_relays_only() {
    local verbose=false
    local parallel=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --verbose)
                verbose=true
                shift
                ;;
            --parallel)
                parallel=true
                shift
                ;;
            *)
                shift
                ;;
        esac
    done
    
    print_info "Starting only relays that are not currently running..."
    
    # Get list of all relay instances
    local all_relays=()
    if [ -d "/etc/tor/instances" ]; then
        mapfile -t all_relays < <(ls -1 /etc/tor/instances/)
    fi
    
    if [ ${#all_relays[@]} -eq 0 ]; then
        print_warning "No relay instances found in /etc/tor/instances/"
        return 1
    fi
    
    # Filter to only non-running relays
    local non_running_relays=()
    local already_running_count=0
    
    print_info "Checking which relays are not currently running..."
    for relay in "${all_relays[@]}"; do
        if ! sudo systemctl is-active "tor@$relay" >/dev/null 2>&1; then
            non_running_relays+=("$relay")
            if [ "$verbose" = true ]; then
                print_info "Found non-running relay: $relay"
            fi
        else
            ((already_running_count++))
            if [ "$verbose" = true ]; then
                print_info "Skipping already running relay: $relay"
            fi
        fi
    done
    
    print_info "Found ${#non_running_relays[@]} relays to start (${already_running_count} already running)"
    
    if [ ${#non_running_relays[@]} -eq 0 ]; then
        print_success "All relays are already running!"
        return 0
    fi
    
    local success_count=0
    local error_count=0
    
    # Start only the non-running relays
    if [ "$parallel" = true ]; then
        print_info "Starting ${#non_running_relays[@]} relays in parallel..."
        local pids=()
        local relay_num=0
        
        for relay in "${non_running_relays[@]}"; do
            ((relay_num++))
            
            # Start relay in background
            start_single_relay_all "$relay" "$relay_num" "${#non_running_relays[@]}" "$verbose" &
            pids+=($!)
            
            # Limit concurrent jobs
            if [ ${#pids[@]} -ge 10 ]; then
                for pid in "${pids[@]}"; do
                    local ret_code
                    wait "$pid"
                    ret_code=$?
                    if [ $ret_code -eq 0 ]; then
                        ((success_count++))
                    elif [ $ret_code -ne 2 ]; then  # Don't count "already running" as errors
                        ((error_count++))
                    fi
                done
                pids=()
            fi
        done
        
        # Wait for remaining jobs
        for pid in "${pids[@]}"; do
            local ret_code
            wait "$pid"
            ret_code=$?
            if [ $ret_code -eq 0 ]; then
                ((success_count++))
            elif [ $ret_code -ne 2 ]; then  # Don't count "already running" as errors
                ((error_count++))
            fi
        done
    else
        # Sequential processing
        print_info "Starting ${#non_running_relays[@]} relays sequentially..."
        local relay_num=0
        for relay in "${non_running_relays[@]}"; do
            ((relay_num++))
            
            local ret_code
            # Temporarily disable strict error checking for systemctl operations
            set +e
            start_single_relay_all "$relay" "$relay_num" "${#non_running_relays[@]}" "$verbose"
            ret_code=$?
            set -e
            
            if [ $ret_code -eq 0 ]; then
                ((success_count++))
            elif [ $ret_code -ne 2 ]; then  # Don't count "already running" as errors
                ((error_count++))
            fi
        done
    fi
    
    echo ""
    print_info "Start New Relays Summary:"
    echo "  Relays to start: ${#non_running_relays[@]}"
    echo "  Successfully started: $success_count"
    echo "  Failed: $error_count"
    echo "  Already running (skipped): $already_running_count"
    
    if [ $error_count -eq 0 ]; then
        print_success "All new relays started successfully!"
        return 0
    else
        print_warning "$success_count relays started, $error_count failed"
        return 1
    fi
}

# Function to start all relays with error reporting  
start_all_relays() {
    local verbose=false
    local parallel=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --verbose)
                verbose=true
                shift
                ;;
            --parallel)
                parallel=true
                shift
                ;;
            *)
                shift
                ;;
        esac
    done
    
    print_info "Starting all relay services..."
    
    # Get list of all relay instances
    local all_relays=()
    if [ -d "/etc/tor/instances" ]; then
        mapfile -t all_relays < <(ls -1 /etc/tor/instances/ 2>/dev/null | sort)
    fi
    
    if [ ${#all_relays[@]} -eq 0 ]; then
        print_warning "No relay instances found in /etc/tor/instances/"
        return 1
    fi
    
    print_info "Found ${#all_relays[@]} total relay instances"
    
    # Temporarily disable strict error checking for this function
    set +e
    
    local success_count=0
    local error_count=0
    local already_running=0
    local errors_detail=()
    
    if [ "$verbose" = true ]; then
        print_info "Starting relays in $([ "$parallel" = true ] && echo "parallel" || echo "sequential") mode..."
    fi
    
    if [ "$parallel" = true ]; then
        # Parallel processing
        print_info "Using parallel mode with batches of 20 relays..."
        local pids=()
        local relay_num=0
        local batch_count=0
        
        for relay in "${all_relays[@]}"; do
            ((relay_num++))
            
            if [ "$verbose" = true ]; then
                echo "Starting $relay ($relay_num/${#all_relays[@]})..."
            fi
            
            # Start relay in background
            (
                start_single_relay_all "$relay" "$relay_num" "${#all_relays[@]}" "$verbose"
            ) &
            pids+=($!)
            
            # Limit concurrent jobs to 20
            if [ ${#pids[@]} -ge 20 ]; then
                ((batch_count++))
                if [ "$verbose" = true ]; then
                    print_info "Waiting for batch $batch_count to complete..."
                fi
                
                for pid in "${pids[@]}"; do
                    local ret_code
                    wait "$pid"
                    ret_code=$?
                    if [ $ret_code -eq 0 ]; then
                        ((success_count++))
                    elif [ $ret_code -eq 2 ]; then
                        ((already_running++))
                    else
                        ((error_count++))
                    fi
                done
                pids=()
            fi
        done
        
        # Wait for remaining jobs
        if [ ${#pids[@]} -gt 0 ]; then
            ((batch_count++))
            if [ "$verbose" = true ]; then
                print_info "Waiting for final batch $batch_count to complete..."
            fi
            
            for pid in "${pids[@]}"; do
                local ret_code
                wait "$pid"
                ret_code=$?
                if [ $ret_code -eq 0 ]; then
                    ((success_count++))
                elif [ $ret_code -eq 2 ]; then
                    ((already_running++))
                else
                    ((error_count++))
                fi
            done
        fi
    else
        # Sequential processing
        print_info "Using sequential mode..."
        local relay_num=0
        for relay in "${all_relays[@]}"; do
            ((relay_num++))
            
            # Add periodic progress report every 20 relays or when verbose
            if [ "$verbose" = true ] || [ $((relay_num % 20)) -eq 0 ]; then
                print_info "Processing relay $relay_num/${#all_relays[@]}: $relay"
            fi
            
            local ret_code
            start_single_relay_all "$relay" "$relay_num" "${#all_relays[@]}" "$verbose"
            ret_code=$?
            
            if [ $ret_code -eq 0 ]; then
                ((success_count++))
            elif [ $ret_code -eq 2 ]; then
                ((already_running++))
            else
                ((error_count++))
                if [ "$verbose" = true ]; then
                    errors_detail+=("$relay: systemctl start failed")
                fi
            fi
            
            # Show immediate feedback for verbose mode every 10 relays
            if [ "$verbose" = true ] && [ $((relay_num % 10)) -eq 0 ]; then
                print_info "Progress: $relay_num/${#all_relays[@]} processed (started: $success_count, running: $already_running, failed: $error_count)"
            fi
        done
    fi
    
    # Re-enable strict error checking
    set -e
    
    echo ""
    print_info "Start All Summary:"
    echo "  Total relays: ${#all_relays[@]}"
    echo "  Successfully started: $success_count"
    echo "  Already running: $already_running"
    echo "  Failed: $error_count"
    
    if [ $error_count -gt 0 ] && [ "$verbose" = true ]; then
        echo ""
        print_warning "Failed relays and reasons:"
        for error in "${errors_detail[@]}"; do
            echo "  - $error"
        done
        echo ""
        print_info "To check individual relay logs:"
        echo "  sudo journalctl -u tor@<relay_name> -f"
    fi
    
    local total_active=$((success_count + already_running))
    if [ $error_count -eq 0 ]; then
        print_success "All $total_active relays are now running!"
        return 0
    else
        print_warning "$total_active relays running, $error_count failed"
        return 1
    fi
}

# Function to manage relays
manage_relays() {
    if [ $# -eq 0 ]; then
        print_error "No action specified for manage command"
        show_command_help "manage"
        exit 1
    fi
    
    local action="$1"
    shift
    
    case "$action" in
        --help)
            show_command_help "manage"
            exit 0
            ;;
        start)
            # Handle start with special options
            local start_mode="all"  # default
            local remaining_args=()
            
            # Parse start-specific options
            while [[ $# -gt 0 ]]; do
                case $1 in
                    --all)
                        start_mode="all"
                        shift
                        ;;
                    --migrated-only)
                        start_mode="migrated"
                        shift
                        ;;
                    --new-only)
                        start_mode="new"
                        shift
                        ;;
                    *)
                        remaining_args+=("$1")
                        shift
                        ;;
                esac
            done
            
            # Call appropriate start function
            if [ "$start_mode" = "migrated" ]; then
                start_migrated_relays "${remaining_args[@]}"
            elif [ "$start_mode" = "new" ]; then
                start_new_relays_only "${remaining_args[@]}"
            else
                # For --all, use our improved start_all_relays function
                start_all_relays "${remaining_args[@]}"
            fi
            ;;
        stop|restart|reload|status|enable|disable|list|count)
            "$SCRIPT_DIR/manage_tor_relays.sh" "$action" "$@"
            ;;
        *)
            print_error "Unknown manage action: $action"
            show_command_help "manage"
            exit 1
            ;;
    esac
}

# Function to inventory deployed relays
inventory_deployed_relays() {
    local output="deployed_relay_inventory.txt"
    local format="txt"
    local sort_field="nickname"
    local verbose=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --output)
                output="$2"
                shift 2
                ;;
            --format)
                format="$2"
                shift 2
                ;;
            --sort)
                sort_field="$2"
                shift 2
                ;;
            --verbose)
                verbose=true
                shift
                ;;
            --help)
                cat << EOF
${CYAN}INVENTORY Command${NC}

Inventory all currently deployed relays by scanning /etc/tor/instances/.

${YELLOW}USAGE:${NC}
    $0 inventory [options]

${YELLOW}OPTIONS:${NC}
    --output FILE       Output file (default: deployed_relay_inventory.txt)
    --format FORMAT     Output format: txt, csv, json (default: txt)
    --sort FIELD        Sort by: nickname, ip, fingerprint (default: nickname)
    --verbose           Show detailed output
    --help              Show this help

${YELLOW}EXAMPLES:${NC}
    $0 inventory --format csv --output deployed_relays.csv
    $0 inventory --sort ip --verbose
    $0 inventory --format json

EOF
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    print_header "Inventorying Deployed Relays"
    
    # Check if instances directory exists
    if [ ! -d "/etc/tor/instances" ]; then
        print_error "No deployed relay instances found in /etc/tor/instances/"
        exit 1
    fi
    
    # Get list of deployed relays
    local deployed_relays=()
    mapfile -t deployed_relays < <(ls -1 /etc/tor/instances/ 2>/dev/null || true)
    
    if [ ${#deployed_relays[@]} -eq 0 ]; then
        print_error "No relay instances found in /etc/tor/instances/"
        exit 1
    fi
    
    print_info "Found ${#deployed_relays[@]} deployed relay instances"
    
    local temp_file=$(mktemp)
    trap "rm -f $temp_file" EXIT
    
    # Process each deployed relay
    local relay_count=0
    local success_count=0
    local error_count=0
    
    # Temporarily disable strict error checking for this section
    set +e
    
    for relay_name in "${deployed_relays[@]}"; do
        ((relay_count++))
        
        if [ "$verbose" = true ]; then
            print_info "Processing relay: $relay_name ($relay_count/${#deployed_relays[@]})"
        fi
        
        local torrc_file="/etc/tor/instances/$relay_name/torrc"
        local fingerprint_file="/var/lib/tor-instances/$relay_name/fingerprint"
        
        # Check if torrc exists
        if [ ! -f "$torrc_file" ]; then
            if [ "$verbose" = true ]; then
                print_warning "Torrc not found for $relay_name, skipping"
            fi
            ((error_count++))
            continue
        fi
        
        # Extract information from torrc
        local ip_address="N/A"
        local control_port="N/A"
        local metrics_port="N/A"
        
        # Get IP address from Address line or ORPort line
        ip_address=$(sudo grep "^Address" "$torrc_file" 2>/dev/null | head -1 | awk '{print $2}')
        if [ -z "$ip_address" ]; then
            ip_address=$(sudo grep "^ORPort" "$torrc_file" 2>/dev/null | head -1 | awk '{print $2}' | cut -d':' -f1)
        fi
        if [ -z "$ip_address" ]; then
            ip_address="N/A"
        fi
        
        # Get ControlPort (extract port number after colon)
        control_port=$(sudo grep "^ControlPort" "$torrc_file" 2>/dev/null | head -1 | awk '{print $2}' | cut -d':' -f2)
        if [ -z "$control_port" ]; then
            control_port="N/A"
        fi
        
        # Get MetricsPort (extract port number after colon, ignore additional text like "prometheus")
        metrics_port=$(sudo grep "^MetricsPort" "$torrc_file" 2>/dev/null | head -1 | awk '{print $2}' | cut -d':' -f2)
        if [ -z "$metrics_port" ]; then
            metrics_port="N/A"
        fi
        
        # Get fingerprint (use sudo for file test since files are owned by _tor-relay user)
        local fingerprint="N/A"
        if sudo test -f "$fingerprint_file"; then
            local fp_content
            fp_content=$(sudo cat "$fingerprint_file" 2>/dev/null)
            if [ -n "$fp_content" ]; then
                fingerprint=$(echo "$fp_content" | awk '{print $2}' | tr -d '\n')
                if [ -z "$fingerprint" ]; then
                    fingerprint="N/A"
                fi
            fi
        fi
        
        # Write to temp file with error handling
        if echo "$relay_name|$fingerprint|$ip_address|$control_port|$metrics_port" >> "$temp_file"; then
            ((success_count++))
            if [ "$verbose" = true ]; then
                print_success "Processed $relay_name: IP=$ip_address, Control=$control_port, Metrics=$metrics_port"
            fi
        else
            ((error_count++))
            if [ "$verbose" = true ]; then
                print_error "Failed to write data for $relay_name"
            fi
        fi
    done
    
    # Re-enable strict error checking
    set -e
    
    print_info "Successfully processed $success_count of $relay_count relays (errors: $error_count)"
    
    # Check if temp file has any content
    if [ ! -s "$temp_file" ]; then
        print_error "No relay data generated. Check that relays exist and files are accessible."
        rm -f "$temp_file"
        exit 1
    fi
    
    # Sort the data
    case "$sort_field" in
        nickname) sort_key=1 ;;
        ip) sort_key=3 ;;
        fingerprint) sort_key=2 ;;
        *) sort_key=1 ;;
    esac
    
    sorted_file=$(mktemp)
    trap "rm -f $temp_file $sorted_file" EXIT
    sort -t'|' -k${sort_key} "$temp_file" > "$sorted_file"
    
    # Generate output in requested format
    case "$format" in
        txt)
            {
                echo "# Deployed Tor Relay Inventory"
                echo "# Generated: $(date)"
                echo "# Format: Nickname | Fingerprint | IP Address | ControlPort | MetricsPort"
                echo "# Source: /etc/tor/instances/ and /var/lib/tor-instances/"
                echo "#"
                printf "%-25s | %-40s | %-15s | %-11s | %-11s\n" "NICKNAME" "FINGERPRINT" "IP_ADDRESS" "CONTROLPORT" "METRICSPORT"
                echo "$(printf '%*s' 120 '' | tr ' ' '-')"
                while IFS='|' read -r nickname fingerprint ip control_port metrics_port; do
                    printf "%-25s | %-40s | %-15s | %-11s | %-11s\n" "$nickname" "$fingerprint" "$ip" "$control_port" "$metrics_port"
                done < "$sorted_file"
            } > "$output"
            ;;
        csv)
            {
                echo "nickname,fingerprint,ip_address,control_port,metrics_port"
                while IFS='|' read -r nickname fingerprint ip control_port metrics_port; do
                    echo "$nickname,$fingerprint,$ip,$control_port,$metrics_port"
                done < "$sorted_file"
            } > "$output"
            ;;
        json)
            {
                echo "{"
                echo "  \"generated\": \"$(date -Iseconds)\","
                echo "  \"source\": \"Deployed relay inventory from /etc/tor/instances/\","
                echo "  \"relays\": ["
                local first=true
                while IFS='|' read -r nickname fingerprint ip control_port metrics_port; do
                    if [ "$first" = true ]; then
                        first=false
                    else
                        echo ","
                    fi
                    echo -n "    {\"nickname\": \"$nickname\", \"fingerprint\": \"$fingerprint\", \"ip_address\": \"$ip\", \"control_port\": \"$control_port\", \"metrics_port\": \"$metrics_port\"}"
                done < "$sorted_file"
                echo ""
                echo "  ]"
                echo "}"
            } > "$output"
            ;;
        *)
            print_error "Unknown format: $format"
            rm -f "$temp_file" "$sorted_file"
            exit 1
            ;;
    esac
    
    rm -f "$temp_file" "$sorted_file"
    
    # Verify the output file was created and has content
    if [ ! -f "$output" ]; then
        print_error "Failed to create output file: $output"
        exit 1
    fi
    
    # Count lines excluding header for CSV format
    local count
    if [ "$format" = "csv" ]; then
        # For CSV, subtract 1 to exclude header row
        count=$(grep -c '^[^#]' "$output" 2>/dev/null || echo "0")
        if [ "$count" -gt 0 ]; then
            ((count--))
        fi
    else
        # For other formats, count non-comment lines
        count=$(grep -c '^[^#]' "$output" 2>/dev/null || echo "0")
    fi
    
    if [ "$count" -eq 0 ]; then
        print_warning "Generated file $output has no relay data"
    else
        print_success "Generated $output with $count deployed relays (format: $format, sorted by: $sort_field)"
    fi
}

# Function to generate master relay list
generate_master_list() {
    local output="$MASTER_LIST"
    local format="txt"
    local sort_field="nickname"
    local verbose=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --output)
                output="$2"
                shift 2
                ;;
            --format)
                format="$2"
                shift 2
                ;;
            --sort)
                sort_field="$2"
                shift 2
                ;;
            --verbose)
                verbose=true
                shift
                ;;
            --help)
                show_command_help "list"
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    print_header "Generating Master Relay List"
    
    if [ ! -f "$BATCH_FILE" ] || [ ! -f "$IP_FILE" ]; then
        print_error "Required files not found. Run migration first."
        print_info "Batch file: $BATCH_FILE (exists: $([ -f "$BATCH_FILE" ] && echo "yes" || echo "no"))"
        print_info "IP file: $IP_FILE (exists: $([ -f "$IP_FILE" ] && echo "yes" || echo "no"))"
        exit 1
    fi
    
    # Read IP addresses into array (skip comments and empty lines)
    mapfile -t ip_addresses < <(grep -v '^[[:space:]]*#' "$IP_FILE" | grep -v '^[[:space:]]*$')
    
    if [ ${#ip_addresses[@]} -eq 0 ]; then
        print_error "No IP addresses found in $IP_FILE"
        exit 1
    fi
    
    print_info "Found ${#ip_addresses[@]} IP addresses in $IP_FILE"
    
    local temp_file=$(mktemp)
    trap "rm -f $temp_file" EXIT
    
    # Create temporary data file
    local ip_index=0
    local relay_count=0
    
    # Temporarily disable strict error checking for this section
    set +e
    while read -r old_relay new_relay; do
        # Skip comments and empty lines
        if [[ -z "$old_relay" || "$old_relay" =~ ^[[:space:]]*# ]]; then
            continue
        fi
        
        ((relay_count++))
        
        # Get IP address
        local ip="N/A"
        if [ "$ip_index" -lt "${#ip_addresses[@]}" ]; then
            ip="${ip_addresses[$ip_index]}"
        else
            print_warning "Not enough IP addresses for relay $new_relay (index $ip_index)"
        fi
        
        # Get fingerprint (use old relay name since that's where the fingerprint files are stored)
        local fingerprint="N/A"
        if [ -f "/var/lib/tor-instances/$old_relay/fingerprint" ]; then
            fingerprint=$(sudo cat "/var/lib/tor-instances/$old_relay/fingerprint" 2>/dev/null | awk '{print $2}' | tr -d '\n' || echo "N/A")
        elif [ -f "$SOURCE_KEYS_DIR/$old_relay/fingerprint" ]; then
            fingerprint=$(cat "$SOURCE_KEYS_DIR/$old_relay/fingerprint" 2>/dev/null | awk '{print $2}' | tr -d '\n' || echo "N/A")
        fi
        
                # Get control port and metrics port from actual torrc files (read-only)
        local control_port=$((CONTROL_PORT_START + ip_index))
        local metrics_port="N/A"
        
        # Read actual metrics port from torrc file (no modifications)
        if [ -f "/etc/tor/instances/$new_relay/torrc" ]; then
            # Extract port number from MetricsPort line, handling different formats
            metrics_port=$(sudo grep "^MetricsPort" "/etc/tor/instances/$new_relay/torrc" 2>/dev/null | head -1 | sed 's/.*:\([0-9]*\).*/\1/' | grep -o '[0-9]*' | head -1 || echo "")
            # If the above didn't work (no colon format), try extracting just the number
            if [ -z "$metrics_port" ]; then
                metrics_port=$(sudo grep "^MetricsPort" "/etc/tor/instances/$new_relay/torrc" 2>/dev/null | head -1 | grep -o '[0-9]\+' | head -1 || echo "N/A")
            fi
            # If still empty, set to N/A
            if [ -z "$metrics_port" ]; then
                metrics_port="N/A"
            fi
            
            if [ "$verbose" = true ] && [ "$metrics_port" != "N/A" ]; then
                print_info "Read MetricsPort $metrics_port from $new_relay torrc"
            elif [ "$verbose" = true ]; then
                print_warning "No MetricsPort found in $new_relay torrc"
            fi
        fi
        
        # Write to temp file with error handling
        echo "$new_relay|$fingerprint|$ip|$control_port|$metrics_port" >> "$temp_file" || {
            print_error "Failed to write relay data for $new_relay"
            continue
        }
        ((ip_index++))
    done < "$BATCH_FILE"
    
    # Re-enable strict error checking
    set -e
    
    print_info "Processed $relay_count relays from $BATCH_FILE"
    
    # Check if temp file has any content
    if [ ! -s "$temp_file" ]; then
        print_error "No relay data generated. Check that relays exist and files are correct."
        rm -f "$temp_file"
        exit 1
    fi
    
    # Sort the data
    case "$sort_field" in
        nickname) sort_key=1 ;;
        ip) sort_key=3 ;;
        fingerprint) sort_key=2 ;;
        *) sort_key=1 ;;
    esac
    
    sorted_file=$(mktemp)
    trap "rm -f $temp_file $sorted_file" EXIT
    sort -t'|' -k${sort_key} "$temp_file" > "$sorted_file"
    
    # Generate output in requested format
    case "$format" in
        txt)
            {
                echo "# Tor Relay Master List"
                echo "# Generated: $(date)"
                echo "# Format: Nickname | Fingerprint | IP Address | ControlPort | MetricsPort"
                echo "#"
                printf "%-25s | %-40s | %-15s | %-11s | %-11s\n" "NICKNAME" "FINGERPRINT" "IP_ADDRESS" "CONTROLPORT" "METRICSPORT"
                echo "$(printf '%*s' 120 '' | tr ' ' '-')"
                while IFS='|' read -r nickname fingerprint ip control_port metrics_port; do
                    printf "%-25s | %-40s | %-15s | %-11s | %-11s\n" "$nickname" "$fingerprint" "$ip" "$control_port" "$metrics_port"
                done < "$sorted_file"
            } > "$output"
            ;;
        csv)
            {
                echo "nickname,fingerprint,ip_address,control_port,metrics_port"
                while IFS='|' read -r nickname fingerprint ip control_port metrics_port; do
                    echo "$nickname,$fingerprint,$ip,$control_port,$metrics_port"
                done < "$sorted_file"
            } > "$output"
            ;;
        json)
            {
                echo "{"
                echo "  \"generated\": \"$(date -Iseconds)\","
                echo "  \"relays\": ["
                local first=true
                while IFS='|' read -r nickname fingerprint ip control_port metrics_port; do
                    if [ "$first" = true ]; then
                        first=false
                    else
                        echo ","
                    fi
                    echo -n "    {\"nickname\": \"$nickname\", \"fingerprint\": \"$fingerprint\", \"ip_address\": \"$ip\", \"control_port\": $control_port, \"metrics_port\": $metrics_port}"
                done < "$sorted_file"
                echo ""
                echo "  ]"
                echo "}"
            } > "$output"
            ;;
        *)
            print_error "Unknown format: $format"
            rm -f "$temp_file" "$sorted_file"
            exit 1
            ;;
    esac
    
    rm -f "$temp_file" "$sorted_file"
    
    # Verify the output file was created and has content
    if [ ! -f "$output" ]; then
        print_error "Failed to create output file: $output"
        exit 1
    fi
    
    # Count lines excluding header for CSV format
    local count
    if [ "$format" = "csv" ]; then
        # For CSV, subtract 1 to exclude header row
        count=$(grep -c '^[^#]' "$output" 2>/dev/null || echo "0")
        if [ "$count" -gt 0 ]; then
            ((count--))
        fi
    else
        # For other formats, count non-comment lines
        count=$(grep -c '^[^#]' "$output" 2>/dev/null || echo "0")
    fi
    
    if [ "$count" -eq 0 ]; then
        print_warning "Generated file $output has no relay data"
    else
        print_success "Generated $output with $count relays (format: $format, sorted by: $sort_field)"
    fi
}

# Function to verify migration
verify_migration() {
    local check_services=false
    local check_configs=false
    local check_ports=false
    local check_all=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --check-services)
                check_services=true
                shift
                ;;
            --check-configs)
                check_configs=true
                shift
                ;;
            --check-ports)
                check_ports=true
                shift
                ;;
            --all)
                check_all=true
                shift
                ;;
            --help)
                show_command_help "verify"
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    if [ "$check_all" = true ]; then
        check_services=true
        check_configs=true
        check_ports=true
    fi
    
    # Default to basic checks if nothing specified
    if [ "$check_services" = false ] && [ "$check_configs" = false ] && [ "$check_ports" = false ]; then
        check_services=true
        check_configs=true
    fi
    
    print_header "Verifying Migration"
    
    local issues=0
    
    if [ "$check_services" = true ]; then
        print_info "Checking service status..."
        local active_count=$(sudo systemctl list-units 'tor@*' --state=active --no-legend | wc -l)
        local total_count=$(ls -1 /etc/tor/instances/ 2>/dev/null | wc -l)
        
        if [ "$active_count" -eq "$total_count" ]; then
            print_success "All $total_count relay services are active"
        else
            print_warning "$active_count of $total_count relay services are active"
            ((issues++))
        fi
    fi
    
    if [ "$check_configs" = true ]; then
        print_info "Checking torrc configurations..."
        local config_issues=0
        
        if [ -f "$BATCH_FILE" ]; then
            while read -r old_relay new_relay; do
                if [[ -z "$old_relay" || "$old_relay" =~ ^[[:space:]]*# ]]; then
                    continue
                fi
                
                local torrc_file="/etc/tor/instances/$new_relay/torrc"
                if [ ! -f "$torrc_file" ]; then
                    print_warning "Missing torrc: $torrc_file"
                    ((config_issues++))
                fi
            done < "$BATCH_FILE"
        fi
        
        if [ "$config_issues" -eq 0 ]; then
            print_success "All torrc files are present"
        else
            print_warning "$config_issues torrc configuration issues found"
            ((issues++))
        fi
    fi
    
    if [ "$check_ports" = true ]; then
        print_info "Checking port bindings..."
        local port_issues=0
        
        # Check for port conflicts
        local used_ports=$(ss -ltn | awk 'NR>1 {print $4}' | cut -d':' -f2 | sort -n | uniq -c | awk '$1>1 {print $2}')
        if [ -n "$used_ports" ]; then
            print_warning "Port conflicts detected: $used_ports"
            ((port_issues++))
        fi
        
        if [ "$port_issues" -eq 0 ]; then
            print_success "No port conflicts detected"
        else
            ((issues++))
        fi
    fi
    
    echo ""
    if [ "$issues" -eq 0 ]; then
        print_success "Migration verification completed successfully"
    else
        print_warning "Migration verification completed with $issues issue(s)"
        return 1
    fi
}

# Function to show migration status
show_status() {
    print_header "Tor Relay Migration Status"
    
    # Check if input files/directories exist
    print_info "Input Files:"
    
    # Check directory
    if [ -d "$INPUT_RELAYS_DIR" ]; then
        print_success "$INPUT_RELAYS_DIR/ directory exists"
    else
        print_warning "$INPUT_RELAYS_DIR/ directory missing"
    fi
    
    # Check files
    for file in "$BATCH_FILE" "$IP_FILE" "$OUTPUT_RELAYS"; do
        if [ -f "$file" ]; then
            print_success "$file exists"
        else
            print_warning "$file missing"
        fi
    done
    
    echo ""
    
    # Check migration progress
    if [ -f "$BATCH_FILE" ]; then
        local total_relays=$(grep -c '^[^#]' "$BATCH_FILE" 2>/dev/null || echo "0")
        local migrated_instances=0
        local migrated_torrc=0
        
        while read -r old_relay new_relay; do
            if [[ -z "$old_relay" || "$old_relay" =~ ^[[:space:]]*# ]]; then
                continue
            fi
            
            if [ -d "/var/lib/tor-instances/$new_relay" ]; then
                ((migrated_instances++))
            fi
            
            if [ -f "/etc/tor/instances/$new_relay/torrc" ]; then
                ((migrated_torrc++))
            fi
        done < "$BATCH_FILE"
        
        print_info "Migration Progress:"
        echo "  Total relays: $total_relays"
        echo "  Instances migrated: $migrated_instances"
        echo "  Torrc files created: $migrated_torrc"
    fi
    
    echo ""
    
    # Service status summary
    if command -v systemctl >/dev/null 2>&1; then
        local active=$(sudo systemctl list-units 'tor@*' --state=active --no-legend | wc -l)
        local failed=$(sudo systemctl list-units 'tor@*' --state=failed --no-legend | wc -l)
        
        print_info "Service Status:"
        echo "  Active: $active"
        echo "  Failed: $failed"
    fi
}

# Function to cleanup temporary files
cleanup_files() {
    print_header "Cleaning Up Temporary Files"
    
    local files_to_clean=(
        "*.tmp"
        "*.bak"
        "/tmp/tor_migration_*"
    )
    
    for pattern in "${files_to_clean[@]}"; do
        if ls $pattern 1> /dev/null 2>&1; then
            rm -f $pattern
            print_success "Cleaned up: $pattern"
        fi
    done
    
    print_success "Cleanup completed"
}

# Function to fix ownership of existing instances
fix_ownership() {
    local verbose=false
    local dry_run=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --verbose)
                verbose=true
                shift
                ;;
            --dry-run)
                dry_run=true
                shift
                ;;
            --help)
                cat << EOF
${CYAN}FIX-OWNERSHIP Command${NC}

Fix ownership of existing Tor relay instances.

${YELLOW}USAGE:${NC}
    $0 fix-ownership [options]

${YELLOW}OPTIONS:${NC}
    --verbose      Show detailed output
    --dry-run      Show what would be done without executing
    --help         Show this help

${YELLOW}DESCRIPTION:${NC}
This command fixes the ownership of files in /var/lib/tor-instances/ to use
the correct _tor-{relayname} user instead of the generic debian-tor user.

${YELLOW}EXAMPLES:${NC}
    $0 fix-ownership --verbose
    $0 fix-ownership --dry-run

EOF
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    print_header "Fixing Tor Instance Ownership"
    
    if [ ! -d "/var/lib/tor-instances" ]; then
        print_error "Tor instances directory not found: /var/lib/tor-instances"
        exit 1
    fi
    
    local total=0
    local fixed=0
    local errors=0
    
    for instance_dir in /var/lib/tor-instances/*/; do
        if [ ! -d "$instance_dir" ]; then
            continue
        fi
        
        local relay_name=$(basename "$instance_dir")
        ((total++))
        
        if [ "$verbose" = true ]; then
            echo "Processing: $relay_name"
        fi
        
        # Check if the relay user exists
        if ! id "_tor-$relay_name" >/dev/null 2>&1; then
            if [ "$verbose" = true ]; then
                print_warning "User _tor-$relay_name does not exist, skipping"
            fi
            ((errors++))
            continue
        fi
        
        if [ "$dry_run" = false ]; then
            if sudo chown -R "_tor-$relay_name:_tor-$relay_name" "$instance_dir"; then
                if [ "$verbose" = true ]; then
                    print_success "Fixed ownership for: $relay_name"
                fi
                ((fixed++))
            else
                print_error "Failed to fix ownership for: $relay_name"
                ((errors++))
            fi
        else
            if [ "$verbose" = true ]; then
                echo "  [DRY-RUN] Would fix ownership for: $relay_name"
            fi
            ((fixed++))
        fi
    done
    
    echo ""
    print_info "Ownership Fix Summary:"
    echo "  Total instances: $total"
    echo "  Fixed: $fixed"
    echo "  Errors: $errors"
    
    if [ "$errors" -eq 0 ]; then
        print_success "Ownership fix completed successfully"
    else
        print_warning "Ownership fix completed with $errors error(s)"
        return 1
    fi
}

# Function to create new relays with new keys
create_new_relays() {
    local nicknames_file=""
    local ip_file="$IP_FILE"
    local verbose=false
    local dry_run=false
    local control_port_start="$CONTROL_PORT_START"
    local metrics_port_start="$METRICS_PORT_START"
    local manual_ports=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --nicknames)
                nicknames_file="$2"
                shift 2
                ;;
            --ip-file)
                ip_file="$2"
                shift 2
                ;;
            --control-port-start)
                control_port_start="$2"
                manual_ports=true
                shift 2
                ;;
            --metrics-port-start)
                metrics_port_start="$2"
                manual_ports=true
                shift 2
                ;;
            --verbose)
                verbose=true
                shift
                ;;
            --dry-run)
                dry_run=true
                shift
                ;;
            --help)
                cat << EOF
${CYAN}CREATE-NEW Command${NC}

Create new Tor relays with new keys, automatically finding next available ports.

${YELLOW}USAGE:${NC}
    $0 create-new [options]

${YELLOW}OPTIONS:${NC}
    --nicknames FILE    File containing new relay nicknames (one per line)
    --ip-file FILE      File containing IP addresses for new relays (default: ${IP_FILE})
    --verbose           Show detailed output
    --dry-run           Show what would be done without executing
    --help              Show this help

${YELLOW}DESCRIPTION:${NC}
This command creates entirely new Tor relays with fresh keys. It automatically:
- Scans existing relays in /etc/tor/instances/ to find highest port numbers
- Increments ControlPort and MetricsPort by 1 for each new relay
- Creates new relay instances with tor-instance-create
- Generates torrc configurations with appropriate settings

${YELLOW}INPUT FILES:${NC}
- Nicknames file: One relay nickname per line (underscores not allowed)
- IP file: One IPv4 address per line matching the number of nicknames

${YELLOW}EXAMPLES:${NC}
    $0 create-new --nicknames new_relays.txt --ip-file new_ips.txt --verbose
    $0 create-new --nicknames new_relays.txt --dry-run

EOF
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    print_header "Creating New Tor Relays"
    
    # Validate input files
    if [ -z "$nicknames_file" ]; then
        print_error "Nicknames file required. Use --nicknames FILE"
        exit 1
    fi
    
    if [ ! -f "$nicknames_file" ]; then
        print_error "Nicknames file not found: $nicknames_file"
        exit 1
    fi
    
    if [ ! -f "$ip_file" ]; then
        print_error "IP file not found: $ip_file"
        exit 1
    fi
    
    # Read nicknames and IPs into arrays (skip comments and empty lines)
    mapfile -t new_nicknames < <(grep -v '^[[:space:]]*#' "$nicknames_file" | grep -v '^[[:space:]]*$')
    mapfile -t new_ips < <(grep -v '^[[:space:]]*#' "$ip_file" | grep -v '^[[:space:]]*$')
    
    if [ ${#new_nicknames[@]} -eq 0 ]; then
        print_error "No nicknames found in $nicknames_file"
        exit 1
    fi
    
    if [ ${#new_ips[@]} -eq 0 ]; then
        print_error "No IP addresses found in $ip_file"
        exit 1
    fi
    
    if [ ${#new_nicknames[@]} -ne ${#new_ips[@]} ]; then
        print_error "Number of nicknames (${#new_nicknames[@]}) doesn't match number of IPs (${#new_ips[@]})"
        exit 1
    fi
    
    print_info "Found ${#new_nicknames[@]} nicknames and ${#new_ips[@]} IP addresses"
    
    # Validate nicknames for underscores and Tor naming rules
    print_info "Validating relay nicknames..."
    local invalid_names=()
    for nickname in "${new_nicknames[@]}"; do
        if [[ "$nickname" == *"_"* ]]; then
            invalid_names+=("$nickname (contains underscore)")
        elif [[ ! "$nickname" =~ ^[a-zA-Z0-9]+$ ]]; then
            invalid_names+=("$nickname (invalid characters)")
        elif [ ${#nickname} -gt 19 ]; then
            print_warning "Nickname '$nickname' (${#nickname} chars) will be truncated to 19 characters"
        fi
    done
    
    if [ ${#invalid_names[@]} -gt 0 ]; then
        print_error "Invalid relay nicknames found:"
        for name in "${invalid_names[@]}"; do
            echo "  - $name"
        done
        print_info "Relay nicknames must contain only letters and numbers, no underscores"
        exit 1
    fi
    
    print_success "All relay nicknames are valid"
    
    # Validate IP addresses for conflicts with existing relays
    print_info "Checking for IP address conflicts with existing relays..."
    local existing_ips=()
    local ip_conflicts=()
    
    # Temporarily disable strict error checking for IP scanning
    set +e
    
    if [ -d "/etc/tor/instances" ]; then
        local torrc_files
        torrc_files=$(find /etc/tor/instances -name "torrc" -type f 2>/dev/null)
        
        if [ -n "$torrc_files" ]; then
            while IFS= read -r torrc_file; do
                if [ ! -f "$torrc_file" ]; then
                    continue
                fi
                
                local relay_name=$(basename "$(dirname "$torrc_file")")
                
                # Extract IP addresses from Address, ORPort, and OutboundBindAddress lines
                local existing_ip=""
                
                # Try Address line first
                existing_ip=$(sudo grep "^Address" "$torrc_file" 2>/dev/null | head -1 | awk '{print $2}')
                
                # If no Address line, try ORPort
                if [ -z "$existing_ip" ]; then
                    existing_ip=$(sudo grep "^ORPort" "$torrc_file" 2>/dev/null | head -1 | awk '{print $2}' | cut -d':' -f1)
                fi
                
                # If we found an IP, add it to our list
                if [ -n "$existing_ip" ] && [[ "$existing_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
                    existing_ips+=("$existing_ip")
                    if [ "$verbose" = true ]; then
                        print_info "Found existing IP: $existing_ip (relay: $relay_name)"
                    fi
                fi
            done <<< "$torrc_files"
        fi
    fi
    
    # Re-enable strict error checking
    set -e
    
    # Check new IPs against existing ones
    for new_ip in "${new_ips[@]}"; do
        for existing_ip in "${existing_ips[@]}"; do
            if [ "$new_ip" = "$existing_ip" ]; then
                ip_conflicts+=("$new_ip")
                break
            fi
        done
    done
    
    if [ ${#ip_conflicts[@]} -gt 0 ]; then
        print_error "IP address conflicts detected! The following IPs are already in use:"
        for conflict_ip in "${ip_conflicts[@]}"; do
            echo "  - $conflict_ip"
        done
        echo ""
        print_info "Please update your IP file ($ip_file) with different IP addresses."
        print_info "Existing IPs in use: ${existing_ips[*]}"
        exit 1
    fi
    
    print_success "No IP address conflicts detected"
    
    # Find highest existing ports by scanning all torrc files - simplified approach
    print_info "Scanning existing relays to find highest port numbers..."
    local max_control_port=0
    local max_metrics_port=0
    local existing_count=0
    
    # Temporarily disable strict error checking for this entire section
    set +e
    
    if [ -d "/etc/tor/instances" ]; then
        if [ "$verbose" = true ]; then
            print_info "/etc/tor/instances directory found, scanning torrc files..."
        fi
        
        # Use a simpler approach - find all torrc files and process them
        local torrc_files
        torrc_files=$(find /etc/tor/instances -name "torrc" -type f 2>/dev/null)
        
        if [ -n "$torrc_files" ]; then
            while IFS= read -r torrc_file; do
                if [ ! -f "$torrc_file" ]; then
                    continue
                fi
                
                existing_count=$((existing_count + 1))
                local relay_name=$(basename "$(dirname "$torrc_file")")
                
                if [ "$verbose" = true ]; then
                    print_info "Scanning $relay_name/torrc (count: $existing_count)"
                fi
                
                # Extract ControlPort number
                local control_line
                control_line=$(sudo grep "^ControlPort" "$torrc_file" 2>/dev/null | head -1)
                if [ -n "$control_line" ]; then
                    local extracted_port
                    extracted_port=$(echo "$control_line" | sed 's/.*:\([0-9][0-9]*\).*/\1/')
                    if [[ "$extracted_port" =~ ^[0-9]+$ ]] && [ "$extracted_port" -gt "$max_control_port" ]; then
                        max_control_port="$extracted_port"
                        if [ "$verbose" = true ]; then
                            print_info "New max ControlPort: $max_control_port from $relay_name"
                        fi
                    fi
                fi
                
                # Extract MetricsPort number
                local metrics_line
                metrics_line=$(sudo grep "^MetricsPort" "$torrc_file" 2>/dev/null | head -1)
                if [ -n "$metrics_line" ]; then
                    local extracted_port
                    extracted_port=$(echo "$metrics_line" | sed 's/.*:\([0-9][0-9]*\).*/\1/')
                    if [[ "$extracted_port" =~ ^[0-9]+$ ]] && [ "$extracted_port" -gt "$max_metrics_port" ]; then
                        max_metrics_port="$extracted_port"
                        if [ "$verbose" = true ]; then
                            print_info "New max MetricsPort: $max_metrics_port from $relay_name"
                        fi
                    fi
                fi
            done <<< "$torrc_files"
        else
            if [ "$verbose" = true ]; then
                print_info "No torrc files found in /etc/tor/instances/"
            fi
        fi
    else
        if [ "$verbose" = true ]; then
            print_info "/etc/tor/instances/ directory does not exist"
        fi
    fi
    
    # Re-enable strict error checking
    set -e
    
    # Set starting ports based on whether manual ports were provided
    local next_control_port
    local next_metrics_port
    
    if [ "$manual_ports" = true ]; then
        # Use manually specified starting ports
        next_control_port="$control_port_start"
        next_metrics_port="$metrics_port_start"
        print_info "Using manually specified starting ports:"
        print_info "  ControlPort starting at: $next_control_port"
        print_info "  MetricsPort starting at: $next_metrics_port"
    else
        # Set starting ports (next available)
        next_control_port=$((max_control_port + 1))
        next_metrics_port=$((max_metrics_port + 1))
        
        # If no existing relays, use defaults
        if [ "$max_control_port" -eq 0 ]; then
            next_control_port="$CONTROL_PORT_START"
        fi
        if [ "$max_metrics_port" -eq 0 ]; then
            next_metrics_port="$METRICS_PORT_START"
        fi
        
        print_info "Found $existing_count existing relay configurations"
        print_info "Highest ControlPort: $max_control_port, starting new relays at: $next_control_port"
        print_info "Highest MetricsPort: $max_metrics_port, starting new relays at: $next_metrics_port"
    fi
    
    # Select a template torrc file from existing relays
    print_info "Finding template torrc file from existing relays..."
    local template_torrc=""
    
    # Look for an existing torrc file to use as template
    if [ -f "instances/bg/torrc" ]; then
        template_torrc="instances/bg/torrc"
    elif [ -f "instances/boosiebada/torrc" ]; then
        template_torrc="instances/boosiebada/torrc"
    elif [ -f "instances/crimemob/torrc" ]; then
        template_torrc="instances/crimemob/torrc"
    else
        # Try to find any torrc file in instances directory
        for instance_dir in instances/*/; do
            if [ -f "$instance_dir/torrc" ]; then
                template_torrc="$instance_dir/torrc"
                break
            fi
        done
    fi
    
    if [ -z "$template_torrc" ] || [ ! -f "$template_torrc" ]; then
        print_error "No template torrc file found in instances directory"
        exit 1
    fi
    
    if [ "$verbose" = true ]; then
        print_success "Using template torrc: $template_torrc"
    fi
    
    # Validate that template contains ControlPort and MetricsPort, or use manual starting points
    if [ "$manual_ports" = false ]; then
        local template_has_controlport=false
        local template_has_metricsport=false
        
        if grep -q "^[[:space:]]*ControlPort[[:space:]]" "$template_torrc"; then
            template_has_controlport=true
        fi
        
        if grep -q "^[[:space:]]*MetricsPort[[:space:]]" "$template_torrc"; then
            template_has_metricsport=true
        fi
        
        if [ "$template_has_controlport" = false ] || [ "$template_has_metricsport" = false ]; then
            print_error "Template torrc file missing required port configurations:"
            if [ "$template_has_controlport" = false ]; then
                echo "  - Missing ControlPort line"
            fi
            if [ "$template_has_metricsport" = false ]; then
                echo "  - Missing MetricsPort line"
            fi
            echo ""
            print_info "The template file ($template_torrc) doesn't contain ControlPort and/or MetricsPort lines."
            print_info "To fix this, provide starting port numbers manually:"
            echo ""
            echo "  $0 create-new --nicknames $nicknames_file --ip-file $ip_file --control-port-start <NUM> --metrics-port-start <NUM>"
            echo ""
            print_info "Where <NUM> are the starting port numbers for ControlPort and MetricsPort."
            print_info "The script will increment these numbers for each new relay."
            echo ""
            print_info "Example:"
            echo "  $0 create-new --nicknames $nicknames_file --ip-file $ip_file --control-port-start 47200 --metrics-port-start 31100"
            exit 1
        fi
    fi
    
    # Create new relays
    local success_count=0
    local error_count=0
    local relay_index=0
    
    for nickname in "${new_nicknames[@]}"; do
        local ip="${new_ips[$relay_index]}"
        local control_port=$((next_control_port + relay_index))
        local metrics_port=$((next_metrics_port + relay_index))
        
        relay_index=$((relay_index + 1))
        
        if [ "$verbose" = true ]; then
            print_info "Creating relay $relay_index/${#new_nicknames[@]}: $nickname"
            echo "  IP: $ip"
            echo "  ControlPort: 127.0.0.1:$control_port"
            echo "  MetricsPort: 127.0.0.1:$metrics_port"
        fi
        
        if [ "$dry_run" = false ]; then
            # Create new relay instance
            if sudo tor-instance-create "$nickname" >/dev/null 2>&1; then
                if [ "$verbose" = true ]; then
                    print_success "Created instance: $nickname"
                fi
            else
                print_error "Failed to create instance: $nickname"
                error_count=$((error_count + 1))
                continue
            fi
            
            # Create torrc configuration using template
            local torrc_file="/etc/tor/instances/$nickname/torrc"
            local temp_torrc=$(mktemp)
            
            # Track which required lines we've processed
            local controlport_added=false
            local metricsport_added=false
            local orport_added=false
            local address_added=false
            local outboundbind_added=false
            local nickname_added=false
            
            # Copy template and modify only the required fields
            while IFS= read -r line; do
                # Update ControlPort 
                if [[ "$line" =~ ^[[:space:]]*ControlPort[[:space:]] ]]; then
                    echo "ControlPort 127.0.0.1:$control_port"
                    controlport_added=true
                # Update ORPort 
                elif [[ "$line" =~ ^[[:space:]]*ORPort[[:space:]] ]]; then
                    echo "ORPort $ip:443"
                    orport_added=true
                # Update Address 
                elif [[ "$line" =~ ^[[:space:]]*Address[[:space:]] ]]; then
                    echo "Address $ip"
                    address_added=true
                # Update OutboundBindAddress 
                elif [[ "$line" =~ ^[[:space:]]*OutboundBindAddress[[:space:]] ]]; then
                    echo "OutboundBindAddress $ip"
                    outboundbind_added=true
                # Update Nickname (auto-truncate to 19 characters if needed)
                elif [[ "$line" =~ ^[[:space:]]*Nickname[[:space:]] ]]; then
                    local truncated_name="$nickname"
                    if [ ${#nickname} -gt 19 ]; then
                        truncated_name="${nickname:0:19}"
                        if [ "$verbose" = true ]; then
                            print_warning "Nickname '$nickname' (${#nickname} chars) truncated to '$truncated_name' (19 chars limit)"
                        fi
                    fi
                    echo "Nickname $truncated_name"
                    nickname_added=true
                # Update MetricsPort 
                elif [[ "$line" =~ ^[[:space:]]*MetricsPort[[:space:]] ]]; then
                    echo "MetricsPort 127.0.0.1:$metrics_port"
                    metricsport_added=true
                # Keep all other lines unchanged (including comments and %include)
                else
                    echo "$line"
                fi
            done < "$template_torrc" > "$temp_torrc"
            
            # Ensure all required lines are present - add them if missing
            if [ "$controlport_added" = false ]; then
                echo "ControlPort 127.0.0.1:$control_port" >> "$temp_torrc"
                if [ "$verbose" = true ]; then
                    print_info "Added missing ControlPort line to $nickname"
                fi
            fi
            
            if [ "$metricsport_added" = false ]; then
                echo "MetricsPort 127.0.0.1:$metrics_port" >> "$temp_torrc"
                if [ "$verbose" = true ]; then
                    print_info "Added missing MetricsPort line to $nickname"
                fi
            fi
            
            if [ "$orport_added" = false ]; then
                echo "ORPort $ip:443" >> "$temp_torrc"
                if [ "$verbose" = true ]; then
                    print_info "Added missing ORPort line to $nickname"
                fi
            fi
            
            if [ "$address_added" = false ]; then
                echo "Address $ip" >> "$temp_torrc"
                if [ "$verbose" = true ]; then
                    print_info "Added missing Address line to $nickname"
                fi
            fi
            
            if [ "$outboundbind_added" = false ]; then
                echo "OutboundBindAddress $ip" >> "$temp_torrc"
                if [ "$verbose" = true ]; then
                    print_info "Added missing OutboundBindAddress line to $nickname"
                fi
            fi
            
            if [ "$nickname_added" = false ]; then
                local truncated_name="$nickname"
                if [ ${#nickname} -gt 19 ]; then
                    truncated_name="${nickname:0:19}"
                    if [ "$verbose" = true ]; then
                        print_warning "Nickname '$nickname' (${#nickname} chars) truncated to '$truncated_name' (19 chars limit)"
                    fi
                fi
                echo "Nickname $truncated_name" >> "$temp_torrc"
                if [ "$verbose" = true ]; then
                    print_info "Added missing Nickname line to $nickname"
                fi
            fi
            
            # Copy torrc to destination
            if sudo cp "$temp_torrc" "$torrc_file"; then
                sudo chown "_tor-$nickname:_tor-$nickname" "$torrc_file"
                if [ "$verbose" = true ]; then
                    print_success "Created torrc: $torrc_file"
                fi
                success_count=$((success_count + 1))
            else
                print_error "Failed to create torrc: $torrc_file"
                error_count=$((error_count + 1))
            fi
            
            rm -f "$temp_torrc"
        else
            if [ "$verbose" = true ]; then
                echo "  [DRY-RUN] Would create instance: $nickname"
                echo "  [DRY-RUN] Would create torrc using template: $template_torrc"
                echo "  [DRY-RUN] Would set: Control=$control_port, Metrics=$metrics_port, IP=$ip"
            fi
            success_count=$((success_count + 1))
        fi
    done
    
    echo ""
    print_info "New Relay Creation Summary:"
    echo "  Total requested: ${#new_nicknames[@]}"
    echo "  Successfully created: $success_count"
    echo "  Errors: $error_count"
    echo "  Port ranges used:"
    echo "    ControlPort: $next_control_port-$((next_control_port + ${#new_nicknames[@]} - 1))"
    echo "    MetricsPort: $next_metrics_port-$((next_metrics_port + ${#new_nicknames[@]} - 1))"
    
    if [ "$error_count" -eq 0 ]; then
        print_success "All new relays created successfully!"
        if [ "$dry_run" = false ]; then
            echo ""
            print_info "Next steps:"
            echo "  1. Start the new relays: $0 manage start --verbose"
            echo "  2. Check their status: $0 manage status"
            echo "  3. Generate updated master list: $0 list"
        fi
    else
        print_warning "New relay creation completed with $error_count error(s)"
        return 1
    fi
}

# Main script logic
main() {
    # Parse global options
    local verbose=false
    local dry_run=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --help|-h)
                show_help
                exit 0
                ;;
            --version|-v)
                echo "Tor Migration Tool v$VERSION"
                exit 0
                ;;
            --verbose)
                verbose=true
                shift
                ;;
            --dry-run)
                dry_run=true
                shift
                ;;
            --batch-file)
                BATCH_FILE="$2"
                shift 2
                ;;
            --ip-file)
                IP_FILE="$2"
                shift 2
                ;;
            --control-port-start)
                CONTROL_PORT_START="$2"
                shift 2
                ;;
            --metrics-port-start)
                METRICS_PORT_START="$2"
                shift 2
                ;;
            create-inputs|create-new|migrate|migrate-instances|migrate-torrc|manage|list|inventory|verify|status|cleanup|fix-ownership)
                local command="$1"
                shift
                break
                ;;
            *)
                print_error "Unknown option: $1"
                print_info "Use '$0 --help' for usage information"
                exit 1
                ;;
        esac
    done
    
    # Check if command was provided
    if [ -z "${command:-}" ]; then
        print_error "No command specified"
        show_help
        exit 1
    fi
    
    # Set global flags for child scripts
    if [ "$verbose" = true ]; then
        export TOR_MIGRATION_VERBOSE=1
    fi
    if [ "$dry_run" = true ]; then
        export TOR_MIGRATION_DRY_RUN=1
    fi
    
    # Check prerequisites for commands that need them
    case "$command" in
        migrate|migrate-instances|migrate-torrc|manage|verify)
            if ! check_prerequisites; then
                exit 1
            fi
            ;;
    esac
    
    # Execute the command
    case "$command" in
        create-inputs)
            create_inputs "$@"
            ;;
        create-new)
            # Set global flags for create-new
            local args=()
            if [ "$verbose" = true ]; then
                args+=("--verbose")
            fi
            if [ "$dry_run" = true ]; then
                args+=("--dry-run")
            fi
            create_new_relays "${args[@]}" "$@"
            ;;
        migrate)
            migrate_relays "$@"
            ;;
        migrate-instances)
            if [ ! -f "$BATCH_FILE" ]; then
                print_error "Batch file not found: $BATCH_FILE"
                exit 1
            fi
            local args=("--batch-file" "$BATCH_FILE")
            if [ "$verbose" = true ]; then
                args+=("--verbose")
            fi
            if [ "$dry_run" = true ]; then
                args+=("--dry-run")
            fi
            migrate_instances "${args[@]}" "$@"
            ;;
        migrate-torrc)
            if [ ! -f "$BATCH_FILE" ] || [ ! -f "$IP_FILE" ]; then
                print_error "Required files not found: $BATCH_FILE or $IP_FILE"
                exit 1
            fi
            # Pass global port settings along with any command-line overrides
            local args=("--batch-file" "$BATCH_FILE" "--ip-file" "$IP_FILE" "--control-port-start" "$CONTROL_PORT_START" "--metrics-port-start" "$METRICS_PORT_START")
            if [ "$verbose" = true ]; then
                args+=("--verbose")
            fi
            if [ "$dry_run" = true ]; then
                args+=("--dry-run")
            fi
            migrate_torrc "${args[@]}" "$@"
            ;;
        manage)
            manage_relays "$@"
            ;;
        list)
            generate_master_list "$@"
            ;;
        inventory)
            inventory_deployed_relays "$@"
            ;;
        verify)
            verify_migration "$@"
            ;;
        status)
            show_status
            ;;
        cleanup)
            cleanup_files
            ;;
        fix-ownership)
            fix_ownership "$@"
            ;;
        *)
            print_error "Unknown command: $command"
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@" 
