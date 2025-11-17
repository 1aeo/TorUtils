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

Network and IP address tools.

- `apply_netplan_changes.sh` - Configure IPs via netplan

## Requirements

- Ubuntu 24.04 or Debian-based Linux
- Tor installed: `sudo apt install tor`
- Root/sudo access

## License

See [LICENSE](LICENSE)
