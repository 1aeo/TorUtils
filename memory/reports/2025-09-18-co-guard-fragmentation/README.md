# Guard Relay Memory Fragmentation Investigation

**Period:** September 9-18, 2025  
**Problem:** Guard relays consuming ~5 GB RAM each  
**Cause:** Memory fragmentation from directory caching + glibc malloc

## Summary

This investigation identified that Tor guard relays experience severe memory fragmentation due to:
1. Directory caching (required for guard status) creates fragmented allocations
2. glibc malloc does not efficiently release fragmented memory
3. Physical memory grows to ~5 GB per relay within 48 hours

### Key Finding

`DirCache 0` reduces memory from ~5 GB to ~0.3 GB but **removes guard relay status**.
No acceptable solution found that maintains guard status with minimal memory.

### Recommended Next Steps

1. Compile Tor with OpenBSD malloc (`--enable-openbsd-malloc`) - officially recommended by Tor Project
2. Test alternative allocators (jemalloc, tcmalloc)
3. Investigate `MaxConsensusAgeForDiffs` setting

## Files

- `data.csv` - Raw memory measurements (13 relays, 9 days)
- `charts/` - Generated visualizations
- [REPORT.md](REPORT.md) - Full investigation report with citations

## Reproduction

```bash
# Generate charts from this data
cd ../../tools
python3 generate-charts.py \
  --data ../reports/2025-09-18-co-guard-fragmentation/data.csv \
  --output-dir ../reports/2025-09-18-co-guard-fragmentation/charts/
```

