# Tor Memory Optimization: What Actually Works

**By 1AEO Team • January 2026**

Over the past four months, we conducted extensive memory experiments across 100+ relay-days on high-bandwidth Tor relays running **Ubuntu 24.04** with **Tor 0.4.8.x**. Our goal: understand why Guard relays on Linux consistently see memory "stick" at 5–6 GB after ~48 hours—and how to fix it.

## Key Findings

1. **The Culprit:** Memory fragmentation in glibc's allocator, caused by high churn of Directory Cache objects
2. **False Hopes:** Standard config tweaks like `MaxMemInQueues` don't fix this. Disabling `DirCache` works but disqualifies you as a Guard
3. **The Fix:** Changing the memory allocator is the only viable solution

## What We Tested

| Approach | Result | Viable? |
|----------|--------|---------|
| **mimalloc 2.1** | 1.16 GB (79% ↓) | ✅ Yes |
| **jemalloc 5.3** | 1.63 GB (71% ↓) | ✅ Yes |
| tcmalloc 4.5 | 3.68 GB (35% ↓) | ⚠️ Partial |
| DirCache 0 | 0.29 GB (94% ↓) | ❌ Loses Guard |
| MaxMemInQueues | ~5 GB (no change) | ❌ No |
| MaxConsensusAgeForDiffs | ~5.7 GB (no change) | ❌ No |
| Periodic restarts | 4.5–5 GB (minimal) | ⚠️ Workaround only |

## The Problem Visualized

![Memory Fragmentation by Group](memory_by_group.png)

The chart shows the stark difference: glibc groups (D, E, Z) plateau at 5–6 GB while mimalloc (B) and jemalloc (A) stay under 2 GB. This isn't a gradual leak—it's a sudden expansion around Day 2 that never recovers under glibc.

## Recommendation

For operators running Guard relays on Ubuntu 24.04, move away from the default allocator. Switching to **mimalloc** or **jemalloc** reduced our memory footprint by 70–80% without any loss in performance, stability, or Guard status.

```bash
# Ubuntu 24.04 - Quick deploy
sudo apt install libmimalloc2.0  # mimalloc 2.1.2
sudo systemctl edit tor@relay_name
# Add: Environment="LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libmimalloc.so.2"
```

With this single change, you can run more relays on the same hardware—capacity you can reinvest in the network.

---

*Based on 1AEO's memory experiments across 100+ relays on Ubuntu 24.04, September 2025 – January 2026*

📊 **Raw data:** [Sept 2025 experiment](https://github.com/1aeo/TorUtils/tree/main/memory/reports/2025-09-18-co-guard-fragmentation) | [Dec 2025 experiment](https://github.com/1aeo/TorUtils/tree/main/memory/reports/2025-12-26-co-unified-memory-test)
