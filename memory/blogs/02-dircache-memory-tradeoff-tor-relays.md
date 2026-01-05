# The DirCache Dilemma: The Fix We Can't Use (Yet)

**By 1AEO Team • January 2026**

In September 2025 we investigated a pattern on our guard relays: memory looked normal after restart (~0.5 GB), then after ~48 hours RSS jumped and "stuck" around 5 GB. That's costly at fleet scale and a reliability risk.

We tested a radical configuration: `DirCache 0`. The impact was immediate and dramatic.

## What We Found

| Configuration | Start RSS | End RSS | Change |
|--------------|-----------|---------|--------|
| DirCache 0 | — | 0.33 GB | **-93.8%** |
| Control (default) | 0.57 GB | 5.14 GB | +802% |

Memory remained stable for 9+ days with DirCache disabled—no fragmentation, no gradual creep.

![DirCache 0 vs Control Memory Usage](chart_dircache.png)

## The Catch

There's no free lunch. Disabling DirCache instantly revokes your relay's Guard status. The network requires Guards to handle directory traffic, so you cannot turn this feature off to save RAM if you want to remain a Guard.

## The Diagnostic Value

The control relay shows the signature "fragmentation spike" inside the ~48-hour window, while the `DirCache 0` relay remains flat. This experiment proved that memory isn't "leaking" in the traditional sense—it's being **fragmented by the churn of directory data**.

Since `DirCache 0` is incompatible with Guard operation, the practical path is allocator-level mitigation (jemalloc/mimalloc) so guards can keep caching *without* ballooning to 5–6 GB RSS.

---

*Data from 1AEO's guard relay investigation, September 2025*

📊 **Raw data:** [View experiment data and relay configs on GitHub](https://github.com/1aeo/TorUtils/tree/main/memory/reports/2025-09-18-co-guard-fragmentation)
