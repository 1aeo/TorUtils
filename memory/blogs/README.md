# Tor Relay Memory Optimization Blog Series

This directory contains the blog posts and supporting materials for our Tor relay memory optimization research.

## Blog Posts

1. **[Tor Memory Optimization: What Actually Works](tor-memory-optizations-what-actually-works.md)** (Summary)
   - Executive overview of all findings from 103 relays across two studies
   - Chart: `images/tor-memory-optimizations-what-actually-works-chart.png`

2. **[Solving Tor Memory Fragmentation with Custom Allocators](memory-allocators-tor-relay-fragmentation-with-custom-allocators.md)**
   - Detailed comparison of memory allocators (mimalloc, jemalloc, tcmalloc vs glibc)
   - Chart: `images/memory-allocators-tor-relay-fragmentation-with-custom-allocators-chart.png`

3. **[The DirCache Dilemma: The Fix We Can't Reduce Guard Memory With](dircache-memory-trade-off-tor-guard-relays.md)**
   - Analysis of DirCache 0 effectiveness and Guard status tradeoff
   - Chart: `images/dircache-memory-trade-off-tor-guard-relays.png`

4. **[The MaxMemInQueues Myth For Guard Memory](maxmeminqueues-myth-for-guard-memory.md)**
   - Why MaxMemInQueues doesn't solve memory fragmentation
   - Chart: `images/maxmeminqueues_myth_guard_memory.png`

5. **[Periodic Restarts: A Brute-Force Workaround For Reducing Guard Memory](periodic-restarts-workaround-guard-memory.md)**
   - Evaluation of scheduled restarts as a workaround
   - Chart: `images/periodic-restarts-workaround-guard-memory.png`

6. **[MaxConsensusAgeForDiffs: Why Limiting Consensus Cache Doesn't Help Guard Memory](maxconsensusagefordiffs-limiting-for-guard-memory.md)**
   - Testing consensus diff cache limits for memory reduction
   - Chart: `images/maxconsensusagefordiffs-limiting-for-guard-memory.png`

7. **[mimalloc 2.0.9: 5-Way Allocator Test and 200-Relay Deployment](mimalloc-209-tor-relay-deployment.md)**
   - 5-way comparison on 100 relays (5 groups × 20), then 200-relay production migration
   - Chart: `images/mimalloc-209-tor-relay-deployment-chart.png`
   - Data: 6-10 day test periods per group, mimalloc 2.0.9 used 7.4× less memory than 3.0.1

## One-Sentence Summaries (for index)

- **Summary Blog:** After testing allocators, config tweaks, and restarts across 100+ relays, we found that switching to mimalloc or jemalloc is the only fix that actually stops Tor guard memory from ballooning to 5+ GB.
- **Allocators Blog:** Our 90-relay experiment on Ubuntu 24.04 proves that swapping glibc for mimalloc (79% reduction) or jemalloc (71% reduction) keeps Tor guards under 2 GB without recompiling or losing Guard status.
- **DirCache Blog:** Disabling DirCache cuts memory by 94%, but it also removes your Guard flag—making it a diagnostic proof point rather than a viable solution for production Guard relays.
- **MaxMemInQueues Blog:** Despite its promising name, MaxMemInQueues only limits circuit buffers—not the directory cache fragmentation that actually causes Tor relays to bloat to 5 GB.
- **Restarts Blog:** Scheduled restarts can reduce memory by up to 19%, but they disrupt circuits and still leave you at 4.5 GB—use them only as a stopgap while migrating to a better allocator.
- **Consensus Age Blog:** Limiting how long Tor keeps consensus diffs had zero impact on memory—all test groups ended at 5.6–5.8 GB, proving the fragmentation problem lies in glibc, not cache retention.
- **5-Way Deployment Blog:** Testing 5 allocators on 100 relays (20 per group) for 6-10 days showed mimalloc 2.0.9 (1.41 GB) used 7.4× less memory than 3.0.1 (10.44 GB), so we migrated all 200 production relays to 2.0.9.

## Key Takeaways

1. **Root Cause:** Memory fragmentation in glibc's allocator caused by directory cache churn
2. **Best Solution:** Switch to mimalloc 2.0.9 (Debian 13) or mimalloc 2.1 (Ubuntu 24.04)
3. **Config Tweaks Don't Work:** MaxMemInQueues and MaxConsensusAgeForDiffs don't address fragmentation
4. **DirCache 0:** Effective but incompatible with Guard status
5. **Periodic Restarts:** Workaround only, doesn't solve root cause
6. **Avoid mimalloc 3.0.1:** Severe regression on Debian 13

## Results Summary

| Approach | Memory | Reduction | Notes |
|----------|--------|-----------|-------|
| **mimalloc 2.0.9** | **1.41 GB** | **75%** | **Best (Debian 13, build from source)** |
| mimalloc 2.1.7 | 1.83 GB | 68% | Good (Debian 13, build from source) |
| mimalloc 2.1 | 1.16 GB | 79% | Recommended (Ubuntu 24.04: libmimalloc2.0) |
| jemalloc 5.3 | 2.74 GB | 52% | Good fallback (apt: libjemalloc2) |
| tcmalloc 4.5 | 3.68 GB | 35% | Partial improvement |
| DirCache 0 | 0.29 GB | 94% | Loses Guard status |
| MaxMemInQueues | ~5 GB | 0% | Doesn't address fragmentation |
| MaxConsensusAgeForDiffs | ~5.7 GB | 0% | No improvement |
| Periodic restarts | 4.5 GB | 19% | Workaround only |
| glibc 2.41 (control) | 4.15 GB | — | Baseline (Debian 13) |
| glibc 2.39 (control) | 5.64 GB | — | Baseline (Ubuntu 24.04) |
| **mimalloc 3.0.1** | **10.44 GB** | **-151%** | **⚠️ AVOID - Regression** |

## Charts

All charts are located in the `images/` subdirectory:

- `tor-memory-optimizations-what-actually-works-chart.png` - Summary comparison (Blog 1)
- `memory-allocators-tor-relay-fragmentation-with-custom-allocators-chart.png` - Allocator time series (Blog 2)
- `dircache-memory-trade-off-tor-guard-relays.png` - DirCache comparison (Blog 3)
- `maxmeminqueues_myth_guard_memory.png` - MaxMemInQueues comparison (Blog 4)
- `periodic-restarts-workaround-guard-memory.png` - Restart intervals time series (Blog 5)
- `maxconsensusagefordiffs-limiting-for-guard-memory.png` - Consensus age comparison (Blog 6)
- `mimalloc-209-tor-relay-deployment-chart.png` - 5-way comparison (Blog 7)

## Data Sources

- [September 2025 Experiment](../reports/2025-09-18-co-guard-fragmentation/) - 13 relays, 9 days (Ubuntu)
- [December 2025 Experiment](../reports/2025-12-26-co-unified-memory-test/) - 90 relays, 10 days (Ubuntu 24.04)
- [January 2026 5-Way Experiment](../experiments/2026-01-08-5way-allocator-comparison/) - 100 relays (5×20), 6-10 days (Debian 13)
