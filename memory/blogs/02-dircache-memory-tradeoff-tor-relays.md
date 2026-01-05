# DirCache and Memory: A 94% Reduction You Probably Can't Use

**By 1AEO Team • January 2026**

During our Tor relay memory investigation, we discovered a setting that slashes memory usage by 94%—from 5+ GB down to ~300 MB. There's just one catch: it removes your relay's Guard flag.

## What We Found

In our September 2025 experiment with 13 guard relays, disabling the directory cache (`DirCache 0`) produced dramatic results:

| Configuration | Start RSS | End RSS | Change |
|--------------|-----------|---------|--------|
| DirCache 0 + MaxMem 2GB | 5.35 GB | 0.29 GB | **-94.6%** |
| DirCache 0 only | — | 0.33 GB | **-93.8%** |
| MaxMem 2GB only | 0.55 GB | 4.17 GB | +658% |
| Control (default) | 0.57 GB | 5.14 GB | +802% |

Memory remained rock-stable for 9+ days with DirCache disabled—no fragmentation, no gradual creep.

## Why It Works (And Why It Hurts)

Tor's directory cache stores consensus data and diffs to serve other relays and clients. This cache creates thousands of small allocations that glibc never efficiently reclaims. Disabling DirCache eliminates the allocation churn entirely.

The problem: Guard relays must serve directory information to maintain their Guard flag. Within days of enabling `DirCache 0`, our relays lost Guard status. For middle relays this might be acceptable, but for guards it's a non-starter.

## The Lesson

DirCache 0 proved that fragmentation—not Tor itself—is the memory problem. The directory cache's allocation pattern combined with glibc's reclamation weakness creates the 5 GB bloat. This insight led us to test alternative allocators, which solve the problem without sacrificing Guard status.

If you're running middle relays and don't need the Guard flag, `DirCache 0` remains a valid option. For guards, see our allocator comparison instead.

---

*Data from 1AEO's guard relay memory investigation, September 2025*
