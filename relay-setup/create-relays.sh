#!/bin/bash
set -e -u
RED='\033[0;31m' GREEN='\033[0;32m' YELLOW='\033[1;33m' CYAN='\033[0;36m' NC='\033[0m'

# Defaults
CONFIG_FILE="relay-config.csv"
TORRC_ALL="/etc/tor/torrc.all"
HASHED_PASSWORD=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse command-line arguments
show_usage() {
    cat << EOF
Usage: sudo $0 [OPTIONS]

Options:
  -p, --password <hash>    HashedControlPassword (generate with: tor --hash-password YourPassword)
  -t, --torrc <path>       Path to shared torrc.all file (default: /etc/tor/torrc.all)
  -h, --help               Show this help message

Examples:
  sudo $0 --password "16:ABC..." --torrc /path/to/torrc.all
  sudo $0 -p "16:ABC..."
  sudo $0  (interactive mode)

Generate password hash:
  tor --hash-password YourPasswordHere
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -p|--password)
            HASHED_PASSWORD="$2"
            shift 2
            ;;
        -t|--torrc)
            TORRC_ALL="$2"
            shift 2
            ;;
        -h|--help)
            show_usage
            ;;
        *)
            echo -e "${RED}ERROR: Unknown option: $1${NC}"
            show_usage
            ;;
    esac
done

# Check requirements
[ "$EUID" -ne 0 ] && { echo -e "${RED}ERROR: Run with sudo${NC}"; exit 1; }
[ ! -f "$SCRIPT_DIR/$CONFIG_FILE" ] && { echo -e "${RED}ERROR: $CONFIG_FILE not found${NC}"; exit 1; }
[ ! -f "$TORRC_ALL" ] && { echo -e "${RED}ERROR: $TORRC_ALL not found${NC}"; exit 1; }
command -v tor &>/dev/null || { echo -e "${RED}ERROR: Tor not installed${NC}"; exit 1; }

# Prompt for password if not provided
if [ -z "$HASHED_PASSWORD" ]; then
    echo -e "${YELLOW}No password provided. Generate one with:${NC}"
    echo "  tor --hash-password YourPasswordHere"
    echo ""
    read -p "Enter HashedControlPassword (or press Enter to skip ControlPort): " HASHED_PASSWORD
    [ -z "$HASHED_PASSWORD" ] && echo -e "${YELLOW}WARNING: ControlPort will not be configured${NC}"
fi

echo -e "${CYAN}Tor Relay Creation${NC}\n"

command -v tor-instance-create &>/dev/null && echo -e "${GREEN}✓ tor-instance-create found${NC}" || echo -e "${YELLOW}⚠ Manual mode${NC}"
HAS_TOR_INSTANCE_CREATE=$?

# [1/5] Setup directories
echo -e "\n${GREEN}[1/5] Directories${NC}"
mkdir -p /etc/tor/instances /var/lib/tor-instances
cmp -s "$TORRC_ALL" /etc/tor/torrc.all || cp "$TORRC_ALL" /etc/tor/torrc.all
echo "  ✓ Ready"

# [2/5] Validate CSV
echo -e "${GREEN}[2/5] Validating CSV${NC}"
declare -a seen_nicks=() seen_ips=()
errors=0 line=0 relay=0

while IFS=',' read -r nick lan wan or ctl met; do
    line=$((line + 1))
    [[ "$nick" =~ ^#.*$ ]] || [ -z "$nick" ] && continue
    
    nick=$(echo "$nick" | xargs)
    wan=$(echo "$wan" | xargs)
    or=$(echo "$or" | xargs)
    ctl=$(echo "$ctl" | xargs)
    met=$(echo "$met" | xargs)
    
    if [ $relay -eq 0 ]; then
        [ -z "$nick" ] || [ -z "$wan" ] || [ -z "$or" ] || [ -z "$ctl" ] || [ -z "$met" ] && \
            { echo -e "  ${RED}✗ Line $line: First relay needs all fields${NC}"; errors=$((errors + 1)); }
    else
        [ -z "$nick" ] || [ -z "$wan" ] && \
            { echo -e "  ${RED}✗ Line $line: Need nickname, wan_ip${NC}"; errors=$((errors + 1)); }
    fi
    
    [[ " ${seen_nicks[@]} " =~ " $nick " ]] && \
        { echo -e "  ${RED}✗ Line $line: Duplicate nick '$nick'${NC}"; errors=$((errors + 1)); }
    seen_nicks+=("$nick")
    
    [[ " ${seen_ips[@]} " =~ " $wan " ]] && \
        echo -e "  ${YELLOW}⚠ Line $line: Duplicate IP '$wan'${NC}"
    seen_ips+=("$wan")
    
    relay=$((relay + 1))
done < "$SCRIPT_DIR/$CONFIG_FILE"

[ $errors -gt 0 ] && { echo -e "  ${RED}$errors error(s)${NC}"; exit 1; }
echo -e "  ${GREEN}✓ $relay relays validated${NC}"

# [3/5] Parse CSV
echo -e "${GREEN}[3/5] Reading config${NC}"
declare -a NICKS=() LANS=() WANS=() ORS=() CTLS=() METS=()
DEF_OR="" DEF_CTL="" DEF_MET=""
line=0 idx=0

while IFS=',' read -r nick lan wan or ctl met; do
    line=$((line + 1))
    [[ "$nick" =~ ^#.*$ ]] || [ -z "$nick" ] && continue
    
    nick=$(echo "$nick" | xargs)
    lan=$(echo "$lan" | xargs)
    wan=$(echo "$wan" | xargs)
    or=$(echo "$or" | xargs)
    ctl=$(echo "$ctl" | xargs)
    met=$(echo "$met" | xargs)
    
    if [ $idx -eq 0 ]; then
        DEF_OR="$or" DEF_CTL="$ctl" DEF_MET="$met"
    else
        [ -z "$or" ] && or="$DEF_OR"
        [ -z "$ctl" ] && ctl=$((DEF_CTL + idx))
        [ -z "$met" ] && met=$((DEF_MET + idx))
    fi
    
    NICKS+=("$nick") LANS+=("$lan") WANS+=("$wan") ORS+=("$or") CTLS+=("$ctl") METS+=("$met")
    idx=$((idx + 1))
done < "$SCRIPT_DIR/$CONFIG_FILE"

echo "  ✓ ${#NICKS[@]} relays"

# [4/5] Create relays
echo -e "${GREEN}[4/5] Creating relays${NC}"
for i in "${!NICKS[@]}"; do
    n="${NICKS[$i]}" l="${LANS[$i]}" w="${WANS[$i]}" o="${ORS[$i]}" c="${CTLS[$i]}" m="${METS[$i]}"
    echo "  [$((i + 1))/${#NICKS[@]}] $n"
    
    id "_tor-$n" &>/dev/null || useradd --system --no-create-home --shell /bin/false "_tor-$n"
    
    idir="/etc/tor/instances/$n"
    mkdir -p "$idir"
    
    cat > "$idir/torrc" << EOF
# $n - $(date +%F)
EOF
    
    if [ -n "$HASHED_PASSWORD" ]; then
        cat >> "$idir/torrc" << EOF
ControlPort 127.0.0.1:$c
HashedControlPassword $HASHED_PASSWORD
EOF
    fi
    
    cat >> "$idir/torrc" << EOF
EOF
    
    if [ -n "$l" ]; then
        cat >> "$idir/torrc" << EOF
ORPort $w:$o NoListen
ORPort $l:$o NoAdvertise
Address $w
OutboundBindAddress $l
EOF
    else
        cat >> "$idir/torrc" << EOF
ORPort $w:$o
Address $w
EOF
    fi
    
    cat >> "$idir/torrc" << EOF
Nickname $n
MetricsPort 127.0.0.1:$m
%include /etc/tor/torrc.all
EOF
    
    chown -R "_tor-$n:_tor-$n" "$idir"
    chmod 755 "$idir"; chmod 644 "$idir/torrc"
    
    ddir="/var/lib/tor-instances/$n"
    mkdir -p "$ddir"
    chown "_tor-$n:_tor-$n" "$ddir"
    chmod 2700 "$ddir"
    
    if [ $HAS_TOR_INSTANCE_CREATE -ne 0 ]; then
        odir="/etc/systemd/system/tor@$n.service.d"
        mkdir -p "$odir"
        cat > "$odir/override.conf" << EOF
[Service]
User=_tor-$n
Group=_tor-$n
Type=notify
ExecStart=
ExecStart=/usr/bin/tor --defaults-torrc /usr/share/tor/tor-service-defaults-torrc -f $idir/torrc
EOF
    fi
done

[ $HAS_TOR_INSTANCE_CREATE -ne 0 ] && systemctl daemon-reload

# [5/5] Start services
echo -e "${GREEN}[5/5] Starting services${NC}"
for n in "${NICKS[@]}"; do
    systemctl enable "tor@$n.service" 2>&1 | grep -v "Created symlink" || true
    systemctl is-active --quiet "tor@$n.service" || systemctl start "tor@$n.service"
done

sleep 3
RUNNING=$(echo "${NICKS[@]}" | xargs -n1 | xargs -I{} systemctl is-active --quiet "tor@{}.service" && echo 1 || true | wc -l)

echo -e "\n${CYAN}Complete!${NC}"
echo "Relays: ${#NICKS[@]}"
echo "Running: $RUNNING/${#NICKS[@]}"
[ $RUNNING -eq ${#NICKS[@]} ] && echo -e "${GREEN}✓ All running${NC}" || echo -e "${YELLOW}⚠ Check logs${NC}"
echo -e "\nNext: ./verify-relays.sh"
