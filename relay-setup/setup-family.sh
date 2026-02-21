#!/bin/bash
# setup-family.sh - Configure Tor 0.4.9.x Happy Family across relay servers
#
# Generates a family key, distributes it to all relay instances (local or remote
# via SSH), configures torrc with the FamilyId directive, and manages the full
# lifecycle including legacy MyFamily support, status, and removal.
#
# Modes:
#   Local:  Run directly on the Tor server to configure its relay instances.
#   Remote: Run from a control server, SSH into remote Tor servers.
#     --remote <host>   Interactive single-server (sudo prompts work via ssh -tt)
#     --servers <file>  Batch multi-server (requires passwordless sudo or root)
#
# Requires: Tor >= 0.4.9.1-alpha (for --keygen-family support)
# Platforms: Ubuntu 24.04, Debian 13 (or other Debian-based Linux)
#
# See: https://community.torproject.org/relay/setup/post-install/family-ids/

set -euo pipefail

VERSION="1.0.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export VERSION SCRIPT_DIR  # used in help text and may be used by extensions

# ── Colors ───────────────────────────────────────────────────────────────────

if [[ -t 1 ]] && [[ "${TERM:-dumb}" != "dumb" ]]; then
    RED='\033[0;31m' GREEN='\033[0;32m' YELLOW='\033[1;33m'
    BLUE='\033[0;34m' CYAN='\033[0;36m' NC='\033[0m'
else
    RED='' GREEN='' YELLOW='' BLUE='' CYAN='' NC=''
fi

# ── Defaults ─────────────────────────────────────────────────────────────────

COMMAND=""
KEY_NAME="family"
KEY_FILE=""
FAMILY_ID=""
INSTANCE_NAME=""
REMOTE_HOST=""
SERVERS_FILE=""
OUTPUT_FILE=""
MYFAMILY_LINE=""
SSH_USER=""
SSH_KEY=""
SSH_PORT=""
SSH_USER_SET=false
SSH_PORT_SET=false
INSTANCES_DIR="/etc/tor/instances"
DATA_DIR="/var/lib/tor-instances"
SUDO=""
ASK_SUDO_PASS=false
REMOTE_SUDO_PASS=""
VERBOSE=false
DRY_RUN=false
NO_RELOAD=false
LEGACY_FAMILY=false

# ── Logging ──────────────────────────────────────────────────────────────────

log_info()    { echo -e "${BLUE}ℹ${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn()    { echo -e "${YELLOW}⚠${NC} $1"; }
log_error()   { echo -e "${RED}✗${NC} $1" >&2; }
log_verbose() { if $VERBOSE; then echo -e "  ${CYAN}…${NC} $1"; fi; }
log_header()  { echo -e "\n${CYAN}=== $1 ===${NC}"; }

die() { log_error "$1"; exit 1; }

# ── Privilege Handling ───────────────────────────────────────────────────────

# Ensure root/sudo access for commands that write to system directories.
# Sets SUDO="" (already root) or SUDO="sudo" (escalated).
# Prompts for password interactively if possible; fails clearly otherwise.
ensure_privilege() {
    if [[ $EUID -eq 0 ]]; then
        SUDO=""
        return 0
    fi
    if sudo -n true 2>/dev/null; then
        SUDO="sudo"
        log_verbose "Using passwordless sudo"
        return 0
    fi
    if [[ -t 0 ]]; then
        log_info "Root access required. You may be prompted for your password."
        if sudo -v 2>/dev/null; then
            SUDO="sudo"
            return 0
        fi
    fi
    die "Root access required. Run with sudo or configure passwordless sudo for: $(whoami)"
}

# Lighter privilege check for read-only commands (status, collect-fingerprints).
# Degrades gracefully: warns but continues if root is unavailable.
ensure_read_privilege() {
    if [[ $EUID -eq 0 ]]; then
        SUDO=""
        return 0
    fi
    if sudo -n true 2>/dev/null; then
        SUDO="sudo"
        return 0
    fi
    if [[ -t 0 ]]; then
        log_info "Some files require elevated access. You may be prompted for your password."
        if sudo -v 2>/dev/null; then
            SUDO="sudo"
            return 0
        fi
    fi
    SUDO=""
    log_warn "Running without root — some data (key files, fingerprints) may be unreadable"
    return 0
}

# Block embedded at the top of every remote heredoc script.
# Handles: root, passwordless sudo, password sudo (via --ask-sudo-pass), or clear error.
# __REMOTE_SUDO_PASS__ is substituted before sending to the remote server.
#
# When a password is provided, sets SUDO to a wrapper function (_sudo_cmd)
# that pipes the password to every sudo invocation via sudo -S. This avoids
# relying on sudo credential caching, which fails in non-TTY SSH sessions
# because the timestamp is tied to the TTY device.
# shellcheck disable=SC2016  # Intentionally single-quoted: expands on remote server, not locally
REMOTE_SUDO_BLOCK='
SUDO=""
_SUDO_PASS="__REMOTE_SUDO_PASS__"
_sudo_cmd() {
    printf "%s\n" "$_SUDO_PASS" | sudo -S "$@" 2>/dev/null
}
if [ "$(id -u)" -ne 0 ]; then
    if sudo -n true 2>/dev/null; then
        SUDO="sudo"
    elif [ -n "$_SUDO_PASS" ]; then
        if printf "%s\n" "$_SUDO_PASS" | sudo -S true 2>/dev/null; then
            SUDO="_sudo_cmd"
        else
            echo "ERROR:WRONG_SUDO_PASS"
            echo "Sudo password rejected on $(hostname)."
            exit 1
        fi
    else
        echo "ERROR:NEED_SUDO"
        echo "Root or passwordless sudo required on $(hostname)."
        echo "Use --ask-sudo-pass to provide the sudo password, or configure passwordless sudo:"
        echo "  echo '"'"'$(whoami) ALL=(ALL) NOPASSWD: ALL'"'"' | sudo tee /etc/sudoers.d/tor-admin"
        exit 1
    fi
fi
'

# Prompt for sudo password if --ask-sudo-pass was given and we haven't prompted yet.
# Called once at the start of any remote command that may need sudo.
prompt_sudo_pass() {
    if $ASK_SUDO_PASS && [[ -z "$REMOTE_SUDO_PASS" ]]; then
        if [[ -t 0 ]]; then
            read -r -s -p "Sudo password for remote server(s): " REMOTE_SUDO_PASS
            echo "" >&2
            if [[ -z "$REMOTE_SUDO_PASS" ]]; then
                die "No password entered"
            fi
        else
            die "--ask-sudo-pass requires an interactive terminal"
        fi
    fi
}

# Substitute the sudo password placeholder in a remote script string.
# If no password was provided, replaces with empty string (triggers NEED_SUDO path).
inject_sudo_pass() {
    local script="$1"
    echo "${script//__REMOTE_SUDO_PASS__/$REMOTE_SUDO_PASS}"
}

# ── Usage ────────────────────────────────────────────────────────────────────

show_usage() {
    cat << EOF
Tor Happy Family Setup v${VERSION}

Configure Tor 0.4.9.x cryptographic family keys across relay instances.

USAGE:
    setup-family.sh <command> [options]

COMMANDS:
    generate             Generate a new family key (or recover FamilyId from existing key)
    import-key           Extract existing key + FamilyId from a local relay instance
    import-key-remote    Extract existing key + FamilyId from a remote server via SSH
    deploy               Deploy family key and configure local relay instances
    deploy-remote        Deploy to remote servers via SSH (batch or single)
    status               Show family configuration status of local instances
    status-remote        Show family status on remote servers via SSH
    collect-fingerprints Collect fingerprints from local and/or remote servers for MyFamily
    deploy-myfamily      Push a MyFamily line to local torrc
    deploy-myfamily-remote  Push a MyFamily line to remote servers via SSH
    remove               Remove family configuration from local instances
    remove-remote        Remove family configuration from remote servers via SSH

OPTIONS:
    -n, --name NAME           Family key name (default: family)
    -k, --key FILE            Path to existing .secret_family_key file
    -i, --family-id ID        FamilyId string (auto-resolved if omitted)
        --instance NAME       Relay instance name (for import-key)
    -r, --remote HOST         Single remote server (interactive: sudo prompts work)
    -s, --servers FILE        File listing remote servers (batch: needs passwordless sudo)
    -u, --ssh-user USER       SSH user override (global default for all servers)
        --ssh-key FILE        SSH private key file
        --ssh-port PORT       SSH port override (global default for all servers)
        --instances-dir DIR   Tor instances config dir (default: /etc/tor/instances)
        --data-dir DIR        Tor instances data dir (default: /var/lib/tor-instances)
        --legacy-family       Also configure MyFamily with fingerprints (transitional)
        --ask-sudo-pass      Prompt for sudo password and relay it to remote servers
        --myfamily LINE       MyFamily value for deploy-myfamily (e.g., "\$FP1,\$FP2")
    -o, --output FILE         Output file (for collect-fingerprints)
        --no-reload           Don't reload Tor after configuration changes
        --dry-run             Show what would be done without executing
        --verbose             Enable verbose output
    -h, --help                Show this help message

SSH CONFIGURATION:
    The script respects ~/.ssh/config by default. Entries in the servers file
    can be SSH Host aliases, IP addresses, or hostnames. Resolution priority:

      1. Per-line user@host:port in servers file     (highest)
      2. --ssh-user / --ssh-port CLI flags            (global fallback)
      3. ~/.ssh/config Host entries                   (automatic)
      4. System defaults (current user, port 22)      (lowest)

    Example ~/.ssh/config:
        Host tor-*
            User admin
            IdentityFile ~/.ssh/tor_ed25519
            Port 2222

    Then servers.txt can simply list:
        tor-relay-01
        tor-relay-02
        tor-relay-03

REMOTE MODES — --remote vs --servers:
    --remote HOST   Single-server connection. SSH password/key authentication
                    prompts work normally. The remote user must be root or
                    have passwordless sudo configured.

    --servers FILE  Batch multi-server connection. Uses BatchMode=yes to
                    prevent hanging on prompts. SSH must use key auth, and
                    the remote user must be root or have passwordless sudo.

    Both modes respect ~/.ssh/config. The difference is that --remote
    allows SSH password authentication while --servers requires key auth.

PRIVILEGE HANDLING:
    Local:          Prompts for sudo password if needed (interactive terminal).
                    Use --dry-run to preview without root.
    Remote:         The SSH user on each server must be root, have passwordless
                    sudo, or use --ask-sudo-pass to relay the sudo password.
                    Failures report the exact sudoers fix command.

    --ask-sudo-pass prompts once locally (password is not echoed), then
    securely relays it to each remote server via the encrypted SSH tunnel.
    The password is never written to disk.

SERVERS FILE FORMAT:
    # One server per line, blank lines and comments (#) ignored
    192.168.1.10
    192.168.1.11:2222
    root@203.0.113.50
    admin@tor-relay-04.example.com:2200
    tor-relay-05           # SSH config Host alias

SINGLE SERVER VIA SSH CONFIG (--remote):
    If ~/.ssh/config defines a Host alias for your server, use --remote
    with just the alias. SSH resolves User, Port, IdentityFile, etc.

      # Check family status on one server:
      ./setup-family.sh status-remote --remote myserver

      # Deploy to one server:
      ./setup-family.sh deploy-remote --key family.secret_family_key \
          --family-id "..." --remote myserver

      # Import key from one server:
      ./setup-family.sh import-key-remote --remote myserver

    This works with any Host alias, hostname, or IP address.

WORKFLOWS:
    New family:
      1. ./setup-family.sh generate --name myfamily
      2. ./setup-family.sh deploy --key myfamily.secret_family_key
      3. ./setup-family.sh status

    New family (remote, single server via SSH config):
      1. ./setup-family.sh generate --name myfamily
      2. ./setup-family.sh deploy-remote --key myfamily.secret_family_key \
             --remote myserver
      3. ./setup-family.sh status-remote --remote myserver

    New family (remote, multiple servers):
      1. ./setup-family.sh generate --name myfamily
      2. ./setup-family.sh deploy-remote --key myfamily.secret_family_key \
             --servers servers.txt
      3. ./setup-family.sh status-remote --servers servers.txt

    Add server to existing family:
      1. ./setup-family.sh import-key-remote --remote existing-server
      2. ./setup-family.sh deploy-remote --key family.secret_family_key \
             --remote new-server
      3. ./setup-family.sh status-remote --remote new-server

    Recover FamilyId from key file:
      1. ./setup-family.sh generate --name myfamily
         (safe if key exists — outputs FamilyId without overwriting)

    Legacy MyFamily across all servers:
      1. ./setup-family.sh collect-fingerprints --servers servers.txt
      2. ./setup-family.sh deploy-myfamily-remote --servers servers.txt \
             --myfamily "\$FP1,\$FP2,\$FP3,..."

NOTES:
    - Requires Tor >= 0.4.9.1-alpha for Happy Family support
    - During the transitional period, use --legacy-family to also set MyFamily
    - The .secret_family_key file must be kept secure; anyone with it can
      claim membership in your family
    - See: https://community.torproject.org/relay/setup/post-install/family-ids/
EOF
    # Substitute version at display time (not inside the heredoc to avoid escaping issues)
    exit 0
}

# ── Argument Parsing ─────────────────────────────────────────────────────────

parse_args() {
    [[ $# -eq 0 ]] && show_usage

    COMMAND="$1"
    shift

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -n|--name)          KEY_NAME="$2"; shift 2 ;;
            -k|--key)           KEY_FILE="$2"; shift 2 ;;
            -i|--family-id)     FAMILY_ID="$2"; shift 2 ;;
            --instance)         INSTANCE_NAME="$2"; shift 2 ;;
            -r|--remote)        REMOTE_HOST="$2"; shift 2 ;;
            -s|--servers)       SERVERS_FILE="$2"; shift 2 ;;
            -o|--output)        OUTPUT_FILE="$2"; shift 2 ;;
            --myfamily)         MYFAMILY_LINE="$2"; shift 2 ;;
            -u|--ssh-user)      SSH_USER="$2"; SSH_USER_SET=true; shift 2 ;;
            --ssh-key)          SSH_KEY="$2"; shift 2 ;;
            --ssh-port)         SSH_PORT="$2"; SSH_PORT_SET=true; shift 2 ;;
            --instances-dir)    INSTANCES_DIR="$2"; shift 2 ;;
            --data-dir)         DATA_DIR="$2"; shift 2 ;;
            --legacy-family)    LEGACY_FAMILY=true; shift ;;
            --ask-sudo-pass)    ASK_SUDO_PASS=true; shift ;;
            --no-reload)        NO_RELOAD=true; shift ;;
            --dry-run)          DRY_RUN=true; shift ;;
            --verbose)          VERBOSE=true; shift ;;
            -h|--help)          show_usage ;;
            *)                  die "Unknown option: $1 (try --help)" ;;
        esac
    done
}

# ── SSH Helpers ──────────────────────────────────────────────────────────────

# Base SSH options (for both interactive and batch modes).
build_ssh_opts() {
    local opts=(-o "ConnectTimeout=10")
    [[ -n "$SSH_KEY" ]] && opts+=(-i "$SSH_KEY")
    echo "${opts[@]}"
}

# Batch SSH options: adds BatchMode=yes to prevent interactive prompts.
build_batch_ssh_opts() {
    echo "$(build_ssh_opts) -o BatchMode=yes"
}

# Parse a server line: [user@]host[:port]
# Sets globals: _SSH_HOST, _SSH_USER, _SSH_PORT
# Empty _SSH_USER/_SSH_PORT means "let SSH config or system default decide".
parse_server_line() {
    local line="$1"
    _SSH_HOST="" _SSH_USER="" _SSH_PORT=""

    line="${line%%#*}"
    line="$(echo "$line" | xargs)"
    [[ -z "$line" ]] && return 1

    if [[ "$line" == *@* ]]; then
        _SSH_USER="${line%%@*}"
        line="${line#*@}"
    fi
    if [[ "$line" == *:* ]]; then
        _SSH_PORT="${line##*:}"
        _SSH_HOST="${line%:*}"
    else
        _SSH_HOST="$line"
    fi

    # CLI flags serve as global defaults when not overridden per-line
    [[ -z "$_SSH_USER" ]] && $SSH_USER_SET && _SSH_USER="$SSH_USER"
    [[ -z "$_SSH_PORT" ]] && $SSH_PORT_SET && _SSH_PORT="$SSH_PORT"
    return 0
}

# Build the SSH target string: conditionally includes user@ and -p.
# Requires _SSH_HOST, _SSH_USER, _SSH_PORT to be set (via parse_server_line).
build_ssh_target() {
    local target="$_SSH_HOST"
    [[ -n "$_SSH_USER" ]] && target="${_SSH_USER}@${_SSH_HOST}"
    if [[ -n "$_SSH_PORT" ]]; then
        echo "-p $_SSH_PORT $target"
    else
        echo "$target"
    fi
}

# Build the SCP target string: uses -P (not -p) for port.
build_scp_target_args() {
    local port_args=""
    [[ -n "$_SSH_PORT" ]] && port_args="-P $_SSH_PORT"
    local dest="$_SSH_HOST"
    [[ -n "$_SSH_USER" ]] && dest="${_SSH_USER}@${dest}"
    echo "$port_args $dest"
}

# Execute a script on a remote server for --remote (single server).
# Like batch mode but WITHOUT BatchMode=yes, so SSH can still prompt for
# password/key auth via /dev/tty if needed. The remote server must be root
# or have passwordless sudo (same as batch for sudo, but more flexible for
# SSH authentication).
run_remote_interactive() {
    local script="$1"
    local ssh_opts
    ssh_opts=$(build_ssh_opts)
    local target_args
    target_args=$(build_ssh_target)

    # shellcheck disable=SC2086
    ssh $ssh_opts $target_args "bash -s" <<< "$script" 2>&1
}

# Execute a script on a remote server in batch mode (--servers).
# Uses single-step SSH with BatchMode=yes. No interactivity.
run_remote_batch() {
    local script="$1"
    local ssh_opts
    ssh_opts=$(build_batch_ssh_opts)
    local target_args
    target_args=$(build_ssh_target)

    # shellcheck disable=SC2086
    ssh $ssh_opts $target_args "bash -s" <<< "$script" 2>&1
}

# Read servers from a file, returning non-empty non-comment lines.
read_servers_file() {
    local file="$1"
    [[ ! -f "$file" ]] && die "Servers file not found: $file"
    local servers=()
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%%#*}"
        line="$(echo "$line" | xargs)"
        [[ -n "$line" ]] && servers+=("$line")
    done < "$file"
    [[ ${#servers[@]} -eq 0 ]] && die "No servers found in $file"
    printf '%s\n' "${servers[@]}"
}

# ── Portable Grep Helpers ────────────────────────────────────────────────────
# macOS ships BSD grep which lacks -P (Perl regex). These helpers work on
# both GNU grep (Linux) and BSD grep (macOS).

# Extract a numeric value from KEY:VALUE output (e.g., "TOTAL:18" → "18").
# Usage: parse_kv "$result" "TOTAL"
parse_kv() {
    echo "$1" | sed -n "s/.*${2}:\\([0-9]*\\).*/\\1/p" | head -1
}

# Extract FamilyId value from a line like "FamilyId wweKJrJx..."
# Usage: extract_family_id < file   OR   echo "$text" | extract_family_id
extract_family_id() {
    sed -n 's/^FamilyId //p' | head -1
}

# Extract the path from a %include directive.
# Usage: extract_include_path < file   OR   echo "$text" | extract_include_path
extract_include_path() {
    awk '/^%include/{print $2; exit}'
}

# ── Local Instance Helpers ───────────────────────────────────────────────────

# List local relay instance names from the instances directory.
list_local_instances() {
    if [[ -d "$INSTANCES_DIR" ]]; then
        # shellcheck disable=SC2012  # ls is fine here; instance names are controlled alphanumeric strings
        ls "$INSTANCES_DIR" 2>/dev/null | sort
    fi
}

# Get relay fingerprint from the data directory.
# Uses $SUDO if set; returns empty string on failure.
get_fingerprint() {
    local name="$1"
    local fp_file="$DATA_DIR/$name/fingerprint"
    if [[ -n "$SUDO" ]]; then
        $SUDO cat "$fp_file" 2>/dev/null | awk '{print $2}'
    else
        awk '{print $2}' "$fp_file" 2>/dev/null
    fi
}

# Detect if all instances %include the same shared torrc file.
# Returns the path if found and the file exists, or empty string.
detect_shared_torrc() {
    local shared=""
    local name
    for name in $(list_local_instances); do
        local torrc="$INSTANCES_DIR/$name/torrc"
        local include_path
        if [[ -n "$SUDO" ]]; then
            # shellcheck disable=SC2016  # $2 is an awk field reference, not a shell variable
            include_path=$($SUDO awk '/^%include/{print $2; exit}' "$torrc" 2>/dev/null || true)
        else
            # shellcheck disable=SC2016
            include_path=$(awk '/^%include/{print $2; exit}' "$torrc" 2>/dev/null || true)
        fi

        if [[ -z "$include_path" ]]; then
            echo ""
            return
        fi
        if [[ -z "$shared" ]]; then
            shared="$include_path"
        elif [[ "$shared" != "$include_path" ]]; then
            echo ""
            return
        fi
    done

    if [[ -n "$shared" ]]; then
        # Check file existence (may need sudo)
        if [[ -n "$SUDO" ]]; then
            $SUDO test -f "$shared" 2>/dev/null && echo "$shared" || echo ""
        else
            [[ -f "$shared" ]] && echo "$shared" || echo ""
        fi
    else
        echo ""
    fi
}

# Update FamilyId (and optionally MyFamily) in a torrc file.
# Handles: replace existing line, or insert before %include, or append.
# Usage: update_torrc_family <torrc_path> <family_id> [my_family_line]
update_torrc_family() {
    local torrc="$1" family_id="$2" my_family_line="${3:-}"

    # FamilyId
    if $SUDO grep -q "^FamilyId " "$torrc" 2>/dev/null; then
        $SUDO sed -i "s|^FamilyId .*|FamilyId $family_id|" "$torrc"
    else
        if $SUDO grep -q "^%include" "$torrc" 2>/dev/null; then
            $SUDO sed -i "/^%include/i FamilyId $family_id" "$torrc"
        else
            echo "FamilyId $family_id" | $SUDO tee -a "$torrc" > /dev/null
        fi
    fi

    # MyFamily (legacy)
    if [[ -n "$my_family_line" ]]; then
        if $SUDO grep -q "^MyFamily " "$torrc" 2>/dev/null; then
            $SUDO sed -i "s|^MyFamily .*|$my_family_line|" "$torrc"
        else
            if $SUDO grep -q "^%include" "$torrc" 2>/dev/null; then
                $SUDO sed -i "/^%include/i $my_family_line" "$torrc"
            else
                echo "$my_family_line" | $SUDO tee -a "$torrc" > /dev/null
            fi
        fi
    fi
}

# Update MyFamily only in a torrc file.
update_torrc_myfamily() {
    local torrc="$1" my_family_line="$2"

    if $SUDO grep -q "^MyFamily " "$torrc" 2>/dev/null; then
        $SUDO sed -i "s|^MyFamily .*|$my_family_line|" "$torrc"
    else
        if $SUDO grep -q "^%include" "$torrc" 2>/dev/null; then
            $SUDO sed -i "/^%include/i $my_family_line" "$torrc"
        else
            echo "$my_family_line" | $SUDO tee -a "$torrc" > /dev/null
        fi
    fi
}

# Reload all running Tor instances in a single systemctl call.
# Usage: reload_instances instance1 instance2 ...
reload_instances() {
    local services=()
    local name
    for name in "$@"; do
        if $SUDO systemctl is-active --quiet "tor@$name.service" 2>/dev/null; then
            services+=("tor@$name.service")
        else
            log_verbose "$name: not running, skipping reload"
        fi
    done
    if [[ ${#services[@]} -gt 0 ]]; then
        if $SUDO systemctl reload "${services[@]}" 2>/dev/null; then
            log_success "Reloaded ${#services[@]} running instance(s)"
        else
            log_warn "Some instances failed to reload, trying restart..."
            $SUDO systemctl restart "${services[@]}" 2>/dev/null || \
                log_warn "Some instances failed to restart"
        fi
    else
        log_verbose "No running instances to reload"
    fi
}

# Auto-resolve FamilyId when --family-id is not provided.
# Tries: shared torrc → instance torrc → derive from key file.
resolve_family_id() {
    # 1. Check shared torrc
    local shared_torrc
    shared_torrc=$(detect_shared_torrc)
    if [[ -n "$shared_torrc" ]]; then
        local fid
        if [[ -n "$SUDO" ]]; then
            fid=$($SUDO sed -n 's/^FamilyId //p' "$shared_torrc" 2>/dev/null | head -1 || true)
        else
            fid=$(sed -n 's/^FamilyId //p' "$shared_torrc" 2>/dev/null | head -1 || true)
        fi
        if [[ -n "$fid" ]]; then
            FAMILY_ID="$fid"
            log_info "FamilyId resolved from shared torrc: $shared_torrc"
            return 0
        fi
    fi

    # 2. Check any instance torrc
    local name
    for name in $(list_local_instances); do
        local torrc="$INSTANCES_DIR/$name/torrc"
        local fid
        if [[ -n "$SUDO" ]]; then
            fid=$($SUDO sed -n 's/^FamilyId //p' "$torrc" 2>/dev/null | head -1 || true)
        else
            fid=$(sed -n 's/^FamilyId //p' "$torrc" 2>/dev/null | head -1 || true)
        fi
        if [[ -n "$fid" ]]; then
            FAMILY_ID="$fid"
            log_info "FamilyId resolved from instance torrc: $name"
            return 0
        fi
    done

    # 3. Derive from key file via tor --keygen-family (idempotent)
    if [[ -n "$KEY_FILE" ]] && [[ -f "$KEY_FILE" ]] && command -v tor &>/dev/null; then
        local tmpdir
        tmpdir=$(mktemp -d)
        local base
        base=$(basename "$KEY_FILE" .secret_family_key)
        cp "$KEY_FILE" "$tmpdir/${base}.secret_family_key"
        local output
        if output=$(cd "$tmpdir" && tor --keygen-family "$base" 2>&1); then
            local fid
            fid=$(echo "$output" | sed -n 's/^FamilyId //p' || true)
            if [[ -n "$fid" ]]; then
                FAMILY_ID="$fid"
                log_info "FamilyId derived from key file via tor --keygen-family"
                rm -rf "$tmpdir"
                return 0
            fi
        fi
        rm -rf "$tmpdir"
    fi

    return 1
}

# ── Shared Remote Script Fragments ──────────────────────────────────────────

# Shared torrc detection logic for remote scripts (POSIX-compatible).
# shellcheck disable=SC2016  # Intentionally single-quoted: expands on remote server
REMOTE_DETECT_SHARED_TORRC='
detect_shared_torrc() {
    local shared=""
    for _name in $(ls "$INSTANCES_DIR" 2>/dev/null | sort); do
        local _torrc="$INSTANCES_DIR/$_name/torrc"
        local _inc
        _inc=$($SUDO awk '"'"'/^%include/{print $2; exit}'"'"' "$_torrc" 2>/dev/null || true)
        if [ -z "$_inc" ]; then echo ""; return; fi
        if [ -z "$shared" ]; then
            shared="$_inc"
        elif [ "$shared" != "$_inc" ]; then
            echo ""; return
        fi
    done
    if [ -n "$shared" ] && $SUDO test -f "$shared" 2>/dev/null; then
        echo "$shared"
    else
        echo ""
    fi
}
'

# ── Command: generate ────────────────────────────────────────────────────────

cmd_generate() {
    log_header "Generate Family Key"

    command -v tor &>/dev/null || die "Tor is not installed"

    # Check Tor version >= 0.4.9.1
    local tor_version_line
    tor_version_line=$(tor --version | head -n1)
    log_info "Tor version: $tor_version_line"

    local ver
    ver=$(echo "$tor_version_line" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)
    if [[ -n "$ver" ]]; then
        local major minor patch sub
        IFS='.' read -r major minor patch sub <<< "$ver"
        if [[ "$major" -lt 0 ]] || \
           [[ "$major" -eq 0 && "$minor" -lt 4 ]] || \
           [[ "$major" -eq 0 && "$minor" -eq 4 && "$patch" -lt 9 ]] || \
           [[ "$major" -eq 0 && "$minor" -eq 4 && "$patch" -eq 9 && "$sub" -lt 1 ]]; then
            die "Tor >= 0.4.9.1-alpha required for --keygen-family (found: $ver)"
        fi
    else
        log_warn "Could not parse Tor version; attempting --keygen-family anyway"
    fi

    # Check for existing key file
    local key_existed=false
    if [[ -f "${KEY_NAME}.secret_family_key" ]]; then
        key_existed=true
        log_info "Existing key file found: ${KEY_NAME}.secret_family_key"
        log_info "Re-running tor --keygen-family to recover FamilyId (key will not be overwritten)"
    fi

    if $DRY_RUN; then
        log_info "[dry-run] Would run: tor --keygen-family $KEY_NAME"
        return
    fi

    local output
    output=$(tor --keygen-family "$KEY_NAME" 2>&1) || \
        die "Failed to generate family key. Is Tor >= 0.4.9.1-alpha?\n\nOutput:\n$output"

    echo ""
    echo "$output"
    echo ""

    local fid
    fid=$(echo "$output" | sed -n 's/^FamilyId //p' || true)

    if [[ -f "${KEY_NAME}.secret_family_key" ]]; then
        chmod 600 "${KEY_NAME}.secret_family_key"
        if $key_existed; then
            log_success "FamilyId recovered from existing key"
        else
            log_success "Key file created: ${KEY_NAME}.secret_family_key (permissions: 600)"
        fi
    else
        log_warn "Expected key file ${KEY_NAME}.secret_family_key not found in current directory"
    fi

    echo ""
    log_info "Next steps:"
    echo "  1. Deploy to local instances:"
    echo "     $0 deploy --key ${KEY_NAME}.secret_family_key --family-id \"${fid:-<FamilyId>}\""
    echo "  2. Or deploy to remote servers:"
    echo "     $0 deploy-remote --key ${KEY_NAME}.secret_family_key \\"
    echo "         --family-id \"${fid:-<FamilyId>}\" --servers servers.txt"
}

# ── Command: import-key ──────────────────────────────────────────────────────

cmd_import_key() {
    log_header "Import Family Key (Local)"

    ensure_privilege
    [[ ! -d "$INSTANCES_DIR" ]] && die "Instances directory not found: $INSTANCES_DIR"
    [[ ! -d "$DATA_DIR" ]] && die "Data directory not found: $DATA_DIR"

    local source_instance="" source_key_path=""

    if [[ -n "$INSTANCE_NAME" ]]; then
        # Use specified instance
        local key_dir="$DATA_DIR/$INSTANCE_NAME/keys"
        source_key_path=$($SUDO find "$key_dir" -name "*.secret_family_key" 2>/dev/null | head -1 || true)
        [[ -z "$source_key_path" ]] && die "No .secret_family_key found in $key_dir"
        source_instance="$INSTANCE_NAME"
    else
        # Auto-detect: find first instance with a key
        local name
        for name in $(list_local_instances); do
            local key_dir="$DATA_DIR/$name/keys"
            local kp
            kp=$($SUDO find "$key_dir" -name "*.secret_family_key" 2>/dev/null | head -1 || true)
            if [[ -n "$kp" ]]; then
                source_key_path="$kp"
                source_instance="$name"
                break
            fi
        done
        [[ -z "$source_key_path" ]] && die "No .secret_family_key found in any instance KeyDir"
    fi

    local output_name="${KEY_NAME}.secret_family_key"

    log_info "Source instance: $source_instance"
    log_info "Source key: $source_key_path"

    if $DRY_RUN; then
        log_info "[dry-run] Would copy key to: $output_name"
        return
    fi

    # Copy key to CWD
    $SUDO cp "$source_key_path" "$output_name"
    # Make readable by current user
    if [[ $EUID -ne 0 ]]; then
        $SUDO chown "$(id -u):$(id -g)" "$output_name"
    fi
    chmod 600 "$output_name"
    log_success "Key saved to: $output_name"

    # Try to get FamilyId
    local fid=""
    local shared_torrc
    shared_torrc=$(detect_shared_torrc)
    if [[ -n "$shared_torrc" ]]; then
        fid=$($SUDO sed -n 's/^FamilyId //p' "$shared_torrc" 2>/dev/null || true)
    fi
    if [[ -z "$fid" ]]; then
        local torrc="$INSTANCES_DIR/$source_instance/torrc"
        fid=$($SUDO sed -n 's/^FamilyId //p' "$torrc" 2>/dev/null || true)
    fi
    if [[ -z "$fid" ]] && command -v tor &>/dev/null; then
        # Derive via tor --keygen-family
        local tmpdir
        tmpdir=$(mktemp -d)
        local base
        base=$(basename "$output_name" .secret_family_key)
        cp "$output_name" "$tmpdir/${base}.secret_family_key"
        local output
        if output=$(cd "$tmpdir" && tor --keygen-family "$base" 2>&1); then
            fid=$(echo "$output" | sed -n 's/^FamilyId //p' || true)
        fi
        rm -rf "$tmpdir"
    fi

    echo ""
    if [[ -n "$fid" ]]; then
        log_success "FamilyId: $fid"
    else
        log_warn "Could not determine FamilyId (deploy will auto-resolve, or use --family-id)"
    fi

    echo ""
    log_info "Next steps:"
    echo "  $0 deploy --key $output_name${fid:+ --family-id \"$fid\"}"
    echo "  $0 deploy-remote --key $output_name${fid:+ --family-id \"$fid\"} --servers servers.txt"
}

# ── Command: import-key-remote ───────────────────────────────────────────────

cmd_import_key_remote() {
    log_header "Import Family Key (Remote)"

    [[ -z "$REMOTE_HOST" ]] && die "Missing --remote: remote server to import key from"

    prompt_sudo_pass

    parse_server_line "$REMOTE_HOST" || die "Invalid remote host: $REMOTE_HOST"
    log_info "Remote server: $_SSH_HOST"

    local import_script
    import_script="$(cat << REMOTE_SCRIPT
#!/bin/bash
set -euo pipefail
INSTANCES_DIR="$INSTANCES_DIR"
DATA_DIR="$DATA_DIR"
INSTANCE_NAME="$INSTANCE_NAME"
$REMOTE_SUDO_BLOCK

# Find the key file
source_instance=""
source_key_path=""
if [ -n "\$INSTANCE_NAME" ]; then
    key_dir="\$DATA_DIR/\$INSTANCE_NAME/keys"
    source_key_path=\$(\$SUDO find "\$key_dir" -name "*.secret_family_key" 2>/dev/null | head -1 || true)
    [ -z "\$source_key_path" ] && { echo "ERROR:No .secret_family_key in \$key_dir"; exit 1; }
    source_instance="\$INSTANCE_NAME"
else
    for name in \$(ls "\$INSTANCES_DIR" 2>/dev/null | sort); do
        key_dir="\$DATA_DIR/\$name/keys"
        kp=\$(\$SUDO find "\$key_dir" -name "*.secret_family_key" 2>/dev/null | head -1 || true)
        if [ -n "\$kp" ]; then
            source_key_path="\$kp"
            source_instance="\$name"
            break
        fi
    done
    [ -z "\$source_key_path" ] && { echo "ERROR:No .secret_family_key found in any instance"; exit 1; }
fi

# Read key and base64-encode
key_b64=\$(\$SUDO cat "\$source_key_path" | base64 -w0)
key_filename=\$(basename "\$source_key_path")

# Try to read FamilyId from config
fid=""
# Check shared torrc
shared=""
for name in \$(ls "\$INSTANCES_DIR" 2>/dev/null | sort); do
    inc=\$(\$SUDO awk '/^%include/{print \$2; exit}' "\$INSTANCES_DIR/\$name/torrc" 2>/dev/null || true)
    if [ -z "\$inc" ]; then shared=""; break; fi
    if [ -z "\$shared" ]; then shared="\$inc"
    elif [ "\$shared" != "\$inc" ]; then shared=""; break; fi
done
if [ -n "\$shared" ] && \$SUDO test -f "\$shared" 2>/dev/null; then
    fid=\$(\$SUDO sed -n 's/^FamilyId //p' "\$shared" 2>/dev/null || true)
fi
if [ -z "\$fid" ]; then
    fid=\$(\$SUDO sed -n 's/^FamilyId //p' "\$INSTANCES_DIR/\$source_instance/torrc" 2>/dev/null || true)
fi

echo "KEY_B64:\$key_b64"
echo "KEY_FILENAME:\$key_filename"
echo "INSTANCE:\$source_instance"
echo "FAMILY_ID:\$fid"
REMOTE_SCRIPT
)"

    if $DRY_RUN; then
        log_info "[dry-run] Would SSH to $_SSH_HOST and extract family key"
        return
    fi

    import_script=$(inject_sudo_pass "$import_script")

    log_info "Connecting to $_SSH_HOST..."
    local result
    result=$(run_remote_interactive "$import_script") || {
        if echo "$result" | grep -q "ERROR:WRONG_SUDO_PASS"; then
            die "Sudo password rejected on $_SSH_HOST"
        fi
        if echo "$result" | grep -q "ERROR:NEED_SUDO"; then
            die "Need root or passwordless sudo on $_SSH_HOST (or use --ask-sudo-pass)"
        fi
        die "Failed to import key from $_SSH_HOST:\n$result"
    }

    # Parse output
    local key_b64 key_filename instance_name fid
    key_b64=$(echo "$result" | grep "^KEY_B64:" | head -1 | cut -d: -f2-)
    key_filename=$(echo "$result" | grep "^KEY_FILENAME:" | head -1 | cut -d: -f2-)
    instance_name=$(echo "$result" | grep "^INSTANCE:" | head -1 | cut -d: -f2-)
    fid=$(echo "$result" | grep "^FAMILY_ID:" | head -1 | cut -d: -f2-)

    [[ -z "$key_b64" ]] && die "No key data received from $_SSH_HOST"

    # Use original filename from remote server, or fall back to --name default
    local output_name
    if [[ -n "$key_filename" ]]; then
        output_name="$key_filename"
    else
        output_name="${KEY_NAME}.secret_family_key"
    fi
    echo "$key_b64" | base64 -d > "$output_name"
    chmod 600 "$output_name"

    log_success "Key saved to: $output_name"
    log_info "Source: $_SSH_HOST (instance: ${instance_name:-unknown})"
    if [[ -n "$fid" ]]; then
        log_success "FamilyId: $fid"
    else
        log_warn "FamilyId not found in remote config (deploy will auto-resolve, or use --family-id)"
    fi

    echo ""
    log_info "Next steps:"
    echo "  $0 deploy --key $output_name${fid:+ --family-id \"$fid\"}"
    echo "  $0 deploy-remote --key $output_name${fid:+ --family-id \"$fid\"} --servers servers.txt"
}

# ── Command: deploy (local) ──────────────────────────────────────────────────

cmd_deploy() {
    log_header "Deploy Family Key (Local)"

    ensure_privilege

    [[ -z "$KEY_FILE" ]] && die "Missing --key: path to .secret_family_key file"
    [[ ! -f "$KEY_FILE" ]] && die "Key file not found: $KEY_FILE"
    [[ ! -d "$INSTANCES_DIR" ]] && die "Instances directory not found: $INSTANCES_DIR"

    local key_basename
    key_basename=$(basename "$KEY_FILE")
    [[ "$key_basename" != *.secret_family_key ]] && \
        die "Key filename must end with .secret_family_key (got: $key_basename)"

    # Auto-resolve FamilyId if not provided
    if [[ -z "$FAMILY_ID" ]]; then
        if ! resolve_family_id; then
            die "Missing --family-id: could not auto-resolve FamilyId. Provide it explicitly."
        fi
    fi

    local instances
    mapfile -t instances < <(list_local_instances)
    [[ ${#instances[@]} -eq 0 ]] && die "No relay instances found in $INSTANCES_DIR"

    log_info "Key file: $KEY_FILE"
    log_info "Family ID: $FAMILY_ID"
    log_info "Instances: ${#instances[@]} found in $INSTANCES_DIR"
    echo ""

    # Collect fingerprints for legacy MyFamily if requested
    local my_family_line=""
    if $LEGACY_FAMILY; then
        log_info "Collecting fingerprints for legacy MyFamily..."
        local fps=()
        for name in "${instances[@]}"; do
            local fp
            fp=$(get_fingerprint "$name")
            if [[ -n "$fp" ]]; then
                fps+=("\$$fp")
                log_verbose "$name: $fp"
            else
                log_warn "No fingerprint for $name (relay may not have started yet)"
            fi
        done
        if [[ ${#fps[@]} -gt 0 ]]; then
            my_family_line="MyFamily ${fps[*]}"
            log_info "MyFamily will include ${#fps[@]} fingerprints"
        else
            log_warn "No fingerprints found; skipping MyFamily"
            LEGACY_FAMILY=false
        fi
    fi

    # Detect shared torrc
    local shared_torrc
    shared_torrc=$(detect_shared_torrc)

    if [[ -n "$shared_torrc" ]]; then
        log_info "Shared torrc detected: $shared_torrc"
        log_info "Family config will be written to shared torrc"

        if ! $DRY_RUN; then
            local legacy_arg=""
            $LEGACY_FAMILY && [[ -n "$my_family_line" ]] && legacy_arg="$my_family_line"
            update_torrc_family "$shared_torrc" "$FAMILY_ID" "$legacy_arg"
            log_success "Updated family config in $shared_torrc"
        else
            log_info "[dry-run] Would update FamilyId in $shared_torrc"
        fi
    fi

    # Deploy key to each instance
    local deployed=0
    for name in "${instances[@]}"; do
        echo -n "  $name: "

        local key_dir="$DATA_DIR/$name/keys"
        local torrc="$INSTANCES_DIR/$name/torrc"
        local tor_user="_tor-$name"

        if $DRY_RUN; then
            echo "[dry-run] would deploy key and update torrc"
            deployed=$((deployed + 1))
            continue
        fi

        # Create keys directory if needed
        if ! $SUDO test -d "$key_dir" 2>/dev/null; then
            $SUDO mkdir -p "$key_dir"
            $SUDO chown "$tor_user:$tor_user" "$key_dir" 2>/dev/null || true
            $SUDO chmod 2700 "$key_dir"
        fi

        # Copy key file
        $SUDO cp "$KEY_FILE" "$key_dir/$key_basename"
        $SUDO chown "$tor_user:$tor_user" "$key_dir/$key_basename" 2>/dev/null || true
        $SUDO chmod 600 "$key_dir/$key_basename"

        # Update per-instance torrc only if no shared torrc
        if [[ -z "$shared_torrc" ]]; then
            local legacy_arg=""
            $LEGACY_FAMILY && [[ -n "$my_family_line" ]] && legacy_arg="$my_family_line"
            update_torrc_family "$torrc" "$FAMILY_ID" "$legacy_arg"
        fi

        echo -e "${GREEN}deployed${NC}"
        deployed=$((deployed + 1))
    done

    echo ""
    log_success "Deployed to $deployed/${#instances[@]} instances"

    # Reload
    if ! $NO_RELOAD && ! $DRY_RUN; then
        echo ""
        log_info "Reloading Tor instances..."
        reload_instances "${instances[@]}"
    elif $NO_RELOAD; then
        echo ""
        log_info "Skipping reload (--no-reload)"
    fi

    echo ""
    log_info "Verify with: $0 status"
}

# ── Command: deploy-remote ───────────────────────────────────────────────────

cmd_deploy_remote() {
    log_header "Deploy Family Key (Remote)"

    prompt_sudo_pass

    [[ -z "$KEY_FILE" ]] && die "Missing --key: path to .secret_family_key file"
    [[ ! -f "$KEY_FILE" ]] && die "Key file not found: $KEY_FILE"

    local key_basename
    key_basename=$(basename "$KEY_FILE")
    [[ "$key_basename" != *.secret_family_key ]] && \
        die "Key filename must end with .secret_family_key (got: $key_basename)"

    # Auto-resolve FamilyId if not provided
    if [[ -z "$FAMILY_ID" ]]; then
        # Try 1: derive from key file using local tor binary
        if [[ -f "$KEY_FILE" ]] && command -v tor &>/dev/null; then
            local tmpdir
            tmpdir=$(mktemp -d)
            local base
            base=$(basename "$KEY_FILE" .secret_family_key)
            cp "$KEY_FILE" "$tmpdir/${base}.secret_family_key"
            local output
            if output=$(cd "$tmpdir" && tor --keygen-family "$base" 2>&1); then
                FAMILY_ID=$(echo "$output" | sed -n 's/^FamilyId //p' || true)
                [[ -n "$FAMILY_ID" ]] && log_info "FamilyId derived from key file"
            fi
            rm -rf "$tmpdir"
        fi

        # Try 2: read from the first target server's config via SSH
        if [[ -z "$FAMILY_ID" ]]; then
            local resolve_target=""
            if [[ -n "$REMOTE_HOST" ]]; then
                resolve_target="$REMOTE_HOST"
            elif [[ -n "$SERVERS_FILE" && -f "$SERVERS_FILE" ]]; then
                resolve_target=$(read_servers_file "$SERVERS_FILE" | head -1)
            fi
            if [[ -n "$resolve_target" ]]; then
                log_verbose "Trying to resolve FamilyId from remote server..."
                local resolve_script
                resolve_script="$(cat << REMOTE_SCRIPT
INSTANCES_DIR="$INSTANCES_DIR"
$REMOTE_SUDO_BLOCK
# Check shared torrc first
for name in \$(ls "\$INSTANCES_DIR" 2>/dev/null | head -1); do
    inc=\$(\$SUDO awk '/^%include/{print \$2; exit}' "\$INSTANCES_DIR/\$name/torrc" 2>/dev/null || true)
    if [ -n "\$inc" ] && \$SUDO test -f "\$inc" 2>/dev/null; then
        fid=\$(\$SUDO sed -n 's/^FamilyId //p' "\$inc" 2>/dev/null | head -1)
        [ -n "\$fid" ] && { echo "FID:\$fid"; exit 0; }
    fi
    fid=\$(\$SUDO sed -n 's/^FamilyId //p' "\$INSTANCES_DIR/\$name/torrc" 2>/dev/null | head -1)
    [ -n "\$fid" ] && { echo "FID:\$fid"; exit 0; }
done
REMOTE_SCRIPT
)"
                resolve_script=$(inject_sudo_pass "$resolve_script")
                parse_server_line "$resolve_target" || true
                if [[ -n "$_SSH_HOST" ]]; then
                    local resolve_result
                    resolve_result=$(run_remote_interactive "$resolve_script" 2>&1) || true
                    local remote_fid
                    remote_fid=$(echo "$resolve_result" | grep "^FID:" | head -1 | cut -d: -f2-)
                    if [[ -n "$remote_fid" ]]; then
                        FAMILY_ID="$remote_fid"
                        log_info "FamilyId resolved from remote server: $_SSH_HOST"
                    fi
                fi
            fi
        fi

        if [[ -z "$FAMILY_ID" ]]; then
            die "Missing --family-id: could not auto-resolve FamilyId from key file or remote config"
        fi
    fi

    # Base64-encode the key for embedding in the remote script
    local key_b64
    key_b64=$(base64 -w0 "$KEY_FILE")

    log_info "Key file: $KEY_FILE"
    log_info "Family ID: $FAMILY_ID"

    # Build the remote deploy script
    local deploy_script
    deploy_script="$(cat << REMOTE_SCRIPT
#!/bin/bash
set -euo pipefail
KEY_BASENAME="$key_basename"
FAMILY_ID="$FAMILY_ID"
INSTANCES_DIR="$INSTANCES_DIR"
DATA_DIR="$DATA_DIR"
NO_RELOAD="$NO_RELOAD"
LEGACY_FAMILY="$LEGACY_FAMILY"
KEY_B64="$key_b64"
$REMOTE_SUDO_BLOCK

# Decode key to temp file
TMP_KEY="/tmp/.tor_family_key_\$\$"
trap 'rm -f "\$TMP_KEY"' EXIT
echo "\$KEY_B64" | base64 -d > "\$TMP_KEY"
chmod 600 "\$TMP_KEY"

instances=\$(ls "\$INSTANCES_DIR" 2>/dev/null | sort)
[ -z "\$instances" ] && { echo "ERROR:No instances in \$INSTANCES_DIR"; exit 1; }

# Collect fingerprints for legacy family
fps=()
if [ "\$LEGACY_FAMILY" = "true" ]; then
    for name in \$instances; do
        fp_file="\$DATA_DIR/\$name/fingerprint"
        if \$SUDO test -f "\$fp_file" 2>/dev/null; then
            fp=\$(\$SUDO cat "\$fp_file" 2>/dev/null | awk '{print \$2}' || true)
            [ -n "\$fp" ] && fps+=("\\\$\$fp")
        fi
    done
fi
my_family_line=""
[ \${#fps[@]} -gt 0 ] && my_family_line="MyFamily \${fps[*]}"

# Detect shared torrc
$REMOTE_DETECT_SHARED_TORRC
shared_torrc=\$(detect_shared_torrc)

# Update shared torrc if detected
if [ -n "\$shared_torrc" ]; then
    if \$SUDO grep -q "^FamilyId " "\$shared_torrc" 2>/dev/null; then
        \$SUDO sed -i "s|^FamilyId .*|FamilyId \$FAMILY_ID|" "\$shared_torrc"
    else
        echo "FamilyId \$FAMILY_ID" | \$SUDO tee -a "\$shared_torrc" > /dev/null
    fi
    if [ "\$LEGACY_FAMILY" = "true" ] && [ -n "\$my_family_line" ]; then
        if \$SUDO grep -q "^MyFamily " "\$shared_torrc" 2>/dev/null; then
            \$SUDO sed -i "s|^MyFamily .*|\$my_family_line|" "\$shared_torrc"
        else
            echo "\$my_family_line" | \$SUDO tee -a "\$shared_torrc" > /dev/null
        fi
    fi
fi

count=0
for name in \$instances; do
    key_dir="\$DATA_DIR/\$name/keys"
    torrc="\$INSTANCES_DIR/\$name/torrc"
    tor_user="_tor-\$name"

    \$SUDO mkdir -p "\$key_dir"
    \$SUDO chown "\$tor_user:\$tor_user" "\$key_dir" 2>/dev/null || true
    \$SUDO chmod 2700 "\$key_dir"

    \$SUDO cp "\$TMP_KEY" "\$key_dir/\$KEY_BASENAME"
    \$SUDO chown "\$tor_user:\$tor_user" "\$key_dir/\$KEY_BASENAME" 2>/dev/null || true
    \$SUDO chmod 600 "\$key_dir/\$KEY_BASENAME"

    # Update per-instance torrc only if no shared torrc
    if [ -z "\$shared_torrc" ]; then
        if \$SUDO grep -q "^FamilyId " "\$torrc" 2>/dev/null; then
            \$SUDO sed -i "s|^FamilyId .*|FamilyId \$FAMILY_ID|" "\$torrc"
        else
            if \$SUDO grep -q "^%include" "\$torrc" 2>/dev/null; then
                \$SUDO sed -i "/^%include/i FamilyId \$FAMILY_ID" "\$torrc"
            else
                echo "FamilyId \$FAMILY_ID" | \$SUDO tee -a "\$torrc" > /dev/null
            fi
        fi
        if [ "\$LEGACY_FAMILY" = "true" ] && [ -n "\$my_family_line" ]; then
            if \$SUDO grep -q "^MyFamily " "\$torrc" 2>/dev/null; then
                \$SUDO sed -i "s|^MyFamily .*|\$my_family_line|" "\$torrc"
            else
                if \$SUDO grep -q "^%include" "\$torrc" 2>/dev/null; then
                    \$SUDO sed -i "/^%include/i \$my_family_line" "\$torrc"
                else
                    echo "\$my_family_line" | \$SUDO tee -a "\$torrc" > /dev/null
                fi
            fi
        fi
    fi

    count=\$((count + 1))
done

echo "DEPLOYED:\$count"

# Reload all at once
if [ "\$NO_RELOAD" != "true" ]; then
    services=""
    for name in \$instances; do
        if \$SUDO systemctl is-active --quiet "tor@\$name.service" 2>/dev/null; then
            services="\$services tor@\$name.service"
        fi
    done
    if [ -n "\$services" ]; then
        \$SUDO systemctl reload \$services 2>/dev/null || \$SUDO systemctl restart \$services 2>/dev/null || true
        reloaded=\$(echo \$services | wc -w)
    else
        reloaded=0
    fi
    echo "RELOADED:\$reloaded"
fi
REMOTE_SCRIPT
)"
    deploy_script=$(inject_sudo_pass "$deploy_script")

    # Determine mode: --remote (interactive) or --servers (batch)
    if [[ -n "$REMOTE_HOST" ]]; then
        # Interactive single-server mode
        parse_server_line "$REMOTE_HOST" || die "Invalid remote host: $REMOTE_HOST"
        log_info "Server: $_SSH_HOST (interactive mode)"
        echo ""

        if $DRY_RUN; then
            echo "  $_SSH_HOST: [dry-run] would deploy key and configure instances"
            return
        fi

        echo -n "  $_SSH_HOST: "
        local result
        result=$(run_remote_interactive "$deploy_script") || {
            echo -e "${RED}FAILED${NC}"
            if echo "$result" | grep -q "ERROR:WRONG_SUDO_PASS"; then
                die "Sudo password rejected on $_SSH_HOST"
            fi
            if echo "$result" | grep -q "ERROR:NEED_SUDO"; then
                die "Need root or passwordless sudo on $_SSH_HOST (or use --ask-sudo-pass)"
            fi
            $VERBOSE && echo "    $result"
            die "Deploy failed on $_SSH_HOST"
        }

        local deployed reloaded
        deployed=$(parse_kv "$result" "DEPLOYED")
        reloaded=$(parse_kv "$result" "RELOADED")
        echo -e "${GREEN}OK${NC} (${deployed:-0} instances, ${reloaded:-?} reloaded)"

    elif [[ -n "$SERVERS_FILE" ]]; then
        # Batch multi-server mode
        [[ ! -f "$SERVERS_FILE" ]] && die "Servers file not found: $SERVERS_FILE"

        local servers=()
        while IFS= read -r line; do
            servers+=("$line")
        done < <(read_servers_file "$SERVERS_FILE")
        log_info "Servers: ${#servers[@]} (batch mode)"
        echo ""

        local success=0 fail=0
        for entry in "${servers[@]}"; do
            parse_server_line "$entry" || continue

            echo -n "  $_SSH_HOST: "

            if $DRY_RUN; then
                echo "[dry-run] would deploy key and configure instances"
                success=$((success + 1))
                continue
            fi

            local result
            result=$(run_remote_batch "$deploy_script") || {
                echo -e "${RED}FAILED${NC}"
                if echo "$result" | grep -q "ERROR:WRONG_SUDO_PASS"; then
                    echo "    Sudo password rejected on $_SSH_HOST"
                elif echo "$result" | grep -q "ERROR:NEED_SUDO"; then
                    echo "    Need root/sudo on $_SSH_HOST (try --ask-sudo-pass)"
                fi
                $VERBOSE && echo "    $result"
                fail=$((fail + 1))
                continue
            }

            local deployed reloaded
            deployed=$(parse_kv "$result" "DEPLOYED")
            reloaded=$(parse_kv "$result" "RELOADED")
            echo -e "${GREEN}OK${NC} (${deployed:-0} instances, ${reloaded:-?} reloaded)"
            success=$((success + 1))
        done

        echo ""
        log_success "Done: $success/${#servers[@]} servers succeeded"
        [[ $fail -gt 0 ]] && log_warn "$fail server(s) failed"
    else
        die "Missing --remote or --servers: specify target server(s)"
    fi
}

# ── Command: status (local) ──────────────────────────────────────────────────

cmd_status() {
    log_header "Family Configuration Status (Local)"

    ensure_read_privilege

    [[ ! -d "$INSTANCES_DIR" ]] && die "Instances directory not found: $INSTANCES_DIR"

    local instances
    mapfile -t instances < <(list_local_instances)
    [[ ${#instances[@]} -eq 0 ]] && die "No relay instances found in $INSTANCES_DIR"

    # Check shared torrc
    local shared_torrc
    shared_torrc=$(detect_shared_torrc)
    local shared_fid="" shared_myfamily=false

    if [[ -n "$shared_torrc" ]]; then
        log_info "Shared torrc: $shared_torrc"
        if [[ -n "$SUDO" ]]; then
            shared_fid=$($SUDO sed -n 's/^FamilyId //p' "$shared_torrc" 2>/dev/null || true)
            $SUDO grep -q "^MyFamily " "$shared_torrc" 2>/dev/null && shared_myfamily=true
        else
            shared_fid=$(sed -n 's/^FamilyId //p' "$shared_torrc" 2>/dev/null || true)
            grep -q "^MyFamily " "$shared_torrc" 2>/dev/null && shared_myfamily=true
        fi
        [[ -n "$shared_fid" ]] && log_info "FamilyId in shared torrc: ${shared_fid:0:20}..."
        $shared_myfamily && log_info "MyFamily present in shared torrc"
        echo ""
    fi

    local configured=0 key_present=0

    printf "  %-20s %-10s %-10s %s\n" "INSTANCE" "FAMILYID" "KEY" "STATUS"
    printf "  %-20s %-10s %-10s %s\n" "--------" "--------" "---" "------"

    for name in "${instances[@]}"; do
        local torrc="$INSTANCES_DIR/$name/torrc"
        local key_dir="$DATA_DIR/$name/keys"

        # Check FamilyId
        local has_fid="no"
        if [[ -n "$SUDO" ]]; then
            $SUDO grep -q "^FamilyId " "$torrc" 2>/dev/null && has_fid="yes"
        else
            grep -q "^FamilyId " "$torrc" 2>/dev/null && has_fid="yes"
        fi
        [[ "$has_fid" == "no" && -n "$shared_fid" ]] && has_fid="shared"
        [[ "$has_fid" != "no" ]] && configured=$((configured + 1))

        # Check key file
        local has_key="no"
        if [[ -n "$SUDO" ]]; then
            local kc
            kc=$($SUDO find "$key_dir" -name "*.secret_family_key" 2>/dev/null | wc -l)
            [[ "$kc" -gt 0 ]] && { has_key="yes"; key_present=$((key_present + 1)); }
        else
            if [[ -d "$key_dir" ]]; then
                local kc
                kc=$(find "$key_dir" -name "*.secret_family_key" 2>/dev/null | wc -l)
                [[ "$kc" -gt 0 ]] && { has_key="yes"; key_present=$((key_present + 1)); }
            else
                has_key="?"
            fi
        fi

        # Service status
        local svc_status
        if systemctl is-active --quiet "tor@$name.service" 2>/dev/null; then
            svc_status="${GREEN}running${NC}"
        else
            svc_status="${RED}stopped${NC}"
        fi

        printf "  %-20s %-10s %-10s " "$name" "$has_fid" "$has_key"
        echo -e "$svc_status"
    done

    echo ""
    log_info "Instances: ${#instances[@]}"
    log_info "FamilyId configured: $configured/${#instances[@]}"
    log_info "Key file present: $key_present/${#instances[@]}"
}

# ── Command: status-remote ───────────────────────────────────────────────────

cmd_status_remote() {
    log_header "Family Configuration Status (Remote)"

    [[ -z "$SERVERS_FILE" && -z "$REMOTE_HOST" ]] && \
        die "Missing --servers or --remote: specify target server(s)"

    prompt_sudo_pass

    local status_script
    status_script="$(cat << REMOTE_SCRIPT
#!/bin/bash
INSTANCES_DIR="$INSTANCES_DIR"
DATA_DIR="$DATA_DIR"
$REMOTE_SUDO_BLOCK
$REMOTE_DETECT_SHARED_TORRC

instances=\$(ls "\$INSTANCES_DIR" 2>/dev/null | sort)
[ -z "\$instances" ] && { echo "NO_INSTANCES"; exit 0; }

# Check shared torrc for FamilyId
shared_torrc=\$(detect_shared_torrc)
shared_fid=""
if [ -n "\$shared_torrc" ]; then
    shared_fid=\$(\$SUDO sed -n 's/^FamilyId //p' "\$shared_torrc" 2>/dev/null || true)
fi

total=0 configured=0 keys=0 running=0
for name in \$instances; do
    torrc="\$INSTANCES_DIR/\$name/torrc"
    key_dir="\$DATA_DIR/\$name/keys"

    total=\$((total + 1))

    # Count as configured if FamilyId in per-instance torrc OR shared torrc
    if \$SUDO grep -q "^FamilyId " "\$torrc" 2>/dev/null; then
        configured=\$((configured + 1))
    elif [ -n "\$shared_fid" ]; then
        configured=\$((configured + 1))
    fi

    if \$SUDO test -d "\$key_dir" 2>/dev/null; then
        kc=\$(\$SUDO find "\$key_dir" -name '*.secret_family_key' 2>/dev/null | wc -l)
        [ "\$kc" -gt 0 ] && keys=\$((keys + 1))
    fi
    \$SUDO systemctl is-active --quiet "tor@\$name.service" 2>/dev/null && running=\$((running + 1))
done
echo "TOTAL:\$total CONFIGURED:\$configured KEYS:\$keys RUNNING:\$running"
REMOTE_SCRIPT
)"
    status_script=$(inject_sudo_pass "$status_script")

    # Collect servers
    local servers=()
    if [[ -n "$REMOTE_HOST" ]]; then
        servers+=("$REMOTE_HOST")
    else
        while IFS= read -r line; do
            servers+=("$line")
        done < <(read_servers_file "$SERVERS_FILE")
    fi

    printf "  %-30s %-8s %-12s %-8s %s\n" "SERVER" "RELAYS" "FAMILYID" "KEYS" "RUNNING"
    printf "  %-30s %-8s %-12s %-8s %s\n" "------" "------" "--------" "----" "-------"

    local total_relays=0 total_configured=0

    for entry in "${servers[@]}"; do
        parse_server_line "$entry" || continue

        local result run_func
        if [[ -n "$REMOTE_HOST" && ${#servers[@]} -eq 1 ]]; then
            run_func="run_remote_interactive"
        else
            run_func="run_remote_batch"
        fi

        # shellcheck disable=SC2086
        result=$($run_func "$status_script" 2>&1) || {
            printf "  %-30s " "$_SSH_HOST"
            echo -e "${RED}CONNECTION FAILED${NC}"
            continue
        }

        if [[ "$result" == *"NO_INSTANCES"* ]]; then
            printf "  %-30s %s\n" "$_SSH_HOST" "no instances"
            continue
        fi

        local total conf keys running
        total=$(parse_kv "$result" "TOTAL")
        conf=$(parse_kv "$result" "CONFIGURED")
        keys=$(parse_kv "$result" "KEYS")
        running=$(parse_kv "$result" "RUNNING")
        total=${total:-0} conf=${conf:-0} keys=${keys:-0} running=${running:-0}

        total_relays=$((total_relays + total))
        total_configured=$((total_configured + conf))

        local conf_status run_status
        [[ "$conf" -eq "$total" ]] && conf_status="${GREEN}${conf}/${total}${NC}" || conf_status="${YELLOW}${conf}/${total}${NC}"
        [[ "$running" -eq "$total" ]] && run_status="${GREEN}${running}/${total}${NC}" || run_status="${YELLOW}${running}/${total}${NC}"

        printf "  %-30s %-8s " "$_SSH_HOST" "$total"
        echo -ne "$conf_status"
        printf "         %-8s " "${keys}/${total}"
        echo -e "$run_status"
    done

    echo ""
    log_info "Total relays: $total_relays"
    log_info "Family configured: $total_configured/$total_relays"
}

# ── Command: collect-fingerprints ────────────────────────────────────────────

cmd_collect_fingerprints() {
    log_header "Collect Fingerprints"

    local all_fps=()

    # Collect local fingerprints if instances exist
    if [[ -d "$INSTANCES_DIR" ]]; then
        ensure_read_privilege
        local instances
        mapfile -t instances < <(list_local_instances)
        if [[ ${#instances[@]} -gt 0 ]]; then
            log_info "Local instances: ${#instances[@]}"
            for name in "${instances[@]}"; do
                local fp
                fp=$(get_fingerprint "$name")
                if [[ -n "$fp" ]]; then
                    all_fps+=("\$$fp")
                    log_verbose "  $name: $fp"
                else
                    log_verbose "  $name: no fingerprint"
                fi
            done
        fi
    fi

    # Collect remote fingerprints if --servers or --remote specified
    if [[ -n "$SERVERS_FILE" || -n "$REMOTE_HOST" ]]; then
        if [[ -n "$SERVERS_FILE" ]]; then
            [[ ! -f "$SERVERS_FILE" ]] && die "Servers file not found: $SERVERS_FILE"
        fi

        prompt_sudo_pass

        local fp_script
        fp_script="$(cat << REMOTE_SCRIPT
#!/bin/bash
INSTANCES_DIR="$INSTANCES_DIR"
DATA_DIR="$DATA_DIR"
$REMOTE_SUDO_BLOCK

for name in \$(ls "\$INSTANCES_DIR" 2>/dev/null | sort); do
    fp_file="\$DATA_DIR/\$name/fingerprint"
    if \$SUDO test -f "\$fp_file" 2>/dev/null; then
        fp=\$(\$SUDO cat "\$fp_file" 2>/dev/null | awk '{print \$2}')
        [ -n "\$fp" ] && echo "FP:\$fp"
    fi
done
REMOTE_SCRIPT
)"
        fp_script=$(inject_sudo_pass "$fp_script")

        # Build server list from --remote or --servers
        local servers=()
        if [[ -n "$REMOTE_HOST" ]]; then
            servers+=("$REMOTE_HOST")
        else
            while IFS= read -r line; do
                servers+=("$line")
            done < <(read_servers_file "$SERVERS_FILE")
        fi

        log_info "Remote servers: ${#servers[@]}"
        for entry in "${servers[@]}"; do
            parse_server_line "$entry" || continue
            log_verbose "Collecting from $_SSH_HOST..."

            local result run_func
            if [[ -n "$REMOTE_HOST" && ${#servers[@]} -eq 1 ]]; then
                run_func="run_remote_interactive"
            else
                run_func="run_remote_batch"
            fi

            result=$($run_func "$fp_script" 2>&1) || {
                log_warn "Failed to collect from $_SSH_HOST"
                continue
            }

            while IFS= read -r fpline; do
                if [[ "$fpline" == FP:* ]]; then
                    local fp="${fpline#FP:}"
                    all_fps+=("\$$fp")
                fi
            done <<< "$result"
        done
    fi

    [[ ${#all_fps[@]} -eq 0 ]] && die "No fingerprints collected"

    # Deduplicate
    local unique_fps
    unique_fps=$(printf '%s\n' "${all_fps[@]}" | sort -u)
    local count
    count=$(echo "$unique_fps" | wc -l)

    local myfamily_value
    myfamily_value=$(echo "$unique_fps" | tr '\n' ',' | sed 's/,$//')
    local myfamily_line="MyFamily $myfamily_value"

    log_success "Collected $count unique fingerprints"
    echo ""

    if [[ -n "$OUTPUT_FILE" ]]; then
        echo "$myfamily_line" > "$OUTPUT_FILE"
        log_success "Written to: $OUTPUT_FILE"
    else
        echo "$myfamily_line"
    fi

    echo ""
    log_info "Deploy with:"
    echo "  $0 deploy-myfamily --myfamily \"$myfamily_value\""
    echo "  $0 deploy-myfamily-remote --myfamily \"$myfamily_value\" --servers servers.txt"
}

# ── Command: deploy-myfamily (local) ─────────────────────────────────────────

cmd_deploy_myfamily() {
    log_header "Deploy MyFamily (Local)"

    ensure_privilege

    [[ -z "$MYFAMILY_LINE" ]] && die "Missing --myfamily: the MyFamily value (e.g., \"\\\$FP1,\\\$FP2,...\")"
    [[ ! -d "$INSTANCES_DIR" ]] && die "Instances directory not found: $INSTANCES_DIR"

    local instances
    mapfile -t instances < <(list_local_instances)
    [[ ${#instances[@]} -eq 0 ]] && die "No relay instances found in $INSTANCES_DIR"

    local full_line="MyFamily $MYFAMILY_LINE"
    log_info "Instances: ${#instances[@]}"
    log_verbose "MyFamily: ${full_line:0:80}..."
    echo ""

    # Detect shared torrc
    local shared_torrc
    shared_torrc=$(detect_shared_torrc)

    if [[ -n "$shared_torrc" ]]; then
        log_info "Shared torrc detected: $shared_torrc"
        if ! $DRY_RUN; then
            update_torrc_myfamily "$shared_torrc" "$full_line"
            log_success "Updated MyFamily in $shared_torrc"
        else
            log_info "[dry-run] Would update MyFamily in $shared_torrc"
        fi
    else
        local updated=0
        for name in "${instances[@]}"; do
            local torrc="$INSTANCES_DIR/$name/torrc"
            echo -n "  $name: "
            if $DRY_RUN; then
                echo "[dry-run] would update MyFamily"
                updated=$((updated + 1))
                continue
            fi
            update_torrc_myfamily "$torrc" "$full_line"
            echo -e "${GREEN}updated${NC}"
            updated=$((updated + 1))
        done
        echo ""
        log_success "Updated $updated/${#instances[@]} instances"
    fi

    # Reload
    if ! $NO_RELOAD && ! $DRY_RUN; then
        echo ""
        log_info "Reloading Tor instances..."
        reload_instances "${instances[@]}"
    fi
}

# ── Command: deploy-myfamily-remote ──────────────────────────────────────────

cmd_deploy_myfamily_remote() {
    log_header "Deploy MyFamily (Remote)"

    [[ -z "$MYFAMILY_LINE" ]] && die "Missing --myfamily: the MyFamily value"
    [[ -z "$SERVERS_FILE" && -z "$REMOTE_HOST" ]] && \
        die "Missing --servers or --remote: specify target server(s)"

    prompt_sudo_pass

    local full_line="MyFamily $MYFAMILY_LINE"

    local myfamily_script
    myfamily_script="$(cat << REMOTE_SCRIPT
#!/bin/bash
set -euo pipefail
INSTANCES_DIR="$INSTANCES_DIR"
DATA_DIR="$DATA_DIR"
NO_RELOAD="$NO_RELOAD"
MYFAMILY_LINE='$full_line'
$REMOTE_SUDO_BLOCK
$REMOTE_DETECT_SHARED_TORRC

instances=\$(ls "\$INSTANCES_DIR" 2>/dev/null | sort)
[ -z "\$instances" ] && { echo "ERROR:No instances"; exit 1; }

shared_torrc=\$(detect_shared_torrc)

if [ -n "\$shared_torrc" ]; then
    if \$SUDO grep -q "^MyFamily " "\$shared_torrc" 2>/dev/null; then
        \$SUDO sed -i "s|^MyFamily .*|\$MYFAMILY_LINE|" "\$shared_torrc"
    else
        echo "\$MYFAMILY_LINE" | \$SUDO tee -a "\$shared_torrc" > /dev/null
    fi
else
    for name in \$instances; do
        torrc="\$INSTANCES_DIR/\$name/torrc"
        if \$SUDO grep -q "^MyFamily " "\$torrc" 2>/dev/null; then
            \$SUDO sed -i "s|^MyFamily .*|\$MYFAMILY_LINE|" "\$torrc"
        else
            if \$SUDO grep -q "^%include" "\$torrc" 2>/dev/null; then
                \$SUDO sed -i "/^%include/i \$MYFAMILY_LINE" "\$torrc"
            else
                echo "\$MYFAMILY_LINE" | \$SUDO tee -a "\$torrc" > /dev/null
            fi
        fi
    done
fi

updated=\$(echo \$instances | wc -w)
echo "UPDATED:\$updated"

if [ "\$NO_RELOAD" != "true" ]; then
    services=""
    for name in \$instances; do
        if \$SUDO systemctl is-active --quiet "tor@\$name.service" 2>/dev/null; then
            services="\$services tor@\$name.service"
        fi
    done
    if [ -n "\$services" ]; then
        \$SUDO systemctl reload \$services 2>/dev/null || \$SUDO systemctl restart \$services 2>/dev/null || true
        reloaded=\$(echo \$services | wc -w)
    else
        reloaded=0
    fi
    echo "RELOADED:\$reloaded"
fi
REMOTE_SCRIPT
)"
    myfamily_script=$(inject_sudo_pass "$myfamily_script")

    # Collect servers
    local servers=()
    if [[ -n "$REMOTE_HOST" ]]; then
        servers+=("$REMOTE_HOST")
    else
        while IFS= read -r line; do
            servers+=("$line")
        done < <(read_servers_file "$SERVERS_FILE")
    fi

    log_info "Servers: ${#servers[@]}"
    echo ""

    local success=0 fail=0
    for entry in "${servers[@]}"; do
        parse_server_line "$entry" || continue
        echo -n "  $_SSH_HOST: "

        if $DRY_RUN; then
            echo "[dry-run] would update MyFamily"
            success=$((success + 1))
            continue
        fi

        local result run_func
        if [[ -n "$REMOTE_HOST" && ${#servers[@]} -eq 1 ]]; then
            run_func="run_remote_interactive"
        else
            run_func="run_remote_batch"
        fi

        result=$($run_func "$myfamily_script" 2>&1) || {
            echo -e "${RED}FAILED${NC}"
            fail=$((fail + 1))
            continue
        }

        local updated reloaded
        updated=$(parse_kv "$result" "UPDATED")
        reloaded=$(parse_kv "$result" "RELOADED")
        echo -e "${GREEN}OK${NC} (${updated:-0} instances, ${reloaded:-?} reloaded)"
        success=$((success + 1))
    done

    echo ""
    log_success "Done: $success/${#servers[@]} servers succeeded"
    [[ $fail -gt 0 ]] && log_warn "$fail server(s) failed"
}

# ── Command: remove (local) ──────────────────────────────────────────────────

cmd_remove() {
    log_header "Remove Family Configuration (Local)"

    ensure_privilege

    [[ ! -d "$INSTANCES_DIR" ]] && die "Instances directory not found: $INSTANCES_DIR"

    local instances
    mapfile -t instances < <(list_local_instances)
    [[ ${#instances[@]} -eq 0 ]] && die "No relay instances found in $INSTANCES_DIR"

    log_info "Instances: ${#instances[@]}"

    # Detect and clean shared torrc
    local shared_torrc
    shared_torrc=$(detect_shared_torrc)

    if [[ -n "$shared_torrc" ]]; then
        log_info "Shared torrc detected: $shared_torrc"
    fi
    echo ""

    if [[ -n "$shared_torrc" ]] && ! $DRY_RUN; then
        local shared_changes=false
        if $SUDO grep -q "^FamilyId " "$shared_torrc" 2>/dev/null; then
            $SUDO sed -i '/^FamilyId /d' "$shared_torrc"
            shared_changes=true
        fi
        if $SUDO grep -q "^MyFamily " "$shared_torrc" 2>/dev/null; then
            $SUDO sed -i '/^MyFamily /d' "$shared_torrc"
            shared_changes=true
        fi
        $shared_changes && log_success "Removed family config from $shared_torrc"
    fi

    local removed=0
    for name in "${instances[@]}"; do
        echo -n "  $name: "

        local torrc="$INSTANCES_DIR/$name/torrc"
        local key_dir="$DATA_DIR/$name/keys"
        local changes=false

        if $DRY_RUN; then
            echo "[dry-run] would remove family config"
            removed=$((removed + 1))
            continue
        fi

        # Remove from per-instance torrc
        if $SUDO grep -q "^FamilyId " "$torrc" 2>/dev/null; then
            $SUDO sed -i '/^FamilyId /d' "$torrc"
            changes=true
        fi
        if $SUDO grep -q "^MyFamily " "$torrc" 2>/dev/null; then
            $SUDO sed -i '/^MyFamily /d' "$torrc"
            changes=true
        fi

        # Remove key files
        if $SUDO test -d "$key_dir" 2>/dev/null; then
            local key_files
            key_files=$($SUDO find "$key_dir" -name "*.secret_family_key" 2>/dev/null || true)
            if [[ -n "$key_files" ]]; then
                echo "$key_files" | while read -r kf; do
                    $SUDO rm -f "$kf"
                done
                changes=true
            fi
        fi

        if $changes; then
            echo -e "${GREEN}removed${NC}"
            removed=$((removed + 1))
        else
            echo "nothing to remove"
        fi
    done

    echo ""
    log_success "Cleaned $removed/${#instances[@]} instances"

    # Reload
    if ! $NO_RELOAD && ! $DRY_RUN && [[ $removed -gt 0 ]]; then
        log_info "Reloading Tor instances..."
        reload_instances "${instances[@]}"
    fi
}

# ── Command: remove-remote ───────────────────────────────────────────────────

cmd_remove_remote() {
    log_header "Remove Family Configuration (Remote)"

    [[ -z "$SERVERS_FILE" && -z "$REMOTE_HOST" ]] && \
        die "Missing --servers or --remote: specify target server(s)"

    prompt_sudo_pass

    local remove_script
    remove_script="$(cat << REMOTE_SCRIPT
#!/bin/bash
set -euo pipefail
INSTANCES_DIR="$INSTANCES_DIR"
DATA_DIR="$DATA_DIR"
NO_RELOAD="$NO_RELOAD"
$REMOTE_SUDO_BLOCK
$REMOTE_DETECT_SHARED_TORRC

instances=\$(ls "\$INSTANCES_DIR" 2>/dev/null | sort)
[ -z "\$instances" ] && { echo "NO_INSTANCES"; exit 0; }

# Remove from shared torrc
shared_torrc=\$(detect_shared_torrc)
if [ -n "\$shared_torrc" ]; then
    \$SUDO sed -i '/^FamilyId /d' "\$shared_torrc" 2>/dev/null || true
    \$SUDO sed -i '/^MyFamily /d' "\$shared_torrc" 2>/dev/null || true
fi

removed=0
for name in \$instances; do
    torrc="\$INSTANCES_DIR/\$name/torrc"
    key_dir="\$DATA_DIR/\$name/keys"

    \$SUDO sed -i '/^FamilyId /d' "\$torrc" 2>/dev/null || true
    \$SUDO sed -i '/^MyFamily /d' "\$torrc" 2>/dev/null || true
    \$SUDO find "\$key_dir" -name "*.secret_family_key" -exec \$SUDO rm -f {} \; 2>/dev/null || true
    removed=\$((removed + 1))
done

echo "REMOVED:\$removed"

if [ "\$NO_RELOAD" != "true" ]; then
    services=""
    for name in \$instances; do
        if \$SUDO systemctl is-active --quiet "tor@\$name.service" 2>/dev/null; then
            services="\$services tor@\$name.service"
        fi
    done
    if [ -n "\$services" ]; then
        \$SUDO systemctl reload \$services 2>/dev/null || \$SUDO systemctl restart \$services 2>/dev/null || true
        reloaded=\$(echo \$services | wc -w)
    else
        reloaded=0
    fi
    echo "RELOADED:\$reloaded"
fi
REMOTE_SCRIPT
)"
    remove_script=$(inject_sudo_pass "$remove_script")

    # Collect servers
    local servers=()
    if [[ -n "$REMOTE_HOST" ]]; then
        servers+=("$REMOTE_HOST")
    else
        while IFS= read -r line; do
            servers+=("$line")
        done < <(read_servers_file "$SERVERS_FILE")
    fi

    log_info "Servers: ${#servers[@]}"
    echo ""

    local success=0 fail=0
    for entry in "${servers[@]}"; do
        parse_server_line "$entry" || continue
        echo -n "  $_SSH_HOST: "

        if $DRY_RUN; then
            echo "[dry-run] would remove family config"
            success=$((success + 1))
            continue
        fi

        local result run_func
        if [[ -n "$REMOTE_HOST" && ${#servers[@]} -eq 1 ]]; then
            run_func="run_remote_interactive"
        else
            run_func="run_remote_batch"
        fi

        result=$($run_func "$remove_script" 2>&1) || {
            echo -e "${RED}FAILED${NC}"
            fail=$((fail + 1))
            continue
        }

        if echo "$result" | grep -q "NO_INSTANCES"; then
            echo "no instances"
            continue
        fi

        local removed reloaded
        removed=$(parse_kv "$result" "REMOVED")
        reloaded=$(parse_kv "$result" "RELOADED")
        echo -e "${GREEN}OK${NC} (${removed:-0} instances cleaned, ${reloaded:-?} reloaded)"
        success=$((success + 1))
    done

    echo ""
    log_success "Done: $success/${#servers[@]} servers succeeded"
    [[ $fail -gt 0 ]] && log_warn "$fail server(s) failed"
}

# ── Main ─────────────────────────────────────────────────────────────────────

parse_args "$@"

case "$COMMAND" in
    generate)               cmd_generate ;;
    import-key)             cmd_import_key ;;
    import-key-remote)      cmd_import_key_remote ;;
    deploy)                 cmd_deploy ;;
    deploy-remote)          cmd_deploy_remote ;;
    status)                 cmd_status ;;
    status-remote)          cmd_status_remote ;;
    collect-fingerprints)   cmd_collect_fingerprints ;;
    deploy-myfamily)        cmd_deploy_myfamily ;;
    deploy-myfamily-remote) cmd_deploy_myfamily_remote ;;
    remove)                 cmd_remove ;;
    remove-remote)          cmd_remove_remote ;;
    help|--help|-h)         show_usage ;;
    *)                      die "Unknown command: $COMMAND (try --help)" ;;
esac
