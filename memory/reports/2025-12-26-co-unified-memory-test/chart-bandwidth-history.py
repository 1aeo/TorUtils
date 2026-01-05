#!/usr/bin/env python3
"""
Generate bandwidth time-series chart by experiment group.
Similar to memory chart - shows bandwidth over time per group.
"""

import csv
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from collections import defaultdict
from pathlib import Path

# Use script directory for relative paths
EXP_DIR = Path(__file__).parent
BANDWIDTH_CSV = EXP_DIR / "bandwidth_measurements.csv"
OUTPUT_FILE = EXP_DIR / "charts" / "bandwidth_over_time.png"

# Group configuration with colors matching memory chart
GROUP_CONFIG = {
    'A': {'name': 'jemalloc 5.3.0', 'color': '#2ecc71'},
    'B': {'name': 'mimalloc 2.1.2', 'color': '#3498db'},
    'C': {'name': 'tcmalloc 2.15', 'color': '#9b59b6'},
    'D': {'name': 'consensus-4h', 'color': '#f39c12'},
    'E': {'name': 'consensus-8h', 'color': '#e67e22'},
    'F': {'name': 'restart-24h', 'color': '#1abc9c'},
    'G': {'name': 'restart-48h', 'color': '#16a085'},
    'H': {'name': 'restart-72h', 'color': '#27ae60'},
    'I': {'name': 'mimalloc 3.0.1', 'color': '#00bcd4'},
    'Z': {'name': 'control', 'color': '#e74c3c'},
}

def main():
    print(f"Reading {BANDWIDTH_CSV}...")
    
    # Data structure: {group: {timestamp: [mbps_values]}}
    data = defaultdict(lambda: defaultdict(list))
    
    with open(BANDWIDTH_CSV, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            group = row.get('group', '')
            if group not in GROUP_CONFIG:
                continue
            
            # Only use rows with write_mbps (from bandwidth history, not snapshot)
            write_mbps = row.get('write_mbps', '')
            if not write_mbps:
                continue
            
            try:
                timestamp = datetime.fromisoformat(row['timestamp'])
                mbps = float(write_mbps)
                data[group][timestamp].append(mbps)
            except (ValueError, KeyError):
                continue
    
    if not data:
        print("Error: No data found")
        return
    
    # Calculate averages per group per timestamp
    group_series = {}
    for group in GROUP_CONFIG.keys():
        timestamps = sorted(data[group].keys())
        averages = [sum(data[group][t]) / len(data[group][t]) for t in timestamps]
        group_series[group] = (timestamps, averages)
    
    # Create figure
    fig, ax = plt.subplots(figsize=(14, 8))
    
    # Plot each group
    for group, config in GROUP_CONFIG.items():
        timestamps, values = group_series.get(group, ([], []))
        if timestamps:
            ax.plot(timestamps, values, 
                   label=f"{group}: {config['name']}", 
                   color=config['color'],
                   linewidth=2,
                   marker='o',
                   markersize=3,
                   alpha=0.8)
    
    # Formatting
    ax.set_xlabel('Date', fontsize=12)
    ax.set_ylabel('Bandwidth (Mbps)', fontsize=12)
    ax.set_title('Tor Relay Bandwidth Over Time by Experiment Group\n(Verifying Allocators Don\'t Harm Performance)', fontsize=14)
    
    # Format x-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    ax.xaxis.set_major_locator(mdates.DayLocator())
    plt.xticks(rotation=45, ha='right')
    
    # Grid and legend
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper left', fontsize=10, bbox_to_anchor=(1.01, 1))
    
    # Set y-axis to start at 0
    ax.set_ylim(bottom=0)
    
    plt.tight_layout()
    
    print(f"Saving to {OUTPUT_FILE}...")
    plt.savefig(OUTPUT_FILE, dpi=150, bbox_inches='tight')
    print(f"Done!")
    
    # Print latest stats
    print("\n--- Latest Bandwidth by Group ---")
    latest_stats = []
    for group, (timestamps, values) in group_series.items():
        if values:
            # Average of last few data points for stability
            recent_avg = sum(values[-5:]) / len(values[-5:]) if len(values) >= 5 else values[-1]
            latest_stats.append((group, recent_avg))
    
    for group, val in sorted(latest_stats, key=lambda x: x[1], reverse=True):
        config = GROUP_CONFIG[group]
        print(f"  {group} ({config['name']}): {val:.1f} Mbps")

if __name__ == '__main__':
    main()


