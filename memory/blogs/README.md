# Tor Relay Memory Optimization Blog Series

Four blog posts summarizing findings from 1AEO's memory experiments under `TorUtils/memory/reports`.

## Blog Overview

| # | Title | Focus | Chart |
|---|-------|-------|-------|
| 00 | [Tor Memory Optimization: What Actually Works](00-tor-relay-memory-optimization-summary.md) | Executive summary | memory_by_group.png |
| 01 | [Solving Tor Memory Fragmentation with Custom Allocators](01-memory-allocators-tor-relay-fragmentation.md) | jemalloc, mimalloc, tcmalloc | memory_by_group.png |
| 02 | [The DirCache Dilemma](02-dircache-memory-tradeoff-tor-relays.md) | 94% reduction tradeoff | chart1_memory_over_time.png |
| 03 | [The MaxMemInQueues Myth](03-maxmeminqueues-consensus-age-dont-help.md) | Config tuning myths | chart2_final_comparison.png |
| 04 | [Periodic Restarts: A Brute-Force Workaround](04-periodic-restarts-workaround.md) | Restart intervals | chart3_fragmentation_timeline.png |

---

## Key Takeaways

1. **The Culprit:** Memory fragmentation in glibc's allocator, caused by Directory Cache churn
2. **False Hopes:** `MaxMemInQueues`, `MaxConsensusAgeForDiffs`, and periodic restarts don't solve root cause
3. **The Fix:** Modern allocators (mimalloc, jemalloc) reduce memory 70-80%

## Results Summary (Ubuntu 24.04)

| Allocator | Package | Avg Memory | vs Control |
|-----------|---------|------------|------------|
| mimalloc 2.1 | `libmimalloc2.0` | 1.16 GB | -79% |
| jemalloc 5.3 | `libjemalloc2` | 1.63 GB | -71% |
| tcmalloc 4.5 | `libgoogle-perftools4` | 3.68 GB | -35% |
| glibc 2.39 | (default) | 5.64 GB | baseline |

---

## Charts Included

| File | Description | Used In |
|------|-------------|---------|
| `memory_by_group.png` | Allocator comparison (Dec 2025 experiment) | Blog 00, 01 |
| `chart_dircache.png` | DirCache 0 vs Control timeline | Blog 02 |
| `chart_maxmem.png` | MaxMemInQueues comparison | Blog 03 |
| `chart3_fragmentation_timeline.png` | Restart interval comparison | Blog 04 |
| `bandwidth_by_group.png` | Bandwidth by allocator group | Reference |
| `bandwidth_over_time.png` | Bandwidth timeline | Reference |

---

## Data Sources

- `../reports/2025-09-18-co-guard-fragmentation/` — DirCache and MaxMemInQueues (13 relays, 9 days)
- `../reports/2025-12-26-co-unified-memory-test/` — Allocator comparison (90 relays, 14 days)

## Style Notes

Posts follow 1aeo.com/blog conventions:
- Short paragraphs (2-4 sentences)
- Bullet point summaries
- One chart per post
- Data tables with specific numbers
- <7 paragraphs per post
- Actionable deployment instructions
