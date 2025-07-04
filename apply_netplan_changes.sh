#!/bin/bash

# Script to add IP addresses to a network interface via netplan
# Usage: ./apply_netplan_changes.sh <interface> <ip_range>
# Example: ./apply_netplan_changes.sh enp0 1.1.0.0/24

set -e  # Exit on any error

# Check if correct number of arguments provided
if [ $# -ne 2 ]; then
    echo "Usage: $0 <interface> <ip_range>"
    echo "Example: $0 enp0 1.1.0.0/24"
    echo ""
    echo "Parameters:"
    echo "  interface  - Network interface name (e.g., enp0, eth0)"
    echo "  ip_range   - IP range in /24 format (e.g., 1.1.0.0/24)"
    exit 1
fi

INTERFACE="$1"
IP_RANGE="$2"

# Validate IP range format
if [[ ! "$IP_RANGE" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.0/24$ ]]; then
    echo "Error: IP range must be in format x.x.x.0/24"
    echo "Example: 1.1.0.0/24"
    exit 1
fi

# Extract network portion (remove /24)
NETWORK_BASE=$(echo "$IP_RANGE" | sed 's|/24||' | sed 's|\.0$||')

NETPLAN_FILE="/etc/netplan/50-cloud-init.yaml"
BACKUP_FILE="/etc/netplan/50-cloud-init.yaml.backup.$(date +%Y%m%d_%H%M%S)"
TEMP_FILE="/tmp/netplan_updated.yaml"

echo "Adding IP range $IP_RANGE to interface $INTERFACE"
echo "Network base: $NETWORK_BASE"
echo ""

# Check if netplan file exists
if [ ! -f "$NETPLAN_FILE" ]; then
    echo "Error: Netplan configuration file not found: $NETPLAN_FILE"
    exit 1
fi

# Create backup with timestamp
echo "Creating backup: $BACKUP_FILE"
sudo cp "$NETPLAN_FILE" "$BACKUP_FILE"

if [ $? -eq 0 ]; then
    echo "✓ Backup created successfully"
else
    echo "✗ Failed to create backup"
    exit 1
fi

# Read existing configuration and modify it
echo "Reading existing netplan configuration..."

# Create a Python script to modify the YAML
cat > /tmp/modify_netplan.py << EOF
#!/usr/bin/env python3
import yaml
import sys

interface = "$INTERFACE"
network_base = "$NETWORK_BASE"

# Read existing configuration
with open("$NETPLAN_FILE", 'r') as f:
    config = yaml.safe_load(f)

# Ensure the structure exists
if 'network' not in config:
    config['network'] = {}
if 'ethernets' not in config['network']:
    config['network']['ethernets'] = {}
if interface not in config['network']['ethernets']:
    config['network']['ethernets'][interface] = {}
if 'addresses' not in config['network']['ethernets'][interface]:
    config['network']['ethernets'][interface]['addresses'] = []

# Get existing addresses
existing_addresses = config['network']['ethernets'][interface]['addresses']

# Generate new IP addresses (0-255)
new_addresses = []
for i in range(256):
    new_ip = f"{network_base}.{i}/32"
    if new_ip not in existing_addresses:
        new_addresses.append(new_ip)

# Add new addresses to existing ones
config['network']['ethernets'][interface]['addresses'].extend(new_addresses)

# Write updated configuration
with open("$TEMP_FILE", 'w') as f:
    yaml.dump(config, f, default_flow_style=False, sort_keys=False)

print(f"Added {len(new_addresses)} new IP addresses to interface {interface}")
EOF

# Run the Python script to modify the configuration
python3 /tmp/modify_netplan.py

if [ $? -ne 0 ]; then
    echo "✗ Failed to generate updated configuration"
    exit 1
fi

# Copy the updated configuration
echo "Applying updated configuration..."
sudo cp "$TEMP_FILE" "$NETPLAN_FILE"

if [ $? -eq 0 ]; then
    echo "✓ Configuration file updated successfully"
else
    echo "✗ Failed to update configuration file"
    echo "Restoring backup..."
    sudo cp "$BACKUP_FILE" "$NETPLAN_FILE"
    exit 1
fi

# Test the configuration
echo "Testing netplan configuration..."
sudo netplan try --timeout 30

if [ $? -eq 0 ]; then
    echo "✓ Configuration test passed"
else
    echo "✗ Configuration test failed"
    echo "Restoring backup..."
    sudo cp "$BACKUP_FILE" "$NETPLAN_FILE"
    rm -f "$TEMP_FILE"
    rm -f /tmp/modify_netplan.py
    exit 1
fi

# Clean up temporary files
rm -f "$TEMP_FILE"
rm -f /tmp/modify_netplan.py

echo ""
echo "Configuration applied successfully!"
echo "Interface: $INTERFACE"
echo "IP Range Added: $IP_RANGE (256 addresses)"
echo "Backup saved as: $BACKUP_FILE"
echo ""
echo "To verify, run: ip addr show $INTERFACE"
echo "To see all addresses: ip addr show $INTERFACE | grep inet" 
