# TorUtils Memory Data Schema

This document defines the unified CSV format for Tor relay memory monitoring data.

## Overview

All memory data is stored in a single CSV format that includes:
- **Aggregate rows**: Summary statistics across all relays (1 per collection)
- **Relay rows**: Per-relay detailed metrics (N per collection)

This unified format replaces the previous separate formats from `monitor.sh` and `memory-tool.sh`.

## CSV Format

### File Header

```csv
timestamp,server,type,fingerprint,nickname,rss_kb,vmsize_kb,hwm_kb,frag_ratio,count,total_kb,avg_kb,min_kb,max_kb
```

### Column Definitions

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `timestamp` | ISO 8601 | Yes | Collection time (e.g., `2025-12-25T02:00:00`) |
| `server` | string | Yes | Hostname of the server |
| `type` | enum | Yes | Row type: `aggregate` or `relay` |
| `fingerprint` | hex(40) | relay only | Relay fingerprint (40 hex characters) |
| `nickname` | string | relay only | Relay nickname from torrc |
| `rss_kb` | integer | relay only | Resident Set Size in KB |
| `vmsize_kb` | integer | relay only | Virtual Memory Size in KB |
| `hwm_kb` | integer | relay only | High Water Mark (peak RSS) in KB |
| `frag_ratio` | float | relay only | Fragmentation ratio (VmSize/RSS), optional |
| `count` | integer | aggregate only | Number of relays |
| `total_kb` | integer | aggregate only | Sum of all relay RSS in KB |
| `avg_kb` | integer | aggregate only | Average RSS per relay in KB |
| `min_kb` | integer | aggregate only | Minimum relay RSS in KB |
| `max_kb` | integer | aggregate only | Maximum relay RSS in KB |

### Row Types

#### Aggregate Row

One row per collection with summary statistics:

```csv
2025-12-25T02:00:00,gatedopen,aggregate,,,,,,,120,567211904,4726765,404392,5264624
```

- `fingerprint`, `nickname`, `rss_kb`, `vmsize_kb`, `hwm_kb`, `frag_ratio` are empty
- `count`, `total_kb`, `avg_kb`, `min_kb`, `max_kb` are populated

#### Relay Row

One row per relay per collection with detailed metrics:

```csv
2025-12-25T02:00:00,gatedopen,relay,A1B2C3D4E5F67890A1B2C3D4E5F67890A1B2C3D4,22gz,4500000,9800000,4600000,1.95,,,,,
```

- `fingerprint`, `nickname`, `rss_kb`, `vmsize_kb`, `hwm_kb` are populated
- `frag_ratio` is optional (requires sudo access to /proc/PID/smaps)
- `count`, `total_kb`, `avg_kb`, `min_kb`, `max_kb` are empty

## Relay Identification

Relays are identified by both **fingerprint** and **nickname**:

- **Fingerprint**: 40-character hex string derived from relay keys. Never changes for a relay's lifetime. Use this for reliable tracking across nickname changes.
  
- **Nickname**: Human-readable name from torrc. Can be changed by the operator. Useful for quick identification but not stable.

### Fingerprint Location

Fingerprint is read from: `${TOR_INSTANCES_DIR}/${relay}/fingerprint`

Example: `/etc/tor/instances/22gz/fingerprint`

## Example Data

```csv
timestamp,server,type,fingerprint,nickname,rss_kb,vmsize_kb,hwm_kb,frag_ratio,count,total_kb,avg_kb,min_kb,max_kb
2025-12-25T02:00:00,gatedopen,aggregate,,,,,,,120,567211904,4726765,404392,5264624
2025-12-25T02:00:00,gatedopen,relay,A1B2C3D4E5F67890A1B2C3D4E5F67890A1B2C3D4,22gz,4500000,9800000,4600000,1.95,,,,,
2025-12-25T02:00:00,gatedopen,relay,B2C3D4E5F67890A1B2C3D4E5F67890A1B2C3D4E5,24kgoldn,4600000,9900000,4700000,1.92,,,,,
2025-12-25T02:00:00,gatedopen,relay,C3D4E5F67890A1B2C3D4E5F67890A1B2C3D4E5F6,42dugg,4400000,9700000,4500000,1.98,,,,,
2025-12-26T02:00:00,gatedopen,aggregate,,,,,,,120,570000000,4750000,410000,5300000
2025-12-26T02:00:00,gatedopen,relay,A1B2C3D4E5F67890A1B2C3D4E5F67890A1B2C3D4,22gz,4550000,9850000,4600000,1.94,,,,,
```

## Querying Data

### Using grep

```bash
# All aggregate rows (quick overview)
grep ",aggregate," memory.csv

# All relay rows (detailed analysis)
grep ",relay," memory.csv

# Specific relay by fingerprint (stable)
grep "A1B2C3D4E5F67890" memory.csv

# Specific relay by nickname
grep ",22gz," memory.csv

# Data from specific date
grep "^2025-12-25" memory.csv
```

### Using Python/pandas

```python
import pandas as pd

df = pd.read_csv('memory.csv')

# Aggregate data only
agg = df[df['type'] == 'aggregate']

# Per-relay data only
relays = df[df['type'] == 'relay']

# Specific relay history
relay_22gz = df[df['fingerprint'] == 'A1B2C3D4E5F67890A1B2C3D4E5F67890A1B2C3D4']

# Daily averages
df['date'] = pd.to_datetime(df['timestamp']).dt.date
daily = agg.groupby('date')['avg_kb'].mean()
```

## Extended Format (Experiments)

For experiments, an additional `group` column is added after `nickname`:

```csv
timestamp,server,type,fingerprint,nickname,group,rss_kb,vmsize_kb,hwm_kb,frag_ratio,count,total_kb,avg_kb,min_kb,max_kb
```

### Group Column

| Value | Meaning |
|-------|---------|
| `A`, `B`, `C`, etc. | Experiment group assignment |
| Empty | Routine monitoring (no experiment) or aggregate row |

### Using Group Assignments

To enable group assignments, provide a relay config file:

```bash
./collect.sh --output memory_measurements.csv --config relay_config.csv
```

The config file maps fingerprints to groups:

```csv
fingerprint,nickname,group,dircache,maxmem,notes
A1B2C3D4E5F67890A1B2C3D4E5F67890A1B2C3D4,22gz,A,0,2GB,Test relay
B2C3D4E5F67890A1B2C3D4E5F67890A1B2C3D4E5,24kgoldn,B,default,default,Control
```

See [experiments.md](experiments.md) for experiment-specific documentation.

## Migration from Legacy Formats

### From monitor.sh output (memory_stats.csv)

Legacy format:
```csv
date,time,num_relays,total_mb,avg_mb,min_mb,max_mb,total_kb,avg_kb,min_kb,max_kb
```

Migration creates aggregate-only rows (no per-relay data was collected).

### From memory-tool.sh output

Legacy format:
```csv
relay,pid,rss_gb,vmsize_gb,hwm_gb,frag_ratio
```

Migration creates relay rows with timestamp from file modification time.

Use `migrate-monitoring.sh` for automated migration.

