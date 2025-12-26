#!/usr/bin/env python3
"""
Tor Relay Memory Investigation - Chart Generator

Generates visualizations from experiment data (A/B test comparisons):
  1. Memory usage over time by configuration group
  2. Final memory comparison (Day 9) by configuration  
  3. Control vs Optimized relay comparison

Usage:
    python3 generate-charts.py --data data.csv --output-dir ./charts/

Requirements:
    pip install matplotlib
"""

import argparse
import csv
from pathlib import Path
import sys

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

from chart_utils import check_matplotlib, save_chart

check_matplotlib()

import matplotlib.pyplot as plt

# Experiment group configuration
COLORS = {
    'A': '#2ecc71',  # Green - DirCache 0 + MaxMem 2GB
    'B': '#e74c3c',  # Red - Control (no optimization)
    'C': '#f39c12',  # Orange - MaxMem 2GB only
    'D': '#f1c40f',  # Yellow - MaxMem 4GB only
    'E': '#3498db',  # Blue - DirCache 0 only
}

GROUP_LABELS = {
    'A': 'DirCache 0 + MaxMem 2GB',
    'B': 'Control (default)',
    'C': 'MaxMemInQueues 2GB',
    'D': 'MaxMemInQueues 4GB',
    'E': 'DirCache 0 only',
}

GROUP_ORDER = ['A', 'E', 'C', 'D', 'B']  # Sorted by effectiveness
DAY_COLS = ['day0', 'day1', 'day2', 'day3', 'day4', 'day5', 'day9']
DAYS = [0, 1, 2, 3, 4, 5, 9]


def load_data(csv_path: str) -> list[dict]:
    """Load and parse the CSV data, skipping comment and empty lines."""
    rows = []
    with open(csv_path, 'r') as f:
        # Skip comment and empty lines
        lines = [line for line in f if line.strip() and not line.strip().startswith('#')]
    
    reader = csv.DictReader(lines)
    for row in reader:
        # Convert day columns to float
        for col in DAY_COLS:
            if col in row and row[col]:
                try:
                    row[col] = float(row[col])
                except ValueError:
                    row[col] = None
            else:
                row[col] = None
        rows.append(row)
    
    return rows


def get_group_data(rows: list[dict], group: str) -> list[dict]:
    """Filter rows by group."""
    return [r for r in rows if r.get('group') == group]


def chart1_memory_over_time(rows: list[dict], output_path: Path):
    """Chart 1: Line chart showing memory usage over time by configuration group."""
    try:
        plt.style.use('seaborn-v0_8-whitegrid')
    except OSError:
        plt.style.use('ggplot')  # Fallback for older matplotlib
    fig, ax = plt.subplots(figsize=(12, 7))
    
    for group in GROUP_ORDER:
        group_rows = get_group_data(rows, group)
        if not group_rows:
            continue
        
        # Calculate group average for each day
        avg_values = []
        for col in DAY_COLS:
            vals = [r[col] for r in group_rows if r[col] is not None]
            avg_values.append(sum(vals) / len(vals) if vals else None)
        
        # Filter out None values for plotting
        plot_days = [d for d, v in zip(DAYS, avg_values) if v is not None]
        plot_vals = [v for v in avg_values if v is not None]
        
        if plot_days:
            ax.plot(plot_days, plot_vals, 
                    marker='o', linewidth=2.5, markersize=8,
                    color=COLORS[group], label=GROUP_LABELS[group])
    
    # Styling
    ax.set_xlabel('Days Since Configuration Change', fontsize=12, fontweight='bold')
    ax.set_ylabel('RSS Memory (GB)', fontsize=12, fontweight='bold')
    ax.set_title('Tor Guard Relay Memory Usage Over Time\nby Configuration', 
                 fontsize=14, fontweight='bold', pad=20)
    
    ax.set_xlim(-0.5, 9.5)
    ax.set_ylim(0, 6)
    ax.set_xticks(DAYS)
    ax.set_xticklabels(['Day 0\n(Baseline)', 'Day 1', 'Day 2', 'Day 3', 'Day 4', 'Day 5', 'Day 9'])
    
    ax.yaxis.grid(True, linestyle='--', alpha=0.7)
    ax.xaxis.grid(False)
    
    # Add annotations
    ax.axhline(y=1.0, color='gray', linestyle=':', alpha=0.5)
    ax.text(9.3, 1.0, 'Expected max\n(per Tor docs)', fontsize=9, color='gray', va='center')
    ax.axhspan(4, 6, alpha=0.1, color='red')
    ax.text(0.2, 5.5, '⚠ Fragmentation Zone', fontsize=10, color='red', alpha=0.7)
    
    ax.legend(loc='center left', bbox_to_anchor=(1.02, 0.5), fontsize=10)
    
    plt.tight_layout()
    save_chart(fig, output_path)
    print(f"✓ Chart 1 saved: {output_path}")


def chart2_final_comparison(rows: list[dict], output_path: Path):
    """Chart 2: Horizontal bar chart showing final memory (Day 9) by configuration."""
    fig, ax = plt.subplots(figsize=(12, 7))
    
    # Calculate group averages for day 9
    results = []
    for group in GROUP_ORDER:
        group_rows = get_group_data(rows, group)
        vals = [r['day9'] for r in group_rows if r['day9'] is not None]
        if vals:
            avg_day9 = sum(vals) / len(vals)
            results.append({
                'group': group,
                'label': GROUP_LABELS[group],
                'memory': avg_day9,
                'color': COLORS[group]
            })
    
    results.sort(key=lambda x: x['memory'])
    
    y_pos = range(len(results))
    bars = ax.barh(y_pos, [r['memory'] for r in results], 
                   color=[r['color'] for r in results],
                   height=0.6, edgecolor='black', linewidth=1)
    
    # Add value labels on bars
    for bar, result in zip(bars, results):
        width = bar.get_width()
        if result['group'] in ['A', 'E']:
            reduction = ((5.35 - width) / 5.35) * 100
            label = f"{width:.2f} GB  ({reduction:.0f}% reduction)"
        else:
            label = f"{width:.2f} GB"
        ax.text(width + 0.15, bar.get_y() + bar.get_height()/2,
                label, va='center', fontsize=11, fontweight='bold', color='black')
    
    # Build y-axis labels with status indicators
    y_labels = []
    for result in results:
        status = "⚠ Loses Guard" if result['group'] in ['A', 'E'] else "✓ Keeps Guard"
        y_labels.append(f"{result['label']}\n({status})")
    
    ax.set_yticks(y_pos)
    ax.set_yticklabels(y_labels, fontsize=10)
    ax.set_xlabel('RSS Memory (GB)', fontsize=12, fontweight='bold')
    ax.set_title('Final Memory Usage (Day 9) by Configuration\nLower is Better', 
                 fontsize=14, fontweight='bold', pad=20)
    ax.set_xlim(0, 7)
    
    # Reference lines
    ax.axvline(x=1.0, color='darkgreen', linestyle='--', alpha=0.7, linewidth=2)
    ax.text(1.0, -0.6, 'Tor docs:\n500-1000 MB\nnormal', 
            fontsize=9, color='darkgreen', ha='center', va='top')
    ax.axvline(x=5.35, color='darkred', linestyle='--', alpha=0.7, linewidth=2)
    ax.text(5.35, -0.6, 'Original\nbaseline', fontsize=9, color='darkred', ha='center', va='top')
    
    ax.invert_yaxis()
    plt.subplots_adjust(left=0.25)
    plt.tight_layout()
    save_chart(fig, output_path)
    print(f"✓ Chart 2 saved: {output_path}")


def chart3_fragmentation_timeline(rows: list[dict], output_path: Path):
    """Chart 3: Comparison of control relay vs DirCache 0 relay."""
    fig, ax = plt.subplots(figsize=(12, 7))
    
    # Get first control relay (group B)
    control_rows = get_group_data(rows, 'B')
    if not control_rows:
        print("Warning: No control group (B) found, skipping chart 3")
        plt.close()
        return
    control = control_rows[0]
    control_name = control.get('relay', 'control')
    control_vals = [control.get(col) for col in DAY_COLS]
    
    # Get first optimized relay (group A)
    optimized_rows = get_group_data(rows, 'A')
    if not optimized_rows:
        print("Warning: No optimized group (A) found, skipping chart 3")
        plt.close()
        return
    optimized = optimized_rows[0]
    optimized_name = optimized.get('relay', 'optimized')
    optimized_vals = [optimized.get(col) for col in DAY_COLS]
    
    # Plot control relay
    ctrl_days = [d for d, v in zip(DAYS, control_vals) if v is not None]
    ctrl_vals = [v for v in control_vals if v is not None]
    if ctrl_days:
        ax.fill_between(ctrl_days, ctrl_vals, alpha=0.3, color=COLORS['B'])
        ax.plot(ctrl_days, ctrl_vals, marker='s', linewidth=3, markersize=10,
                color=COLORS['B'], label=f'Control ({control_name}) - No optimization')
    
    # Plot optimized relay
    opt_days = [d for d, v in zip(DAYS, optimized_vals) if v is not None]
    opt_vals = [v for v in optimized_vals if v is not None]
    if opt_days:
        ax.fill_between(opt_days, opt_vals, alpha=0.3, color=COLORS['A'])
        ax.plot(opt_days, opt_vals, marker='o', linewidth=3, markersize=10,
                color=COLORS['A'], label=f'Optimized ({optimized_name}) - DirCache 0 + MaxMem 2GB')
    
    # Annotations
    if len(ctrl_vals) >= 3 and control_vals[2] is not None:
        spike_val = control_vals[2]
        ax.annotate(f'Fragmentation spike!\n0.57 GB → {spike_val:.1f} GB\n(+{((spike_val/0.57)-1)*100:.0f}% in 24h)',
                    xy=(2, spike_val), xytext=(3.5, spike_val + 0.3),
                    fontsize=11, color=COLORS['B'], fontweight='bold',
                    arrowprops=dict(arrowstyle='->', color=COLORS['B'], lw=2))
    
    ax.annotate('Stable at 0.3 GB\n(94% reduction)',
                xy=(5, 0.33), xytext=(6, 1.5),
                fontsize=11, color=COLORS['A'], fontweight='bold',
                arrowprops=dict(arrowstyle='->', color=COLORS['A'], lw=2))
    
    ax.axvspan(1, 3, alpha=0.1, color='red')
    ax.text(2, 0.3, '48-hour\nfragmentation\nwindow', ha='center', fontsize=10, 
            color='red', alpha=0.7, style='italic')
    
    ax.set_xlabel('Days Since Restart', fontsize=12, fontweight='bold')
    ax.set_ylabel('RSS Memory (GB)', fontsize=12, fontweight='bold')
    ax.set_title('Memory Fragmentation: Control vs Optimized Relay\nSingle Relay Comparison', 
                 fontsize=14, fontweight='bold', pad=20)
    
    ax.set_xlim(-0.5, 9.5)
    ax.set_ylim(0, 6.5)
    ax.set_xticks(DAYS)
    ax.set_xticklabels(['Day 0', 'Day 1', 'Day 2', 'Day 3', 'Day 4', 'Day 5', 'Day 9'])
    ax.legend(loc='upper right', fontsize=11, framealpha=0.9)
    
    textstr = 'Key Finding:\nDirCache 0 prevents fragmentation\nbut removes guard relay status'
    props = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
    ax.text(0.02, 0.98, textstr, transform=ax.transAxes, fontsize=11,
            verticalalignment='top', bbox=props)
    
    plt.tight_layout()
    save_chart(fig, output_path)
    print(f"✓ Chart 3 saved: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Generate charts from Tor memory investigation data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python3 generate-charts.py --data data.csv
    python3 generate-charts.py --data custom_data.csv --output-dir ./charts/
        """
    )
    parser.add_argument('--data', default='data.csv',
                        help='Path to CSV data file (default: data.csv)')
    parser.add_argument('--output-dir', default='./',
                        help='Directory for output charts (default: ./)')
    
    args = parser.parse_args()
    
    data_path = Path(args.data)
    if not data_path.exists():
        print(f"Error: Data file not found: {data_path}")
        sys.exit(1)
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Loading data from: {data_path}")
    rows = load_data(str(data_path))
    groups = set(r.get('group') for r in rows if r.get('group'))
    print(f"Loaded {len(rows)} relay records across {len(groups)} groups")
    
    print("\nGenerating charts...")
    chart1_memory_over_time(rows, output_dir / 'chart1_memory_over_time.png')
    chart2_final_comparison(rows, output_dir / 'chart2_final_comparison.png')
    chart3_fragmentation_timeline(rows, output_dir / 'chart3_fragmentation_timeline.png')
    
    print(f"\n✓ All charts generated in: {output_dir.absolute()}")


if __name__ == '__main__':
    main()
