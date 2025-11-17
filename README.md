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
```

See [relay-setup/README.md](relay-setup/README.md)

### `migration/` - Migrate Relays

Migrate Tor relays between servers, preserving keys and identity.

- `tor_migration.sh` - Migration orchestration
- `migrate_instance_keys.sh` - Key migration

### `network/` - Network Configuration

Tool for adding /24 IP ranges. Auto-detects netplan or NetworkManager.

- `configure_ip_range.sh` - Add /24 ranges (works on Ubuntu 24.04 and Debian 13)

## Requirements

- Ubuntu 24.04 or Debian 13 (or other Debian-based Linux)
- Tor installed: `sudo apt install tor`
- Root/sudo access
- For network tools: netplan (Ubuntu) or NetworkManager (Debian)

## License

See [LICENSE](LICENSE)
