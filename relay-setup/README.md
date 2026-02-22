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

Cryptographic family keys replace the O(n²) `MyFamily` lists.
Requires **Tor >= 0.4.9.1-alpha** on all relay servers.

### 1. Create a new family key

```bash
./setup-family.sh generate --name myfamily
```

Save the output — you'll need the `FamilyId` and the `.secret_family_key` file.

### 2. Deploy key to remote servers

**If you have the key file locally** (from step 1 or a backup):

```bash
./setup-family.sh deploy-remote \
    --key myfamily.secret_family_key \
    --family-id "wweKJrJx..." \
    --remote myserver --ask-sudo-pass
```

**If the key is already on another server** (pull it first):

```bash
./setup-family.sh import-key-remote --remote existing-server --ask-sudo-pass
./setup-family.sh deploy-remote \
    --key myfamily.secret_family_key \
    --remote new-server --ask-sudo-pass
```

Use `--servers servers.txt` instead of `--remote` for multiple servers at once.

### 3. Verify

```bash
./setup-family.sh status-remote --remote myserver --ask-sudo-pass
```

### Notes

- `--ask-sudo-pass` prompts once and relays the password to the remote server.
  Not needed if the SSH user is root or has passwordless sudo.
- `--remote` targets one server. `--servers servers.txt` targets many (one per line).
- The script respects `~/.ssh/config` — use Host aliases in place of IPs.
- Run `./setup-family.sh --help` for all commands and options.

## Troubleshooting

```bash
# Check logs
sudo journalctl -u tor@<nickname>.service -n 50

# Verify config  
sudo -u _tor-<nickname> tor --verify-config -f /etc/tor/instances/<nickname>/torrc

# System check
./verify-relays.sh
```
