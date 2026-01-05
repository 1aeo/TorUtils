# Solving Tor Memory Fragmentation with Custom Allocators

**By 1AEO Team • January 2026**

Running high-capacity Tor relays on Linux often leads to a familiar headache: memory usage that creeps up to 5+ GB despite configuration limits. Our 90-relay experiment confirms that the default system allocator (`glibc`) is the bottleneck—not Tor itself.

## The Results

The difference was stark. While glibc relays bloated to nearly 6 GB, relays using modern allocators remained stable:

| Allocator | Avg Memory | Reduction vs Control |
|-----------|------------|---------------------|
| **mimalloc** | 1.16 GB | 79% |
| **jemalloc** | 1.63 GB | 71% |
| tcmalloc | 3.68 GB | 35% |
| glibc (control) | 5.64 GB | — |

![Memory Usage by Allocator Group](memory_by_group.png)

## Why Modern Allocators Work

Tor's directory cache creates millions of small allocations that glibc struggles to release back to the OS. Modern allocators like jemalloc and mimalloc handle this fragmentation pattern efficiently—returning memory promptly without the permanent RSS bloat.

## How to Deploy

The best part: no recompilation needed. A simple systemd override swaps the allocator:

```bash
# Install
sudo apt install libmimalloc2.0  # or libjemalloc2

# Enable per-relay
sudo systemctl edit tor@relay_name
# Add:
[Service]
Environment="LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libmimalloc.so.2"
```

## Bottom Line

If you're running a Guard relay on Linux, the single most effective optimization isn't in your `torrc`—it's swapping your allocator. We recommend **mimalloc** (best results) or **jemalloc** (battle-tested in Firefox/Redis) to reclaim gigabytes of wasted RAM while maintaining Guard status and full bandwidth.

---

*Data from 1AEO's 90-relay memory experiment, Dec 2025 – Jan 2026*
