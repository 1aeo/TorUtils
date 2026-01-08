#!/usr/bin/env python3
"""
Generate memory chart for allocators blog - ONLY allocator groups.
Shows: jemalloc (A), mimalloc (B), tcmalloc (C), glibc control (Z)
Excludes: consensus groups (D, E) and restart groups (F, G, H)
"""

import csv
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from collections import defaultdict
from pathlib import Path

# Use script directory for relative paths
SCRIPT_DIR = Path(__file__).parent
CSV_FILE = SCRIPT_DIR.parent / "reports/2025-12-26-co-unified-memory-test/memory_measurements.csv"
OUTPUT_FILE = SCRIPT_DIR / "images/memory-allocators-tor-relay-fragmentation-with-custom-allocators-chart.png"

# ONLY allocator groups
GROUP_CONFIG = {
    'A': {'name': 'jemalloc 5.3.0', 'color': '#2ecc71'},       # green
    'B': {'name': 'mimalloc 2.1.2', 'color': '#3498db'},       # blue
    'C': {'name': 'tcmalloc 2.15', 'color': '#9b59b6'},        # purple
    'I': {'name': 'mimalloc 3.0.1', 'color': '#00bcd4'},       # cyan
    'Z': {'name': 'glibc 2.39', 'color': '#e74c3c'},           # red
}

def main():
    print(f"Reading {CSV_FILE}...")
    
    # Data structure: {group: {timestamp: [rss_values]}}
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
    
    # Calculate averages per group per timestamp
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
    
    # Plot each group with thicker lines for clarity
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
    ax.set_title('Memory Allocator Comparison: Tor Relay RSS Over Time\nUbuntu 24.04, Tor 0.4.8.x (10 relays per allocator)', 
                 fontsize=14, fontweight='bold', pad=15)
    
    # Format x-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    plt.xticks(rotation=45, ha='right')
    
    # Grid and legend
    ax.grid(True, alpha=0.3, color='#444444')
    ax.legend(loc='upper left', fontsize=11, framealpha=0.9)
    
    # Set y-axis
    ax.set_ylim(bottom=0, top=7)
    
    # Add horizontal reference lines
    ax.axhline(y=5, color='#666666', linestyle='--', alpha=0.5, linewidth=1)
    ax.text(timestamps[-1], 5.15, '5 GB', fontsize=9, color='#888888', ha='right')
    
    ax.axhline(y=2, color='#00ff7f', linestyle='--', alpha=0.4, linewidth=1)
    ax.text(timestamps[-1], 2.15, '2 GB', fontsize=9, color='#00ff7f', alpha=0.7, ha='right')
    
    # Style spines
    for spine in ax.spines.values():
        spine.set_color('#444444')
    ax.tick_params(colors='#888888')
    
    plt.tight_layout()
    
    # Save
    print(f"Saving to {OUTPUT_FILE}...")
    plt.savefig(OUTPUT_FILE, dpi=150, bbox_inches='tight', facecolor='#0d1117', edgecolor='none')
    print(f"Done! Chart saved to {OUTPUT_FILE}")
    
    # Show stats
    print("\n--- Final Memory by Allocator ---")
    for group, (timestamps, values) in sorted(group_series.items(), key=lambda x: x[1][1][-1] if x[1][1] else 99):
        if values:
            config = GROUP_CONFIG[group]
            print(f"  {config['name']}: {values[-1]:.2f} GB")

if __name__ == '__main__':
    main()
