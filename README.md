# TorUtils

Tor relay infrastructure management toolkit.

## Tools

### `relay-setup/` - Create and Manage Relays

Create and manage Tor relay instances on Ubuntu 24.04.

```bash
cd relay-setup
cp relay-config.csv.example relay-config.csv
nano relay-config.csv
sudo ./create-relays.sh -p "16:HASH" -t /path/to/torrc.all
./manage-relays.sh status

# Configure Tor 0.4.9.x Happy Family (local or via SSH to remote servers)
./setup-family.sh generate --name myfamily
./setup-family.sh deploy --key myfamily.secret_family_key --family-id "..."
./setup-family.sh deploy-remote --key myfamily.secret_family_key \
    --family-id "..." --servers servers.txt
```

See [relay-setup/README.md](relay-setup/README.md)

### `migration/` - Migrate Relays

Migrate Tor relays between servers, preserving keys and identity.

- `tor_migration.sh` - Migration orchestration
- `migrate_instance_keys.sh` - Key migration

### `network/` - Network Configuration

Tool for adding /24 IP ranges. Auto-detects netplan or NetworkManager.

- `configure_ip_range.sh` - Add /24 ranges (works on Ubuntu 24.04 and Debian 13)

### `memory/` - Memory Analysis

Tools and reports for investigating Tor relay memory usage.

- `tools/monitor.sh` - Time-series monitoring (for cron)
- `tools/diagnostics.sh` - System diagnostics for troubleshooting
- `tools/memory-tool.sh` - Point-in-time analysis and experiments
- `tools/timeseries-charts.py` - Charts from monitor.sh data
- `tools/generate-charts.py` - Charts from experiment data
- `reports/` - Date-organized analysis reports

```bash
cd memory/tools

# Time-series monitoring (run via cron)
./monitor.sh --output /var/log/tor_memory.csv
./monitor.sh --output /var/log/tor_memory.csv --with-diagnostics

# Point-in-time analysis
./memory-tool.sh status                    # Show current memory
./memory-tool.sh collect --auto-dir "test" # Collect to dated directory
```

See [memory/README.md](memory/README.md)

## Requirements

- Ubuntu 24.04 or Debian 13 (or other Debian-based Linux)
- Tor installed: `sudo apt install tor`
- Root/sudo access
- For network tools: netplan (Ubuntu) or NetworkManager (Debian)

## License

See [LICENSE](LICENSE)
