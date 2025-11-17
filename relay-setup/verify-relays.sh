#!/bin/bash
set -e -u
RED='\033[0;31m' GREEN='\033[0;32m' YELLOW='\033[1;33m' BLUE='\033[0;34m' CYAN='\033[0;36m' NC='\033[0m'

CONFIG_FILE="relay-config.csv"
TORRC_ALL="/etc/tor/torrc.all"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Read relay names from CSV
get_relay_names() {
    awk -F',' '/^[^#]/ && NF {print $1}' "$SCRIPT_DIR/$CONFIG_FILE" | xargs -n1 echo
}

RELAY_NAMES=($(get_relay_names))
RELAY_COUNT=${#RELAY_NAMES[@]}

echo -e "${CYAN}Tor Relay System Verification${NC}\n"

# 1. Tor installed
command -v tor &>/dev/null && echo -e "${GREEN}✓${NC} Tor: $(tor --version | head -n1)" || { echo -e "${RED}✗${NC} Tor not installed"; exit 1; }

# 2. Config file
[ -f "$SCRIPT_DIR/$CONFIG_FILE" ] && echo -e "${GREEN}✓${NC} Config: $RELAY_COUNT relays" || { echo -e "${RED}✗${NC} No config"; exit 1; }

# 3. Shared config
[ -f "$TORRC_ALL" ] && echo -e "${GREEN}✓${NC} Shared: $TORRC_ALL" || echo -e "${RED}✗${NC} No shared config"

# 4. Instance configs (from actual torrc files)
echo -e "\n${BLUE}Checking torrc files:${NC}"
CONFIG_COUNT=0
CONFIG_ERRORS=0
for name in "${RELAY_NAMES[@]}"; do
    cf="/etc/tor/instances/$name/torrc"
    if [ -f "$cf" ]; then
        control=$(awk '/^ControlPort/{print $2}' "$cf" | cut -d: -f2)
        metrics=$(awk '/^MetricsPort/{print $2}' "$cf" | cut -d: -f2)
        wan=$(awk '/^Address/{print $2}' "$cf")
        or=$(awk '/^ORPort/{print $2; exit}' "$cf" | cut -d: -f2)
        nick=$(awk '/^Nickname/{print $2}' "$cf")
        
        if [ "$nick" = "$name" ] && [ -n "$control" ] && [ -n "$metrics" ] && [ -n "$wan" ] && [ -n "$or" ]; then
            echo -e "  ${GREEN}✓${NC} $name: $wan:$or (Ctl:$control Met:$metrics)"
            CONFIG_COUNT=$((CONFIG_COUNT + 1))
        else
            echo -e "  ${RED}✗${NC} $name: Invalid config"
            CONFIG_ERRORS=$((CONFIG_ERRORS + 1))
        fi
    else
        echo -e "  ${RED}✗${NC} $name: Missing"
        CONFIG_ERRORS=$((CONFIG_ERRORS + 1))
    fi
done

# 5. Users
USER_COUNT=$(echo "${RELAY_NAMES[@]}" | xargs -n1 | xargs -I{} id "_tor-{}" 2>/dev/null | wc -l)
echo -e "\n${BLUE}Users:${NC} $USER_COUNT/$RELAY_COUNT"

# 6. Data dirs
DATA_COUNT=$(echo "${RELAY_NAMES[@]}" | xargs -n1 | xargs -I{} test -d "/var/lib/tor-instances/{}" && echo 1 || true | wc -l)
echo -e "${BLUE}Data dirs:${NC} $DATA_COUNT/$RELAY_COUNT"

# 7. Services
RUNNING_COUNT=$(echo "${RELAY_NAMES[@]}" | xargs -n1 | xargs -I{} systemctl is-active --quiet "tor@{}.service" && echo 1 || true | wc -l)
echo -e "${BLUE}Running:${NC} $RUNNING_COUNT/$RELAY_COUNT"

# Summary
echo ""
if [ $CONFIG_COUNT -eq $RELAY_COUNT ] && [ $CONFIG_ERRORS -eq 0 ] && [ $USER_COUNT -eq $RELAY_COUNT ] && [ $DATA_COUNT -eq $RELAY_COUNT ] && [ $RUNNING_COUNT -eq $RELAY_COUNT ]; then
    echo -e "${GREEN}✓ All $RELAY_COUNT relays configured and running${NC}\n"
    echo "Manage: ./manage-relays.sh status"
else
    echo -e "${YELLOW}⚠ Issues found${NC}"
    [ $CONFIG_ERRORS -gt 0 ] && echo "  - Config errors: $CONFIG_ERRORS"
    [ $USER_COUNT -ne $RELAY_COUNT ] && echo "  - Missing users: $((RELAY_COUNT - USER_COUNT))"
    [ $DATA_COUNT -ne $RELAY_COUNT ] && echo "  - Missing data: $((RELAY_COUNT - DATA_COUNT))"
    [ $RUNNING_COUNT -ne $RELAY_COUNT ] && echo "  - Not running: $((RELAY_COUNT - RUNNING_COUNT))"
fi
