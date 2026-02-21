#!/bin/bash
# check_happy_family_keys.sh - Check Tor "Happy Families" (Proposal 321) deployment status
#
# Checks:
# 1. Directory authority versions and consensus method support
# 2. Current consensus method (need method 35 for family-ids in microdescriptors)
# 3. family-cert entries in server descriptors
# 4. family-ids entries in microdescriptors
#
# Reference: https://spec.torproject.org/proposals/321-happy-families.html
# Consensus method selection requires >2/3 of authorities to support the method.
# With 9 authorities, that means at least 7 must support method 35.

set -euo pipefail

COLLECTOR_BASE="https://collector.torproject.org/recent/relay-descriptors"

# Temp directory for downloaded data
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Check dependencies
for cmd in curl python3 bc; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: $cmd is required but not installed." >&2
        exit 1
    fi
done

echo -e "${BOLD}=== Tor Happy Family Key Deployment Status ===${NC}"
echo -e "${BLUE}Proposal 321: https://spec.torproject.org/proposals/321-happy-families.html${NC}"
echo ""

# --- Step 1: Get latest consensus ---
echo -e "${BOLD}[1/5] Fetching latest consensus...${NC}"
curl -sf "${COLLECTOR_BASE}/consensuses/" > "$TMPDIR/consensus_index.html" 2>/dev/null
LATEST_CONSENSUS=$(grep -oP '\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}-consensus' "$TMPDIR/consensus_index.html" | tail -1)

if [ -z "$LATEST_CONSENSUS" ]; then
    echo -e "${RED}ERROR: Could not find latest consensus file${NC}"
    exit 1
fi

echo "  Latest consensus: $LATEST_CONSENSUS"
curl -sf "${COLLECTOR_BASE}/consensuses/${LATEST_CONSENSUS}" > "$TMPDIR/consensus.txt" 2>/dev/null

CONSENSUS_METHOD=$(grep "^consensus-method " "$TMPDIR/consensus.txt" | awk '{print $2}')
echo -e "  Consensus method: ${BOLD}${CONSENSUS_METHOD}${NC}"

if [ "$CONSENSUS_METHOD" -ge 35 ] 2>/dev/null; then
    echo -e "  ${GREEN}✓ Method 35+ active - family-ids will appear in microdescriptors${NC}"
else
    echo -e "  ${YELLOW}✗ Method <35 - family-ids NOT yet in microdescriptors (need method 35)${NC}"
fi

# --- Step 2: Check directory authority versions ---
echo ""
echo -e "${BOLD}[2/5] Checking directory authority versions...${NC}"
echo -e "  ${BLUE}Consensus method selection requires >2/3 authority support (~7 of 9)${NC}"
echo ""

# Parse authority fingerprints from consensus
grep "^dir-source " "$TMPDIR/consensus.txt" | awk '{print $2, $3}' > "$TMPDIR/auth_fps.txt"

# Get the vote file listing
curl -sf "${COLLECTOR_BASE}/votes/" > "$TMPDIR/vote_index.html" 2>/dev/null
LATEST_VOTE_PREFIX=$(echo "$LATEST_CONSENSUS" | sed 's/-consensus//')

SUPPORTS_35=0
TOTAL_AUTHS=0

echo "  Authority          | Version     | Methods        | Supports 35?"
echo "  -------------------|-------------|----------------|-------------"

while IFS=' ' read -r name fp; do
    TOTAL_AUTHS=$((TOTAL_AUTHS + 1))

    # Find the vote file for this authority
    VOTE_FILE=$(grep -oP "${LATEST_VOTE_PREFIX}-vote-${fp}-[A-F0-9]+" "$TMPDIR/vote_index.html" | head -1 || true)

    if [ -z "$VOTE_FILE" ]; then
        printf "  %-18s | %-11s | %-14s | %b\n" "$name" "(no vote)" "N/A" "${RED}?${NC}"
        continue
    fi

    # Get just the header of the vote
    # Use --range to download only the first 2KB instead of piping through head
    # (piping curl|head causes SIGPIPE errors with pipefail)
    VOTE_HEADER=$(curl -sf --range 0-2047 "${COLLECTOR_BASE}/votes/${VOTE_FILE}" 2>/dev/null || true)
    METHODS=$(echo "$VOTE_HEADER" | grep "^consensus-methods " | sed 's/consensus-methods //')
    HIGHEST_METHOD=$(echo "$METHODS" | tr ' ' '\n' | sort -n | tail -1)

    SUPPORTS=""
    if echo "$METHODS" | grep -qw "35"; then
        SUPPORTS="${GREEN}YES${NC}"
        SUPPORTS_35=$((SUPPORTS_35 + 1))
    else
        SUPPORTS="${RED}NO${NC}"
    fi

    # Determine version from highest method
    if [ "$HIGHEST_METHOD" -ge 34 ] 2>/dev/null; then
        VERSION="0.4.9.x"
    else
        VERSION="0.4.8.x"
    fi

    printf "  %-18s | %-11s | %-14s | %b\n" "$name" "$VERSION" "$METHODS" "$SUPPORTS"
done < "$TMPDIR/auth_fps.txt"

echo ""
echo -e "  Authorities supporting method 35: ${BOLD}${SUPPORTS_35}/${TOTAL_AUTHS}${NC}"

NEEDED=$((TOTAL_AUTHS * 2 / 3 + 1))
if [ "$SUPPORTS_35" -ge "$NEEDED" ]; then
    echo -e "  ${GREEN}✓ Threshold met (>2/3 = need $NEEDED of $TOTAL_AUTHS)${NC}"
else
    REMAINING=$((NEEDED - SUPPORTS_35))
    echo -e "  ${YELLOW}✗ Need $NEEDED of $TOTAL_AUTHS (>2/3) - ${REMAINING} more authority upgrade(s) needed${NC}"
fi

# --- Step 3: Check server descriptors for family-cert ---
echo ""
echo -e "${BOLD}[3/5] Checking server descriptors for family-cert entries...${NC}"

curl -sf "${COLLECTOR_BASE}/server-descriptors/" > "$TMPDIR/sd_index.html" 2>/dev/null
LATEST_SD=$(grep -oP '\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}-server-descriptors' "$TMPDIR/sd_index.html" | tail -1)

if [ -z "$LATEST_SD" ]; then
    echo -e "  ${RED}ERROR: Could not find latest server descriptor file${NC}"
    FAMILY_CERT_COUNT=0
else
    echo "  Latest batch: $LATEST_SD"
    curl -sf "${COLLECTOR_BASE}/server-descriptors/${LATEST_SD}" > "$TMPDIR/server-descriptors.txt" 2>/dev/null

    FAMILY_CERT_COUNT=$(grep -c "^family-cert$" "$TMPDIR/server-descriptors.txt" || true)
    TOTAL_DESCS=$(grep -c "^router " "$TMPDIR/server-descriptors.txt" || true)

    echo -e "  Descriptors in batch: ${TOTAL_DESCS}"
    echo -e "  Descriptors with family-cert: ${BOLD}${FAMILY_CERT_COUNT}${NC}"

    if [ "$FAMILY_CERT_COUNT" -gt 0 ]; then
        echo -e "  ${GREEN}✓ family-cert entries ARE present in server descriptors${NC}"

        # Break down by operator
        echo ""
        echo -e "  ${BOLD}Top operators using family-cert:${NC}"
        python3 - "$TMPDIR/server-descriptors.txt" << 'PYEOF'
import sys
with open(sys.argv[1], 'r') as f:
    text = f.read()
parts = text.split('\nrouter ')
operators = {}
for part in parts[1:]:
    if 'family-cert' not in part:
        continue
    contact = ''
    for line in part.split('\n'):
        if line.startswith('contact'):
            contact = line[8:].strip()[:60]
            break
    if not contact:
        contact = '(no contact)'
    operators[contact] = operators.get(contact, 0) + 1

for op, count in sorted(operators.items(), key=lambda x: -x[1])[:10]:
    is_1aeo = '1aeo' in op.lower()
    marker = ' <-- 1aeo.com' if is_1aeo else ''
    print(f'    {count:4d} relays: {op}{marker}')
PYEOF
    else
        echo -e "  ${YELLOW}✗ No family-cert entries found in this batch${NC}"
    fi
fi

# --- Step 4: Check microdescriptors for family-ids ---
echo ""
echo -e "${BOLD}[4/5] Checking microdescriptors for family-ids entries...${NC}"

curl -sf "${COLLECTOR_BASE}/microdescs/micro/" > "$TMPDIR/micro_index.html" 2>/dev/null
LATEST_MICRO=$(grep -oP '\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}-micro-\d{4}-\d{2}' "$TMPDIR/micro_index.html" | tail -1)

FAMILY_IDS_COUNT=0
if [ -z "$LATEST_MICRO" ]; then
    echo -e "  ${RED}ERROR: Could not find latest microdescriptor file${NC}"
else
    echo "  Latest batch: $LATEST_MICRO"
    curl -sf "${COLLECTOR_BASE}/microdescs/micro/${LATEST_MICRO}" > "$TMPDIR/microdescriptors.txt" 2>/dev/null

    FAMILY_IDS_COUNT=$(grep -c "^family-ids " "$TMPDIR/microdescriptors.txt" || true)
    TOTAL_MICROS=$(grep -c "^onion-key$" "$TMPDIR/microdescriptors.txt" || true)

    echo -e "  Microdescriptors in batch: ${TOTAL_MICROS}"
    echo -e "  Microdescriptors with family-ids: ${BOLD}${FAMILY_IDS_COUNT}${NC}"

    if [ "$FAMILY_IDS_COUNT" -gt 0 ]; then
        echo -e "  ${GREEN}✓ family-ids entries ARE present in microdescriptors${NC}"
    else
        echo -e "  ${YELLOW}✗ No family-ids entries yet (requires consensus method 35)${NC}"
    fi
fi

# --- Step 5: Check Desc=4 protocol support ---
echo ""
echo -e "${BOLD}[5/5] Checking Desc=4 subprotocol support (family-cert capable relays)...${NC}"

# Count relays advertising Desc version ranges that include 4
DESC4_COUNT=$(grep -cP "Desc=\S*4" "$TMPDIR/consensus.txt" || true)
TOTAL_RELAYS=$(grep -c "^r " "$TMPDIR/consensus.txt" || true)

echo -e "  Total relays in consensus: ${TOTAL_RELAYS}"
if [ "$TOTAL_RELAYS" -gt 0 ]; then
    PCT=$(echo "scale=1; $DESC4_COUNT * 100 / $TOTAL_RELAYS" | bc)
    echo -e "  Relays advertising Desc=4: ${BOLD}${DESC4_COUNT}${NC} (${PCT}%)"
fi

# --- Summary ---
echo ""
echo -e "${BOLD}=== Summary ===${NC}"
echo ""
echo "  Proposal 321 Happy Families deployment status:"
echo ""

if [ "$FAMILY_CERT_COUNT" -gt 0 ] 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Server descriptors: family-cert entries present (${FAMILY_CERT_COUNT} in latest batch)"
else
    echo -e "  ${RED}✗${NC} Server descriptors: no family-cert entries"
fi

if [ "$FAMILY_IDS_COUNT" -gt 0 ] 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Microdescriptors: family-ids entries present"
else
    echo -e "  ${YELLOW}✗${NC} Microdescriptors: no family-ids entries yet"
fi

echo -e "  Consensus method: ${CONSENSUS_METHOD} (need 35 for family-ids in microdescriptors)"
echo -e "  Authority support for method 35: ${SUPPORTS_35}/${TOTAL_AUTHS} (need >2/3 = ${NEEDED})"

if [ "$SUPPORTS_35" -ge "$NEEDED" ] 2>/dev/null && [ "${CONSENSUS_METHOD}" -ge 35 ] 2>/dev/null; then
    echo ""
    echo -e "  ${GREEN}${BOLD}FULLY DEPLOYED: Happy family keys are active in consensus${NC}"
elif [ "$FAMILY_CERT_COUNT" -gt 0 ] 2>/dev/null; then
    echo ""
    echo -e "  ${YELLOW}${BOLD}PARTIALLY DEPLOYED: Relays publish family-cert but consensus method 35 not yet active${NC}"
    echo -e "  ${YELLOW}Relays with family-cert can be identified via server descriptors.${NC}"
    echo -e "  ${YELLOW}Clients on 0.4.9.x will use family-cert from server descriptors directly.${NC}"
    echo -e "  ${YELLOW}family-ids in microdescriptors requires ${REMAINING} more authority upgrade(s) to 0.4.9.x${NC}"
else
    echo ""
    echo -e "  ${RED}${BOLD}NOT YET DEPLOYED: No family-cert entries found${NC}"
fi

echo ""
