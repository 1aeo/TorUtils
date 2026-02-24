# mimalloc 2.0.9: 5-Way Allocator Test and 200-Relay Deployment

*By 1AEO Team • January 2026*

*Experiment: 100 relays (5 groups × 20) on Debian 13 with Tor 0.4.8.x*

We tested 5 memory allocators on 100 Tor relays to find the best option for long-running Guard relays. The result: **mimalloc 2.0.9** used 7.4× less memory than mimalloc 3.0.1. We then migrated all 200 relays on the server to the winner.

## Experiment Design

| Group | Allocator | Relays | Test Period | Duration |
|-------|-----------|--------|-------------|----------|
| A | mimalloc 3.0.1 | 20 | Dec 31 – Jan 10 | 10 days |
| B | mimalloc 2.0.9 | 20 | Jan 2 – Jan 10 | 8 days |
| C | mimalloc 2.1.7 | 20 | Jan 2 – Jan 10 | 8 days |
| D | jemalloc 5.3.0 | 20 | Jan 4 – Jan 10 | 6 days |
| E | glibc 2.41 | 20 | Jan 2 – Jan 10 | 8 days |

All 5 groups ran simultaneously from Jan 4–10 (6 days). Each group had 20 relays with identical hardware and Tor configuration.

## Results (Jan 10, 2026)

| Allocator | Avg Memory | vs mimalloc 3.0.1 |
|-----------|------------|-------------------|
| **mimalloc 2.0.9** | **1.41 GB** | **7.4× less** |
| mimalloc 2.1.7 | 1.83 GB | 5.7× less |
| jemalloc 5.3.0 | 2.74 GB | 3.8× less |
| glibc 2.41 | 4.15 GB | 2.5× less |
| mimalloc 3.0.1 | 10.44 GB | — |

![5-Way Allocator Comparison](images/mimalloc-209-tor-relay-deployment-chart.png)

## mimalloc 3.0.1 Regression

mimalloc 3.0.1 showed unbounded memory growth over 10 days:

| Day | Memory |
|-----|--------|
| 1 | ~1.9 GB |
| 5 | ~5.3 GB |
| 10 | 10.44 GB |

The memory continued growing at ~1 GB/day with no sign of stabilizing. In contrast, mimalloc 2.0.9 stabilized at ~1.4 GB by day 3 and remained flat.

## Observation

We don't know why mimalloc 3.0.1 behaves this way. The data shows memory growth; we haven't investigated the root cause in mimalloc's code.

## Security Note

By replacing glibc with mimalloc, you lose glibc's heap-security mitigations
(Safe-Linking, Safe-Unlinking, tcache double-free detection). mimalloc's
out-of-band metadata design provides some passive security benefit, but for
production deployments we recommend building mimalloc in **secure mode**
(`-DMI_SECURE=ON`), which adds guard pages, encrypted free-list pointers,
double-free detection, and allocation randomization — matching or exceeding
glibc's protections with ~10% allocation overhead (negligible for Tor's I/O-bound
workload). See [heap-security-review.md](../docs/heap-security-review.md) for
the full comparison.

## Production Migration

Based on these results, we migrated all 200 relays to mimalloc 2.0.9:

```bash
# Build mimalloc 2.0.9 from source (Debian 13 ships 3.0.1)
# Add -DMI_SECURE=ON for heap-security hardening (recommended)
wget https://github.com/microsoft/mimalloc/archive/refs/tags/v2.0.9.tar.gz
tar xzf v2.0.9.tar.gz && cd mimalloc-2.0.9
mkdir build && cd build && cmake -DMI_SECURE=ON .. && make
sudo mkdir -p /usr/local/lib/mimalloc
sudo cp libmimalloc-secure.so.2.0 /usr/local/lib/mimalloc/libmimalloc-2.0.9-secure.so

# Configure systemd override for each relay
for relay in $(ls /var/lib/tor-instances/); do
    sudo mkdir -p /etc/systemd/system/tor@${relay}.service.d/
    cat <<EOF | sudo tee /etc/systemd/system/tor@${relay}.service.d/allocator.conf
[Service]
Environment="LD_PRELOAD=/usr/local/lib/mimalloc/libmimalloc-2.0.9-secure.so"
EOF
done
sudo systemctl daemon-reload
```

## Debian 13 Warning

The `libmimalloc2.0` package on Debian 13 ships **mimalloc 3.0.1**—the version with the regression. Build 2.0.9 from source instead.

## Summary

| Recommendation | Allocator | Memory |
|----------------|-----------|--------|
| Best | mimalloc 2.0.9 | 1.41 GB |
| Good | mimalloc 2.1.7 | 1.83 GB |
| Acceptable | jemalloc 5.3.0 | 2.74 GB |
| Avoid | mimalloc 3.0.1 | 10.44 GB |

📊 **Data:** [experiments/2026-01-08-5way-allocator-comparison](https://github.com/1aeo/TorUtils/tree/main/memory/experiments/2026-01-08-5way-allocator-comparison)

