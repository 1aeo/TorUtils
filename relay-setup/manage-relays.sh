#!/bin/bash
set -e -u
RED='\033[0;31m' GREEN='\033[0;32m' NC='\033[0m'

CONFIG_FILE="relay-config.csv"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

get_relay_names() {
    awk -F',' '/^[^#]/ && NF {print $1}' "$SCRIPT_DIR/$CONFIG_FILE" | xargs -n1 echo
}

show_usage() {
    cat << EOF
Tor Relay Manager

Usage: $0 <command> [relay_name]

Commands:
  status [name]   - Show status
  start [name]    - Start relay(s)
  stop [name]     - Stop relay(s)
  restart [name]  - Restart relay(s)
  logs <name>     - Follow logs
  list            - List all relays
  config <name>   - Show torrc
  summary         - Show IPs and ports
  export          - Export to CSV format

Examples:
  $0 status
  $0 logs commonsense
  $0 restart kanye
  $0 export > relays.csv
EOF
}

cmd_status() {
    local names=($(get_relay_names))
    if [ -n "${1:-}" ]; then
        systemctl status "tor@$1.service"
    else
        for n in "${names[@]}"; do
            systemctl is-active --quiet "tor@$n.service" 2>/dev/null && \
                echo -e "${GREEN}✓ RUNNING${NC}  tor@$n.service" || \
                echo -e "${RED}✗ STOPPED${NC}  tor@$n.service"
        done
    fi
}

cmd_start() {
    local names=($([ -n "${1:-}" ] && echo "$1" || get_relay_names))
    for n in "${names[@]}"; do
        echo "Starting tor@$n.service"
        sudo systemctl start "tor@$n.service"
    done
}

cmd_stop() {
    local names=($([ -n "${1:-}" ] && echo "$1" || get_relay_names))
    for n in "${names[@]}"; do
        echo "Stopping tor@$n.service"
        sudo systemctl stop "tor@$n.service"
    done
}

cmd_restart() {
    local names=($([ -n "${1:-}" ] && echo "$1" || get_relay_names))
    for n in "${names[@]}"; do
        echo "Restarting tor@$n.service"
        sudo systemctl restart "tor@$n.service"
    done
}

cmd_logs() {
    [ -z "${1:-}" ] && { echo "Error: relay name required"; exit 1; }
    journalctl -u "tor@$1.service" -f
}

cmd_list() {
    local names=($(get_relay_names))
    echo "Relays (${#names[@]}):"
    printf '  %s\n' "${names[@]}"
}

cmd_config() {
    [ -z "${1:-}" ] && { echo "Error: relay name required"; exit 1; }
    local cf="/etc/tor/instances/$1/torrc"
    [ -f "$cf" ] && cat "$cf" || { echo "Error: $cf not found"; exit 1; }
}

cmd_summary() {
    local names=($(get_relay_names))
    echo "Tor Relay Summary (${#names[@]})"
    echo "=================="
    for n in "${names[@]}"; do
        local cf="/etc/tor/instances/$n/torrc"
        [ ! -f "$cf" ] && { echo -e "${RED}MISSING${NC} $n"; continue; }
        
        local ctl=$(awk '/^ControlPort/{print $2}' "$cf" | cut -d: -f2)
        local met=$(awk '/^MetricsPort/{print $2}' "$cf" | cut -d: -f2)
        local wan=$(awk '/^Address/{print $2}' "$cf")
        local or=$(awk '/^ORPort/{print $2; exit}' "$cf" | cut -d: -f2)
        local lan=$(awk '/NoAdvertise/{print $2}' "$cf")
        
        systemctl is-active --quiet "tor@$n.service" 2>/dev/null && \
            local status="${GREEN}RUN${NC}" || local status="${RED}OFF${NC}"
        
        echo -e "$status $n"
        [ -n "$lan" ] && echo "  LAN: $lan | WAN: $wan:$or" || echo "  WAN: $wan:$or"
        echo "  Ctl: 127.0.0.1:$ctl | Met: 127.0.0.1:$met"
    done
}

cmd_export() {
    local names=($(get_relay_names))
    echo "fingerprint,nickname,address,control_port,metrics_port"
    
    for n in "${names[@]}"; do
        systemctl is-active --quiet "tor@$n.service" 2>/dev/null || continue
        
        local cf="/etc/tor/instances/$n/torrc"
        local df="/var/lib/tor-instances/$n/fingerprint"
        [ ! -f "$cf" ] && continue
        
        local fp=$(sudo cat "$df" 2>/dev/null | awk '{print $2}' || echo "")
        local nick=$(awk '/^Nickname/{print $2}' "$cf")
        local addr=$(awk '/^Address/{print $2}' "$cf")
        local ctl=$(awk '/^ControlPort/{print $2}' "$cf" | cut -d: -f2)
        local met=$(awk '/^MetricsPort/{print $2}' "$cf" | cut -d: -f2)
        
        echo "$fp,$nick,$addr,$ctl,$met"
    done
}

[ $# -lt 1 ] && { show_usage; exit 1; }

case "$1" in
    status|start|stop|restart|logs|list|config|summary|export) cmd_$1 "${2:-}";;
    help|--help|-h) show_usage;;
    *) echo "Error: Unknown command '$1'"; show_usage; exit 1;;
esac
