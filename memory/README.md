# Tor Relay Memory Analysis

Tools and reports for investigating Tor relay memory usage.

## Tools

### monitor.sh - Time-Series Monitoring

Collect aggregate memory statistics over time (for cron-based monitoring).

```bash
cd tools

# Initialize a new CSV file
./monitor.sh --init --output /var/log/tor_memory_stats.csv

# Append current stats (run daily via cron)
./monitor.sh --output /var/log/tor_memory_stats.csv

# Cron example (daily at 2am):
# 0 2 * * * /path/to/monitor.sh --output /var/log/tor_memory_stats.csv
```

Output CSV columns: `date, time, num_relays, total_mb, avg_mb, min_mb, max_mb, ...`

### timeseries-charts.py - Time-Series Visualizations

Generate charts from monitor.sh data showing memory trends over time.

```bash
# Generate charts from collected data
python3 timeseries-charts.py \
  --data /var/log/tor_memory_stats.csv \
  --title "Production Server" \
  --output-dir ./charts/

# Outputs:
#   memory_usage.png  - Total and per-relay memory over time
#   memory_weekly.png - Weekly average trends
```

### memory-tool.sh - Point-in-Time Analysis

Collect and analyze per-relay memory statistics (for experiments/debugging).

```bash
cd tools

# Show current memory status
./memory-tool.sh status

# Export CSV to stdout
./memory-tool.sh csv > snapshot.csv

# Collect data to auto-named report directory
./memory-tool.sh collect --auto-dir "baseline"
# Creates: ../reports/YYYY-MM-DD-hostname-baseline/

# Collect to specific directory
./memory-tool.sh collect --output-dir ../reports/2025-12-25-myserver-test/

# Detailed metrics for one relay
./memory-tool.sh detail relay01

# Live monitoring
./memory-tool.sh watch relay01
```

### generate-charts.py

Generate visualizations from memory data CSV files.

```bash
# Install dependencies
pip3 install matplotlib

# Generate charts
python3 generate-charts.py \
  --data ../reports/2025-09-18-co-guard-fragmentation/data.csv \
  --output-dir ../reports/2025-09-18-co-guard-fragmentation/charts/
```

## Reports

Reports are organized by date and server:

```
reports/
├── YYYY-MM-DD-hostname-description/
│   ├── README.md      # Summary
│   ├── REPORT.md      # Full analysis (optional)
│   ├── data.csv       # Collected data
│   └── charts/        # Generated visualizations
```

### Existing Reports

- [2025-09-18-co-guard-fragmentation](reports/2025-09-18-co-guard-fragmentation/) - Guard relay memory fragmentation investigation

## Quick Start

```bash
# 1. Collect baseline data
cd tools
./memory-tool.sh collect --auto-dir "baseline"

# 2. Generate charts
python3 generate-charts.py \
  --data ../reports/$(date +%Y-%m-%d)-$(hostname -s)-baseline/data.csv \
  --output-dir ../reports/$(date +%Y-%m-%d)-$(hostname -s)-baseline/charts/

# 3. Review results
ls ../reports/
```

## Multi-Server Analysis

Each server can collect data independently:

```bash
# On server1:
./memory-tool.sh collect --auto-dir "experiment-a"
# Creates: reports/2025-12-25-server1-experiment-a/

# On server2:
./memory-tool.sh collect --auto-dir "experiment-a"
# Creates: reports/2025-12-25-server2-experiment-a/
```

Merge results by copying report directories or using shared storage.

## References

See the [Guard Relay Fragmentation Report](reports/2025-09-18-co-guard-fragmentation/REPORT.md) for:
- Root cause analysis of memory fragmentation
- Official Tor Project documentation links
- Recommended next steps (alternative allocators, etc.)

