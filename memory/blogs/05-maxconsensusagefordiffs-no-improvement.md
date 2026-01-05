# MaxConsensusAgeForDiffs: Why Limiting Consensus Cache Doesn't Help

**By 1AEO Team • January 2026**

*Experiment: 30 relays over 10 days (Dec 2025–Jan 2026) testing 4h and 8h limits vs control*

When investigating Tor relay memory fragmentation, we hypothesized that the consensus diff cache might be a major contributor. Tor stores multiple versions of network consensus documents to serve diffs to clients—perhaps limiting how long these are kept would reduce allocation churn?

We tested `MaxConsensusAgeForDiffs` at 4 hours and 8 hours against the default. The results: no improvement whatsoever.

## The Results

| Configuration | Avg Memory | vs Control |
|--------------|------------|------------|
| MaxConsensusAgeForDiffs 4h | 5.76 GB | +2% (worse) |
| MaxConsensusAgeForDiffs 8h | 5.72 GB | +1% (worse) |
| Control (default) | 5.64 GB | — |

All three groups followed nearly identical fragmentation curves, converging at 5.6–5.8 GB.

![MaxConsensusAgeForDiffs Comparison](chart_consensus.png)

## Why It Didn't Work

The consensus diff cache is only one part of Tor's directory caching. Even with aggressive limits on diff retention, the relay still:

1. **Caches full consensus documents** for serving to clients
2. **Maintains descriptor caches** for router information
3. **Handles continuous allocation churn** from network updates

The fundamental problem remains: glibc's allocator fragments memory under this workload pattern, regardless of how long individual cache entries are retained.

## When MaxConsensusAgeForDiffs Matters

This setting isn't useless—it just doesn't solve fragmentation:

- **Disk space:** Lower values reduce consensus storage on disk
- **Bandwidth:** Clients with very old consensuses get full documents instead of diffs
- **Specific debugging:** Useful when investigating consensus-related issues

## The Real Fix

Like `MaxMemInQueues`, this is a configuration knob that controls Tor behavior but doesn't address the underlying allocator problem. For memory fragmentation, the solution is switching to mimalloc or jemalloc—which reduced memory from 5.6 GB to 1.1–1.6 GB in our tests.

---

*Data from 1AEO's 90-relay memory experiment on Ubuntu 24.04, Dec 2025 – Jan 2026*

📊 **Raw data:** [View experiment data and relay configs on GitHub](https://github.com/1aeo/TorUtils/tree/main/memory/reports/2025-12-26-co-unified-memory-test)
