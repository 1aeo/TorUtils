# The MaxMemInQueues Myth

**By 1AEO Team • January 2026**

A common piece of advice for high-memory relays: "Just set `MaxMemInQueues` to a lower value." We put this to the test. It doesn't work. Neither does `MaxConsensusAgeForDiffs`.

## MaxMemInQueues: Why It Fails

We configured test groups with strict limits: `MaxMemInQueues 2GB` and `4GB`. Logic suggests the process should stay within these bounds. In reality, both groups fragmented just as badly as the control—hitting ~5 GB within 48 hours.

| Configuration | Avg Memory | Result |
|--------------|------------|--------|
| MaxMemInQueues 2GB | 4.17 GB | Fragmented |
| MaxMemInQueues 4GB | 4.76 GB | Fragmented |
| Control (default) | 5.14 GB | Fragmented |

**Why it failed:** `MaxMemInQueues` strictly limits memory for circuit and connection buffers. It does *not* control the directory cache or the overhead from the allocator itself. The fragmentation happens in memory glibc won't release, not in Tor's queues.

![MaxMemInQueues Comparison](chart2_final_comparison.png)

## MaxConsensusAgeForDiffs: No Better

We hypothesized that limiting consensus diff cache age might reduce allocation churn:

| Configuration | Avg Memory |
|--------------|------------|
| MaxConsensusAgeForDiffs 4h | 5.76 GB |
| MaxConsensusAgeForDiffs 8h | 5.72 GB |
| Control (glibc) | 5.64 GB |

Both performed identically to control—or slightly worse. The fragmentation pattern was unchanged.

## The Real Fix

Configuring queue limits is good practice for overload protection, but don't rely on it to fix memory fragmentation. The root cause is glibc's inability to handle fragmented allocations—only changing the allocator solves the underlying problem.

---

*Data from 1AEO's memory experiments, September 2025 and December 2025 – January 2026*
