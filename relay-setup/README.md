# Tor Relay Setup

Create and manage Tor relays on Ubuntu 24.04 or Debian 13.

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

- `create-relays.sh` - Create relays (auto-detects Ubuntu/Debian)
- `verify-relays.sh` - Verify system
- `manage-relays.sh` - Daily management
- `setup-family.sh` - Configure Tor 0.4.9.x Happy Family (local or remote via SSH)

**Platform compatibility**: Scripts auto-detect and work on both Ubuntu 24.04 and Debian 13.

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

## Happy Family Setup (Tor 0.4.9.x)

Configure cryptographic family keys so your relays are recognized as a family
without the O(n²) `MyFamily` overhead. Requires Tor >= 0.4.9.1-alpha.

### New family

```bash
# 1. Generate a family key (once, on any machine with tor installed)
./setup-family.sh generate --name myfamily

# 2a. Deploy locally (run on each Tor server — prompts for sudo if needed)
./setup-family.sh deploy \
    --key myfamily.secret_family_key \
    --family-id "wweKJrJxUDs1EdtFFHCDtvVgTKftOC/crUl1mYJv830"

# 2b. Or deploy to remote servers from a control machine
cp servers.txt.example servers.txt
nano servers.txt  # Add your server IPs or SSH config Host aliases
./setup-family.sh deploy-remote \
    --key myfamily.secret_family_key \
    --family-id "wweKJrJxUDs1EdtFFHCDtvVgTKftOC/crUl1mYJv830" \
    --servers servers.txt

# 3. Check status
./setup-family.sh status                              # local
./setup-family.sh status-remote --servers servers.txt  # remote
```

### Add a new server to an existing family

```bash
# 1. Import the key from a server that already has it
./setup-family.sh import-key-remote --remote existing-server

# 2. Deploy to the new server(s)
./setup-family.sh deploy-remote \
    --key family.secret_family_key \
    --family-id "wweKJrJx..." \
    --remote new-server

# 3. Verify
./setup-family.sh status-remote --servers servers.txt
```

### Legacy MyFamily (transitional period)

Until all Tor clients support Happy Families, add `--legacy-family` to also
set `MyFamily` with fingerprints, or collect fingerprints across all servers:

```bash
./setup-family.sh collect-fingerprints --servers servers.txt
./setup-family.sh deploy-myfamily-remote \
    --myfamily '$FP1,$FP2,$FP3,...' --servers servers.txt
```

### SSH config support

The script respects `~/.ssh/config` by default. Your servers file can use
Host aliases:

```
# servers.txt
tor-relay-01
tor-relay-02
tor-relay-03
```

With `--remote` (single server), sudo password prompts work through the SSH
session. With `--servers` (batch), passwordless sudo or root is required.

See `./setup-family.sh --help` for all commands and options.

## Troubleshooting

```bash
# Check logs
sudo journalctl -u tor@<nickname>.service -n 50

# Verify config  
sudo -u _tor-<nickname> tor --verify-config -f /etc/tor/instances/<nickname>/torrc

# System check
./verify-relays.sh
```
