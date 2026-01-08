#!/usr/bin/env python3
"""
Generate memory chart for unified memory experiment.
Uses only standard library + matplotlib (no pandas).
"""

import csv
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from collections import defaultdict
from pathlib import Path

# Use script directory for relative paths
EXP_DIR = Path(__file__).parent
CSV_FILE = EXP_DIR / "memory_measurements.csv"
OUTPUT_FILE = EXP_DIR / "charts" / "memory_by_group.png"

# Group labels and colors
GROUP_CONFIG = {
    'A': {'name': 'jemalloc 5.3.0', 'color': '#2ecc71'},      # green
    'B': {'name': 'mimalloc 2.1.2', 'color': '#3498db'},      # blue
    'C': {'name': 'tcmalloc 2.15', 'color': '#9b59b6'},     # purple
    'D': {'name': 'consensus-4h', 'color': '#f39c12'},      # orange
    'E': {'name': 'consensus-8h', 'color': '#e67e22'},      # dark orange
    'F': {'name': 'restart-24h', 'color': '#1abc9c'},       # teal
    'G': {'name': 'restart-48h', 'color': '#16a085'},       # dark teal
    'H': {'name': 'restart-72h', 'color': '#27ae60'},       # dark green
    'I': {'name': 'mimalloc 3.0.1', 'color': '#00bcd4'},      # cyan
    'Z': {'name': 'glibc 2.39', 'color': '#e74c3c'},         # red
}

def main():
    print(f"Reading {CSV_FILE}...")
    
    # Data structure: {group: {timestamp: [rss_values]}}
    data = defaultdict(lambda: defaultdict(list))
    
    with open(CSV_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip aggregate rows
            if row['type'] != 'relay':
                continue
            
            group = row.get('group', '')
            if not group or group not in GROUP_CONFIG:
                continue
            
            try:
                timestamp = datetime.fromisoformat(row['timestamp'])
                rss_kb = float(row['rss_kb'])
                rss_gb = rss_kb / 1024 / 1024
                data[group][timestamp].append(rss_gb)
            except (ValueError, KeyError):
                continue
    
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
                   markersize=4)
    
    # Formatting
    ax.set_xlabel('Date', fontsize=12)
    ax.set_ylabel('Memory (GB)', fontsize=12)
    ax.set_title('Tor Relay Memory by Experiment Group\nUnified Memory Experiment (co, Ubuntu 24.04)', fontsize=14)
    
    # Format x-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    ax.xaxis.set_major_locator(mdates.DayLocator())
    plt.xticks(rotation=45, ha='right')
    
    # Grid and legend
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper left', fontsize=10)
    
    # Set y-axis to start at 0
    ax.set_ylim(bottom=0)
    
    # Add horizontal line at 5GB for reference
    ax.axhline(y=5, color='gray', linestyle='--', alpha=0.5)
    
    plt.tight_layout()
    
    # Save
    print(f"Saving to {OUTPUT_FILE}...")
    plt.savefig(OUTPUT_FILE, dpi=150, bbox_inches='tight')
    print(f"Done! Chart saved to {OUTPUT_FILE}")
    
    # Show latest stats
    print("\n--- Latest Memory by Group ---")
    latest_stats = []
    for group, (timestamps, values) in group_series.items():
        if values:
            latest_stats.append((group, values[-1]))
    
    for group, val in sorted(latest_stats, key=lambda x: x[1]):
        config = GROUP_CONFIG[group]
        print(f"  {group} ({config['name']}): {val:.2f} GB")

if __name__ == '__main__':
    main()
