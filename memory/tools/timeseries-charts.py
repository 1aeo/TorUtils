#!/usr/bin/env python3
"""
Tor Relay Memory Time-Series Charts

Generates visualizations from time-series memory data (monitor.sh output):
  1. Total and per-relay memory usage over time
  2. Weekly average trends

Usage:
    python3 timeseries-charts.py --data memory_stats.csv --output-dir ./
    python3 timeseries-charts.py --data memory_stats.csv --title "My Server"

Requirements:
    pip install matplotlib
"""

import argparse
import csv
from datetime import datetime
from pathlib import Path
import sys

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

from chart_utils import (
    check_matplotlib, setup_dark_theme, style_axis, style_figure,
    save_chart, format_date_axis, calculate_weekly_averages, calculate_weekly_max, THEME
)

check_matplotlib()

import matplotlib.pyplot as plt


def load_data(csv_path: str) -> dict:
    """Load time-series data from CSV."""
    data = {
        'dates': [],
        'num_relays': [],
        'total_mb': [],
        'avg_mb': [],
        'min_mb': [],
        'max_mb': [],
    }
    
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dt = datetime.strptime(f"{row['date']} {row['time']}", "%Y-%m-%d %H:%M:%S")
                data['dates'].append(dt)
                data['num_relays'].append(int(row['num_relays']))
                data['total_mb'].append(int(row['total_mb']))
                data['avg_mb'].append(int(row['avg_mb']))
                data['min_mb'].append(int(row['min_mb']))
                data['max_mb'].append(int(row['max_mb']))
            except (KeyError, ValueError) as e:
                print(f"Warning: Skipping invalid row: {e}")
                continue
    
    # Convert to GB
    data['total_gb'] = [x / 1024 for x in data['total_mb']]
    data['avg_gb'] = [x / 1024 for x in data['avg_mb']]
    data['min_gb'] = [x / 1024 for x in data['min_mb']]
    data['max_gb'] = [x / 1024 for x in data['max_mb']]
    
    return data


def find_relay_changes(dates: list, num_relays: list) -> list[tuple]:
    """
    Find points where relay count changes.
    
    Returns:
        List of (date, new_count) tuples at change points
    """
    changes = []
    if not num_relays:
        return changes
    
    # Always include first point
    changes.append((dates[0], num_relays[0]))
    
    prev_count = num_relays[0]
    for i in range(1, len(num_relays)):
        if num_relays[i] != prev_count:
            changes.append((dates[i], num_relays[i]))
            prev_count = num_relays[i]
    
    return changes


def add_relay_change_lines(ax, changes: list[tuple], y_max: float):
    """Add vertical lines and labels for relay count changes."""
    for i, (date, count) in enumerate(changes):
        # Vertical dashed line
        ax.axvline(x=date, color='#888888', linestyle='--', linewidth=1, alpha=0.7)
        
        # Label at top of chart (alternate positions to avoid overlap)
        y_pos = y_max * (0.95 if i % 2 == 0 else 0.85)
        ax.text(date, y_pos, f'{count} relays', 
                fontsize=9, color='#cccccc', ha='center', va='top',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='#1a1a2e', 
                         edgecolor='#444444', alpha=0.9))


def chart_usage_over_time(data: dict, output_path: Path, title: str, color: str):
    """Generate usage over time chart with total and per-relay views."""
    setup_dark_theme()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), dpi=150)
    
    dates = data['dates']
    total_gb = data['total_gb']
    avg_gb = data['avg_gb']
    min_gb = data['min_gb']
    max_gb = data['max_gb']
    num_relays = data['num_relays']
    current_relays = num_relays[-1] if num_relays else 0
    
    # Find relay count change points
    relay_changes = find_relay_changes(dates, num_relays)
    
    fig.suptitle(f'Tor Relay Memory Usage - {title} ({current_relays} Relays)', 
                 fontsize=16, fontweight='bold', color=color)
    
    # Chart 1: Total Memory Usage
    ax1.fill_between(dates, total_gb, alpha=0.3, color=color)
    ax1.plot(dates, total_gb, color=color, linewidth=2, marker='o', markersize=3)
    ax1.set_ylabel('Total Memory (GB)', fontsize=12, color='#ffffff')
    ax1.set_title('Total Memory Usage Across All Relays', fontsize=12, color='#aaaaaa')
    
    # Set y-axis minimum based on data
    y_min = min(total_gb) * 0.9 if total_gb else 0
    ax1.set_ylim(bottom=max(0, y_min))
    
    # Annotate key points
    if total_gb:
        min_idx = total_gb.index(min(total_gb))
        max_idx = total_gb.index(max(total_gb))
        
        ax1.annotate(f'Low: {total_gb[min_idx]:.1f} GB\n{dates[min_idx].strftime("%b %d")}', 
                     xy=(dates[min_idx], total_gb[min_idx]), 
                     xytext=(10, 30), textcoords='offset points',
                     fontsize=9, color=THEME['secondary'],
                     arrowprops=dict(arrowstyle='->', color=THEME['secondary'], lw=1))
        ax1.annotate(f'High: {total_gb[max_idx]:.1f} GB\n{dates[max_idx].strftime("%b %d")}', 
                     xy=(dates[max_idx], total_gb[max_idx]), 
                     xytext=(10, -40), textcoords='offset points',
                     fontsize=9, color='#4ecdc4',
                     arrowprops=dict(arrowstyle='->', color='#4ecdc4', lw=1))
    
    # Chart 2: Per-Relay Memory (Avg, Min, Max)
    ax2.fill_between(dates, min_gb, max_gb, alpha=0.2, color=THEME['secondary'], label='Min-Max Range')
    ax2.plot(dates, max_gb, color=THEME['secondary'], linewidth=1.5, linestyle='--', 
             label=f'Max ({max_gb[-1]:.2f} GB)' if max_gb else 'Max', alpha=0.8)
    ax2.plot(dates, avg_gb, color=THEME['accent'], linewidth=2.5, marker='o', markersize=3, 
             label=f'Average ({avg_gb[-1]:.2f} GB)' if avg_gb else 'Average')
    ax2.plot(dates, min_gb, color=THEME['success'], linewidth=1.5, linestyle='--', 
             label=f'Min ({min_gb[-1]:.2f} GB)' if min_gb else 'Min', alpha=0.8)
    
    ax2.set_xlabel('Date', fontsize=12, color='#ffffff')
    ax2.set_ylabel('Memory per Relay (GB)', fontsize=12, color='#ffffff')
    ax2.set_title('Per-Relay Memory Usage (Average, Min, Max)', fontsize=12, color='#aaaaaa')
    ax2.legend(loc='center left', bbox_to_anchor=(1.01, 0.5), fontsize=10, facecolor='#1a1a2e', edgecolor='#444444')
    
    # Set reasonable y limits
    if min_gb:
        ax2.set_ylim(bottom=max(0, min(min_gb) * 0.9))
    
    # Add relay count change markers (only if count changed)
    if len(relay_changes) > 1:
        add_relay_change_lines(ax1, relay_changes, max(total_gb) * 1.1 if total_gb else 100)
        add_relay_change_lines(ax2, relay_changes, max(max_gb) * 1.1 if max_gb else 10)
    
    # Apply styling
    for ax in [ax1, ax2]:
        style_axis(ax)
        format_date_axis(ax)
    
    style_figure(fig)
    plt.tight_layout()
    save_chart(fig, output_path)
    print(f"✓ Usage chart saved: {output_path}")


def chart_weekly_trend(data: dict, output_path: Path, title: str, color: str):
    """Generate weekly average trend chart with relay counts."""
    setup_dark_theme()
    fig, ax = plt.subplots(figsize=(12, 6), dpi=150)
    
    dates = data['dates']
    total_gb = data['total_gb']
    num_relays = data['num_relays']
    
    weeks, week_avgs = calculate_weekly_averages(dates, total_gb)
    _, week_max_relays = calculate_weekly_max(dates, num_relays)
    
    if not week_avgs:
        print("Warning: Not enough data for weekly chart")
        plt.close()
        return
    
    # Bar chart with gradient colors
    cmap = plt.cm.viridis if color == THEME['primary'] else plt.cm.Reds
    colors = cmap([0.3 + 0.5 * i/len(week_avgs) for i in range(len(week_avgs))])
    bars = ax.bar(range(len(week_avgs)), week_avgs, color=colors, edgecolor=color, linewidth=1)
    
    # Get year from data
    year = dates[0].year if dates else 2025
    
    ax.set_xlabel(f'Week Number ({year})', fontsize=12, color='#ffffff')
    ax.set_ylabel('Average Total Memory (GB)', fontsize=12, color='#ffffff')
    ax.set_title(f'{title} - Weekly Average Memory Usage', fontsize=14, fontweight='bold', color=color)
    ax.set_xticks(range(len(weeks)))
    ax.set_xticklabels([f'W{w}' for w in weeks], rotation=45, ha='right')
    
    # Add value labels on bars (GB + relay count)
    for bar, val, relays in zip(bars, week_avgs, week_max_relays):
        label = f'{val:.0f} GB\n({relays} relays)'
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(week_avgs) * 0.02, 
                label, ha='center', va='bottom', fontsize=8, color='#ffffff')
    
    style_axis(ax, show_grid=True)
    
    # Set y-axis with some headroom for labels
    ax.set_ylim(0, max(week_avgs) * 1.15)
    
    style_figure(fig)
    plt.tight_layout()
    save_chart(fig, output_path)
    print(f"✓ Weekly chart saved: {output_path}")


def print_summary(data: dict, title: str):
    """Print summary statistics."""
    if not data['dates']:
        print("No data available")
        return
    
    print(f"\n=== {title} Memory Summary ===")
    print(f"Monitoring period: {data['dates'][0].strftime('%Y-%m-%d')} to {data['dates'][-1].strftime('%Y-%m-%d')}")
    print(f"Data points: {len(data['dates'])}")
    print(f"Number of relays: {data['num_relays'][-1]}")
    print(f"Starting total: {data['total_gb'][0]:.1f} GB")
    print(f"Current total: {data['total_gb'][-1]:.1f} GB")
    
    growth = data['total_gb'][-1] - data['total_gb'][0]
    growth_pct = ((data['total_gb'][-1] / data['total_gb'][0]) - 1) * 100 if data['total_gb'][0] > 0 else 0
    print(f"Growth: {'+' if growth >= 0 else ''}{growth:.1f} GB ({growth_pct:+.0f}%)")
    
    print(f"Current avg/relay: {data['avg_gb'][-1]:.2f} GB")
    print(f"Current min relay: {data['min_gb'][-1]:.2f} GB")
    print(f"Current max relay: {data['max_gb'][-1]:.2f} GB")


def main():
    parser = argparse.ArgumentParser(
        description='Generate time-series memory charts from monitor.sh data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python3 timeseries-charts.py --data memory_stats.csv
    python3 timeseries-charts.py --data stats.csv --title "Production" --color "#ff6b6b"
    python3 timeseries-charts.py --data stats.csv --output-dir ./charts/
        """
    )
    parser.add_argument('--data', required=True,
                        help='Path to CSV data file from monitor.sh')
    parser.add_argument('--output-dir', default='./',
                        help='Directory for output charts (default: ./)')
    parser.add_argument('--title', default='Server',
                        help='Title/name for charts (default: Server)')
    parser.add_argument('--color', default=THEME['primary'],
                        help=f"Primary color for charts (default: {THEME['primary']})")
    parser.add_argument('--prefix', default='memory',
                        help='Output filename prefix (default: memory)')
    
    args = parser.parse_args()
    
    # Validate input file
    data_path = Path(args.data)
    if not data_path.exists():
        print(f"Error: Data file not found: {data_path}")
        sys.exit(1)
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load data
    print(f"Loading data from: {data_path}")
    data = load_data(str(data_path))
    print(f"Loaded {len(data['dates'])} data points")
    
    if not data['dates']:
        print("Error: No valid data found in CSV")
        sys.exit(1)
    
    # Generate charts
    print("\nGenerating charts...")
    chart_usage_over_time(data, output_dir / f'{args.prefix}_usage.png', args.title, args.color)
    chart_weekly_trend(data, output_dir / f'{args.prefix}_weekly.png', args.title, args.color)
    
    # Print summary
    print_summary(data, args.title)
    
    print(f"\n✓ All charts generated in: {output_dir.absolute()}")


if __name__ == '__main__':
    main()
