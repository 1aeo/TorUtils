# Solving Tor Memory Fragmentation with Custom Allocators

**By 1AEO Team • January 2026**

Running high-capacity Tor relays on Linux often leads to a familiar headache: memory that looks fine after restart, then "sticks" at 5–6 GB after ~48 hours. Our 90-relay experiment on **Ubuntu 24.04** with **Tor 0.4.8.21** confirms that the default system allocator (`glibc 2.39`) is the bottleneck—not Tor itself.

## The Results

The difference was stark. While glibc relays bloated to nearly 6 GB, relays using modern allocators remained stable:

| Allocator | Package (Ubuntu 24.04) | Avg Memory | Reduction |
|-----------|------------------------|------------|-----------|
| **mimalloc 2.1** | `libmimalloc2.0` | 1.16 GB | 79% |
| **jemalloc 5.3** | `libjemalloc2` | 1.63 GB | 71% |
| tcmalloc 4.5 | `libgoogle-perftools4` | 3.68 GB | 35% |
| glibc 2.39 | (default) | 5.64 GB | — |

![Memory Usage by Allocator Group](chart_allocators.png)

## Why Modern Allocators Work

Tor's directory cache creates millions of small allocations that glibc struggles to release back to the OS. Modern allocators like jemalloc and mimalloc handle this fragmentation pattern efficiently—returning memory promptly without the permanent RSS bloat.

## How to Deploy (Ubuntu 24.04)

The best part: no recompilation needed. A simple systemd override swaps the allocator:

```bash
# Install (Ubuntu 24.04)
sudo apt install libmimalloc2.0  # mimalloc 2.1.2
# Or: sudo apt install libjemalloc2  # jemalloc 5.3.0

# Enable per-relay
sudo systemctl edit tor@relay_name
```

Add the override:

```ini
[Service]
Environment="LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libmimalloc.so.2"
```

For jemalloc, use: `/usr/lib/x86_64-linux-gnu/libjemalloc.so.2`

## Bottom Line

If you're running a Guard relay on Ubuntu 24.04, the single most effective optimization isn't in your `torrc`—it's swapping your allocator. We recommend **mimalloc 2.1** (best results) or **jemalloc 5.3** (battle-tested in Firefox/Redis) to reclaim gigabytes of wasted RAM while maintaining Guard status and full bandwidth.

---

*Data from 1AEO's 90-relay memory experiment on Ubuntu 24.04, Dec 2025 – Jan 2026*

📊 **Raw data:** [View experiment data and relay configs on GitHub](https://github.com/1aeo/TorUtils/tree/main/memory/reports/2025-12-26-co-unified-memory-test)
