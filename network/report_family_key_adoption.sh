#!/bin/bash
# report_family_key_adoption.sh - Report on Proposal 321 family-key adoption across the Tor network
#
# Scans multiple CollecTor server descriptor batches to find all relays publishing
# family-cert, then cross-references with Onionoo to determine effective family
# status and group relays by operator.
#
# Unlike a single hourly batch (which contains ~1,300 of ~8,000 relays), this
# script scans ~24h of batches to capture most relays (descriptors are republished
# every ~18h).
#
# Usage: ./report_family_key_adoption.sh [hours_to_scan]
#   hours_to_scan: number of hours of server descriptor batches to scan (default: 24)
#
# Output: ranked list of operators using family-cert, with relay counts and
#         effective family sizes from Onionoo.

set -euo pipefail

COLLECTOR_BASE="https://collector.torproject.org/recent/relay-descriptors"
ONIONOO_BASE="https://onionoo.torproject.org"
HOURS="${1:-24}"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'
BOLD='\033[1m'

for cmd in curl python3; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: $cmd is required but not installed." >&2
        exit 1
    fi
done

echo -e "${BOLD}=== Proposal 321 Family Key Adoption Report ===${NC}"
echo -e "${BLUE}Scanning ~${HOURS}h of server descriptor batches from CollecTor${NC}"
echo ""

# --- Step 1: Get batch list ---
echo -e "${BOLD}[1/3] Fetching server descriptor batch index...${NC}"
curl -sf "${COLLECTOR_BASE}/server-descriptors/" > "$TMPDIR/sd_index.html" 2>/dev/null

python3 - "$TMPDIR/sd_index.html" "$HOURS" "$TMPDIR/batch_list.txt" << 'PYEOF'
import re, sys
from datetime import datetime, timedelta

with open(sys.argv[1]) as f:
    html = f.read()
hours = int(sys.argv[2])
outfile = sys.argv[3]

batches = sorted(set(re.findall(r'\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}-server-descriptors', html)))

# Filter to last N hours
cutoff = datetime.utcnow() - timedelta(hours=hours)
recent = []
for b in batches:
    ts_str = b.replace('-server-descriptors', '')
    try:
        ts = datetime.strptime(ts_str, '%Y-%m-%d-%H-%M-%S')
        if ts >= cutoff:
            recent.append(b)
    except ValueError:
        continue

with open(outfile, 'w') as f:
    for b in recent:
        f.write(b + '\n')

print(f"  {len(batches)} total batches available, using {len(recent)} from last {hours}h")
PYEOF

# --- Step 2: Download batches and extract family-cert relays ---
echo ""
echo -e "${BOLD}[2/3] Scanning server descriptor batches for family-cert...${NC}"

python3 - "$TMPDIR/batch_list.txt" "$COLLECTOR_BASE/server-descriptors" "$TMPDIR/cert_relays.json" "$TMPDIR" << 'PYEOF'
import json, subprocess, sys

batch_file = sys.argv[1]
base_url = sys.argv[2]
outfile = sys.argv[3]
tmpdir = sys.argv[4]

with open(batch_file) as f:
    batches = [line.strip() for line in f if line.strip()]

relays = {}  # fingerprint -> info
batch_count = 0
total = len(batches)

for batch in batches:
    batch_count += 1
    print(f"\r  Downloading {batch_count}/{total}: {batch}...", end="", flush=True)

    result = subprocess.run(
        ["curl", "-sf", f"{base_url}/{batch}"],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        continue

    text = result.stdout
    parts = text.split('\nrouter ')

    for part in parts[1:]:
        if 'family-cert' not in part:
            continue

        lines = part.split('\n')
        tokens = lines[0].split()
        name = tokens[0] if tokens else 'unknown'
        ip = tokens[1] if len(tokens) > 1 else ''

        fingerprint = ''
        contact = ''
        platform = ''

        for line in lines:
            if line.startswith('fingerprint '):
                fingerprint = line[12:].replace(' ', '')
            elif line.startswith('contact '):
                contact = line[8:].strip()
            elif line.startswith('platform '):
                platform = line[9:].strip()

        if fingerprint:
            relays[fingerprint] = {
                'name': name,
                'ip': ip,
                'contact': contact,
                'platform': platform,
            }

print(f"\n  Found {len(relays)} unique relays with family-cert")

with open(outfile, 'w') as f:
    json.dump(relays, f)
PYEOF

# --- Step 3: Cross-reference with Onionoo and build report ---
echo ""
echo -e "${BOLD}[3/3] Cross-referencing with Onionoo for family details...${NC}"

python3 - "$TMPDIR/cert_relays.json" "$ONIONOO_BASE" << 'PYEOF'
import json, subprocess, sys, time
from collections import defaultdict

with open(sys.argv[1]) as f:
    cert_relays = json.load(f)
onionoo_base = sys.argv[2]

if not cert_relays:
    print("  No family-cert relays found.")
    sys.exit(0)

# Group by contact
contacts = defaultdict(list)
for fp, info in cert_relays.items():
    c = info['contact'] if info['contact'] else '(no contact)'
    contacts[c].append({'fp': fp, **info})

sorted_contacts = sorted(contacts.items(), key=lambda x: -len(x[1]))

# For operators with 2+ relays, sample one relay's effective_family from Onionoo
eff_family = {}
queried = 0
for contact, relays in sorted_contacts:
    if contact == '(no contact)':
        continue
    if len(relays) < 2:
        continue

    fp = relays[0]['fp']
    url = f"{onionoo_base}/details?lookup={fp}&fields=fingerprint,effective_family"
    result = subprocess.run(
        ["curl", "-sf", url],
        capture_output=True, text=True, timeout=30
    )

    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            relay_list = data.get('relays', [])
            if relay_list:
                eff = relay_list[0].get('effective_family', [])
                eff_family[contact] = len(eff)
        except:
            pass

    queried += 1
    if queried % 10 == 0:
        print(f"\r  Queried {queried} operators...", end="", flush=True)
    time.sleep(0.3)

print(f"\r  Queried {queried} operators for effective family data")

# Also get network-wide stats: total relays with Desc=4 from Onionoo
# (We skip this for speed - the main check_happy_family_keys.sh script has it)

# --- Build report ---
print()
print("=" * 95)
print("  PROPOSAL 321 FAMILY KEY ADOPTION - ALL OPERATORS")
print("  Source: CollecTor server descriptors (family-cert) + Onionoo (effective_family)")
print("=" * 95)
print()

total_relays = len(cert_relays)
total_ops = len(contacts)

# Extract unique Tor versions
versions = defaultdict(int)
for fp, info in cert_relays.items():
    p = info.get('platform', '')
    ver = 'unknown'
    for i, tok in enumerate(p.split()):
        if tok == 'Tor' and i + 1 < len(p.split()):
            ver = p.split()[i + 1]
            break
    versions[ver] += 1

print(f"  Total relays with family-cert: {total_relays}")
print(f"  Total unique operators:        {total_ops}")
print()

print(f"  Tor versions:")
for ver in sorted(versions.keys()):
    print(f"    {ver}: {versions[ver]} relays")
print()

# Ranked operator table
print(f"  {'#':<4} {'Cert':>5} {'Eff.':>5} {'Status':<12} {'Operator'}")
print(f"  {'─'*4} {'─'*5} {'─'*5} {'─'*12} {'─'*65}")

rank = 0
for contact, relays in sorted_contacts:
    rank += 1

    cert_count = len(relays)
    eff_size = eff_family.get(contact, None)

    # Determine status
    if eff_size is not None:
        if eff_size >= cert_count:
            status = "\033[0;32m✓ complete\033[0m"
        elif eff_size > 1:
            status = "\033[1;33m◐ partial\033[0m "
        else:
            status = "\033[0;31m✗ pending\033[0m "
    else:
        if cert_count == 1:
            status = "· single  "
        else:
            status = "? unknown "

    eff_str = str(eff_size) if eff_size is not None else "-"

    # Clean up contact for display
    display = contact[:65]

    print(f"  {rank:<4} {cert_count:>5} {eff_str:>5} {status}  {display}")

print()
print(f"  {'─'*4} {'─'*5} {'─'*5} {'─'*12} {'─'*65}")
print(f"  {'':4} {total_relays:>5}       {'':12} {total_ops} operators")
print()

# Status legend
print("  Legend:")
print("    Cert    = relays publishing family-cert in server descriptors")
print("    Eff.    = effective (mutual) family size from Onionoo for one sampled relay")
print("    Status:")
print("      \033[0;32m✓ complete\033[0m = effective family >= cert count (all relays confirmed)")
print("      \033[1;33m◐ partial\033[0m  = some relays confirmed, others still alleged/pending")
print("      \033[0;31m✗ pending\033[0m  = family-cert published but no effective family yet")
print("      · single   = single-relay operator (no family needed)")
print("      ? unknown  = could not query Onionoo for this operator")
print()

# Interesting observations
print("  Notes:")

# Find operators that might share a family key (different contacts, but eff > cert)
shared_key = []
for contact, relays in sorted_contacts:
    eff = eff_family.get(contact)
    if eff is not None and eff > len(relays) + 2:
        shared_key.append((contact[:50], len(relays), eff))

if shared_key:
    print("    Operators where effective_family > cert_count (may share a key with other contacts):")
    for c, cert, eff in shared_key:
        print(f"      {c}: {cert} cert, {eff} effective")
    print()

# Operators with cert but no effective family
pending = [(c[:50], len(r)) for c, r in sorted_contacts if eff_family.get(c) == 1 and len(r) > 1]
if pending:
    print("    Operators with family-cert but NO effective family (may need investigation):")
    for c, count in pending:
        print(f"      {c}: {count} relays")
    print()

PYEOF

echo ""
