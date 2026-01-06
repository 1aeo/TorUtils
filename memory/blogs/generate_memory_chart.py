#!/usr/bin/env python3
"""
Generate memory chart for unified memory experiment.
Excludes group I (mimalloc 3.0.1 - bad data).
"""

import csv
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from collections import defaultdict
from pathlib import Path

CSV_FILE = Path("/workspace/memory/reports/2025-12-26-co-unified-memory-test/memory_measurements.csv")
OUTPUT_FILE = Path("/workspace/memory/blogs/memory_by_group.png")

# Group labels and colors - EXCLUDING GROUP I
GROUP_CONFIG = {
    'A': {'name': 'jemalloc 5.3.0', 'color': '#2ecc71'},      # green
    'B': {'name': 'mimalloc 2.1.2', 'color': '#3498db'},      # blue
    'C': {'name': 'tcmalloc 2.15', 'color': '#9b59b6'},       # purple
    'D': {'name': 'consensus-4h', 'color': '#f39c12'},        # orange
    'E': {'name': 'consensus-8h', 'color': '#e67e22'},        # dark orange
    'F': {'name': 'restart-24h', 'color': '#1abc9c'},         # teal
    'G': {'name': 'restart-48h', 'color': '#16a085'},         # dark teal
    'H': {'name': 'restart-72h', 'color': '#27ae60'},         # dark green
    # 'I': EXCLUDED - mimalloc 3.0.1 had bad data
    'Z': {'name': 'control (glibc)', 'color': '#e74c3c'},     # red
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
    
    # Create figure with dark theme
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(14, 8))
    fig.set_facecolor('#0d1117')
    ax.set_facecolor('#0d1117')
    
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
    ax.set_xlabel('Date', fontsize=12, fontweight='bold')
    ax.set_ylabel('Memory (GB)', fontsize=12, fontweight='bold')
    ax.set_title('Tor Relay Memory by Experiment Group\nUnified Memory Experiment (Ubuntu 24.04, Tor 0.4.8.x)', 
                 fontsize=14, fontweight='bold', pad=15)
    
    # Format x-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    plt.xticks(rotation=45, ha='right')
    
    # Grid and legend
    ax.grid(True, alpha=0.3, color='#444444')
    ax.legend(loc='upper left', fontsize=10, framealpha=0.9)
    
    # Set y-axis to start at 0
    ax.set_ylim(bottom=0, top=7)
    
    # Add horizontal reference lines
    ax.axhline(y=5, color='#666666', linestyle='--', alpha=0.5)
    ax.axhline(y=2, color='#00ff7f', linestyle='--', alpha=0.3)
    
    # Style spines
    for spine in ax.spines.values():
        spine.set_color('#444444')
    ax.tick_params(colors='#888888')
    
    plt.tight_layout()
    
    # Save
    print(f"Saving to {OUTPUT_FILE}...")
    plt.savefig(OUTPUT_FILE, dpi=150, bbox_inches='tight', facecolor='#0d1117', edgecolor='none')
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
