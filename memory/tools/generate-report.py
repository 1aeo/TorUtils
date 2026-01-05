#!/usr/bin/env python3
"""
Tor Relay Memory Experiment Report Generator

Generates charts and auto-populates REPORT.md template from experiment data.

Usage:
    python3 generate-report.py --experiment reports/2025-12-25-server-test/

Requirements:
    pip install matplotlib
"""

import argparse
import csv
import json
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


def load_experiment_metadata(exp_dir: Path) -> dict:
    """Load experiment.json metadata."""
    json_path = exp_dir / 'experiment.json'
    if json_path.exists():
        with open(json_path, 'r') as f:
            return json.load(f)
    return {}


def load_relay_config(exp_dir: Path) -> dict:
    """Load relay_config.csv into fingerprint->group mapping."""
    config_path = exp_dir / 'relay_config.csv'
    config = {}
    
    if config_path.exists():
        with open(config_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('fingerprint') and not row['fingerprint'].startswith('#'):
                    config[row['fingerprint']] = {
                        'nickname': row.get('nickname', ''),
                        'group': row.get('group', ''),
                        'dircache': row.get('dircache', ''),
                        'maxmem': row.get('maxmem', ''),
                        'notes': row.get('notes', ''),
                    }
    return config


def load_measurements(exp_dir: Path) -> dict:
    """Load memory_measurements.csv into structured data."""
    data = {
        'dates': [],
        'aggregates': [],
        'relays': defaultdict(lambda: {'dates': [], 'rss_kb': [], 'group': '', 'nickname': ''}),
        'groups': defaultdict(lambda: {'dates': [], 'total_rss': [], 'count': 0, 'relays': set()}),
    }
    
    measurements_path = exp_dir / 'memory_measurements.csv'
    if not measurements_path.exists():
        return data
    
    with open(measurements_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dt = datetime.fromisoformat(row['timestamp'])
                row_type = row.get('type', '')
                
                if row_type == 'aggregate':
                    data['dates'].append(dt)
                    data['aggregates'].append({
                        'timestamp': dt,
                        'count': int(row.get('count', 0)),
                        'total_kb': int(row.get('total_kb', 0)),
                        'avg_kb': int(row.get('avg_kb', 0)),
                        'min_kb': int(row.get('min_kb', 0)),
                        'max_kb': int(row.get('max_kb', 0)),
                    })
                    
                elif row_type == 'relay':
                    fp = row.get('fingerprint', '')
                    group = row.get('group', '')
                    rss_kb = int(row.get('rss_kb', 0))
                    
                    if fp:
                        data['relays'][fp]['dates'].append(dt)
                        data['relays'][fp]['rss_kb'].append(rss_kb)
                        data['relays'][fp]['group'] = group
                        data['relays'][fp]['nickname'] = row.get('nickname', fp[:8])
                    
                    if group:
                        data['groups'][group]['relays'].add(fp)
                        
            except (KeyError, ValueError) as e:
                continue
    
    # Calculate group statistics
    for group_name, group_data in data['groups'].items():
        group_data['count'] = len(group_data['relays'])
    
    return data


def calculate_group_metrics(data: dict) -> dict:
    """Calculate per-group metrics over time."""
    groups = data['groups']
    relays = data['relays']
    
    group_metrics = {}
    
    for group_name, group_info in groups.items():
        # Use pre-collected relay set instead of re-scanning all relays
        group_relays = [fp for fp in group_info['relays'] if fp in relays]
        
        if not group_relays:
            continue
        
        # Get first relay's dates as reference
        if group_relays and relays[group_relays[0]]['dates']:
            dates = relays[group_relays[0]]['dates']
        else:
            continue
        
        # Calculate average RSS per date
        avg_rss = []
        for i, date in enumerate(dates):
            rss_values = []
            for fp in group_relays:
                if i < len(relays[fp]['rss_kb']):
                    rss_values.append(relays[fp]['rss_kb'][i])
            if rss_values:
                avg_rss.append(sum(rss_values) / len(rss_values) / 1048576)  # Convert to GB
            else:
                avg_rss.append(0)
        
        group_metrics[group_name] = {
            'dates': dates,
            'avg_rss_gb': avg_rss,
            'relay_count': len(group_relays),
            'start_rss_gb': avg_rss[0] if avg_rss else 0,
            'end_rss_gb': avg_rss[-1] if avg_rss else 0,
        }
    
    return group_metrics


def chart_group_comparison(group_metrics: dict, metadata: dict, output_path: Path):
    """Generate group comparison chart."""
    if not group_metrics:
        print("Warning: No group data for comparison chart")
        return
    
    setup_dark_theme()
    fig, ax = plt.subplots(figsize=(12, 7), dpi=150)
    
    colors = plt.cm.Set2(range(len(group_metrics)))
    
    for i, (group_name, metrics) in enumerate(sorted(group_metrics.items())):
        dates = metrics['dates']
        rss = metrics['avg_rss_gb']
        
        # Get group label from metadata
        group_info = metadata.get('groups', {}).get(group_name, {})
        label = group_info.get('name', f'Group {group_name}')
        
        ax.plot(dates, rss, color=colors[i], linewidth=2.5, marker='o', markersize=4,
                label=f'{label} ({metrics["relay_count"]} relays)')
    
    ax.set_xlabel('Date', fontsize=12, color='#ffffff')
    ax.set_ylabel('Average Memory per Relay (GB)', fontsize=12, color='#ffffff')
    ax.set_title(f'{metadata.get("name", "Experiment")} - Group Comparison', 
                 fontsize=14, fontweight='bold', color=THEME['primary'])
    
    ax.legend(loc='center left', bbox_to_anchor=(1.01, 0.5), fontsize=10,
              facecolor='#1a1a2e', edgecolor='#444444')
    
    style_axis(ax)
    format_date_axis(ax)
    style_figure(fig)
    plt.tight_layout()
    save_chart(fig, output_path)
    print(f"✓ Group comparison chart saved: {output_path}")


def chart_memory_over_time(data: dict, metadata: dict, output_path: Path):
    """Generate memory over time chart."""
    if not data['aggregates']:
        print("Warning: No aggregate data for memory chart")
        return
    
    setup_dark_theme()
    fig, ax = plt.subplots(figsize=(12, 6), dpi=150)
    
    dates = [a['timestamp'] for a in data['aggregates']]
    total_gb = [a['total_kb'] / 1048576 for a in data['aggregates']]
    
    ax.fill_between(dates, total_gb, alpha=0.3, color=THEME['primary'])
    ax.plot(dates, total_gb, color=THEME['primary'], linewidth=2, marker='o', markersize=4)
    
    ax.set_xlabel('Date', fontsize=12, color='#ffffff')
    ax.set_ylabel('Total Memory (GB)', fontsize=12, color='#ffffff')
    ax.set_title(f'{metadata.get("name", "Experiment")} - Total Memory Over Time', 
                 fontsize=14, fontweight='bold', color=THEME['primary'])
    
    style_axis(ax)
    format_date_axis(ax)
    style_figure(fig)
    plt.tight_layout()
    save_chart(fig, output_path)
    print(f"✓ Memory over time chart saved: {output_path}")


def chart_final_comparison(group_metrics: dict, metadata: dict, output_path: Path):
    """Generate final comparison bar chart."""
    if not group_metrics:
        return
    
    setup_dark_theme()
    fig, ax = plt.subplots(figsize=(10, 6), dpi=150)
    
    groups = sorted(group_metrics.keys())
    end_rss = [group_metrics[g]['end_rss_gb'] for g in groups]
    
    # Color by performance (green = low, red = high)
    colors = [THEME['success'] if rss < sum(end_rss)/len(end_rss) else THEME['secondary'] for rss in end_rss]
    
    bars = ax.barh(range(len(groups)), end_rss, color=colors, height=0.6, edgecolor='white')
    
    # Labels
    group_labels = []
    for g in groups:
        group_info = metadata.get('groups', {}).get(g, {})
        group_labels.append(group_info.get('name', f'Group {g}'))
    
    ax.set_yticks(range(len(groups)))
    ax.set_yticklabels(group_labels, fontsize=11)
    ax.set_xlabel('Final Average Memory per Relay (GB)', fontsize=12, color='#ffffff')
    ax.set_title('Final Memory by Group (Lower is Better)', fontsize=14, fontweight='bold', color=THEME['primary'])
    
    # Value labels
    for bar, val in zip(bars, end_rss):
        ax.text(val + 0.05, bar.get_y() + bar.get_height()/2,
                f'{val:.2f} GB', va='center', fontsize=10, color='#ffffff')
    
    ax.invert_yaxis()
    style_axis(ax, show_grid=True)
    style_figure(fig)
    plt.tight_layout()
    save_chart(fig, output_path)
    print(f"✓ Final comparison chart saved: {output_path}")


def generate_report(exp_dir: Path, metadata: dict, data: dict, group_metrics: dict):
    """Generate REPORT.md from template with auto-populated data."""
    template_path = Path(__file__).parent.parent / 'templates' / 'REPORT.md'
    report_path = exp_dir / 'REPORT.md'
    
    # Load template
    if template_path.exists():
        with open(template_path, 'r') as f:
            template = f.read()
    else:
        print("Warning: REPORT.md template not found, skipping report generation")
        return
    
    # Calculate metrics for template
    start_date = data['dates'][0].strftime('%Y-%m-%d') if data['dates'] else '[start]'
    end_date = data['dates'][-1].strftime('%Y-%m-%d') if data['dates'] else '[end]'
    
    # Build groups table
    groups_table = ""
    for group_name in sorted(metadata.get('groups', {}).keys()):
        group_info = metadata['groups'][group_name]
        metrics = group_metrics.get(group_name, {})
        
        config_str = json.dumps(group_info.get('config', {})) if group_info.get('config') else group_info.get('name', '')
        relay_count = metrics.get('relay_count', 0)
        
        groups_table += f"| {group_name} | {config_str} | {relay_count} | {group_info.get('name', '')} |\n"
    
    # Build metrics table
    metrics_table = ""
    for group_name in sorted(group_metrics.keys()):
        metrics = group_metrics[group_name]
        start_rss = metrics.get('start_rss_gb', 0)
        end_rss = metrics.get('end_rss_gb', 0)
        
        if start_rss > 0:
            change_pct = ((end_rss - start_rss) / start_rss) * 100
            change_str = f"{'+' if change_pct >= 0 else ''}{change_pct:.0f}%"
        else:
            change_str = "N/A"
        
        status = "STABLE" if end_rss < 1.0 else "FRAGMENTED" if end_rss > 3.0 else "MODERATE"
        
        metrics_table += f"| {group_name} | {start_rss:.2f} GB | {end_rss:.2f} GB | {change_str} | {status} |\n"
    
    # Apply replacements
    replacements = {
        '[Experiment Title]': metadata.get('name', 'Memory Experiment'),
        '[hostname]': metadata.get('server', '[hostname]'),
        '[start]': start_date,
        '[end]': end_date,
        '[version]': metadata.get('tor_version', '[version]'),
        '[glibc/jemalloc/tcmalloc]': metadata.get('allocator', 'glibc'),
        '[N]': str(data['aggregates'][-1]['count']) if data['aggregates'] else '[N]',
        '[path]': str(exp_dir),
        '[date]': datetime.now().strftime('%Y-%m-%d'),
    }
    
    report = template
    for placeholder, value in replacements.items():
        report = report.replace(placeholder, value)
    
    # Write report
    with open(report_path, 'w') as f:
        f.write(report)
    
    print(f"✓ Report generated: {report_path}")
    print("  Note: Some sections require manual completion (Analysis, Root Cause, etc.)")


def main():
    parser = argparse.ArgumentParser(
        description='Generate experiment report with charts from collected data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python3 generate-report.py --experiment reports/2025-12-25-server-test/
    python3 generate-report.py -e reports/2025-12-25-server-test/ --charts-only

The tool will:
  1. Load experiment.json, relay_config.csv, and memory_measurements.csv
  2. Generate charts in the charts/ subdirectory
  3. Create/update REPORT.md with auto-populated data
        """
    )
    parser.add_argument('--experiment', '-e', required=True,
                        help='Path to experiment directory')
    parser.add_argument('--charts-only', action='store_true',
                        help='Generate charts only, skip REPORT.md')
    
    args = parser.parse_args()
    
    exp_dir = Path(args.experiment)
    if not exp_dir.exists():
        print(f"Error: Experiment directory not found: {exp_dir}")
        sys.exit(1)
    
    charts_dir = exp_dir / 'charts'
    charts_dir.mkdir(exist_ok=True)
    
    print(f"=== Generating Report for: {exp_dir.name} ===\n")
    
    # Load data
    print("Loading data...")
    metadata = load_experiment_metadata(exp_dir)
    relay_config = load_relay_config(exp_dir)
    data = load_measurements(exp_dir)
    
    print(f"  Metadata: {metadata.get('name', 'unnamed')}")
    print(f"  Relay config: {len(relay_config)} relays")
    print(f"  Measurements: {len(data['aggregates'])} data points")
    print(f"  Groups: {list(data['groups'].keys())}")
    
    # Calculate group metrics
    group_metrics = calculate_group_metrics(data)
    
    # Generate charts
    print("\nGenerating charts...")
    chart_memory_over_time(data, metadata, charts_dir / 'memory_over_time.png')
    chart_group_comparison(group_metrics, metadata, charts_dir / 'group_comparison.png')
    chart_final_comparison(group_metrics, metadata, charts_dir / 'final_comparison.png')
    
    # Generate report
    if not args.charts_only:
        print("\nGenerating report...")
        generate_report(exp_dir, metadata, data, group_metrics)
    
    print(f"\n✓ Done! Results in: {exp_dir}")


if __name__ == '__main__':
    main()

