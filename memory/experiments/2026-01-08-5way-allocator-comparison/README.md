# 5-Way Memory Allocator Comparison

**Period:** December 31, 2025 - January 8, 2026  
**Server:** go.1aeo.com (200 Tor relays)  
**Status:** ✅ Concluded

## Summary

Compared 5 memory allocators to address Tor relay memory bloat:

| Rank | Allocator | Avg Memory | Recommendation |
|------|-----------|------------|----------------|
| 🥇 | mimalloc 2.0.9 | 1.28 GB | **Use this** |
| 🥈 | mimalloc 2.1.7 | 1.72 GB | Good alternative |
| 🥉 | jemalloc 5.3.0 | 2.64 GB | Available via apt |
| 4 | glibc 2.41 | 4.01 GB | System default |
| 5 | mimalloc 3.0.1 | 8.62 GB | ❌ Avoid (regression) |

## Key Finding

**mimalloc 3.0.1 has a severe regression** - it uses 6.7x more memory than 2.0.9 and grows unbounded (~1 GB/day).

## Files

```
.
├── REPORT.md           # Full experiment report
├── README.md           # This file
├── memory.csv          # Memory measurements (200 relays, 17 data points)
├── events.csv          # Experiment timeline events
├── diagnostics.csv     # System diagnostics
├── experiment_chart.py # Chart generation script
├── charts/
│   ├── memory_timeseries.png    # 5-way comparison over time
│   ├── memory_distribution.png  # Per-relay distribution
│   ├── memory_trajectories.png  # Individual relay trends
│   ├── memory_usage.png         # Overall usage
│   ├── memory_weekly.png        # Weekly aggregation
│   ├── memory_comparison.png    # Side-by-side comparison
│   └── memory_boxplot.png       # Statistical distribution
└── groups/
    ├── group_A_mimalloc301.txt  # mimalloc 3.0.1 (20 relays)
    ├── group_B_mimalloc209.txt  # mimalloc 2.0.9 (80 relays)
    ├── group_C_mimalloc217.txt  # mimalloc 2.1.7 (60 relays)
    ├── group_D_jemalloc.txt     # jemalloc (20 relays)
    └── group_E_glibc.txt        # glibc control (20 relays)
```

## Reproduction

```bash
# Regenerate charts from this data
python3 experiment_chart.py

# Or use the standard tools
python3 ../../tools/timeseries-charts.py \
  --data memory.csv \
  --output-dir charts/ \
  --title "go" \
  --prefix "memory"
```

## Configuration

To use mimalloc 2.0.9 on a Tor relay:

```bash
# 1. Install custom mimalloc to /usr/local/lib/mimalloc/
sudo cp libmimalloc-2.0.9.so /usr/local/lib/mimalloc/

# 2. Create systemd override
sudo mkdir -p /etc/systemd/system/tor@RELAY.service.d/
sudo tee /etc/systemd/system/tor@RELAY.service.d/allocator.conf <<EOF
[Service]
Environment="LD_PRELOAD=/usr/local/lib/mimalloc/libmimalloc-2.0.9.so"
EOF

# 3. Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart tor@RELAY
```

## See Also

- [Full Report](REPORT.md) - Detailed analysis and recommendations
- [Previous Investigation](../../reports/2025-09-18-co-guard-fragmentation/) - glibc fragmentation study

