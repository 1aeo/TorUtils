# MaxMemInQueues Won't Save Your Relay's Memory

**By 1AEO Team • January 2026**

Tor's `MaxMemInQueues` setting sounds like the answer to memory bloat—set a cap and Tor will respect it. We tested it. It doesn't work for fragmentation. Neither does `MaxConsensusAgeForDiffs`.

## MaxMemInQueues: The Wrong Target

In our first experiment, relays with `MaxMemInQueues 2GB` fragmented from 0.55 GB to 4.17 GB in under a week—a 658% increase. The 4GB setting performed even worse. Control relays hit 5.14 GB.

The problem: MaxMemInQueues only limits circuit and connection buffers. Directory cache allocations—the actual source of fragmentation—are unaffected. Tor respects your limit; glibc's fragmentation doesn't.

## MaxConsensusAgeForDiffs: No Better

We hypothesized that limiting how long Tor keeps consensus diffs might reduce allocation churn. Our 90-relay experiment tested two settings:

| Configuration | Avg Memory |
|--------------|------------|
| MaxConsensusAgeForDiffs 4 hours | 5.76 GB |
| MaxConsensusAgeForDiffs 8 hours | 5.72 GB |
| Control (glibc, no tuning) | 5.64 GB |

Both performed *identically* to the control group—or slightly worse. The fragmentation pattern remained unchanged.

## Periodic Restarts: A Partial Workaround

We also tested scheduled restarts as a brute-force solution:

| Restart Interval | Avg Memory |
|-----------------|------------|
| Every 24 hours | 4.88 GB |
| Every 48 hours | 4.56 GB |
| Every 72 hours | 5.29 GB |

Restarts help, but not dramatically—and they interrupt relay availability and circuit continuity. The 48-hour interval performed best, but even then memory averaged 4.56 GB.

## The Real Fix

Tor's memory problem isn't about configuration limits—it's about glibc's inability to handle fragmented allocations. Alternative allocators like mimalloc and jemalloc solve the root cause. MaxMemInQueues and consensus tuning are useful for other purposes, but they won't fix your 5 GB memory problem.

---

*Data from 1AEO's memory experiments, September 2025 and December 2025 – January 2026*
