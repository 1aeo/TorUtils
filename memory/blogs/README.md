# Tor Relay Memory Optimization Blog Series

Four blog posts summarizing findings from 1AEO's memory experiments under `TorUtils/memory/reports`.

## Blog Overview

| # | Title | Focus | Chart |
|---|-------|-------|-------|
| 00 | [Solving Tor Relay Memory Bloat: What Actually Works](00-tor-relay-memory-optimization-summary.md) | Executive summary | memory_by_group.png |
| 01 | [Memory Allocators: The 80% Solution](01-memory-allocators-tor-relay-fragmentation.md) | jemalloc, mimalloc, tcmalloc | memory_by_group.png |
| 02 | [DirCache and Memory: A 94% Reduction You Can't Use](02-dircache-memory-tradeoff-tor-relays.md) | DirCache 0 tradeoffs | (chart1_memory_over_time.png) |
| 03 | [MaxMemInQueues Won't Save Your Relay's Memory](03-maxmeminqueues-consensus-age-dont-help.md) | Config tuning myths | — |

---

## Blog Outlines

### 00 - Summary Blog (Executive Overview)

**Thesis:** Alternative memory allocators solve Tor relay memory bloat without sacrificing Guard status.

1. **The Problem** — 5+ GB RAM from glibc fragmentation
2. **What We Tested** — Table of all approaches and results
3. **The Solution** — mimalloc/jemalloc via LD_PRELOAD
4. **Key Takeaways** — Four bullet points
5. **Chart** — memory_by_group.png

---

### 01 - Memory Allocators Blog

**Thesis:** mimalloc and jemalloc reduce Tor relay memory by 70-80% without any Tor configuration changes.

1. **Key Findings** — Bullet list: mimalloc (1.16GB), jemalloc (1.63GB), tcmalloc (3.68GB), glibc (5.64GB)
2. **The Experiment** — 90 relays, 9 groups, 14 days, 6-hourly collection
3. **Chart** — memory_by_group.png
4. **Why Alternative Allocators Work** — Fragmentation handling, no recompile needed
5. **How to Deploy** — systemd LD_PRELOAD example
6. **Bottom Line** — Recommendation: mimalloc or jemalloc

---

### 02 - DirCache Blog

**Thesis:** DirCache 0 proves fragmentation is the problem, but isn't viable for guard relays.

1. **What We Found** — Table: DirCache 0 (94% reduction) vs MaxMem vs Control
2. **Why It Works** — Directory cache allocation churn eliminated
3. **Why It Hurts** — Guard flag requires directory serving
4. **The Lesson** — Proof that fragmentation (not Tor) is the issue; leads to allocator testing
5. **When to Use** — Middle relays only

---

### 03 - MaxMemInQueues & Consensus Age Blog

**Thesis:** Tor configuration tuning doesn't solve glibc fragmentation.

1. **MaxMemInQueues: The Wrong Target** — Only limits circuit buffers, not directory cache
2. **MaxConsensusAgeForDiffs: No Better** — Table: 4h/8h settings match control
3. **Periodic Restarts: Partial Workaround** — Table: 24h/48h/72h restart intervals
4. **The Real Fix** — Root cause is allocator, not configuration

---

## Data Sources

- `../reports/2025-09-18-co-guard-fragmentation/` — DirCache and MaxMemInQueues experiment (13 relays, 9 days)
- `../reports/2025-12-26-co-unified-memory-test/` — Allocator comparison experiment (90 relays, 14 days)

## Style Notes

Posts follow 1aeo.com/blog conventions:
- Short paragraphs (2-4 sentences)
- Bullet point summaries
- One chart per post
- Data tables for comparisons
- <7 paragraphs per post
- Actionable conclusions
