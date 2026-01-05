# Memory Allocators: The 80% Solution to Tor Relay Fragmentation

**By 1AEO Team • January 2026**

If you're running Tor guard relays on Linux, you've likely watched memory usage climb to 5+ GB per relay over a few days—even with plenty of free system RAM. The culprit isn't Tor; it's glibc's default memory allocator. We tested alternatives, and the results speak for themselves.

## Key Findings

- **mimalloc** reduced memory usage to **1.16 GB** (79% reduction vs control)
- **jemalloc** achieved **1.63 GB** (71% reduction)
- **tcmalloc** showed **3.68 GB** (35% reduction)
- **glibc control group**: 5.64 GB (fragmented)

## The Experiment

We ran 90 Tor relays across 9 test groups for 14 days, collecting memory data every 6 hours. Groups A, B, and C tested jemalloc, mimalloc, and tcmalloc respectively—all deployed via `LD_PRELOAD` without recompiling Tor. Group Z ran the default glibc allocator as our control.

![Memory by Group](memory_by_group.png)

## Why Alternative Allocators Work

Tor's directory caching creates many small allocations that glibc struggles to release back to the OS. Modern allocators like mimalloc and jemalloc handle fragmentation more efficiently—releasing memory promptly and reducing RSS without impacting relay performance.

The best part: you don't need to recompile Tor. A simple systemd override does the trick:

```bash
sudo systemctl edit tor@relay_name
# Add:
[Service]
Environment="LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libmimalloc.so.2"
```

## Bottom Line

mimalloc delivered the best results in our tests, but jemalloc is a close second and is widely battle-tested in production (Firefox, Redis). Either choice will dramatically reduce your relay's memory footprint while maintaining Guard status and full bandwidth capacity.

---

*Data from 1AEO's 90-relay memory experiment, Dec 2025 – Jan 2026*
