#!/usr/bin/env python3
"""
Generate memory chart for mimalloc regression blog.
Shows: mimalloc 3.0.1, 2.1.7, 2.0.9, jemalloc, glibc
Based on go 5-way experiment (Debian 13)
"""

import csv
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from collections import defaultdict
from pathlib import Path

# Use script directory for relative paths
SCRIPT_DIR = Path(__file__).parent
CSV_FILE = SCRIPT_DIR.parent / "experiments/2026-01-08-5way-allocator-comparison/memory.csv"
GROUPS_DIR = SCRIPT_DIR.parent / "experiments/2026-01-08-5way-allocator-comparison/groups"
OUTPUT_FILE = SCRIPT_DIR / "images/mimalloc-version-regression-3x-vs-2x-tor-relays-chart.png"

# Group config with start times (only show data after allocator was applied)
GROUP_CONFIG = {
    'group_A_mimalloc301.txt': {
        'name': 'mimalloc 3.0.1', 
        'color': '#2ecc71',  # green
        'start_time': datetime.fromisoformat('2025-12-31T22:00:00'),
    },
    'group_B_mimalloc209_historical.txt': {
        'name': 'mimalloc 2.0.9', 
        'color': '#3498db',  # blue
        'start_time': datetime.fromisoformat('2026-01-02T22:00:00'),
    },
    'group_C_mimalloc217_historical.txt': {
        'name': 'mimalloc 2.1.7', 
        'color': '#9b59b6',  # purple
        'start_time': datetime.fromisoformat('2026-01-02T22:00:00'),
    },
    'group_D_jemalloc.txt': {
        'name': 'jemalloc 5.3.0', 
        'color': '#e67e22',  # orange
        'start_time': datetime.fromisoformat('2026-01-04T22:00:00'),
    },
    'group_E_glibc_historical.txt': {
        'name': 'glibc 2.41', 
        'color': '#e74c3c',  # red
        'start_time': datetime.fromisoformat('2026-01-02T00:00:00'),
    },
}

def load_group_file(path: Path) -> set:
    """Load relay names from group file"""
    try:
        with open(path, 'r') as f:
            return set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        return set()

def main():
    print(f"Reading {CSV_FILE}...")
    
    # Load group membership
    relay_to_group = {}
    for filename in GROUP_CONFIG.keys():
        filepath = GROUPS_DIR / filename
        relays = load_group_file(filepath)
        for relay in relays:
            relay_to_group[relay] = filename
        print(f"  {GROUP_CONFIG[filename]['name']}: {len(relays)} relays")
    
    # Data structure: {group_file: {timestamp: [rss_values]}}
    data = defaultdict(lambda: defaultdict(list))
    
    with open(CSV_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('type') != 'relay':
                continue
            
            nickname = row.get('nickname', '')
            group_file = relay_to_group.get(nickname)
            if not group_file:
                continue
            
            try:
                timestamp = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
                if timestamp.tzinfo is not None:
                    timestamp = timestamp.replace(tzinfo=None)
                
                # Filter by start time
                start_time = GROUP_CONFIG[group_file]['start_time']
                if timestamp < start_time:
                    continue
                
                rss_kb = float(row['rss_kb'])
                rss_gb = rss_kb / 1024 / 1024
                data[group_file][timestamp].append(rss_gb)
            except (ValueError, KeyError):
                continue
    
    # Calculate averages per group per timestamp
    group_series = {}
    for group_file, config in GROUP_CONFIG.items():
        timestamps = sorted(data[group_file].keys())
        if timestamps:
            averages = [sum(data[group_file][t]) / len(data[group_file][t]) for t in timestamps]
            group_series[group_file] = (timestamps, averages)
            print(f"  {config['name']}: {len(timestamps)} data points")
    
    # Create figure with dark theme
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(12, 7))
    fig.set_facecolor('#0d1117')
    ax.set_facecolor('#0d1117')
    
    # Plot order: worst to best (so best lines are on top)
    plot_order = [
        'group_A_mimalloc301.txt',      # worst
        'group_E_glibc_historical.txt',
        'group_D_jemalloc.txt',
        'group_C_mimalloc217_historical.txt',
        'group_B_mimalloc209_historical.txt',  # best
    ]
    
    for group_file in plot_order:
        config = GROUP_CONFIG[group_file]
        timestamps, values = group_series.get(group_file, ([], []))
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
    ax.set_title('mimalloc Version Comparison: 3.0.1 vs 2.x\nDebian 13, Tor 0.4.8.x, go (200 relays)', 
                 fontsize=14, fontweight='bold', pad=15)
    
    # Format x-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    plt.xticks(rotation=45, ha='right')
    
    # Grid and legend
    ax.grid(True, alpha=0.3, color='#444444')
    ax.legend(loc='upper left', fontsize=11, framealpha=0.9)
    
    # Set y-axis
    ax.set_ylim(bottom=0, top=10)
    
    # Get last timestamp for label positioning
    all_timestamps = []
    for ts, _ in group_series.values():
        all_timestamps.extend(ts)
    last_ts = max(all_timestamps) if all_timestamps else datetime.now()
    
    # Add horizontal reference lines
    ax.axhline(y=5, color='#666666', linestyle='--', alpha=0.5, linewidth=1)
    ax.text(last_ts, 5.15, '5 GB', fontsize=9, color='#888888', ha='right')
    
    ax.axhline(y=2, color='#00ff7f', linestyle='--', alpha=0.4, linewidth=1)
    ax.text(last_ts, 2.15, '2 GB target', fontsize=9, color='#00ff7f', alpha=0.7, ha='right')
    
    # Style spines
    for spine in ax.spines.values():
        spine.set_color('#444444')
    ax.tick_params(colors='#888888')
    
    plt.tight_layout()
    
    # Save
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    print(f"\nSaving to {OUTPUT_FILE}...")
    plt.savefig(OUTPUT_FILE, dpi=150, bbox_inches='tight', facecolor='#0d1117', edgecolor='none')
    print(f"Done! Chart saved to {OUTPUT_FILE}")
    
    # Show stats
    print("\n--- Final Memory by Allocator ---")
    stats = []
    for group_file, (timestamps, values) in group_series.items():
        if values:
            config = GROUP_CONFIG[group_file]
            stats.append((config['name'], values[-1]))
    
    for name, val in sorted(stats, key=lambda x: x[1]):
        print(f"  {name}: {val:.2f} GB")

if __name__ == '__main__':
    main()

