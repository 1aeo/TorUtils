#!/bin/bash
# Add /24 IP ranges using netplan (Ubuntu) or NetworkManager (Debian)
# Usage: ./configure_ip_range.sh <interface> <ip_range>

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ $# -ne 2 ]; then
    echo "Usage: $0 <interface> <ip_range>"
    echo "Example: $0 ens18 10.0.0.0/24"
    exit 1
fi

INTERFACE="$1"
IP_RANGE="$2"

# Validate IP range format
if [[ ! "$IP_RANGE" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.0/24$ ]]; then
    echo -e "${RED}Error: IP range must be in format x.x.x.0/24${NC}"
    echo "Example: 10.0.0.0/24"
    exit 1
fi

[ "$EUID" -ne 0 ] && { echo -e "${RED}Error: Run with sudo${NC}"; exit 1; }

NETWORK_BASE=$(echo "$IP_RANGE" | sed 's|/24||' | sed 's|\.0$||')

echo "Interface: $INTERFACE"
echo "Range: $IP_RANGE (${NETWORK_BASE}.0-255)"

if [ -d "/etc/netplan" ] && ls /etc/netplan/*.yaml &>/dev/null; then
    MODE="netplan"
elif systemctl is-active --quiet NetworkManager; then
    MODE="nm"
else
    echo -e "${RED}Error: Need netplan or NetworkManager${NC}"
    exit 1
fi
echo "Mode: $MODE"

if [ "$MODE" = "netplan" ]; then
    NETPLAN_FILE="/etc/netplan/50-cloud-init.yaml"
    [ ! -f "$NETPLAN_FILE" ] && NETPLAN_FILE=$(ls /etc/netplan/*.yaml 2>/dev/null | head -n1)
    [ -z "$NETPLAN_FILE" ] && { echo -e "${RED}No netplan config${NC}"; exit 1; }
    
    # Backup
    BACKUP="${NETPLAN_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
    cp "$NETPLAN_FILE" "$BACKUP"
    
    command -v python3 &>/dev/null || { echo -e "${RED}Need python3${NC}"; exit 1; }
    python3 -c "import yaml" &>/dev/null || apt-get install -y python3-yaml >/dev/null 2>&1
    
    # Generate IPs
    TEMP_FILE="/tmp/netplan_updated.yaml"
    python3 << EOF
import yaml

with open("$NETPLAN_FILE", 'r') as f:
    config = yaml.safe_load(f)

# Ensure structure
if 'network' not in config:
    config['network'] = {}
if 'ethernets' not in config['network']:
    config['network']['ethernets'] = {}
if "$INTERFACE" not in config['network']['ethernets']:
    config['network']['ethernets']["$INTERFACE"] = {}
if 'addresses' not in config['network']['ethernets']["$INTERFACE"]:
    config['network']['ethernets']["$INTERFACE"]['addresses'] = []

existing = config['network']['ethernets']["$INTERFACE"]['addresses']

# Add all 256 IPs
for i in range(256):
    ip = f"${NETWORK_BASE}.{i}/32"
    if ip not in existing:
        existing.append(ip)

with open("$TEMP_FILE", 'w') as f:
    yaml.dump(config, f, default_flow_style=False, sort_keys=False)

print(f"✓ Generated {len(existing)} total IPs")
EOF
    
    cp "$TEMP_FILE" "$NETPLAN_FILE" && rm -f "$TEMP_FILE"
    
    echo "Testing (30s)..."
    netplan try --timeout 30 || { cp "$BACKUP" "$NETPLAN_FILE"; exit 1; }
    echo -e "${GREEN}✓ Applied${NC}"
fi

if [ "$MODE" = "nm" ]; then
    # Find connection
    CONN=$(nmcli -t -f NAME,DEVICE connection show --active | grep ":${INTERFACE}$" | cut -d: -f1)
    [ -z "$CONN" ] && { echo -e "${RED}No connection for $INTERFACE${NC}"; exit 1; }
    
    # Backup
    mkdir -p /root/network-backups
    BACKUP="/root/network-backups/nm-${INTERFACE}-$(date +%Y%m%d_%H%M%S).txt"
    nmcli connection show "$CONN" > "$BACKUP" 2>&1
    
    EXISTING=$(nmcli -g ipv4.addresses connection show "$CONN" | tr ',' '\n' | tr '|' '\n')
    
    # Add new IPs
    ALL="$EXISTING"
    for i in {0..255}; do
        echo "$EXISTING" | grep -q "^${NETWORK_BASE}.${i}" && continue
        [ -z "$ALL" ] && ALL="${NETWORK_BASE}.${i}/32" || ALL="${ALL},${NETWORK_BASE}.${i}/32"
    done
    
    GW=$(nmcli -g ipv4.gateway connection show "$CONN")
    DNS=$(nmcli -g ipv4.dns connection show "$CONN")
    
    # Apply
    nmcli connection modify "$CONN" ipv4.method manual ipv4.addresses "$ALL"
    [ -n "$GW" ] && [ "$GW" != "--" ] && nmcli connection modify "$CONN" ipv4.gateway "$GW"
    [ -n "$DNS" ] && [ "$DNS" != "--" ] && nmcli connection modify "$CONN" ipv4.dns "$DNS"
    
    echo "Reloading..."
    nmcli connection down "$CONN" 2>/dev/null || true
    sleep 1
    nmcli connection up "$CONN"
    echo -e "${GREEN}✓ Applied${NC}"
fi

# Verify
sleep 2
CNT=$(ip addr show "$INTERFACE" | grep "inet " | wc -l)
echo -e "${GREEN}✓ $CNT IPs configured${NC}"

