# Solving Tor Relay Memory Bloat: What Actually Works

**By 1AEO Team • January 2026**

Tor guard relays on Linux commonly balloon to 5+ GB of RAM within 48 hours of starting—even on servers with abundant memory. We spent four months and 100+ relay-days investigating why, and what to do about it.

## The Problem

Memory fragmentation in glibc's default allocator causes Tor relays to consume 5-10x more RAM than necessary. The directory cache creates thousands of small allocations that glibc cannot efficiently return to the OS, resulting in permanent RSS growth.

## What We Tested

| Approach | Result | Viable? |
|----------|--------|---------|
| **mimalloc allocator** | 1.16 GB (79% reduction) | ✅ Yes |
| **jemalloc allocator** | 1.63 GB (71% reduction) | ✅ Yes |
| **tcmalloc allocator** | 3.68 GB (35% reduction) | ⚠️ Partial |
| DirCache 0 | 0.29 GB (94% reduction) | ❌ Loses Guard flag |
| MaxMemInQueues | 4-5 GB (no improvement) | ❌ No |
| MaxConsensusAgeForDiffs | 5.7 GB (no improvement) | ❌ No |
| Scheduled restarts | 4.5-5 GB (minimal) | ⚠️ Workaround |

## The Solution

Deploy mimalloc or jemalloc via `LD_PRELOAD`. No recompilation needed:

```bash
# Install
sudo apt install libmimalloc2.0  # or libjemalloc2

# Enable per-relay
sudo systemctl edit tor@relay_name
[Service]
Environment="LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libmimalloc.so.2"
```

Restart your relay, and memory will stabilize around 1-2 GB instead of 5+ GB—while maintaining Guard status and full bandwidth.

## Key Takeaways

1. **The problem is glibc, not Tor.** Configuration tuning doesn't help because glibc's allocator is the bottleneck.
2. **Modern allocators work.** mimalloc and jemalloc handle fragmentation efficiently with no performance penalty.
3. **DirCache 0 is a proof point.** The 94% reduction proves fragmentation is the issue, but disabling DirCache costs Guard status.
4. **Deploy is simple.** LD_PRELOAD swaps allocators without rebuilding Tor.

If you're running multiple Tor relays, switching allocators will save significant memory per server—capacity you can reinvest in more relays for the network.

![Memory by Group](memory_by_group.png)

---

*Based on 1AEO's memory experiments across 100+ relays, September 2025 – January 2026*
