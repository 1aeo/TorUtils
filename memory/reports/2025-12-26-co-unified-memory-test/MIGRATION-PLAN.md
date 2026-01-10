# Experiment End & Migration Plan

## Overview

**Experiment:** 2025-12-26-co-unified-memory-test  
**End Date:** 2026-01-09  
**Decision:** Migrate all 142 relays to production allocators based on experiment results

### Results Summary

| Allocator | Avg RSS | Recommendation |
|-----------|---------|----------------|
| mimalloc 2.1.2 | 1.20 GB | ✓ Primary (90%) |
| jemalloc 5.3.0 | 1.66 GB | ✓ Secondary (10%) |
| tcmalloc 2.15 | 3.86 GB | ✗ Not recommended |
| glibc 2.39 | 5.70 GB | ✗ Default, high fragmentation |

### Target Allocation

- **mimalloc 2.1.2:** 128 relays (90%)
- **jemalloc 5.3.0:** 14 relays (10%)

---

## Phase 1: Pre-Migration Backup

### 1.1 Archive Experiment Data

```bash
# Create experiment archive
cd /home/krim/TorUtils/memory/reports
tar -czvf 2025-12-26-co-unified-memory-test-archive.tar.gz \
    2025-12-26-co-unified-memory-test/

# Verify archive
tar -tzvf 2025-12-26-co-unified-memory-test-archive.tar.gz | head -20
```

### 1.2 Backup Current Configurations

```bash
# Backup all current systemd overrides
sudo tar -czvf /tmp/tor-systemd-overrides-backup.tar.gz \
    /etc/systemd/system/tor@*.service.d/ \
    /etc/systemd/system/tor-restart@*.timer \
    /etc/systemd/system/tor-restart@*.service \
    2>/dev/null || echo "Some files may not exist"

# Backup torrc files with custom settings
for relay in davesantan daylytwatts ddgmoonwalking delasoul destroylonely \
             dicesoho dizaster dnaqueens domaniharris dougieb \
             dustylocane estgee estgizzle famousdex fearlessfour \
             fivioforeign fmbdz foolio fredobang goodzdaanimal; do
    sudo cp /var/lib/tor-instances/${relay}/torrc /tmp/torrc-backup-${relay} 2>/dev/null
done
```

### 1.3 Final Data Collection

```bash
# Collect final measurements before migration
/home/krim/TorUtils/memory/tools/collect.sh \
    --output /home/krim/TorUtils/memory/reports/2025-12-26-co-unified-memory-test/memory_measurements.csv \
    --config /home/krim/TorUtils/memory/reports/2025-12-26-co-unified-memory-test/relay_config.csv

# Generate final chart
cd /home/krim/TorUtils/memory/reports/2025-12-26-co-unified-memory-test
python3 chart-memory.py
```

---

## Phase 2: Stop Experiment Infrastructure

### 2.1 Remove Cron Job

```bash
# View current cron
crontab -l

# Remove experiment cron job
crontab -l | grep -v 'co-unified-memory-test' | crontab -

# Verify removal
crontab -l
```

### 2.2 Stop and Disable Restart Timers

```bash
# List active restart timers
systemctl list-timers | grep tor-restart

# Stop and disable all restart timers
for relay in gperico gunna htowndonkee ianndior icespice icewearvezzo \
             illmaculate jaycritch jayworthy joji kankan kanyc kayflock \
             kencarson kingsun kingvon lakeyah lildurk lilgotit lilkeed \
             lilloaded lilnasx lilofatrat lilskies liltecca liltjay \
             littlesimz louieray machhommy millyz; do
    sudo systemctl stop tor-restart@${relay}.timer 2>/dev/null || true
    sudo systemctl disable tor-restart@${relay}.timer 2>/dev/null || true
done

# Verify no timers remain
systemctl list-timers | grep tor-restart
```

---

## Phase 3: Clean Up Experiment Configurations

### 3.1 Remove All Systemd Overrides

```bash
# Remove all allocator overrides
sudo rm -rf /etc/systemd/system/tor@*.service.d/

# Remove all restart timer/service units
sudo rm -f /etc/systemd/system/tor-restart@*.timer
sudo rm -f /etc/systemd/system/tor-restart@*.service

# Reload systemd
sudo systemctl daemon-reload
```

### 3.2 Revert torrc Changes

```bash
# Remove MaxConsensusAgeForDiffs from affected relays (Groups D and E)
for relay in davesantan daylytwatts ddgmoonwalking delasoul destroylonely \
             dicesoho dizaster dnaqueens domaniharris dougieb \
             dustylocane estgee estgizzle famousdex fearlessfour \
             fivioforeign fmbdz foolio fredobang goodzdaanimal; do
    TORRC="/var/lib/tor-instances/${relay}/torrc"
    if sudo grep -q "MaxConsensusAgeForDiffs" "$TORRC" 2>/dev/null; then
        sudo sed -i '/MaxConsensusAgeForDiffs/d' "$TORRC"
        echo "Cleaned $relay torrc"
    fi
done
```

---

## Phase 4: Apply Production Configuration

### 4.1 Run Migration Script

```bash
# Review the script first
cat /home/krim/TorUtils/memory/reports/2025-12-26-co-unified-memory-test/migrate-to-production.sh

# Execute migration
sudo /home/krim/TorUtils/memory/reports/2025-12-26-co-unified-memory-test/migrate-to-production.sh
```

### 4.2 Verify Configuration

```bash
# Check jemalloc relays (should show LD_PRELOAD with jemalloc)
for relay in 22gz 24kgoldn 42dugg armanicaesar arsonaldarebel \
             autumntwinuzis ayeverb babyfaceray babysmoove bbno \
             bfbdapackman biggk bigpokeyhouston bigtuckdfw; do
    echo -n "$relay: "
    systemctl show tor@${relay} --property=Environment | grep -o 'jemalloc\|mimalloc' || echo "NO ALLOCATOR"
done

# Check mimalloc relays (sample)
for relay in calicoe caseyveggies zmoney yungeenace; do
    echo -n "$relay: "
    systemctl show tor@${relay} --property=Environment | grep -o 'jemalloc\|mimalloc' || echo "NO ALLOCATOR"
done
```

### 4.3 Verify Allocators Are Loaded

```bash
# Check a jemalloc relay
pid=$(systemctl show tor@22gz --property=MainPID --value)
sudo cat /proc/$pid/maps | grep -E 'jemalloc|mimalloc' | head -1

# Check a mimalloc relay
pid=$(systemctl show tor@zmoney --property=MainPID --value)
sudo cat /proc/$pid/maps | grep -E 'jemalloc|mimalloc' | head -1
```

---

## Phase 5: Post-Migration Monitoring

### 5.1 Immediate Health Check

```bash
# Check all relays are running
systemctl list-units 'tor@*' --state=running | wc -l
# Should show 142

# Check for any failed units
systemctl list-units 'tor@*' --state=failed
```

### 5.2 Memory Baseline (24h later)

```bash
# Create a simple monitoring script for ongoing checks
cat > /home/krim/TorUtils/memory/tools/check-memory.sh << 'EOF'
#!/bin/bash
echo "=== Tor Relay Memory Summary ==="
echo "Date: $(date)"
echo ""
total_rss=0
count=0
for relay in $(ls /var/lib/tor-instances/); do
    pid=$(pgrep -f "tor.*instances/${relay}" 2>/dev/null | head -1)
    if [ -n "$pid" ]; then
        rss=$(awk '/VmRSS/ {print $2}' /proc/$pid/status 2>/dev/null)
        if [ -n "$rss" ]; then
            total_rss=$((total_rss + rss))
            count=$((count + 1))
        fi
    fi
done
avg=$((total_rss / count / 1024))
total=$((total_rss / 1024 / 1024))
echo "Relays running: $count"
echo "Average RSS: ${avg} MB"
echo "Total RSS: ${total} GB"
EOF
chmod +x /home/krim/TorUtils/memory/tools/check-memory.sh
```

### 5.3 Ongoing Monitoring (Optional)

If desired, set up periodic monitoring:

```bash
# Add to crontab for daily memory check
(crontab -l 2>/dev/null; echo "0 6 * * * /home/krim/TorUtils/memory/tools/check-memory.sh 2>&1 | logger -t tor-memory") | crontab -
```

---

## Rollback Plan

If issues occur after migration:

### Quick Rollback (Remove Allocators)

```bash
# Remove all allocator overrides
sudo rm -rf /etc/systemd/system/tor@*.service.d/
sudo systemctl daemon-reload

# Restart all relays (will use glibc)
for relay in $(ls /var/lib/tor-instances/); do
    sudo systemctl restart tor@${relay} &
done
wait
```

### Restore from Backup

```bash
# Restore systemd overrides
sudo tar -xzvf /tmp/tor-systemd-overrides-backup.tar.gz -C /
sudo systemctl daemon-reload
```

---

## Checklist

- [ ] Phase 1.1: Archive experiment data
- [ ] Phase 1.2: Backup current configurations
- [ ] Phase 1.3: Final data collection
- [ ] Phase 2.1: Remove cron job
- [ ] Phase 2.2: Stop restart timers
- [ ] Phase 3.1: Remove systemd overrides
- [ ] Phase 3.2: Revert torrc changes
- [ ] Phase 4.1: Run migration script
- [ ] Phase 4.2: Verify configuration
- [ ] Phase 4.3: Verify allocators loaded
- [ ] Phase 5.1: Health check
- [ ] Phase 5.2: Memory baseline (24h later)

---

## Files to Keep

After migration, these files document the experiment:

- `experiment.json` - Experiment metadata
- `memory_measurements.csv` - Raw data
- `relay_config.csv` - Group assignments
- `charts/` - Generated visualizations
- `MIGRATION-PLAN.md` - This document

