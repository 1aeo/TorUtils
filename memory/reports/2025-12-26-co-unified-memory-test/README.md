# Unified Tor Memory Experiment Plan

## Overview

- **Server:** co
- **90 relays** across 9 groups (10 each)
- **52 relays** reserve
- **14 days** duration
- **6-hourly** data collection
- All relays freshly restarted (server just rebooted)

## Experiment Groups

| Group | Relays | Configuration |
|-------|--------|---------------|
| A | 10 | jemalloc via LD_PRELOAD |
| B | 10 | mimalloc via LD_PRELOAD |
| C | 10 | tcmalloc via LD_PRELOAD |
| D | 10 | MaxConsensusAgeForDiffs 4 hours |
| E | 10 | MaxConsensusAgeForDiffs 8 hours |
| F | 10 | Restart every 24 hours |
| G | 10 | Restart every 48 hours |
| H | 10 | Restart every 72 hours |
| Z | 10 | Control (glibc, default, no restarts) |

## Relay Assignment

| Group | Relays |
|-------|--------|
| A (jemalloc) | 22gz, 24kgoldn, 42dugg, armanicaesar, arsonaldarebel, autumntwinuzis, ayeverb, babyfaceray, babysmoove, bbno |
| B (mimalloc) | bfbdapackman, biggk, bigpokeyhouston, bigtuckdfw, bigwalkdog, blovee, bluefacebaby, boldyjames, bonethugs, calicoe |
| C (tcmalloc) | caseyveggies, cashkidd, charlieclips, chiefkeef, chiiild, cjwhoopty, cocash, comethazine, conceitedwildnout, daveeast |
| D (consensus-4h) | davesantan, daylytwatts, ddgmoonwalking, delasoul, destroylonely, dicesoho, dizaster, dnaqueens, domaniharris, dougieb |
| E (consensus-8h) | dustylocane, estgee, estgizzle, famousdex, fearlessfour, fivioforeign, fmbdz, foolio, fredobang, goodzdaanimal |
| F (restart-24h) | gperico, gunna, htowndonkee, ianndior, icespice, icewearvezzo, illmaculate, jaycritch, jayworthy, joji |
| G (restart-48h) | kankan, kanyc, kayflock, kencarson, kingsun, kingvon, lakeyah, lildurk, lilgotit, lilkeed |
| H (restart-72h) | lilloaded, lilnasx, lilofatrat, lilskies, liltecca, liltjay, littlesimz, louieray, machhommy, millyz |
| Z (control) | mobbdeep, moneyman, morray, mozzy, nardowick, nastyc, nikobrim, nocap, ogboobieblack, ogche |
| Reserve | ombpeezy through zmoney (52 relays) |

## Phase 1: Configuration

### Step 1: Install Allocator Libraries

```bash
sudo apt install libjemalloc2 libgoogle-perftools4 libmimalloc2.0
```

Verify library paths:
```bash
ls -la /usr/lib/x86_64-linux-gnu/libjemalloc.so.2
ls -la /usr/lib/x86_64-linux-gnu/libtcmalloc.so.4
ls -la /usr/lib/x86_64-linux-gnu/libmimalloc.so*
```

### Step 2: Initialize Experiment Directory

```bash
cd ../tools
./experiment.sh init --name "unified-memory-test" --groups A,B,C,D,E,F,G,H,Z
```

### Step 3: Collect Fingerprints and Create relay_config.csv

```bash
for relay in 22gz 24kgoldn 42dugg ...; do
  fp=$(sudo cat /var/lib/tor-instances/$relay/fingerprint | awk '{print $2}')
  echo "$fp,$relay,<GROUP>"
done
```

### Step 4: Apply Configurations

Run the apply script:
```bash
sudo ./apply-configs.sh
```

This script handles:
- Groups A/B/C: systemd overrides with LD_PRELOAD for allocators
- Groups D/E: MaxConsensusAgeForDiffs torrc settings
- Groups F/G/H: systemd timers for periodic restarts
- Restarting all modified relays

### Step 5: Verify Configurations

```bash
# Verify allocator is loaded
for relay in 22gz bfbdapackman caseyveggies; do
  pid=$(systemctl show tor@${relay} --property=MainPID --value)
  echo "$relay: $(cat /proc/$pid/maps | grep -E 'jemalloc|mimalloc|tcmalloc' | head -1)"
done

# Verify torrc settings
for relay in davesantan dustylocane; do
  grep MaxConsensusAgeForDiffs /etc/tor/instances/${relay}/torrc
done

# Verify timers are active
systemctl list-timers | grep tor-restart
```

## Phase 2: Data Collection (6-hourly)

```bash
# Add to crontab - every 6 hours (adjust paths for your setup)
0 */6 * * * $TORUTILS/memory/tools/collect.sh \
  --output $TORUTILS/memory/reports/2025-12-26-co-unified-memory-test/memory_measurements.csv \
  --config $TORUTILS/memory/reports/2025-12-26-co-unified-memory-test/relay_config.csv
```

## Phase 3: Analysis (Day 15+)

```bash
cd ../tools
python3 generate-report.py --experiment ../reports/2025-12-26-co-unified-memory-test/
```

## Expected Outcomes

| Group | Expected Memory | Notes |
|-------|-----------------|-------|
| A (jemalloc) | ~1-2 GB stable | Best expected result |
| B (mimalloc) | ~1-2 GB stable | Modern allocator |
| C (tcmalloc) | ~1-2 GB stable | Google allocator |
| D/E (consensus) | Unknown | May reduce churn |
| F/G/H (restarts) | Sawtooth pattern | Periodic reset |
| Z (control) | ~5 GB fragmented | Baseline |

---

*Plan created: 2025-12-26*




