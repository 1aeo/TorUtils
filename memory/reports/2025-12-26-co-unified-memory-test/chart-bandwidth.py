#!/usr/bin/env python3
"""
Generate bandwidth comparison chart by experiment group.
"""

import csv
import matplotlib.pyplot as plt
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Use script directory for relative paths
EXP_DIR = Path(__file__).parent
BANDWIDTH_CSV = EXP_DIR / "bandwidth_measurements.csv"
OUTPUT_FILE = EXP_DIR / "charts" / "bandwidth_by_group.png"

# Group configuration with colors matching memory chart
GROUP_CONFIG = {
    'A': {'name': 'jemalloc 5.3.0', 'color': '#2ecc71'},
    'B': {'name': 'mimalloc 2.1.2', 'color': '#3498db'},
    'C': {'name': 'tcmalloc 2.15', 'color': '#9b59b6'},
    'D': {'name': 'consensus-4h', 'color': '#f39c12'},
    'E': {'name': 'consensus-8h', 'color': '#e67e22'},
    'F': {'name': 'restart-24h', 'color': '#1abc9c'},
    'G': {'name': 'restart-48h', 'color': '#16a085'},
    'H': {'name': 'restart-72h', 'color': '#27ae60'},
    'I': {'name': 'mimalloc 3.0.1', 'color': '#00bcd4'},
    'Z': {'name': 'glibc 2.39', 'color': '#e74c3c'},
}

def main():
    print(f"Reading {BANDWIDTH_CSV}...")
    
    # Load bandwidth data
    group_bandwidth = defaultdict(list)
    
    with open(BANDWIDTH_CSV, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            group = row.get('group', '')
            if group in GROUP_CONFIG:
                # Only use rows with observed_mbps (from bandwidth snapshot, not history)
                observed = row.get('observed_mbps', '')
                if observed:
                    try:
                        mbps = float(observed)
                        if mbps > 0:
                            group_bandwidth[group].append(mbps)
                    except ValueError:
                        continue
    
    if not group_bandwidth:
        print("Error: No bandwidth data found")
        return
    
    # Calculate averages
    group_avgs = {}
    for group, values in group_bandwidth.items():
        if values:
            group_avgs[group] = sum(values) / len(values)
    
    # Sort by bandwidth (descending)
    sorted_groups = sorted(group_avgs.keys(), key=lambda g: group_avgs[g], reverse=True)
    
    # Create figure
    fig, ax = plt.subplots(figsize=(12, 8))
    
    # Bar chart
    x_pos = range(len(sorted_groups))
    bars = ax.bar(x_pos, 
                  [group_avgs[g] for g in sorted_groups],
                  color=[GROUP_CONFIG[g]['color'] for g in sorted_groups],
                  edgecolor='black',
                  linewidth=1)
    
    # Labels
    ax.set_xticks(x_pos)
    ax.set_xticklabels([f"{g}: {GROUP_CONFIG[g]['name']}" for g in sorted_groups], 
                       rotation=45, ha='right', fontsize=10)
    
    ax.set_ylabel('Average Observed Bandwidth (Mbps)', fontsize=12)
    ax.set_title('Tor Relay Bandwidth by Experiment Group\n(Higher is Better - Verifying Allocators Don\'t Harm Performance)', 
                 fontsize=14)
    
    # Add value labels on bars
    for bar, group in zip(bars, sorted_groups):
        height = bar.get_height()
        count = len(group_bandwidth[group])
        ax.text(bar.get_x() + bar.get_width()/2, height + 5,
                f'{height:.0f} Mbps\n({count} relays)',
                ha='center', va='bottom', fontsize=9)
    
    # Grid
    ax.grid(True, axis='y', alpha=0.3)
    ax.set_axisbelow(True)
    
    # Control reference line
    if 'Z' in group_avgs:
        control_bw = group_avgs['Z']
        ax.axhline(y=control_bw, color='red', linestyle='--', alpha=0.5, linewidth=2)
        ax.text(len(sorted_groups) - 0.5, control_bw + 10, 
                f'Control: {control_bw:.0f} Mbps', 
                fontsize=9, color='red', ha='right')
    
    plt.tight_layout()
    
    print(f"Saving to {OUTPUT_FILE}...")
    plt.savefig(OUTPUT_FILE, dpi=150, bbox_inches='tight')
    print(f"Done!")
    
    # Print summary
    print("\n=== Bandwidth Summary ===")
    for group in sorted_groups:
        config = GROUP_CONFIG[group]
        print(f"  {group} ({config['name']}): {group_avgs[group]:.0f} Mbps")

if __name__ == '__main__':
    main()


