#!/bin/bash

# Tor Memory Monitor - Tracks RSS memory usage across all tor relay processes
# To run daily at 2am: (crontab -l; echo "0 2 * * * /path/to/monitor-relays.sh") | crontab -

CSV_FILE="/home/aeo1/tor_memory_stats.csv"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Get RSS memory (KB) for all tor processes
mapfile -t tor_procs < <(ps -eo rss,comm | awk '$2 == "tor" {print $1}')

if [ ${#tor_procs[@]} -eq 0 ]; then
  echo "No tor processes found!"
  exit 1
fi

# Calculate statistics in KB
count=${#tor_procs[@]}
total_kb=0
min_kb=${tor_procs[0]}
max_kb=${tor_procs[0]}

for rss in "${tor_procs[@]}"; do
  total_kb=$((total_kb + rss))
  [ $rss -lt $min_kb ] && min_kb=$rss
  [ $rss -gt $max_kb ] && max_kb=$rss
done

avg_kb=$((total_kb / count))

# Convert to MB
to_mb() { echo $((${1} / 1024)); }
total_mb=$(to_mb $total_kb)
avg_mb=$(to_mb $avg_kb)
min_mb=$(to_mb $min_kb)
max_mb=$(to_mb $max_kb)

# Save to CSV
if [ ! -f "$CSV_FILE" ]; then
  echo "date,time,num_relays,total_mb,avg_mb,min_mb,max_mb,total_kb,avg_kb,min_kb,max_kb" > "$CSV_FILE"
fi
echo "${TIMESTAMP//[ ]*/},${TIMESTAMP##* },$count,$total_mb,$avg_mb,$min_mb,$max_mb,$total_kb,$avg_kb,$min_kb,$max_kb" >> "$CSV_FILE"

# Display results
echo ""
echo "===== Tor Memory Usage - $TIMESTAMP ====="
echo ""
echo "Number of relays: $count"
echo ""
echo "Total RAM:     ${total_mb} MB (${total_kb} KB)"
echo "Average/relay: ${avg_mb} MB (${avg_kb} KB)"
echo "Minimum:       ${min_mb} MB (${min_kb} KB)"
echo "Maximum:       ${max_mb} MB (${max_kb} KB)"
echo ""
echo "Data saved to: $CSV_FILE"
echo ""
echo "Recent history (last 5 entries):"
tail -6 "$CSV_FILE" | column -t -s,
echo ""