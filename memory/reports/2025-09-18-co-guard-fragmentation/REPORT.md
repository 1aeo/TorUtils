# Tor Relay Memory Investigation Report

## Executive Summary

**Problem:** Tor guard relays consuming ~5 GB RAM each  
**Cause:** Memory fragmentation from directory caching + glibc malloc  
**Goal:** Reduce memory while maintaining guard relay status

> **Note:** This is a known issue. The Tor Project acknowledges that "On Linux, glibc's malloc implementation has bugs that can lead to memory fragmentation" and recommends alternative allocators.  
> — [Tor Support: Relay Memory](https://support.torproject.org/relay-operators/relay-memory/)

### Investigation Results

| Configuration | Memory | Guard Status | Viable? |
|---------------|--------|--------------|---------|
| Default (DirCache enabled) | ~5 GB/relay | ✅ Maintained | ❌ Too much memory |
| `DirCache 0` | ~0.3 GB/relay | ❌ Lost | ❌ Unacceptable |
| `MaxMemInQueues` only | ~4-5 GB/relay | ✅ Maintained | ❌ Doesn't help |

**Conclusion:** No acceptable solution found yet. `DirCache 0` solves memory but removes guard status. Guard relays require directory caching, which causes fragmentation with glibc malloc.

### Root Cause Confirmed

The memory issue is caused by:
1. Directory caching (required for guard relays) creates fragmented allocations
2. glibc malloc does not efficiently release fragmented memory
3. Physical memory grows to match virtual memory over ~48 hours

**Next step:** Investigate alternative memory allocators (jemalloc, tcmalloc) that handle fragmentation better.

### Key Results (9-Day Study)

| Configuration | Final RSS | Reduction | Stable? | Guard Status |
|---------------|-----------|-----------|---------|--------------|
| DirCache 0 + MaxMem 2GB | 0.29 GB | 94.6% | ✅ | ❌ Lost |
| DirCache 0 only | 0.33 GB | 93.8% | ✅ | ❌ Lost |
| MaxMem 2GB only | 4.17 GB | 22% | ❌ | ✅ Kept |
| MaxMem 4GB only | 4.76 GB | 11% | ❌ | ✅ Kept |
| No optimization | 5.14 GB | - | ❌ | ✅ Kept |

**Conclusion:** `DirCache 0` solves memory fragmentation but is not viable for guard relays. Alternative approaches needed.

---

## Experiments

### Experiment 1: Baseline (Day 0)

**Goal:** Measure unoptimized relay memory usage

| Relay | RSS (GB) | VmSize (GB) | Frag Ratio |
|-------|----------|-------------|------------|
| 22gz | 5.03 | 10.00 | 1.99:1 |
| 24kgoldn | 5.40 | 9.88 | 1.94:1 |
| 42dugg | 5.61 | 9.95 | 2.01:1 |
| **Avg** | **5.35** | **9.94** | **1.98:1** |

**Finding:** Each relay uses ~5 GB physical memory with poor efficiency.

---

### Experiment 2: DirCache 0 + MaxMem 2GB (Days 0-9)

**Goal:** Test combined optimization  
**Config:** `DirCache 0` + `MaxMemInQueues 2 GB`  
**Relays:** 22gz, 24kgoldn, 42dugg

| Relay | Day 0 | Day 1 | Day 2 | Day 3 | Day 4 | Day 5 | Day 9 |
|-------|-------|-------|-------|-------|-------|-------|-------|
| 22gz | 5.03 | 0.28 | 0.32 | 0.34 | 0.32 | 0.33 | 0.27 |
| 24kgoldn | 5.40 | 0.33 | 0.37 | 0.38 | 0.37 | 0.38 | 0.32 |
| 42dugg | 5.61 | 0.31 | 0.36 | 0.37 | 0.36 | 0.36 | 0.29 |
| **Avg** | **5.35** | **0.31** | **0.35** | **0.36** | **0.35** | **0.36** | **0.29** |

**Finding:** ✅ Immediate 94% reduction, stable for 9+ days.

---

### Experiment 3: Control - No Optimization (Days 1-9)

**Goal:** Confirm fragmentation without optimization  
**Config:** None (default)  
**Relay:** armanicaesar

| Day 1 | Day 2 | Day 3 | Day 4 | Day 5 | Day 9 |
|-------|-------|-------|-------|-------|-------|
| 0.57 | **5.15** | 5.40 | 5.41 | 5.62 | 5.14 |

**Finding:** 🚨 Memory explodes from 0.57 GB to 5.15 GB within 24 hours.

---

### Experiment 4: MaxMemInQueues Only (Days 1-9)

**Goal:** Test if MaxMemInQueues alone prevents fragmentation  
**Config:** `MaxMemInQueues 2 GB` (no DirCache 0)  
**Relays:** arsonaldarebel, autumntwinuzis, ayeverb

| Relay | Day 1 | Day 2 | Day 3 | Day 4 | Day 5 | Day 9 |
|-------|-------|-------|-------|-------|-------|-------|
| arsonaldarebel | 0.55 | 0.55 | **3.86** | 4.03 | 4.17 | 4.17 |
| autumntwinuzis | 0.55 | 0.55 | **3.19** | 3.52 | 3.62 | 4.06 |
| ayeverb | 0.56 | 0.56 | **3.78** | 3.84 | 4.18 | 4.29 |
| **Avg** | **0.55** | **0.55** | **3.61** | **3.80** | **3.99** | **4.17** |

**Finding:** ❌ Stable for 2 days, then fragments on Day 3. MaxMemInQueues alone fails.

Also tested `MaxMemInQueues 4 GB` (relays: babyfaceray, babysmoove, bbno) - same result, slightly worse (4.76 GB by Day 9).

---

### Experiment 5: DirCache 0 Only (Days 4-9)

**Goal:** Test if DirCache 0 alone is sufficient  
**Config:** `DirCache 0` (no MaxMemInQueues)  
**Relays:** bfbdapackman, biggk, bigpokeyhouston

| Relay | Day 4 | Day 5 | Day 9 |
|-------|-------|-------|-------|
| bfbdapackman | 0.42 | 0.39 | 0.32 |
| biggk | 0.44 | 0.40 | 0.34 |
| bigpokeyhouston | 0.42 | 0.36 | 0.32 |
| **Avg** | **0.43** | **0.38** | **0.33** |

**Finding:** ✅ DirCache 0 alone achieves 93.8% reduction and remains stable.

---

## Root Cause

**Why it happens:**
1. Tor's directory cache creates many small allocations
2. glibc malloc doesn't efficiently release fragmented memory
3. After ~48 hours, fragmentation causes RSS to explode

> "Bugs in Linux's glibc malloc can cause memory fragmentation, preventing Tor from returning memory to the operating system."  
> — [Tor Support: Relay Memory](https://support.torproject.org/relay-operators/relay-memory/)

**Why DirCache 0 reduces memory:**
- Disables directory caching
- Prevents allocation churn that causes fragmentation
- But: Guard relays REQUIRE directory caching for Guard flag

**Why MaxMemInQueues doesn't help:**
- Only limits circuit/connection buffers (default 8GB on systems with >8GB RAM)
- Does NOT limit directory cache (the actual problem)

> "For servers with 8 GB of memory, the default queue size limit of 8GB may lead to overload states."  
> — [Tor Support: Relay Overload](https://support.torproject.org/relay-operators/relay-bridge-overloaded/)

**The Core Problem:**
- Guard relays must have `DirCache` enabled (default)
- Directory caching + glibc malloc = memory fragmentation
- Need to fix the allocator, not disable caching

**Additional Memory Factors (per Tor docs):**
- Fast relays use ~38KB per TLS socket for OpenSSL buffers
- Normal memory usage for fast exit relays: 500-1000 MB
- Our 5GB usage is ~5x higher than documented norms

---

## Reproduction

### Check Current Memory Usage

```bash
# Quick summary
ps aux | grep tor | grep -v grep | awk '{sum+=$6} END {print sum/1024/1024 " GB total"}'

# Per-relay detail
./tor_memory_tool.sh status
```

### Monitor a Relay

```bash
# Watch specific relay
./tor_memory_tool.sh watch 22gz

# Get detailed metrics
./tor_memory_tool.sh detail 22gz
```

### Collect Data for Analysis

```bash
# CSV output for all relays
./tor_memory_tool.sh csv > memory_snapshot_$(date +%Y%m%d).csv
```

### Test DirCache 0 (Converts to Middle Relay)

```bash
# Only use if willing to lose guard status
./tor_memory_tool.sh apply --dry-run  # Preview
./tor_memory_tool.sh apply relay1     # Apply to test relay
```

---

## Next Steps

The investigation confirmed that memory fragmentation from glibc malloc is the root cause. Since `DirCache 0` is not viable for guard relays, alternative approaches to explore:

### 1. Alternative Memory Allocators (Recommended by Tor Project)

The Tor Project officially recommends compiling Tor with OpenBSD's malloc to avoid glibc fragmentation:

> "You can compile Tor with OpenBSD malloc instead of glibc's malloc. If you do, Tor will be less vulnerable to memory fragmentation [...] This can be done by configuring Tor with the `--enable-openbsd-malloc` option."  
> — [Tor Support: Relay Memory](https://support.torproject.org/relay-operators/relay-memory/)

```bash
# OpenBSD malloc - Officially recommended by Tor Project
# Download Tor source and compile with:
./configure --enable-openbsd-malloc
make && sudo make install

# jemalloc - Alternative, good fragmentation handling
sudo apt install libjemalloc-dev
./configure --with-malloc=jemalloc
make && sudo make install

# tcmalloc - Google's allocator
sudo apt install libgoogle-perftools-dev
./configure --with-malloc=tcmalloc
make && sudo make install
```

> **Trade-off:** "OpenBSD malloc uses more CPU than glibc's malloc."  
> — [Tor Support: Relay Memory](https://support.torproject.org/relay-operators/relay-memory/)

**Expected outcome:** Reduced fragmentation while keeping DirCache enabled.

### 2. Periodic Relay Restarts

Schedule rolling restarts to reset memory fragmentation. While the Tor Project doesn't provide explicit guidance on restart schedules, it is a common administrative practice for long-running services experiencing memory fragmentation.

> Note: The Tor Project recommends running relays with sufficient RAM rather than frequent restarts. However, restarts can be a practical workaround until a proper fix is implemented.  
> — [Tor Support: Relay Overload](https://support.torproject.org/relay-operators/relay-bridge-overloaded/)

```bash
# Restart one relay per hour via cron (rolling restarts across 24 hours)
0 * * * * /usr/bin/systemctl restart tor@$(ls /etc/tor/instances | sed -n "$(($(date +\%H) + 1))p")
```

**Trade-off:** Brief service interruption, but maintains guard status. Schedule during low-traffic periods.

### 3. Reduce Advertised Bandwidth

The Tor Project suggests reducing bandwidth to reduce memory load:

> "You can try reducing your relay's bandwidth by using the `MaxAdvertisedBandwidth` option in your `torrc`."  
> — [Tor Support: Relay Memory](https://support.torproject.org/relay-operators/relay-memory/)

```
# Reduce advertised bandwidth to decrease load
MaxAdvertisedBandwidth 20 MB
```

**Trade-off:** Lower bandwidth attracts fewer users but reduces memory pressure.

### 4. Limit Consensus Diff Cache

The `MaxConsensusAgeForDiffs` option limits how long consensus documents are retained for generating diffs, reducing cache size and memory pressure.

> "When this option is nonzero, Tor caches will not try to generate consensus diffs for any consensus older than this amount of time. [...] You should not set this option unless your cache is severely low on disk space or CPU. If you need to set it, keeping it above 3 or 4 hours will help clients much more than setting it to zero."  
> — [Tor Manual](https://2019.www.torproject.org/docs/tor-manual.html.en)

```
# Limit consensus diff cache age (reduces memory/disk from diff-cache)
MaxConsensusAgeForDiffs 4 hours
```

Community reports indicate this significantly reduces files in the `diff-cache` directory.  
— [Tor Forum Discussion](https://forum.torproject.org/t/tor-fills-tmp-space-and-crashes/17725)

For more details on directory cache behavior, see:  
— [Tor Spec: Directory Cache Operation](https://spec.torproject.org/dir-spec/directory-cache-operation.html)

### 5. Kernel Memory Settings (Linux Administration)

These are general Linux kernel tuning options, not Tor-specific guidance. They may help with memory management but are not officially recommended by the Tor Project.

```bash
# Trigger memory compaction (one-time)
echo 1 > /proc/sys/vm/compact_memory

# Tune writeback thresholds (may help with memory pressure)
sysctl -w vm.dirty_ratio=10
sysctl -w vm.dirty_background_ratio=5
```

**Note:** These settings affect system-wide behavior. Test carefully before applying to production systems.

### 6. Monitor and Document

Continue monitoring to establish patterns:

```bash
# Daily memory snapshot
./tor_memory_tool.sh csv >> /var/log/tor_memory_history.csv
```

### 7. Report to Tor Project

No existing GitLab issues were found documenting this specific guard relay memory problem. Consider submitting our findings:

- **GitLab:** https://gitlab.torproject.org/tpo/core/tor/-/issues
- Include: Data from this investigation, reproduction steps, system specs
- This could help other operators and inform future Tor development

---

## Data Reference

Complete raw data in `tor_memory_data.csv`:
- 13 relays across 5 test groups
- 9 days of measurements
- RSS, VmSize, and fragmentation metrics

---

## References

### Official Tor Project Documentation

1. **Tor Support: My relay is using too much memory**  
   https://support.torproject.org/relay-operators/relay-memory/  
   - Documents glibc malloc fragmentation issue
   - Recommends `--enable-openbsd-malloc` compile option
   - Notes OpenSSL buffer memory (~38KB per socket)
   - Recommends `MaxAdvertisedBandwidth` to reduce load
   - States fast exit relays use 500-1000 MB normally

2. **Tor Support: How can I tell if my relay is overloaded?**  
   https://support.torproject.org/relay-operators/relay-bridge-overloaded/  
   - `MaxMemInQueues` default is 8GB on systems with ≥8GB RAM
   - OOM handler triggers at 75% of available memory
   - Recommends minimum 2GB RAM (4GB for 64-bit)

3. **Tor Manual (torrc options)**  
   https://2019.www.torproject.org/docs/tor-manual.html.en  
   - `MaxConsensusAgeForDiffs` - limits consensus diff cache age
   - `MaxMemInQueues` - limits queue memory
   - `MaxAdvertisedBandwidth` - limits advertised bandwidth

4. **Tor Specification: Directory Cache Operation**  
   https://spec.torproject.org/dir-spec/directory-cache-operation.html  
   - Details on consensus diff generation and caching
   - Technical specification for directory caches

5. **Tor Specification: Memory Exhaustion Attacks**  
   https://spec.torproject.org/dos-spec/memory-exhaustion.html  
   - Documents memory-based DoS vulnerabilities
   - Explains how buffers and queues can be exploited

### Community Resources

6. **Tor Forum: Tor fills /tmp space and crashes**  
   https://forum.torproject.org/t/tor-fills-tmp-space-and-crashes/17725  
   - Community reports on `MaxConsensusAgeForDiffs` effectiveness
   - Practical experience reducing diff-cache size

7. **Tor GitLab Issues**  
   https://gitlab.torproject.org/tpo/core/tor/-/issues  
   - No existing issues found for guard relay memory fragmentation
   - Consider submitting our findings as a new issue

8. **Tor Blog: Release 0.4.5.6**  
   https://blog.torproject.org/new-release-tor-0456/  
   - Introduced consensus diff cache limit (64 items on Windows)
   - Addressed high CPU usage from consensus diff generation

---

*Investigation: September 9-18, 2025 | Report: December 24, 2025*

