# The MaxMemInQueues Myth

**By 1AEO Team • January 2026**

*Experiment: 7 relays over 9 days (Sept 2025) testing 2GB and 4GB limits vs control*

A common piece of advice for high-memory relays: "Just set `MaxMemInQueues` to a lower value." We put this to the test. It doesn't work.

## MaxMemInQueues: Why It Fails

We configured test groups with strict limits: `MaxMemInQueues 2GB` and `4GB`. Logic suggests the process should stay within these bounds. In reality, both groups fragmented just as badly as the control—hitting ~5 GB within 48 hours.

| Configuration | Avg Memory | Result |
|--------------|------------|--------|
| MaxMemInQueues 2GB | 4.17 GB | Fragmented |
| MaxMemInQueues 4GB | 4.76 GB | Fragmented |
| Control (default) | 5.14 GB | Fragmented |

**Why it failed:** `MaxMemInQueues` strictly limits memory for circuit and connection buffers. It does *not* control the directory cache or the overhead from the allocator itself. The fragmentation happens in memory glibc won't release, not in Tor's queues.

![MaxMemInQueues Comparison](chart_maxmem.png)

## The Real Fix

Treat `MaxMemInQueues` as a **congestion/buffer safety setting**—not a solution to allocator-driven fragmentation. It's still good practice for overload protection, but if you're seeing RSS "stick" high on guards, you need allocator-level changes (jemalloc/mimalloc) rather than a larger or smaller MaxMem cap.

---

*Data from 1AEO's memory experiments, September 2025 and December 2025 – January 2026*

📊 **Raw data:** [Sept 2025 experiment](https://github.com/1aeo/TorUtils/tree/main/memory/reports/2025-09-18-co-guard-fragmentation) | [Dec 2025 experiment](https://github.com/1aeo/TorUtils/tree/main/memory/reports/2025-12-26-co-unified-memory-test)
