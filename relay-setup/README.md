# Tor Relay Setup

Create and manage Tor relays on Ubuntu 24.04.

## Quick Start

```bash
# Copy example config
cp relay-config.csv.example relay-config.csv
nano relay-config.csv  # Edit with your values

# Generate hashed password
tor --hash-password YourPasswordHere

# Create relays (with parameters)
sudo ./create-relays.sh --password "16:YOUR_HASH_HERE" --torrc /path/to/torrc.all

# Or short form
sudo ./create-relays.sh -p "16:YOUR_HASH_HERE" -t /path/to/torrc.all

# Or interactive mode (prompts for password)
sudo ./create-relays.sh

# Verify
./verify-relays.sh
```

## Configuration

Format: `nickname,lan_ip,wan_ip,or_port,control_port,metrics_port`

**First relay:** All fields required  
**Following relays:** Only `nickname,wan_ip` required (ports auto-increment)

```csv
relay01,192.168.1.100,203.0.113.100,443,13001,35001
relay02,,203.0.113.101,,,
relay03,,203.0.113.102,,,
```

## Scripts

- `create-relays.sh` - Create relays (validates CSV, creates everything)
- `verify-relays.sh` - Verify system (reads /etc/tor/instances)
- `manage-relays.sh` - Daily management

## Management

```bash
./manage-relays.sh status              # Show status
./manage-relays.sh summary             # Show IPs/ports
./manage-relays.sh export              # Export to CSV
./manage-relays.sh logs <nickname>     # View logs
./manage-relays.sh restart <nickname>  # Restart relay
./manage-relays.sh list                # List all
```

Export to CSV: `./manage-relays.sh export > relays.csv`

## What It Creates

Per relay:
- User: `_tor-<nickname>`
- Config: `/etc/tor/instances/<nickname>/torrc`
- Data: `/var/lib/tor-instances/<nickname>/`
- Service: `tor@<nickname>.service`

Shared: `/etc/tor/torrc.all` (from `$HOME/torrc.all`)

## Troubleshooting

```bash
# Check logs
sudo journalctl -u tor@<nickname>.service -n 50

# Verify config  
sudo -u _tor-<nickname> tor --verify-config -f /etc/tor/instances/<nickname>/torrc

# System check
./verify-relays.sh
```
