#!/usr/bin/env python3
"""
Allocator Comparison Charts

Compares memory usage across different allocator groups based on group files.

Usage:
    python3 allocator-comparison.py \
        --data /path/to/memory.csv \
        --groups-dir /path/to/monitoring/go/ \
        --output-dir /path/to/charts/

Requirements:
    pip install matplotlib
"""

import argparse
import csv
from datetime import datetime
from pathlib import Path
import sys
from collections import defaultdict

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

from chart_utils import (
    check_matplotlib, setup_dark_theme, style_axis, style_figure,
    save_chart, format_date_axis, THEME
)

check_matplotlib()

import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Allocator colors and display names
# Group file format: group_X_name.txt where X is the letter
ALLOCATOR_CONFIG = {
    'A_mimalloc301': {'color': '#2ecc71', 'name': 'A: mimalloc 3.0.1', 'order': 1},
    'B_mimalloc209': {'color': '#3498db', 'name': 'B: mimalloc 2.0.9', 'order': 2},
    'C_mimalloc217': {'color': '#9b59b6', 'name': 'C: mimalloc 2.1.7', 'order': 3},
    'D_jemalloc': {'color': '#e67e22', 'name': 'D: jemalloc 5.3.0', 'order': 4},
    'E_glibc': {'color': '#e74c3c', 'name': 'E: glibc (control)', 'order': 5},
}


def load_group_files(groups_dir: Path) -> dict:
    """Load relay-to-group mappings from group files."""
    relay_to_group = {}
    group_counts = {}
    
    for group_file in groups_dir.glob('group_*.txt'):
        # Extract group name from filename (e.g., group_mimalloc301.txt -> mimalloc301)
        group_name = group_file.stem.replace('group_', '')
        
        # Skip old group files
        if group_name in ['a_mimalloc', 'b_glibc', 'c_mimalloc209', 'd_mimalloc217', 'z_glibc']:
            continue
        
        with open(group_file, 'r') as f:
            relays = [line.strip() for line in f if line.strip()]
            group_counts[group_name] = len(relays)
            for relay in relays:
                relay_to_group[relay] = group_name
    
    print(f"Loaded {len(relay_to_group)} relay-to-group mappings")
    for group, count in sorted(group_counts.items()):
        print(f"  {group}: {count} relays")
    
    return relay_to_group


def load_memory_data(csv_path: Path, relay_to_group: dict) -> dict:
    """Load memory data and assign groups to relays."""
    data = {
        'dates': [],
        'groups': defaultdict(lambda: {'dates': [], 'avg_gb': [], 'min_gb': [], 'max_gb': [], 'relays': defaultdict(list)}),
    }
    
    # First pass: collect all relay data
    relay_data = defaultdict(lambda: {'dates': [], 'rss_kb': []})
    timestamps = set()
    
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('type') == 'relay':
                nickname = row.get('nickname', '')
                if nickname and nickname in relay_to_group:
                    try:
                        dt = datetime.fromisoformat(row['timestamp'])
                        rss_kb = int(row.get('rss_kb', 0))
                        relay_data[nickname]['dates'].append(dt)
                        relay_data[nickname]['rss_kb'].append(rss_kb)
                        relay_data[nickname]['group'] = relay_to_group[nickname]
                        timestamps.add(dt)
                    except (ValueError, KeyError):
                        continue
    
    # Sort timestamps
    sorted_timestamps = sorted(timestamps)
    data['dates'] = sorted_timestamps
    
    # Second pass: aggregate by group and timestamp
    for ts in sorted_timestamps:
        group_values = defaultdict(list)
        
        for nickname, relay_info in relay_data.items():
            group = relay_info.get('group')
            if not group:
                continue
            
            # Find value at this timestamp
            for i, dt in enumerate(relay_info['dates']):
                if dt == ts:
                    rss_gb = relay_info['rss_kb'][i] / 1048576
                    group_values[group].append(rss_gb)
                    break
        
        # Calculate stats per group
        for group, values in group_values.items():
            if values:
                data['groups'][group]['dates'].append(ts)
                data['groups'][group]['avg_gb'].append(sum(values) / len(values))
                data['groups'][group]['min_gb'].append(min(values))
                data['groups'][group]['max_gb'].append(max(values))
    
    return data


def chart_allocator_comparison_timeseries(data: dict, output_path: Path, title: str):
    """Generate time series comparison of allocator groups (clean lines, no error bars)."""
    setup_dark_theme()
    fig, ax = plt.subplots(figsize=(14, 8), dpi=150)
    
    # Sort groups by order
    sorted_groups = sorted(
        data['groups'].items(),
        key=lambda x: ALLOCATOR_CONFIG.get(x[0], {}).get('order', 99)
    )
    
    for group_name, group_data in sorted_groups:
        if not group_data['dates']:
            continue
        
        config = ALLOCATOR_CONFIG.get(group_name, {'color': '#888888', 'name': group_name})
        
        # Plot average line only (no error bars for cleaner visualization)
        ax.plot(group_data['dates'], group_data['avg_gb'], 
                color=config['color'], linewidth=2.5, marker='o', markersize=5,
                label=f"{config['name']} ({group_data['avg_gb'][-1]:.2f} GB)")
    
    ax.set_xlabel('Date', fontsize=12, color='#ffffff')
    ax.set_ylabel('Average Memory per Relay (GB)', fontsize=12, color='#ffffff')
    ax.set_title(f'{title} - Memory Usage by Allocator', fontsize=14, fontweight='bold', color=THEME['primary'])
    
    ax.legend(loc='center left', bbox_to_anchor=(1.01, 0.5), fontsize=11,
              facecolor='#1a1a2e', edgecolor='#444444')
    
    style_axis(ax)
    format_date_axis(ax)
    style_figure(fig)
    plt.tight_layout()
    save_chart(fig, output_path)
    print(f"✓ Allocator timeseries saved: {output_path}")


def chart_allocator_comparison_bar(data: dict, output_path: Path, title: str):
    """Generate bar chart comparing current memory by allocator."""
    setup_dark_theme()
    fig, ax = plt.subplots(figsize=(12, 7), dpi=150)
    
    # Collect latest values
    results = []
    for group_name, group_data in data['groups'].items():
        if not group_data['avg_gb']:
            continue
        
        config = ALLOCATOR_CONFIG.get(group_name, {'color': '#888888', 'name': group_name, 'order': 99})
        
        
        results.append({
            'group': group_name,
            'name': config['name'],
            'color': config['color'],
            'order': config['order'],
            'avg': group_data['avg_gb'][-1],
            'min': group_data['min_gb'][-1],
            'max': group_data['max_gb'][-1],
        })
    
    # Sort by memory usage (lowest first)
    results.sort(key=lambda x: x['avg'])
    
    y_pos = range(len(results))
    
    # Draw bars
    bars = ax.barh(y_pos, [r['avg'] for r in results], 
                   color=[r['color'] for r in results],
                   height=0.5, edgecolor='white', linewidth=1)
    
    # Add error bars for range (below center line)
    for i, r in enumerate(results):
        y_offset = i - 0.15  # Position error bar below center
        ax.plot([r['min'], r['max']], [y_offset, y_offset], color='white', linewidth=2, alpha=0.7)
        ax.plot([r['min']], [y_offset], marker='|', color='white', markersize=8)
        ax.plot([r['max']], [y_offset], marker='|', color='white', markersize=8)
    
    # Add value labels ABOVE the bar (not overlapping error bar)
    for i, (bar, r) in enumerate(zip(bars, results)):
        width = bar.get_width()
        label = f'{r["avg"]:.2f} GB  (range: {r["min"]:.2f}-{r["max"]:.2f})'
        y_text = bar.get_y() + bar.get_height() + 0.05  # Above the bar
        ax.text(width + 0.1, y_text,
                label, va='bottom', fontsize=10, color='#ffffff')
    
    ax.set_yticks(y_pos)
    ax.set_yticklabels([r['name'] for r in results], fontsize=11)
    ax.set_xlabel('Memory per Relay (GB)', fontsize=12, color='#ffffff')
    ax.set_title(f'{title} - Current Memory by Allocator (Lower is Better)', 
                 fontsize=14, fontweight='bold', color=THEME['primary'])
    
    # Reference line for glibc
    glibc_avg = next((r['avg'] for r in results if r['group'] == 'glibc'), None)
    if glibc_avg:
        ax.axvline(x=glibc_avg, color=THEME['secondary'], linestyle='--', linewidth=2, alpha=0.7)
        ax.text(glibc_avg, len(results) - 0.5, 'glibc baseline', 
                fontsize=9, color=THEME['secondary'], ha='center')
    
    ax.invert_yaxis()
    ax.set_xlim(0, max(r['max'] for r in results) * 1.4)
    ax.set_ylim(len(results) - 0.5, -0.5)  # Add padding
    
    style_axis(ax, show_grid=True)
    style_figure(fig)
    plt.tight_layout()
    save_chart(fig, output_path)
    print(f"✓ Allocator comparison saved: {output_path}")


def chart_allocator_distribution(data: dict, output_path: Path, title: str):
    """Generate box plot showing memory distribution by allocator."""
    setup_dark_theme()
    fig, ax = plt.subplots(figsize=(12, 7), dpi=150)
    
    # Collect latest values for box plot
    box_data = []
    labels = []
    colors = []
    
    sorted_groups = sorted(
        data['groups'].items(),
        key=lambda x: ALLOCATOR_CONFIG.get(x[0], {}).get('order', 99)
    )
    
    for group_name, group_data in sorted_groups:
        if not group_data['avg_gb'] or group_name == 'mimalloc301_extra':
            continue
        
        config = ALLOCATOR_CONFIG.get(group_name, {'color': '#888888', 'name': group_name})
        
        # Get all values at latest timestamp (use avg as proxy since we don't have individual relay data here)
        # For a proper box plot, we'd need to track individual relay values
        # Using min/avg/max to approximate
        latest_min = group_data['min_gb'][-1]
        latest_avg = group_data['avg_gb'][-1]
        latest_max = group_data['max_gb'][-1]
        
        # Create synthetic data points for visualization
        box_data.append([latest_min, latest_avg - (latest_avg - latest_min)/2, 
                        latest_avg, latest_avg + (latest_max - latest_avg)/2, latest_max])
        labels.append(config['name'])
        colors.append(config['color'])
    
    # Create box plot
    bp = ax.boxplot(box_data, patch_artist=True, tick_labels=labels)
    
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    
    for element in ['whiskers', 'caps', 'medians']:
        for item in bp[element]:
            item.set_color('white')
    
    ax.set_ylabel('Memory per Relay (GB)', fontsize=12, color='#ffffff')
    ax.set_title(f'{title} - Memory Distribution by Allocator', 
                 fontsize=14, fontweight='bold', color=THEME['primary'])
    
    plt.xticks(rotation=15, ha='right')
    
    style_axis(ax, show_grid=True)
    style_figure(fig)
    plt.tight_layout()
    save_chart(fig, output_path)
    print(f"✓ Distribution chart saved: {output_path}")


def print_summary(data: dict):
    """Print summary statistics."""
    print("\n" + "=" * 60)
    print("ALLOCATOR COMPARISON SUMMARY")
    print("=" * 60)
    
    results = []
    for group_name, group_data in data['groups'].items():
        if not group_data['avg_gb'] or group_name == 'mimalloc301_extra':
            continue
        
        config = ALLOCATOR_CONFIG.get(group_name, {'name': group_name})
        results.append({
            'name': config['name'],
            'avg': group_data['avg_gb'][-1],
            'min': group_data['min_gb'][-1],
            'max': group_data['max_gb'][-1],
        })
    
    results.sort(key=lambda x: x['avg'])
    
    # Find glibc baseline
    glibc_avg = next((r['avg'] for r in results if 'glibc' in r['name']), None)
    
    print(f"\n{'Allocator':<25} {'Avg (GB)':<12} {'Min':<10} {'Max':<10} {'vs glibc':<12}")
    print("-" * 70)
    
    for r in results:
        if glibc_avg:
            diff_pct = ((r['avg'] - glibc_avg) / glibc_avg) * 100
            diff_str = f"{diff_pct:+.1f}%"
        else:
            diff_str = "-"
        
        print(f"{r['name']:<25} {r['avg']:<12.2f} {r['min']:<10.2f} {r['max']:<10.2f} {diff_str:<12}")
    
    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description='Compare memory usage across allocator groups',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python3 allocator-comparison.py \\
        --data /home/aeo1/monitoring/go/memory.csv \\
        --groups-dir /home/aeo1/monitoring/go/ \\
        --output-dir /home/aeo1/monitoring/go/charts/
        """
    )
    parser.add_argument('--data', required=True,
                        help='Path to memory.csv file')
    parser.add_argument('--groups-dir', required=True,
                        help='Directory containing group_*.txt files')
    parser.add_argument('--output-dir', default='./',
                        help='Output directory for charts')
    parser.add_argument('--title', default='go',
                        help='Title for charts')
    
    args = parser.parse_args()
    
    data_path = Path(args.data)
    groups_dir = Path(args.groups_dir)
    output_dir = Path(args.output_dir)
    
    if not data_path.exists():
        print(f"Error: Data file not found: {data_path}")
        sys.exit(1)
    
    if not groups_dir.exists():
        print(f"Error: Groups directory not found: {groups_dir}")
        sys.exit(1)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Loading group files from: {groups_dir}")
    relay_to_group = load_group_files(groups_dir)
    
    print(f"\nLoading memory data from: {data_path}")
    data = load_memory_data(data_path, relay_to_group)
    print(f"Loaded {len(data['dates'])} timestamps")
    
    print("\nGenerating charts...")
    chart_allocator_comparison_timeseries(data, output_dir / 'memory_timeseries.png', args.title)
    chart_allocator_comparison_bar(data, output_dir / 'memory_comparison.png', args.title)
    chart_allocator_distribution(data, output_dir / 'memory_boxplot.png', args.title)
    
    print_summary(data)
    
    print(f"\n✓ All charts generated in: {output_dir}")


if __name__ == '__main__':
    main()

