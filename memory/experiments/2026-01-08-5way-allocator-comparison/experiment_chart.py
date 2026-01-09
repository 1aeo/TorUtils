#!/usr/bin/env python3
"""
Generate progress chart for Tor relay memory experiment
Compares allocator groups: glibc vs mimalloc 2.x vs 3.x
Uses only standard library + matplotlib (no pandas)
"""

import csv
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from collections import defaultdict
from pathlib import Path

# Configuration - relative to this script's location
SCRIPT_DIR = Path(__file__).parent.resolve()
BASE_DIR = SCRIPT_DIR
GROUPS_DIR = BASE_DIR / "groups"
CSV_FILE = BASE_DIR / "memory.csv"
OUTPUT_FILE = BASE_DIR / "charts" / "memory_timeseries.png"

# Group labels, colors, and experiment start times
# Only data AFTER start_time is included for each group
# Using historical groups for B, C, E to preserve experiment data continuity
GROUP_CONFIG = {
    'group_A_mimalloc301.txt': {
        'letter': 'A', 
        'name': 'mimalloc 3.0.1', 
        'color': '#2ecc71',
        'start_time': datetime.fromisoformat('2025-12-31T22:00:00'),  # After restart with mimalloc enabled
    },
    'group_B_mimalloc209_historical.txt': {
        'letter': 'B', 
        'name': 'mimalloc 2.0.9', 
        'color': '#3498db',
        'start_time': datetime.fromisoformat('2026-01-02T22:00:00'),  # After allocator change (was glibc before)
    },
    'group_C_mimalloc217_historical.txt': {
        'letter': 'C', 
        'name': 'mimalloc 2.1.7', 
        'color': '#9b59b6',
        'start_time': datetime.fromisoformat('2026-01-02T22:00:00'),  # After allocator change (was glibc before)
    },
    'group_D_jemalloc.txt': {
        'letter': 'D', 
        'name': 'jemalloc 5.3.0', 
        'color': '#e67e22',
        'start_time': datetime.fromisoformat('2026-01-04T22:00:00'),  # When allocator was activated (Jan 4)
    },
    'group_E_glibc_historical.txt': {
        'letter': 'E', 
        'name': 'glibc 2.41 (control)', 
        'color': '#e74c3c',
        'start_time': datetime.fromisoformat('2026-01-02T00:00:00'),  # Show from Jan 2 for full history
    },
}

def load_group_file(path: Path) -> set:
    """Load relay names from group file"""
    try:
        with open(path, 'r') as f:
            return set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        return set()

def load_events(csv_path: Path) -> list:
    """Load events from events.csv"""
    events = []
    try:
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    ts = datetime.fromisoformat(row['timestamp'])
                    events.append({
                        'timestamp': ts,
                        'type': row.get('event_type', 'unknown'),
                        'description': row.get('description', ''),
                        'group': row.get('group', 'all'),
                    })
                except (ValueError, KeyError):
                    continue
    except FileNotFoundError:
        pass
    return events

def main():
    print(f"Reading {CSV_FILE}...")
    
    # Load group membership
    groups = {}
    relay_to_group = {}
    
    for filename, config in GROUP_CONFIG.items():
        filepath = GROUPS_DIR / filename
        relays = load_group_file(filepath)
        if relays:
            groups[filename] = {
                'relays': relays,
                'config': config,
            }
            for relay in relays:
                relay_to_group[relay] = filename
            print(f"  {config['letter']}: {config['name']} - {len(relays)} relays (data from {config['start_time'].strftime('%Y-%m-%d %H:%M')})")
    
    # Data structure: {group_file: {timestamp: [rss_values]}}
    data = defaultdict(lambda: defaultdict(list))
    
    with open(CSV_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip aggregate rows
            if row.get('type') != 'relay':
                continue
            
            nickname = row.get('nickname', '')
            if not nickname:
                continue
            
            # Determine group from our loaded files
            group_file = relay_to_group.get(nickname)
            if not group_file:
                continue
            
            try:
                timestamp = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
                # Make timestamp naive for comparison
                if timestamp.tzinfo is not None:
                    timestamp = timestamp.replace(tzinfo=None)
                
                # FILTER: Only include data AFTER the experiment started for this group
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
            print(f"  {config['letter']}: {len(timestamps)} data points")
        else:
            print(f"  {config['letter']}: No data yet (experiment just started)")
    
    # Load events
    events = load_events(BASE_DIR / "events.csv")
    
    # Create figure
    fig, ax = plt.subplots(figsize=(14, 8))
    
    # Plot each group (sorted by letter)
    sorted_groups = sorted(GROUP_CONFIG.items(), key=lambda x: x[1]['letter'])
    
    for group_file, config in sorted_groups:
        timestamps, values = group_series.get(group_file, ([], []))
        if timestamps:
            relay_count = len(groups.get(group_file, {}).get('relays', []))
            ax.plot(timestamps, values, 
                   label=f"{config['letter']}: {config['name']} ({relay_count})", 
                   color=config['color'],
                   linewidth=2,
                   marker='o',
                   markersize=4)
    
    # Add event markers (vertical lines) - only show recent ones
    event_colors = {
        'restart': '#ffd93d',
        'config_change': '#6bcb77',
        'relay_add': '#a29bfe',
        'experiment': '#74b9ff',
        'config_activated': '#2ecc71',
    }
    
    for event in events:
        color = event_colors.get(event['type'], '#888888')
        ax.axvline(x=event['timestamp'], color=color, linestyle=':', linewidth=1.5, alpha=0.6)
    
    # Formatting
    ax.set_xlabel('Date', fontsize=12)
    ax.set_ylabel('Memory (GB)', fontsize=12)
    ax.set_title('Tor Relay Memory by Allocator\n5-Way Comparison (go, Debian 13)', fontsize=14)
    
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
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    print(f"\nSaving to {OUTPUT_FILE}...")
    plt.savefig(OUTPUT_FILE, dpi=150, bbox_inches='tight')
    print(f"Done! Chart saved to {OUTPUT_FILE}")
    
    # Show latest stats
    print("\n--- Latest Memory by Group ---")
    latest_stats = []
    for group_file, (timestamps, values) in group_series.items():
        if values:
            config = GROUP_CONFIG[group_file]
            relay_count = len(groups.get(group_file, {}).get('relays', []))
            latest_stats.append((config['letter'], config['name'], values[-1], relay_count))
    
    for letter, name, val, count in sorted(latest_stats, key=lambda x: x[2]):
        print(f"  {letter} ({name}, {count} relays): {val:.2f} GB")
    
    if not latest_stats:
        print("  No data collected yet for any group")
    
    # Show events
    if events:
        print("\n--- Recent Events ---")
        for event in events[-5:]:
            print(f"  {event['timestamp'].strftime('%Y-%m-%d %H:%M')} [{event['type']}] {event['description']}")

if __name__ == '__main__':
    main()
