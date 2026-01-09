# Tor Relay Memory Analysis

Tools and reports for investigating Tor relay memory usage.

## Quick Start

```bash
cd tools

# Initialize and collect first data point
./collect.sh --init --output /var/log/tor/memory.csv

# Generate charts
python3 timeseries-charts.py \
  --data /var/log/tor/memory.csv \
  --title "My Server" \
  --output-dir ./charts/
```

## Monitoring

### collect.sh - Unified Data Collection

Collects both aggregate and per-relay memory statistics in a single CSV. This is the primary tool for all memory data collection.

#### Usage

```bash
cd tools

# Initialize new CSV with header
./collect.sh --init --output /var/log/tor/memory.csv

# Append current data (for cron)
./collect.sh --output /var/log/tor/memory.csv

# Quick check (stdout only)
./collect.sh --stdout

# With system diagnostics
./collect.sh --output memory.csv --with-diagnostics
```

#### Permissions Note

Fingerprint files in `/var/lib/tor-instances/*/fingerprint` are owned by per-relay users (`_tor-*`) and require root/sudo to read. Without sudo, the fingerprint column will be empty but all other data is collected.

```bash
# Run with sudo for full data including fingerprints
sudo ./collect.sh --stdout

# Without sudo - works but fingerprints are empty
./collect.sh --stdout
```

#### Cron Setup

```bash
# Daily collection at 2am (with sudo for fingerprints)
0 2 * * * sudo /path/to/TorUtils/memory/tools/collect.sh --output /var/log/tor/memory.csv

# Hourly collection (for detailed analysis)
0 * * * * sudo /path/to/TorUtils/memory/tools/collect.sh --output /var/log/tor/memory.csv

# With diagnostics (weekly)
0 2 * * 0 sudo /path/to/TorUtils/memory/tools/collect.sh --output /var/log/tor/memory.csv --with-diagnostics
```

#### Output Format

Each collection appends:
- 1 aggregate row (totals across all relays)
- N relay rows (per-relay detail with fingerprint and nickname)

| Column | Description |
|--------|-------------|
| `timestamp` | ISO 8601 collection time |
| `server` | Hostname |
| `type` | `"aggregate"` or `"relay"` |
| `fingerprint` | Relay fingerprint - 40 hex chars (relay rows only) |
| `nickname` | Relay nickname from torrc (relay rows only) |
| `rss_kb` | Resident Set Size in KB (relay rows only) |
| `vmsize_kb` | Virtual Memory Size in KB (relay rows only) |
| `hwm_kb` | High Water Mark in KB (relay rows only) |
| `frag_ratio` | Fragmentation ratio (relay rows only) |
| `count` | Number of relays (aggregate rows only) |
| `total_kb` | Sum of all RSS in KB (aggregate rows only) |
| `avg_kb` | Average RSS in KB (aggregate rows only) |
| `min_kb` | Minimum RSS in KB (aggregate rows only) |
| `max_kb` | Maximum RSS in KB (aggregate rows only) |

See [docs/schema.md](docs/schema.md) for complete format documentation.

#### Querying Data

```bash
# Aggregate stats only (quick overview)
grep ",aggregate," memory.csv

# Per-relay data (detailed analysis)
grep ",relay," memory.csv

# Specific relay history by fingerprint (stable across renames)
grep "A1B2C3D4E5F6" memory.csv

# Specific relay by nickname
grep ",22gz," memory.csv
```

### timeseries-charts.py - Visualizations

Generate charts from collected data. Supports both the new unified format and legacy format.

```bash
cd tools

# Generate all charts
python3 timeseries-charts.py \
  --data /var/log/tor/memory.csv \
  --title "Production Server" \
  --output-dir ./charts/
```

#### Output Charts

| Chart | Description |
|-------|-------------|
| `memory_usage.png` | Total and per-relay memory over time |
| `memory_weekly.png` | Weekly average trends |
| `memory_trajectories.png` | Individual relay memory paths (unified format only) |
| `memory_distribution.png` | Relay memory histogram and top/bottom relays (unified format only) |
| `memory_outliers.png` | Outlier detection highlighting high-memory relays (unified format only) |

### migrate-monitoring.sh - Migration Tool

Convert legacy `memory_stats.csv` files to the new unified format.

```bash
cd tools

# Migrate existing data
./migrate-monitoring.sh /path/to/old/memory_stats.csv /path/to/new/memory.csv

# With explicit server name
./migrate-monitoring.sh --server go old_stats.csv new_stats.csv
```

Note: Migrated data will only contain aggregate rows. Per-relay detail was not collected by the legacy format.

## Point-in-Time Analysis

### memory-tool.sh

For quick checks and debugging without affecting monitoring data.

```bash
cd tools

# Show current memory status
./memory-tool.sh status

# Export CSV to stdout
./memory-tool.sh csv

# Detailed metrics for one relay
./memory-tool.sh detail relay01

# Live monitoring
./memory-tool.sh watch relay01
```

## Reports

Reports are organized by date and server:

```
reports/
├── YYYY-MM-DD-hostname-description/
│   ├── README.md          # Summary
│   ├── REPORT.md          # Full analysis (optional)
│   ├── memory_measurements.csv   # Collected data (unified format)
│   └── charts/            # Generated visualizations
```

### Existing Reports

- [2025-09-18-co-guard-fragmentation](reports/2025-09-18-co-guard-fragmentation/) - Guard relay memory fragmentation investigation

## Experiments

For A/B testing and memory investigations, use the experiment workflow.

### Quick Start

```bash
cd tools

# Initialize experiment with groups
./experiment.sh init --name "DirCache Test" --groups A,B,C

# Configure relay assignments
nano reports/2025-12-25-server-dircache-test/relay_config.csv

# Collect data (run daily)
./collect.sh --output reports/.../memory_measurements.csv --config reports/.../relay_config.csv

# Generate report and charts
python3 generate-report.py --experiment reports/2025-12-25-server-dircache-test/
```

### Experiment Tools

| Tool | Purpose |
|------|---------|
| `experiment.sh init` | Create new experiment with directory structure |
| `experiment.sh status` | Show experiment status and data summary |
| `experiment.sh list` | List all experiments |
| `generate-report.py` | Generate charts and REPORT.md template |
| `compare-experiments.py` | Compare results across experiments |
| `migrate-experiment.py` | Migrate legacy experiment data |

### Comparing Experiments

```bash
python3 compare-experiments.py \
  --experiments reports/exp1 reports/exp2 \
  --output comparison/
```

See [docs/experiments.md](docs/experiments.md) for the complete experiment workflow guide.

## Documentation

- [docs/schema.md](docs/schema.md) - Data format specification
- [docs/experiments.md](docs/experiments.md) - Running memory experiments (Phase 2)

## Multi-Server Monitoring

Each server collects data independently using the same tools:

```bash
# On server1:
./collect.sh --output /var/log/tor/memory.csv
# Collects: go data with server=go

# On server2:
./collect.sh --output /var/log/tor/memory.csv
# Collects: sortaopen data with server=sortaopen
```

Data can be merged or compared since each row includes the server name.

## Legacy Tools (Deprecated)

The following tools are deprecated and replaced by `collect.sh`:

- `monitor.sh` - Use `collect.sh` instead (same options, unified format)
- `memory-tool.sh collect` - Use `collect.sh` instead

These tools remain for backward compatibility but will be removed in a future version.

## References

See the [Guard Relay Fragmentation Report](reports/2025-09-18-co-guard-fragmentation/REPORT.md) for:
- Root cause analysis of memory fragmentation
- Official Tor Project documentation links
- Recommended next steps (alternative allocators, etc.)
