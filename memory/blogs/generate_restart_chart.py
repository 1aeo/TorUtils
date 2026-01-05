#!/usr/bin/env python3
"""
Generate time series chart for periodic restarts blog.
Shows: restart-24h (F), restart-48h (G), restart-72h (H), glibc control (Z)
"""

import csv
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from collections import defaultdict
from pathlib import Path

CSV_FILE = Path("/workspace/memory/reports/2025-12-26-co-unified-memory-test/memory_measurements.csv")
OUTPUT_FILE = Path("/workspace/memory/blogs/chart_restarts.png")

# Only restart groups + control
GROUP_CONFIG = {
    'F': {'name': 'Restart 24h', 'color': '#1abc9c'},       # teal
    'G': {'name': 'Restart 48h', 'color': '#16a085'},       # dark teal
    'H': {'name': 'Restart 72h', 'color': '#27ae60'},       # green
    'Z': {'name': 'glibc (control)', 'color': '#e74c3c'},   # red
}

def main():
    print(f"Reading {CSV_FILE}...")
    
    data = defaultdict(lambda: defaultdict(list))
    
    with open(CSV_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
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
    
    # Calculate averages
    group_series = {}
    for group in GROUP_CONFIG.keys():
        timestamps = sorted(data[group].keys())
        averages = [sum(data[group][t]) / len(data[group][t]) for t in timestamps]
        group_series[group] = (timestamps, averages)
    
    # Create figure with dark theme
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(12, 7))
    fig.set_facecolor('#0d1117')
    ax.set_facecolor('#0d1117')
    
    # Plot each group
    for group, config in GROUP_CONFIG.items():
        timestamps, values = group_series.get(group, ([], []))
        if timestamps:
            ax.plot(timestamps, values, 
                   label=f"{config['name']}", 
                   color=config['color'],
                   linewidth=2.5,
                   marker='o',
                   markersize=5)
    
    # Formatting
    ax.set_xlabel('Date', fontsize=12, fontweight='bold')
    ax.set_ylabel('Memory (GB)', fontsize=12, fontweight='bold')
    ax.set_title('Periodic Restarts vs Control: Memory Over Time\nUbuntu 24.04, Tor 0.4.8.x (10 relays per group)', 
                 fontsize=14, fontweight='bold', pad=15)
    
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    plt.xticks(rotation=45, ha='right')
    
    ax.grid(True, alpha=0.3, color='#444444')
    ax.legend(loc='upper left', fontsize=11, framealpha=0.9)
    
    ax.set_ylim(bottom=0, top=7)
    
    # Reference lines
    ax.axhline(y=5, color='#666666', linestyle='--', alpha=0.5, linewidth=1)
    ax.text(group_series['Z'][0][-1], 5.15, '5 GB', fontsize=9, color='#888888', ha='right')
    
    # Add reference for allocator performance
    ax.axhline(y=1.16, color='#3498db', linestyle='--', alpha=0.6, linewidth=1.5)
    ax.text(group_series['Z'][0][-1], 1.28, 'mimalloc 2.1 (1.16 GB)', fontsize=9, color='#3498db', alpha=0.9, ha='right')
    
    ax.axhline(y=1.63, color='#2ecc71', linestyle='--', alpha=0.6, linewidth=1.5)
    ax.text(group_series['Z'][0][-1], 1.75, 'jemalloc 5.3 (1.63 GB)', fontsize=9, color='#2ecc71', alpha=0.9, ha='right')
    
    for spine in ax.spines.values():
        spine.set_color('#444444')
    ax.tick_params(colors='#888888')
    
    plt.tight_layout()
    
    print(f"Saving to {OUTPUT_FILE}...")
    plt.savefig(OUTPUT_FILE, dpi=150, bbox_inches='tight', facecolor='#0d1117', edgecolor='none')
    print(f"Done!")
    
    print("\n--- Final Memory ---")
    for group, (timestamps, values) in sorted(group_series.items(), key=lambda x: x[1][1][-1] if x[1][1] else 99):
        if values:
            config = GROUP_CONFIG[group]
            print(f"  {config['name']}: {values[-1]:.2f} GB")

if __name__ == '__main__':
    main()
