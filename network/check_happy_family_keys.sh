#!/bin/bash
# check_happy_family_keys.sh - Check Tor "Happy Families" (Proposal 321) deployment status
#
# Checks:
# 1. Consensus method and directory authority support for method 35
# 2. family-cert entries in server descriptors (sampled from CollecTor hourly batches)
# 3. family-ids entries in microdescriptors
# 4. Desc=4 subprotocol support (family-cert capable relays) in consensus
# 5. Operator-specific family status via Onionoo API (complete, not sampled)
#
# Data sources:
#   CollecTor server-descriptors: hourly batches containing only descriptors published
#     in that hour (~1,300 of ~8,000 relays per batch). Used to verify family-cert
#     presence but NOT for counting -- a single batch is a sample, not the full network.
#   Onionoo API: complete view of all relays, including effective_family (mutual),
#     alleged_family (one-sided), platform/version, and contact info.
#
# Reference: https://spec.torproject.org/proposals/321-happy-families.html
# Consensus method selection requires >2/3 of authorities to support the method.
# With 9 authorities, that means at least 7 must support method 35.

set -euo pipefail

COLLECTOR_BASE="https://collector.torproject.org/recent/relay-descriptors"
ONIONOO_BASE="https://onionoo.torproject.org"

# Operator contact to check (default: 1aeo, override with first argument)
OPERATOR_CONTACT="${1:-1aeo}"

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
echo -e "${BOLD}[1/6] Fetching latest consensus...${NC}"
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
echo -e "${BOLD}[2/6] Checking directory authority versions...${NC}"
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

    # Get just the header of the vote (first 2KB)
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
REMAINING=0
if [ "$SUPPORTS_35" -ge "$NEEDED" ]; then
    echo -e "  ${GREEN}✓ Threshold met (>2/3 = need $NEEDED of $TOTAL_AUTHS)${NC}"
else
    REMAINING=$((NEEDED - SUPPORTS_35))
    echo -e "  ${YELLOW}✗ Need $NEEDED of $TOTAL_AUTHS (>2/3) - ${REMAINING} more authority upgrade(s) needed${NC}"
fi

# --- Step 3: Check server descriptors for family-cert (sample) ---
echo ""
echo -e "${BOLD}[3/6] Checking server descriptors for family-cert (hourly batch sample)...${NC}"
echo -e "  ${BLUE}NOTE: Each batch contains ~1 hour of published descriptors, not all relays.${NC}"
echo -e "  ${BLUE}See step 6 for complete counts via Onionoo.${NC}"

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

    echo -e "  Descriptors in this batch: ${TOTAL_DESCS} (of ~8,000 total relays)"
    echo -e "  Descriptors with family-cert in this batch: ${BOLD}${FAMILY_CERT_COUNT}${NC}"

    if [ "$FAMILY_CERT_COUNT" -gt 0 ]; then
        echo -e "  ${GREEN}✓ family-cert entries ARE present in server descriptors${NC}"

        # Break down by operator
        echo ""
        echo -e "  ${BOLD}Top operators with family-cert (in this batch):${NC}"
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
echo -e "${BOLD}[4/6] Checking microdescriptors for family-ids entries...${NC}"

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
echo -e "${BOLD}[5/6] Checking Desc=4 subprotocol support (family-cert capable relays)...${NC}"

# Count relays advertising Desc version ranges that include 4
DESC4_COUNT=$(grep -cP "Desc=\S*4" "$TMPDIR/consensus.txt" || true)
TOTAL_RELAYS=$(grep -c "^r " "$TMPDIR/consensus.txt" || true)

echo -e "  Total relays in consensus: ${TOTAL_RELAYS}"
if [ "$TOTAL_RELAYS" -gt 0 ]; then
    PCT=$(echo "scale=1; $DESC4_COUNT * 100 / $TOTAL_RELAYS" | bc)
    echo -e "  Relays advertising Desc=4: ${BOLD}${DESC4_COUNT}${NC} (${PCT}%)"
fi

# --- Step 6: Operator-specific family status via Onionoo ---
echo ""
echo -e "${BOLD}[6/6] Querying Onionoo for '${OPERATOR_CONTACT}' relay family status...${NC}"
echo -e "  ${BLUE}Onionoo provides the complete view of ALL relays (not just hourly samples).${NC}"
echo -e "  ${BLUE}Source: ${ONIONOO_BASE}/details?contact=${OPERATOR_CONTACT}${NC}"
echo ""

curl -sf "${ONIONOO_BASE}/details?contact=${OPERATOR_CONTACT}&fields=nickname,fingerprint,or_addresses,platform,effective_family,alleged_family" \
    > "$TMPDIR/onionoo.json" 2>/dev/null

python3 - "$TMPDIR/onionoo.json" "$OPERATOR_CONTACT" << 'PYEOF'
import json, sys
from collections import defaultdict

with open(sys.argv[1], 'r') as f:
    data = json.load(f)

operator = sys.argv[2]
relays = data.get('relays', [])
truncated = data.get('relays_truncated', 0)

if not relays:
    print(f"  No relays found for contact '{operator}'")
    sys.exit(0)

total = len(relays) + truncated
if truncated:
    print(f"  WARNING: response truncated, {truncated} relays not shown")

# Categorize relays
subnets = defaultdict(lambda: {
    'total': 0, 'effective': 0, 'alleged': 0, 'none': 0,
    'v049': 0, 'v048': 0, 'v_other': 0,
    'cert_capable': 0,
})

versions = defaultdict(int)
family_by_version = defaultdict(lambda: {'effective': 0, 'alleged': 0, 'none': 0})

for r in relays:
    # Extract IP and subnet
    addr = r.get('or_addresses', [''])[0]
    ip = addr.rsplit(':', 1)[0] if ':' in addr else addr
    # Handle IPv6
    if ip.startswith('['):
        subnet = 'IPv6'
    else:
        octets = ip.split('.')
        subnet = '.'.join(octets[:3]) + '.0/24' if len(octets) == 4 else 'unknown'

    # Extract Tor version
    platform = r.get('platform', '')
    ver = 'unknown'
    for i, tok in enumerate(platform.split()):
        if tok == 'Tor' and i + 1 < len(platform.split()):
            ver = platform.split()[i + 1]
            break
    versions[ver] += 1

    is_049 = ver.startswith('0.4.9')
    is_048 = ver.startswith('0.4.8')

    # Family status
    eff = r.get('effective_family', [])
    alg = r.get('alleged_family', [])

    subnets[subnet]['total'] += 1
    if is_049:
        subnets[subnet]['v049'] += 1
        subnets[subnet]['cert_capable'] += 1
    elif is_048:
        subnets[subnet]['v048'] += 1
    else:
        subnets[subnet]['v_other'] += 1

    if len(eff) > 1:
        subnets[subnet]['effective'] += 1
        family_by_version[ver]['effective'] += 1
    elif len(alg) > 0:
        subnets[subnet]['alleged'] += 1
        family_by_version[ver]['alleged'] += 1
    else:
        subnets[subnet]['none'] += 1
        family_by_version[ver]['none'] += 1

# Print results
total_relays = len(relays)
total_eff = sum(s['effective'] for s in subnets.values())
total_alg = sum(s['alleged'] for s in subnets.values())
total_none = sum(s['none'] for s in subnets.values())
total_049 = sum(s['v049'] for s in subnets.values())
total_048 = sum(s['v048'] for s in subnets.values())

print(f"  {operator} Relay Family Key Status")
print(f"  Total relays: {total_relays}")
print()

# Version summary
print(f"  Tor versions:")
for ver in sorted(versions.keys()):
    count = versions[ver]
    cert = "family-cert capable" if ver.startswith('0.4.9') else "old-style MyFamily only"
    pct = count * 100 / total_relays
    print(f"    {ver}: {count} relays ({pct:.1f}%) - {cert}")
print()

# Family mechanism summary
print(f"  Family mechanism:")
print(f"    New family-key (Proposal 321 family-cert): {total_049} relays ({total_049*100/total_relays:.1f}%) - running Tor 0.4.9.x")
print(f"    Old-style MyFamily (fingerprint lists):    {total_048} relays ({total_048*100/total_relays:.1f}%) - running Tor 0.4.8.x")
print()

# Family status by version
print(f"  Family status by Tor version:")
print(f"    {'Version':<14} {'Total':>6} {'Effective':>10} {'Alleged':>10} {'None':>6}")
print(f"    {'-'*14} {'-'*6} {'-'*10} {'-'*10} {'-'*6}")
for ver in sorted(family_by_version.keys()):
    fv = family_by_version[ver]
    t = fv['effective'] + fv['alleged'] + fv['none']
    print(f"    {ver:<14} {t:>6} {fv['effective']:>10} {fv['alleged']:>10} {fv['none']:>6}")
print()

# Per-subnet breakdown
print(f"  Per /24 subnet breakdown:")
print(f"    {'Subnet':<22} {'Total':>6} {'0.4.9.x':>8} {'0.4.8.x':>8} {'Eff':>6} {'Alleg':>6} {'None':>6}")
print(f"    {'-'*22} {'-'*6} {'-'*8} {'-'*8} {'-'*6} {'-'*6} {'-'*6}")
for subnet in sorted(subnets.keys()):
    s = subnets[subnet]
    print(f"    {subnet:<22} {s['total']:>6} {s['v049']:>8} {s['v048']:>8} {s['effective']:>6} {s['alleged']:>6} {s['none']:>6}")
print(f"    {'-'*22} {'-'*6} {'-'*8} {'-'*8} {'-'*6} {'-'*6} {'-'*6}")
print(f"    {'TOTAL':<22} {total_relays:>6} {total_049:>8} {total_048:>8} {total_eff:>6} {total_alg:>6} {total_none:>6}")
print()

# Summary
print(f"  Summary:")
eff_pct = total_eff * 100 / total_relays
alg_pct = total_alg * 100 / total_relays
none_pct = total_none * 100 / total_relays
cert_pct = total_049 * 100 / total_relays

print(f"    {total_eff} relays ({eff_pct:.1f}%) have confirmed (effective) family")
print(f"    {total_alg} relays ({alg_pct:.1f}%) have alleged family only (one-sided declaration)")
if total_none > 0:
    print(f"    {total_none} relays ({none_pct:.1f}%) have NO family declaration at all")
print()
print(f"    {total_049} relays ({cert_pct:.1f}%) use new family-key (Proposal 321 family-cert)")
print(f"    {total_048} relays ({100-cert_pct:.1f}%) use old-style MyFamily (fingerprint lists)")

# Actionable items
print()
if total_alg > 0:
    print(f"  Pending actions:")
    print(f"    {total_alg} relays have alleged_family (declared family but mutual confirmation incomplete)")
    for subnet in sorted(subnets.keys()):
        s = subnets[subnet]
        if s['alleged'] > 0:
            mech = "family-cert" if s['v049'] > 0 else "MyFamily"
            print(f"      {subnet}: {s['alleged']} alleged ({mech})")
if total_none > 0:
    print(f"    {total_none} relays have NO family config at all:")
    for subnet in sorted(subnets.keys()):
        s = subnets[subnet]
        if s['none'] > 0:
            print(f"      {subnet}: {s['none']} unconfigured")

PYEOF

# --- Summary ---
echo ""
echo -e "${BOLD}=== Network-wide Summary ===${NC}"
echo ""
echo "  Proposal 321 Happy Families deployment status:"
echo ""

if [ "$FAMILY_CERT_COUNT" -gt 0 ] 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Server descriptors: family-cert entries present (${FAMILY_CERT_COUNT} in latest hourly batch)"
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
    if [ "$REMAINING" -gt 0 ]; then
        echo -e "  ${YELLOW}family-ids in microdescriptors requires ${REMAINING} more authority upgrade(s) to 0.4.9.x${NC}"
    fi
else
    echo ""
    echo -e "  ${RED}${BOLD}NOT YET DEPLOYED: No family-cert entries found${NC}"
fi

echo ""
