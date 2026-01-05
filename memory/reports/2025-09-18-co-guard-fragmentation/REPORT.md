# Guard Relay Memory Fragmentation Investigation

## Executive Summary

**Problem:** Tor guard relays consuming ~5 GB RAM each due to memory fragmentation  
**Hypothesis:** DirCache 0 and/or MaxMemInQueues will reduce memory while maintaining guard status  
**Result:** DirCache 0 reduces memory by 94% but removes guard status; MaxMemInQueues alone does not prevent fragmentation  
**Recommendation:** Investigate alternative memory allocators (jemalloc, tcmalloc, OpenBSD malloc) that handle fragmentation better while maintaining guard status

## Experiment Setup

| Parameter | Value |
|-----------|-------|
| Server | co |
| Period | 2025-09-09 to 2025-09-18 |
| Tor Version | unknown |
| Allocator | glibc |
| Relay Count | 13 |

### Groups

| Group | Configuration | Relays | Description |
|-------|---------------|--------|-------------|
| A | DirCache 0 + MaxMem 2GB | 3 | Test combined optimization |
| B | Control (default) | 1 | No optimization baseline |
| C | MaxMem 2GB only | 3 | Test MaxMemInQueues alone |
| D | MaxMem 4GB only | 3 | Test higher MaxMemInQueues |
| E | DirCache 0 only | 3 | Test DirCache alone |

## Results

### Key Metrics

| Group | Configuration | Start RSS | End RSS | Change | Status |
|-------|---------------|-----------|---------|--------|--------|
| A | DirCache 0 + MaxMem 2GB | 5.35 GB | 0.29 GB | -94.6% | STABLE |
| E | DirCache 0 only | - | 0.33 GB | -93.8% | STABLE |
| C | MaxMem 2GB only | 0.55 GB | 4.17 GB | +658% | FRAGMENTED |
| D | MaxMem 4GB only | 0.55 GB | 4.76 GB | +766% | FRAGMENTED |
| B | Control (default) | 0.57 GB | 5.14 GB | +802% | FRAGMENTED |

### Charts

#### A/B Experiment Charts

![Memory Over Time by Group](charts/chart1_memory_over_time.png)

![Final Comparison by Configuration](charts/chart2_final_comparison.png)

![Fragmentation Timeline](charts/chart3_fragmentation_timeline.png)

#### Time-Series Charts

![Memory Usage Over Time](charts/memory_usage.png)

![Weekly Memory Trends](charts/memory_weekly.png)

## Analysis

### What Worked

- **DirCache 0** immediately reduced memory from ~5 GB to ~0.3 GB (94% reduction)
- Memory remained stable for 9+ days with DirCache 0 enabled
- DirCache 0 alone (without MaxMemInQueues) achieves similar results

### What Didn't Work

- **MaxMemInQueues alone** does not prevent fragmentation - memory still explodes after 48 hours
- MaxMemInQueues only limits circuit/connection buffers, not directory cache
- Control relays fragmented from 0.57 GB to 5.15 GB within 24 hours

### Unexpected Observations

- Fragmentation occurs suddenly around Day 2-3, not gradually
- Higher MaxMemInQueues (4GB) performs slightly worse than 2GB
- DirCache 0 causes loss of Guard relay status (expected but confirmed)

## Root Cause

The memory issue is caused by:

1. **Directory caching** (required for guard status) creates many small fragmented allocations
2. **glibc malloc** does not efficiently release fragmented memory back to the OS
3. After ~48 hours of operation, fragmentation causes RSS to explode to ~5 GB

> "If you're on Linux, you may be encountering memory fragmentation bugs in glibc's malloc implementation. That is, when Tor releases memory back to the system, the pieces of memory are fragmented so they're hard to reuse."  
> — [Tor FAQ: Why is my Tor relay using so much memory?](https://2019.www.torproject.org/docs/faq.html.en#RelayMemory)

**Why DirCache 0 works:** Disables directory caching, eliminating the allocation churn that causes fragmentation.

**Why it's not viable:** Guard relays REQUIRE directory caching to maintain Guard flag status.

## Alternative Memory Allocators for Ubuntu 24.04

The following allocators can be used with Tor on Ubuntu 24.04 to potentially reduce fragmentation.

### Allocator Comparison

| Allocator | Installation | CPU Overhead | Fragmentation | Security |
|-----------|-------------|--------------|---------------|----------|
| glibc (default) | Built-in | Low | High | Standard |
| jemalloc | apt + LD_PRELOAD | Low-Medium | Low | Standard |
| tcmalloc | apt + LD_PRELOAD | Low | Low | Standard |
| mimalloc | apt + LD_PRELOAD | Very Low | Very Low | Standard |
| OpenBSD malloc | Recompile Tor | High | Very Low | High |

### Option 1: jemalloc (Recommended)

jemalloc is designed to reduce fragmentation and is widely used in production systems (Firefox, Redis, Facebook). Can be used via LD_PRELOAD without recompiling Tor.

**Installation:**
```bash
sudo apt install libjemalloc2
```

**Usage via LD_PRELOAD:**
```bash
# Edit systemd service file
sudo systemctl edit tor@relay_name
# Add:
[Service]
Environment="LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so.2"
```

### Option 2: tcmalloc (Google)

Google's thread-caching malloc, good for multi-threaded applications.

**Installation:**
```bash
sudo apt install libgoogle-perftools4
```

**Usage via LD_PRELOAD:**
```bash
Environment="LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libtcmalloc.so.4"
```

### Option 3: mimalloc (Microsoft)

Modern allocator with excellent fragmentation handling.

**Installation:**
```bash
sudo apt install libmimalloc2.0
```

**Usage via LD_PRELOAD:**
```bash
Environment="LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libmimalloc.so"
```

### Option 4: OpenBSD malloc (Tor Recommended)

Officially recommended by Tor Project. More secure but uses more CPU. Requires recompiling Tor from source.

**Compile Tor from source:**
```bash
sudo apt install build-essential libevent-dev libssl-dev zlib1g-dev
git clone https://gitlab.torproject.org/tpo/core/tor.git
cd tor
./autogen.sh
./configure --enable-openbsd-malloc
make && sudo make install
```

## Recommendations

1. **Test jemalloc via LD_PRELOAD** - Easiest to deploy, no recompilation needed
2. **Test mimalloc** - Modern allocator with excellent performance characteristics
3. **Periodic Restarts** - Schedule rolling restarts as interim workaround
4. **MaxConsensusAgeForDiffs** - Test limiting consensus diff cache age
5. **Report to Tor Project** - Submit findings to GitLab

## Next Steps

### Proposed Experiments

#### Experiment 1: jemalloc vs glibc (10 days)

**Objective:** Compare memory usage with jemalloc allocator vs default glibc

| Group | Relays | Configuration |
|-------|--------|---------------|
| A | 5 | jemalloc via LD_PRELOAD |
| B | 5 | Control (glibc default) |

**Settings:**
- DirCache: default (enabled)
- MaxMemInQueues: default
- Collection: Daily via `collect.sh`

**Expected Outcome:** jemalloc relays will show lower fragmentation and stable memory around 1-2 GB instead of 5 GB.

#### Experiment 2: mimalloc vs tcmalloc (10 days)

**Objective:** Compare modern allocators for fragmentation handling

| Group | Relays | Configuration |
|-------|--------|---------------|
| A | 4 | mimalloc via LD_PRELOAD |
| B | 4 | tcmalloc via LD_PRELOAD |
| C | 2 | Control (glibc) |

**Settings:**
- DirCache: default (enabled)
- MaxMemInQueues: default
- Collection: Daily via `collect.sh`

**Expected Outcome:** Identify which allocator provides best memory efficiency while maintaining guard status.

#### Experiment 3: MaxConsensusAgeForDiffs (7 days)

**Objective:** Test if limiting consensus diff cache reduces fragmentation

| Group | Relays | Configuration |
|-------|--------|---------------|
| A | 3 | MaxConsensusAgeForDiffs 4 hours |
| B | 3 | MaxConsensusAgeForDiffs 8 hours |
| C | 3 | Control (default - no limit) |

**Settings:**
- DirCache: default (enabled)
- Allocator: glibc (isolate one variable)
- Collection: Daily via `collect.sh`

**Expected Outcome:** Lower diff cache age may reduce memory pressure without losing guard status.

#### Experiment 4: Rolling Restart Impact (14 days)

**Objective:** Measure effectiveness of periodic restarts as workaround

| Group | Relays | Configuration |
|-------|--------|---------------|
| A | 3 | Restart every 24 hours |
| B | 3 | Restart every 48 hours |
| C | 3 | Restart every 72 hours |
| D | 3 | Control (no restarts) |

**Settings:**
- DirCache: default
- Allocator: glibc
- Collection: Every 6 hours via `collect.sh`

**Expected Outcome:** Determine optimal restart interval that balances memory usage with service continuity.

### Implementation Checklist

- [ ] **Experiment 1**: Deploy jemalloc on 5 test relays
- [ ] **Experiment 2**: Deploy mimalloc and tcmalloc comparison
- [ ] **Experiment 3**: Test MaxConsensusAgeForDiffs settings
- [ ] **Experiment 4**: Implement rolling restart schedule
- [ ] **Report to Tor Project**: Submit findings to GitLab with data

## Data Reference

- **Experiment directory**: `reports/2025-09-18-co-guard-fragmentation/`
- **Legacy data**: `data.csv` (13 relays, 9 days, day-column format)
- **Unified data**: `measurements.csv` (72 relay measurements, 7 aggregate rows)
- **Relay config**: `relay_config.csv` (13 relays across 5 groups)
- **Raw data period**: 2025-09-09 to 2025-09-18

## References

1. [Tor FAQ: Why is my Tor relay using so much memory?](https://2019.www.torproject.org/docs/faq.html.en#RelayMemory) - Documents glibc malloc fragmentation and `--enable-openbsd-malloc` solution
2. [Tor Community: Relay Post-Install](https://community.torproject.org/relay/setup/post-install/) - General relay setup and maintenance guidance
3. [Tor Manual (torrc options)](https://2019.www.torproject.org/docs/tor-manual.html.en) - Configuration reference for `MaxMemInQueues`, `MaxConsensusAgeForDiffs`, etc.
4. [Tor Specification: Directory Cache Operation](https://spec.torproject.org/dir-spec/directory-cache-operation.html) - Technical details on consensus diff caching
5. [Tor GitLab Issue Tracker](https://gitlab.torproject.org/tpo/core/tor/-/issues) - For reporting findings and tracking related issues
6. [jemalloc Documentation](https://jemalloc.net/) - Alternative allocator with better fragmentation handling
7. [mimalloc GitHub](https://github.com/microsoft/mimalloc) - Microsoft's high-performance allocator
8. [Tor Forum](https://forum.torproject.org/) - Community discussions on relay operation

---

*Experiment conducted: 2025-09-09 to 2025-09-18*  
*Report generated: 2025-12-26*
