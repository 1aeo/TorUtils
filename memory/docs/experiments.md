# Running Memory Experiments

Guide to setting up, running, and reporting on Tor relay memory experiments.

## Overview

Memory experiments allow you to:
- Compare different Tor configurations (DirCache, MaxMemInQueues, allocators)
- Track memory usage across relay groups over time
- Generate standardized reports with charts and analysis

## Quick Start

```bash
cd tools

# 1. Initialize experiment
./experiment.sh init --name "DirCache Test" --groups A,B,C

# 2. Configure relay groups
nano reports/2025-12-25-server-dircache-test/relay_config.csv

# 3. Apply configurations to relays
# (manual step - edit torrc files per relay_config.csv)

# 4. Collect data daily
./collect.sh --output reports/.../measurements.csv --config reports/.../relay_config.csv

# 5. Generate report
python3 generate-report.py --experiment reports/2025-12-25-server-dircache-test/

# 6. Complete analysis in REPORT.md
```

## Experiment Setup

### Initialize New Experiment

```bash
./experiment.sh init --name "description" --groups A,B,C
```

This creates:
```
reports/YYYY-MM-DD-server-description/
├── experiment.json       # Metadata template
├── relay_config.csv      # Empty relay assignments
├── measurements.csv      # Empty with header
├── charts/               # For generated charts
└── README.md             # Basic documentation
```

### Configure Groups

Edit `experiment.json` to define what each group represents:

```json
{
  "id": "2025-12-25-server-dircache-test",
  "name": "DirCache Configuration Test",
  "server": "gatedopen",
  "start_date": "2025-12-25",
  "end_date": "",
  "hypothesis": "DirCache 0 will reduce memory but may lose guard status",
  "description": "Testing memory impact of DirCache settings",
  "groups": {
    "A": {
      "name": "DirCache 0 + MaxMem 2GB",
      "config": {"dircache": 0, "maxmem": "2GB"}
    },
    "B": {
      "name": "Control (default)",
      "config": {"dircache": "default", "maxmem": "default"}
    },
    "C": {
      "name": "MaxMem 2GB only",
      "config": {"dircache": "default", "maxmem": "2GB"}
    }
  },
  "tor_version": "0.4.8.21",
  "allocator": "glibc"
}
```

### Assign Relays to Groups

Edit `relay_config.csv` to assign relays to experiment groups:

```csv
fingerprint,nickname,group,dircache,maxmem,notes
A1B2C3D4E5F67890A1B2C3D4E5F67890A1B2C3D4,relay1,A,0,2GB,Test relay - was guard
B2C3D4E5F67890A1B2C3D4E5F67890A1B2C3D4E5,relay2,A,0,2GB,Test relay
C3D4E5F67890A1B2C3D4E5F67890A1B2C3D4E5F6,relay3,B,default,default,Control relay
D4E5F67890A1B2C3D4E5F67890A1B2C3D4E5F6A1,relay4,B,default,default,Control relay
E5F67890A1B2C3D4E5F67890A1B2C3D4E5F6A1B2,relay5,C,default,2GB,MaxMem only
```

To get relay fingerprints:
```bash
cat /etc/tor/instances/relay1/fingerprint
# Output: relay1 A1B2C3D4E5F67890A1B2C3D4E5F67890A1B2C3D4
```

### Apply Configurations

Update each relay's torrc based on the group assignment:

```bash
# For Group A relays (DirCache 0 + MaxMem 2GB)
sudo nano /etc/tor/instances/relay1/torrc
# Add:
# DirCache 0
# MaxMemInQueues 2 GB

# Restart relay
sudo systemctl restart tor@relay1
```

## Data Collection

### Manual Collection

```bash
./collect.sh \
  --output reports/2025-12-25-server-dircache-test/measurements.csv \
  --config reports/2025-12-25-server-dircache-test/relay_config.csv
```

### Automated Collection (Cron)

Add to crontab for daily collection:

```bash
# Daily at 2am
0 2 * * * /path/to/TorUtils/memory/tools/collect.sh \
  --output /path/to/experiment/measurements.csv \
  --config /path/to/experiment/relay_config.csv
```

### What Gets Collected

Each collection appends:
- 1 aggregate row with totals
- N relay rows with per-relay metrics and group assignment

Example output:
```csv
timestamp,server,type,fingerprint,nickname,group,rss_kb,vmsize_kb,hwm_kb,frag_ratio,...
2025-12-25T02:00:00,gatedopen,aggregate,,,,,,,,...
2025-12-25T02:00:00,gatedopen,relay,A1B2C3...,relay1,A,4500000,9800000,4600000,1.95,...
2025-12-25T02:00:00,gatedopen,relay,B2C3D4...,relay2,A,4600000,9900000,4700000,1.92,...
```

## Report Generation

### Generate Charts and Report Skeleton

```bash
python3 generate-report.py --experiment reports/2025-12-25-server-dircache-test/
```

This creates:
- `charts/memory_over_time.png` - Total memory trend
- `charts/group_comparison.png` - Memory by group over time
- `charts/final_comparison.png` - Final results comparison
- `REPORT.md` - Template with auto-populated data

### Complete the Report

Edit `REPORT.md` to fill in analysis sections:

1. **Executive Summary** - High-level conclusions
2. **Analysis** - What worked, what didn't, unexpected findings
3. **Root Cause** - Technical explanation of results
4. **Recommendations** - Action items based on findings
5. **Next Steps** - Follow-up experiments or changes

## Comparing Experiments

### Compare Multiple Experiments

```bash
python3 compare-experiments.py \
  --experiments reports/exp1 reports/exp2 reports/exp3 \
  --output comparison/
```

This generates:
- `comparison/comparison.png` - Cross-experiment group comparison
- `comparison/best_configs.png` - Best configuration rankings
- `comparison/COMPARISON.md` - Detailed comparison report

### Example Comparison Output

```
| Rank | Experiment | Configuration | Memory (GB) |
|------|------------|---------------|-------------|
| 1 | DirCache Test | DirCache 0 + MaxMem 2GB | 0.29 |
| 2 | DirCache Test | DirCache 0 only | 0.33 |
| 3 | Allocator Test | jemalloc | 1.85 |
| 4 | DirCache Test | MaxMem 2GB only | 4.17 |
```

## File Formats

### experiment.json

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (directory name) |
| `name` | string | Human-readable experiment name |
| `server` | string | Hostname where experiment runs |
| `start_date` | date | Experiment start date (YYYY-MM-DD) |
| `end_date` | date | Experiment end date (empty if ongoing) |
| `hypothesis` | string | What you expect to find |
| `description` | string | Detailed description |
| `groups` | object | Group definitions (see below) |
| `tor_version` | string | Tor version used |
| `allocator` | string | Memory allocator (glibc/jemalloc/tcmalloc) |

### relay_config.csv

| Column | Required | Description |
|--------|----------|-------------|
| `fingerprint` | Yes | 40-char relay fingerprint |
| `nickname` | Yes | Relay nickname |
| `group` | Yes | Experiment group (A, B, C, etc.) |
| `dircache` | No | DirCache setting (0 or default) |
| `maxmem` | No | MaxMemInQueues setting |
| `notes` | No | Additional notes |

### measurements.csv

See [schema.md](schema.md) for full column documentation.

Key columns for experiments:
- `group` - Experiment group assignment
- `rss_kb` - Resident Set Size in KB
- `timestamp` - When measurement was taken

## Best Practices

### Experiment Design

1. **Control group** - Always include a control group with default settings
2. **Sufficient relays** - Use 3+ relays per group for statistical validity
3. **Duration** - Run experiments for 7+ days to capture fragmentation patterns
4. **Isolation** - Only change one variable per group when possible

### Data Collection

1. **Consistent timing** - Collect at the same time each day
2. **Continuous collection** - Don't skip days during the experiment
3. **Monitor for issues** - Check relay logs for errors/crashes

### Analysis

1. **Compare against baseline** - Always reference control group
2. **Consider variance** - Look at min/max, not just averages
3. **Document anomalies** - Note any unexpected events (restarts, network issues)

## Migrating Legacy Data

If you have data from the old format (day columns), migrate it:

```bash
python3 migrate-experiment.py --experiment reports/old-experiment/
```

This converts:
```
# Old format (data.csv)
group,relay,day0,day1,day2
A,22gz,5.03,0.28,0.32

# New format (measurements.csv)
timestamp,server,type,fingerprint,nickname,group,rss_kb,...
2025-09-09T00:00:00,server,relay,,22gz,A,5277491,...
```

## Troubleshooting

### No group data in charts

Ensure:
1. `relay_config.csv` has relay fingerprints
2. `collect.sh` was run with `--config` flag
3. Fingerprints in config match actual relay fingerprints

### Missing fingerprints

Get fingerprint from relay:
```bash
cat /etc/tor/instances/relay_name/fingerprint
```

### Charts show no data

Check that `measurements.csv` has data:
```bash
wc -l measurements.csv
grep ",relay," measurements.csv | head
```

## See Also

- [schema.md](schema.md) - Data format specification
- [README.md](../README.md) - Main tool documentation
- [templates/REPORT.md](../templates/REPORT.md) - Report template

