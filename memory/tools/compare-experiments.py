#!/usr/bin/env python3
"""
Compare Multiple Tor Relay Memory Experiments

Generates comparison charts and reports across multiple experiments.

Usage:
    python3 compare-experiments.py --experiments exp1 exp2 exp3 --output comparison/
    python3 compare-experiments.py -e reports/exp1 reports/exp2 -o comparison.md

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
    save_chart, THEME
)

check_matplotlib()

import matplotlib.pyplot as plt


def load_experiment(exp_dir: Path) -> dict:
    """Load experiment data from directory."""
    data = {
        'name': exp_dir.name,
        'dir': exp_dir,
        'metadata': {},
        'groups': {},
        'final_metrics': {},
    }
    
    # Load metadata
    json_path = exp_dir / 'experiment.json'
    if json_path.exists():
        with open(json_path, 'r') as f:
            data['metadata'] = json.load(f)
            data['name'] = data['metadata'].get('name', exp_dir.name)
    
    # Load measurements
    measurements_path = exp_dir / 'measurements.csv'
    if measurements_path.exists():
        relays = defaultdict(lambda: {'dates': [], 'rss_kb': [], 'group': '', 'nickname': ''})
        
        with open(measurements_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('type') == 'relay':
                    fp = row.get('fingerprint', '') or row.get('nickname', '')
                    if fp:
                        try:
                            dt = datetime.fromisoformat(row['timestamp'])
                            rss_kb = int(row.get('rss_kb', 0))
                            relays[fp]['dates'].append(dt)
                            relays[fp]['rss_kb'].append(rss_kb)
                            relays[fp]['group'] = row.get('group', '')
                            relays[fp]['nickname'] = row.get('nickname', fp[:8])
                        except (ValueError, KeyError):
                            continue
        
        # Calculate per-group final metrics
        groups = defaultdict(lambda: {'relays': [], 'final_rss_gb': []})
        for fp, relay_data in relays.items():
            group = relay_data['group']
            if group and relay_data['rss_kb']:
                final_rss_gb = relay_data['rss_kb'][-1] / 1048576
                groups[group]['relays'].append(fp)
                groups[group]['final_rss_gb'].append(final_rss_gb)
        
        for group_name, group_data in groups.items():
            if group_data['final_rss_gb']:
                data['groups'][group_name] = {
                    'relay_count': len(group_data['relays']),
                    'avg_final_gb': sum(group_data['final_rss_gb']) / len(group_data['final_rss_gb']),
                    'min_final_gb': min(group_data['final_rss_gb']),
                    'max_final_gb': max(group_data['final_rss_gb']),
                }
    
    return data


def chart_experiments_comparison(experiments: list[dict], output_path: Path):
    """Generate bar chart comparing final results across experiments."""
    setup_dark_theme()
    
    # Collect all unique groups across experiments
    all_groups = set()
    for exp in experiments:
        all_groups.update(exp['groups'].keys())
    all_groups = sorted(all_groups)
    
    if not all_groups:
        print("Warning: No group data found for comparison")
        return
    
    fig, ax = plt.subplots(figsize=(14, 8), dpi=150)
    
    n_experiments = len(experiments)
    n_groups = len(all_groups)
    bar_width = 0.8 / n_experiments
    
    colors = plt.cm.Set2(range(n_experiments))
    
    for i, exp in enumerate(experiments):
        x_positions = [j + i * bar_width for j in range(n_groups)]
        values = []
        
        for group in all_groups:
            if group in exp['groups']:
                values.append(exp['groups'][group]['avg_final_gb'])
            else:
                values.append(0)
        
        bars = ax.bar(x_positions, values, bar_width, label=exp['name'], 
                      color=colors[i], edgecolor='white')
        
        # Add value labels
        for bar, val in zip(bars, values):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05,
                       f'{val:.2f}', ha='center', va='bottom', fontsize=8, color='#ffffff')
    
    ax.set_xlabel('Experiment Group', fontsize=12, color='#ffffff')
    ax.set_ylabel('Average Final Memory per Relay (GB)', fontsize=12, color='#ffffff')
    ax.set_title('Cross-Experiment Comparison by Group', fontsize=14, fontweight='bold', color=THEME['primary'])
    
    ax.set_xticks([j + bar_width * (n_experiments - 1) / 2 for j in range(n_groups)])
    ax.set_xticklabels(all_groups, fontsize=11)
    
    ax.legend(loc='center left', bbox_to_anchor=(1.01, 0.5), fontsize=10,
              facecolor='#1a1a2e', edgecolor='#444444')
    
    style_axis(ax, show_grid=True)
    style_figure(fig)
    plt.tight_layout()
    save_chart(fig, output_path)
    print(f"✓ Comparison chart saved: {output_path}")


def chart_best_configs(experiments: list[dict], output_path: Path):
    """Generate chart showing best configuration from each experiment."""
    setup_dark_theme()
    fig, ax = plt.subplots(figsize=(12, 6), dpi=150)
    
    best_configs = []
    
    for exp in experiments:
        if not exp['groups']:
            continue
        
        # Find best (lowest) group
        best_group = min(exp['groups'].items(), key=lambda x: x[1]['avg_final_gb'])
        group_name, metrics = best_group
        
        # Get group label from metadata
        group_info = exp['metadata'].get('groups', {}).get(group_name, {})
        config_name = group_info.get('name', f'Group {group_name}')
        
        best_configs.append({
            'experiment': exp['name'],
            'config': config_name,
            'group': group_name,
            'avg_gb': metrics['avg_final_gb'],
        })
    
    if not best_configs:
        print("Warning: No data for best configs chart")
        plt.close()
        return
    
    # Sort by avg_gb
    best_configs.sort(key=lambda x: x['avg_gb'])
    
    y_pos = range(len(best_configs))
    colors = [THEME['success'] if c['avg_gb'] < 1.0 else THEME['warning'] if c['avg_gb'] < 3.0 else THEME['secondary'] 
              for c in best_configs]
    
    bars = ax.barh(y_pos, [c['avg_gb'] for c in best_configs], color=colors, height=0.6, edgecolor='white')
    
    ax.set_yticks(y_pos)
    ax.set_yticklabels([f"{c['experiment']}\n({c['config']})" for c in best_configs], fontsize=9)
    ax.set_xlabel('Average Memory per Relay (GB)', fontsize=12, color='#ffffff')
    ax.set_title('Best Configuration from Each Experiment', fontsize=14, fontweight='bold', color=THEME['primary'])
    
    # Value labels
    for bar, c in zip(bars, best_configs):
        ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height()/2,
               f'{c["avg_gb"]:.2f} GB', va='center', fontsize=10, color='#ffffff')
    
    ax.invert_yaxis()
    style_axis(ax, show_grid=True)
    style_figure(fig)
    plt.tight_layout()
    save_chart(fig, output_path)
    print(f"✓ Best configs chart saved: {output_path}")


def generate_comparison_report(experiments: list[dict], output_path: Path):
    """Generate markdown comparison report."""
    
    lines = [
        "# Experiment Comparison Report",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Experiments Compared",
        "",
        "| Experiment | Server | Start Date | Groups |",
        "|------------|--------|------------|--------|",
    ]
    
    for exp in experiments:
        meta = exp['metadata']
        lines.append(f"| {exp['name']} | {meta.get('server', 'unknown')} | "
                    f"{meta.get('start_date', 'unknown')} | {', '.join(exp['groups'].keys())} |")
    
    lines.extend([
        "",
        "## Results by Group",
        "",
        "| Experiment | Group | Avg Memory (GB) | Min | Max | Relays |",
        "|------------|-------|-----------------|-----|-----|--------|",
    ])
    
    for exp in experiments:
        for group_name, metrics in sorted(exp['groups'].items()):
            lines.append(
                f"| {exp['name']} | {group_name} | {metrics['avg_final_gb']:.2f} | "
                f"{metrics['min_final_gb']:.2f} | {metrics['max_final_gb']:.2f} | "
                f"{metrics['relay_count']} |"
            )
    
    lines.extend([
        "",
        "## Best Configurations",
        "",
        "| Rank | Experiment | Configuration | Memory (GB) |",
        "|------|------------|---------------|-------------|",
    ])
    
    # Collect all group results
    all_results = []
    for exp in experiments:
        for group_name, metrics in exp['groups'].items():
            group_info = exp['metadata'].get('groups', {}).get(group_name, {})
            all_results.append({
                'experiment': exp['name'],
                'group': group_name,
                'config': group_info.get('name', f'Group {group_name}'),
                'avg_gb': metrics['avg_final_gb'],
            })
    
    all_results.sort(key=lambda x: x['avg_gb'])
    
    for i, result in enumerate(all_results[:10], 1):
        lines.append(f"| {i} | {result['experiment']} | {result['config']} | {result['avg_gb']:.2f} |")
    
    lines.extend([
        "",
        "## Charts",
        "",
        "![Comparison](comparison.png)",
        "",
        "![Best Configs](best_configs.png)",
        "",
        "---",
        "",
        "*Report generated by compare-experiments.py*",
    ])
    
    with open(output_path, 'w') as f:
        f.write('\n'.join(lines))
    
    print(f"✓ Comparison report saved: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Compare results across multiple experiments',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python3 compare-experiments.py --experiments reports/exp1 reports/exp2
    python3 compare-experiments.py -e exp1 exp2 exp3 --output comparison/
    python3 compare-experiments.py -e exp1 exp2 -o results.md

Output:
  - comparison.png: Bar chart comparing all groups across experiments
  - best_configs.png: Chart showing best configuration from each experiment
  - COMPARISON.md: Detailed comparison report
        """
    )
    parser.add_argument('--experiments', '-e', nargs='+', required=True,
                        help='Paths to experiment directories')
    parser.add_argument('--output', '-o', default='comparison/',
                        help='Output directory or markdown file (default: comparison/)')
    
    args = parser.parse_args()
    
    # Determine output paths
    output = Path(args.output)
    if output.suffix == '.md':
        output_dir = output.parent
        report_path = output
    else:
        output_dir = output
        report_path = output / 'COMPARISON.md'
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"=== Comparing {len(args.experiments)} Experiments ===\n")
    
    # Load experiments
    experiments = []
    for exp_path in args.experiments:
        exp_dir = Path(exp_path)
        if not exp_dir.exists():
            print(f"Warning: Experiment not found: {exp_dir}")
            continue
        
        print(f"Loading: {exp_dir.name}")
        exp_data = load_experiment(exp_dir)
        experiments.append(exp_data)
        print(f"  Groups: {list(exp_data['groups'].keys())}")
    
    if len(experiments) < 2:
        print("\nError: Need at least 2 experiments to compare")
        sys.exit(1)
    
    # Generate charts
    print("\nGenerating charts...")
    chart_experiments_comparison(experiments, output_dir / 'comparison.png')
    chart_best_configs(experiments, output_dir / 'best_configs.png')
    
    # Generate report
    print("\nGenerating report...")
    generate_comparison_report(experiments, report_path)
    
    print(f"\n✓ Done! Results in: {output_dir}")


if __name__ == '__main__':
    main()

