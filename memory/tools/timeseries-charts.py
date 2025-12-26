#!/usr/bin/env python3
"""
Tor Relay Memory Time-Series Charts

Generates visualizations from time-series memory data:
  1. Total and per-relay memory usage over time
  2. Weekly average trends
  3. Per-relay memory trajectories (new unified format)
  4. Relay memory distribution (new unified format)

Supports both legacy format (monitor.sh) and new unified format (collect.sh).

Usage:
    python3 timeseries-charts.py --data memory.csv --output-dir ./
    python3 timeseries-charts.py --data memory.csv --title "My Server"

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
    save_chart, format_date_axis, calculate_weekly_averages, calculate_weekly_max, THEME
)

check_matplotlib()

import matplotlib.pyplot as plt


def detect_format(csv_path: str) -> str:
    """Detect CSV format: 'unified' (new) or 'legacy' (old monitor.sh)."""
    with open(csv_path, 'r') as f:
        header = f.readline().strip()
        if 'type' in header and 'fingerprint' in header:
            return 'unified'
        elif 'date' in header and 'num_relays' in header:
            return 'legacy'
        else:
            raise ValueError(f"Unknown CSV format. Header: {header}")


def load_legacy_data(csv_path: str) -> dict:
    """Load legacy format data from monitor.sh CSV."""
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


def load_unified_data(csv_path: str) -> dict:
    """Load unified format data from collect.sh CSV."""
    data = {
        'dates': [],
        'num_relays': [],
        'total_kb': [],
        'avg_kb': [],
        'min_kb': [],
        'max_kb': [],
        # Per-relay data
        'relays': defaultdict(lambda: {'dates': [], 'rss_kb': [], 'nickname': ''}),
    }
    
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dt = datetime.fromisoformat(row['timestamp'])
                row_type = row.get('type', '')
                
                if row_type == 'aggregate':
                    data['dates'].append(dt)
                    data['num_relays'].append(int(row.get('count', 0)))
                    data['total_kb'].append(int(row.get('total_kb', 0)))
                    data['avg_kb'].append(int(row.get('avg_kb', 0)))
                    data['min_kb'].append(int(row.get('min_kb', 0)))
                    data['max_kb'].append(int(row.get('max_kb', 0)))
                    
                elif row_type == 'relay':
                    fingerprint = row.get('fingerprint', '')
                    if fingerprint:
                        data['relays'][fingerprint]['dates'].append(dt)
                        data['relays'][fingerprint]['rss_kb'].append(int(row.get('rss_kb', 0)))
                        data['relays'][fingerprint]['nickname'] = row.get('nickname', fingerprint[:8])
                        
            except (KeyError, ValueError) as e:
                print(f"Warning: Skipping invalid row: {e}")
                continue
    
    # Convert to MB/GB for aggregate data
    data['total_mb'] = [x / 1024 for x in data['total_kb']]
    data['avg_mb'] = [x / 1024 for x in data['avg_kb']]
    data['min_mb'] = [x / 1024 for x in data['min_kb']]
    data['max_mb'] = [x / 1024 for x in data['max_kb']]
    data['total_gb'] = [x / 1024 for x in data['total_mb']]
    data['avg_gb'] = [x / 1024 for x in data['avg_mb']]
    data['min_gb'] = [x / 1024 for x in data['min_mb']]
    data['max_gb'] = [x / 1024 for x in data['max_mb']]
    
    # Convert per-relay data to GB
    for fp in data['relays']:
        data['relays'][fp]['rss_gb'] = [x / 1048576 for x in data['relays'][fp]['rss_kb']]
    
    return data


def load_data(csv_path: str) -> tuple[dict, str]:
    """Load data from CSV, auto-detecting format."""
    format_type = detect_format(csv_path)
    print(f"Detected format: {format_type}")
    
    if format_type == 'unified':
        return load_unified_data(csv_path), format_type
    else:
        return load_legacy_data(csv_path), format_type


def find_relay_changes(dates: list, num_relays: list) -> list[tuple]:
    """Find points where relay count changes."""
    changes = []
    if not num_relays:
        return changes
    
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
        ax.axvline(x=date, color='#888888', linestyle='--', linewidth=1, alpha=0.7)
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
    
    relay_changes = find_relay_changes(dates, num_relays)
    
    fig.suptitle(f'Tor Relay Memory Usage - {title} ({current_relays} Relays)', 
                 fontsize=16, fontweight='bold', color=color)
    
    # Chart 1: Total Memory Usage
    ax1.fill_between(dates, total_gb, alpha=0.3, color=color)
    ax1.plot(dates, total_gb, color=color, linewidth=2, marker='o', markersize=3)
    ax1.set_ylabel('Total Memory (GB)', fontsize=12, color='#ffffff')
    ax1.set_title('Total Memory Usage Across All Relays', fontsize=12, color='#aaaaaa')
    
    y_min = min(total_gb) * 0.9 if total_gb else 0
    ax1.set_ylim(bottom=max(0, y_min))
    
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
    
    if min_gb:
        ax2.set_ylim(bottom=max(0, min(min_gb) * 0.9))
    
    if len(relay_changes) > 1:
        add_relay_change_lines(ax1, relay_changes, max(total_gb) * 1.1 if total_gb else 100)
        add_relay_change_lines(ax2, relay_changes, max(max_gb) * 1.1 if max_gb else 10)
    
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
    
    cmap = plt.cm.viridis if color == THEME['primary'] else plt.cm.Reds
    colors = cmap([0.3 + 0.5 * i/len(week_avgs) for i in range(len(week_avgs))])
    bars = ax.bar(range(len(week_avgs)), week_avgs, color=colors, edgecolor=color, linewidth=1)
    
    year = dates[0].year if dates else 2025
    
    ax.set_xlabel(f'Week Number ({year})', fontsize=12, color='#ffffff')
    ax.set_ylabel('Average Total Memory (GB)', fontsize=12, color='#ffffff')
    ax.set_title(f'{title} - Weekly Average Memory Usage', fontsize=14, fontweight='bold', color=color)
    ax.set_xticks(range(len(weeks)))
    ax.set_xticklabels([f'W{w}' for w in weeks], rotation=45, ha='right')
    
    for bar, val, relays in zip(bars, week_avgs, week_max_relays):
        label = f'{val:.0f} GB\n({relays} relays)'
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(week_avgs) * 0.02, 
                label, ha='center', va='bottom', fontsize=8, color='#ffffff')
    
    style_axis(ax, show_grid=True)
    ax.set_ylim(0, max(week_avgs) * 1.15)
    
    style_figure(fig)
    plt.tight_layout()
    save_chart(fig, output_path)
    print(f"✓ Weekly chart saved: {output_path}")


def chart_relay_trajectories(data: dict, output_path: Path, title: str, max_relays: int = 20):
    """Generate per-relay memory trajectories chart (unified format only)."""
    relays = data.get('relays', {})
    if not relays:
        print("Warning: No per-relay data available for trajectories chart")
        return
    
    setup_dark_theme()
    fig, ax = plt.subplots(figsize=(14, 8), dpi=150)
    
    # Sort relays by latest RSS (descending) to show top memory users
    relay_list = [(fp, info) for fp, info in relays.items() if info['rss_gb']]
    relay_list.sort(key=lambda x: x[1]['rss_gb'][-1] if x[1]['rss_gb'] else 0, reverse=True)
    
    # Limit to top N relays
    relay_list = relay_list[:max_relays]
    
    # Color palette
    colors = plt.cm.tab20(range(len(relay_list)))
    
    for i, (fp, info) in enumerate(relay_list):
        dates = info['dates']
        rss_gb = info['rss_gb']
        nickname = info['nickname'] or fp[:8]
        
        ax.plot(dates, rss_gb, color=colors[i], linewidth=1.5, marker='o', markersize=2,
                label=f'{nickname} ({rss_gb[-1]:.2f} GB)', alpha=0.8)
    
    ax.set_xlabel('Date', fontsize=12, color='#ffffff')
    ax.set_ylabel('Memory (GB)', fontsize=12, color='#ffffff')
    ax.set_title(f'{title} - Per-Relay Memory Trajectories (Top {len(relay_list)})', 
                 fontsize=14, fontweight='bold', color=THEME['primary'])
    
    # Legend outside plot
    ax.legend(loc='center left', bbox_to_anchor=(1.01, 0.5), fontsize=8, 
              facecolor='#1a1a2e', edgecolor='#444444', ncol=1)
    
    style_axis(ax)
    format_date_axis(ax)
    style_figure(fig)
    plt.tight_layout()
    save_chart(fig, output_path)
    print(f"✓ Relay trajectories chart saved: {output_path}")


def chart_relay_distribution(data: dict, output_path: Path, title: str):
    """Generate relay memory distribution chart (unified format only)."""
    relays = data.get('relays', {})
    if not relays:
        print("Warning: No per-relay data available for distribution chart")
        return
    
    setup_dark_theme()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6), dpi=150)
    
    # Get latest RSS values for all relays
    latest_rss = []
    nicknames = []
    for fp, info in relays.items():
        if info['rss_gb']:
            latest_rss.append(info['rss_gb'][-1])
            nicknames.append(info['nickname'] or fp[:8])
    
    if not latest_rss:
        print("Warning: No data for distribution chart")
        plt.close()
        return
    
    # Calculate mean once
    mean_rss = sum(latest_rss) / len(latest_rss)
    
    # Chart 1: Histogram
    ax1.hist(latest_rss, bins=20, color=THEME['primary'], edgecolor='white', alpha=0.7)
    ax1.axvline(x=mean_rss, color=THEME['accent'], linestyle='--', 
                linewidth=2, label=f'Mean: {mean_rss:.2f} GB')
    ax1.set_xlabel('Memory (GB)', fontsize=12, color='#ffffff')
    ax1.set_ylabel('Number of Relays', fontsize=12, color='#ffffff')
    ax1.set_title('Memory Distribution', fontsize=12, color='#aaaaaa')
    ax1.legend(fontsize=10, facecolor='#1a1a2e', edgecolor='#444444')
    
    # Chart 2: Top/Bottom relays bar chart
    sorted_data = sorted(zip(nicknames, latest_rss), key=lambda x: x[1], reverse=True)
    
    # Show top 10 and bottom 5
    top_n = min(10, len(sorted_data))
    bottom_n = min(5, len(sorted_data) - top_n)
    
    display_data = list(sorted_data[:top_n])
    if bottom_n > 0:
        display_data.append(('...', 0))  # Separator
        display_data.extend(sorted_data[-bottom_n:])
    
    names = [d[0] for d in display_data]
    values = [d[1] for d in display_data]
    
    # Color bars: red for high, green for low
    bar_colors = []
    for i, (name, val) in enumerate(display_data):
        if name == '...':
            bar_colors.append('#333333')
        elif i < top_n:
            bar_colors.append(THEME['secondary'])  # High memory = red
        else:
            bar_colors.append(THEME['success'])  # Low memory = green
    
    bars = ax2.barh(range(len(names)), values, color=bar_colors, edgecolor='white', height=0.7)
    ax2.set_yticks(range(len(names)))
    ax2.set_yticklabels(names, fontsize=9)
    ax2.set_xlabel('Memory (GB)', fontsize=12, color='#ffffff')
    ax2.set_title('Top/Bottom Relays by Memory', fontsize=12, color='#aaaaaa')
    ax2.invert_yaxis()
    
    # Add value labels
    for bar, val in zip(bars, values):
        if val > 0:
            ax2.text(val + 0.05, bar.get_y() + bar.get_height()/2, 
                    f'{val:.2f}', va='center', fontsize=8, color='#ffffff')
    
    for ax in [ax1, ax2]:
        style_axis(ax, show_grid=True)
    
    fig.suptitle(f'{title} - Relay Memory Distribution ({len(latest_rss)} relays)', 
                 fontsize=14, fontweight='bold', color=THEME['primary'])
    
    style_figure(fig)
    plt.tight_layout()
    save_chart(fig, output_path)
    print(f"✓ Distribution chart saved: {output_path}")


def chart_outliers(data: dict, output_path: Path, title: str, threshold_gb: float = None):
    """Identify and chart memory outliers over time."""
    relays = data.get('relays', {})
    if not relays:
        print("Warning: No per-relay data available for outlier detection")
        return
    
    # Calculate threshold if not provided (mean + 2*std)
    all_latest = [info['rss_gb'][-1] for info in relays.values() if info['rss_gb']]
    if not all_latest:
        return
    
    mean_rss = sum(all_latest) / len(all_latest)
    std_rss = (sum((x - mean_rss)**2 for x in all_latest) / len(all_latest)) ** 0.5
    
    if threshold_gb is None:
        threshold_gb = mean_rss + 2 * std_rss
    
    # Find outliers
    outliers = []
    for fp, info in relays.items():
        if info['rss_gb'] and info['rss_gb'][-1] > threshold_gb:
            outliers.append((fp, info))
    
    if not outliers:
        print(f"No outliers found above threshold ({threshold_gb:.2f} GB)")
        return
    
    setup_dark_theme()
    fig, ax = plt.subplots(figsize=(14, 6), dpi=150)
    
    # Plot all relays in gray
    for fp, info in relays.items():
        if info['rss_gb']:
            ax.plot(info['dates'], info['rss_gb'], color='#444444', linewidth=0.5, alpha=0.3)
    
    # Highlight outliers
    colors = plt.cm.Reds([0.4 + 0.6 * i / len(outliers) for i in range(len(outliers))])
    for i, (fp, info) in enumerate(outliers):
        nickname = info['nickname'] or fp[:8]
        ax.plot(info['dates'], info['rss_gb'], color=colors[i], linewidth=2, marker='o', markersize=3,
                label=f'{nickname} ({info["rss_gb"][-1]:.2f} GB)')
    
    # Threshold line
    ax.axhline(y=threshold_gb, color=THEME['warning'], linestyle='--', linewidth=2,
               label=f'Threshold: {threshold_gb:.2f} GB')
    ax.axhline(y=mean_rss, color=THEME['success'], linestyle=':', linewidth=1,
               label=f'Mean: {mean_rss:.2f} GB')
    
    ax.set_xlabel('Date', fontsize=12, color='#ffffff')
    ax.set_ylabel('Memory (GB)', fontsize=12, color='#ffffff')
    ax.set_title(f'{title} - Memory Outliers ({len(outliers)} relays above threshold)', 
                 fontsize=14, fontweight='bold', color=THEME['secondary'])
    
    ax.legend(loc='center left', bbox_to_anchor=(1.01, 0.5), fontsize=9, 
              facecolor='#1a1a2e', edgecolor='#444444')
    
    style_axis(ax)
    format_date_axis(ax)
    style_figure(fig)
    plt.tight_layout()
    save_chart(fig, output_path)
    print(f"✓ Outliers chart saved: {output_path}")


def print_summary(data: dict, title: str, format_type: str):
    """Print summary statistics."""
    if not data['dates']:
        print("No data available")
        return
    
    print(f"\n=== {title} Memory Summary ===")
    print(f"Format: {format_type}")
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
    
    # Per-relay stats (unified format only)
    if format_type == 'unified' and data.get('relays'):
        print(f"\nPer-relay data available: {len(data['relays'])} unique relays tracked")


def main():
    parser = argparse.ArgumentParser(
        description='Generate time-series memory charts from collect.sh or monitor.sh data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python3 timeseries-charts.py --data memory.csv
    python3 timeseries-charts.py --data stats.csv --title "Production" --color "#ff6b6b"
    python3 timeseries-charts.py --data stats.csv --output-dir ./charts/

Supported formats:
  - Unified (collect.sh): timestamp,server,type,fingerprint,nickname,...
  - Legacy (monitor.sh): date,time,num_relays,total_mb,...

The format is auto-detected from the CSV header.
        """
    )
    parser.add_argument('--data', required=True,
                        help='Path to CSV data file from collect.sh or monitor.sh')
    parser.add_argument('--output-dir', default='./',
                        help='Directory for output charts (default: ./)')
    parser.add_argument('--title', default='Server',
                        help='Title/name for charts (default: Server)')
    parser.add_argument('--color', default=THEME['primary'],
                        help=f"Primary color for charts (default: {THEME['primary']})")
    parser.add_argument('--prefix', default='memory',
                        help='Output filename prefix (default: memory)')
    
    args = parser.parse_args()
    
    data_path = Path(args.data)
    if not data_path.exists():
        print(f"Error: Data file not found: {data_path}")
        sys.exit(1)
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Loading data from: {data_path}")
    data, format_type = load_data(str(data_path))
    print(f"Loaded {len(data['dates'])} data points")
    
    if not data['dates']:
        print("Error: No valid data found in CSV")
        sys.exit(1)
    
    print("\nGenerating charts...")
    
    # Standard charts (both formats)
    chart_usage_over_time(data, output_dir / f'{args.prefix}_usage.png', args.title, args.color)
    chart_weekly_trend(data, output_dir / f'{args.prefix}_weekly.png', args.title, args.color)
    
    # Per-relay charts (unified format only)
    if format_type == 'unified' and data.get('relays'):
        chart_relay_trajectories(data, output_dir / f'{args.prefix}_trajectories.png', args.title)
        chart_relay_distribution(data, output_dir / f'{args.prefix}_distribution.png', args.title)
        chart_outliers(data, output_dir / f'{args.prefix}_outliers.png', args.title)
    
    print_summary(data, args.title, format_type)
    
    print(f"\n✓ All charts generated in: {output_dir.absolute()}")


if __name__ == '__main__':
    main()
