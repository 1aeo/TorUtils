#!/usr/bin/env python3
"""
Generate filtered charts for blog posts:
1. DirCache chart (Group E vs B only)
2. MaxMemInQueues chart (Groups C, D, B only)
"""

import matplotlib.pyplot as plt
import numpy as np

# Data from reports/2025-09-18-co-guard-fragmentation/data.csv
# Days: day0, day1, day2, day3, day4, day5, day9
days = [0, 1, 2, 3, 4, 5, 9]

# Group data (averaged across relays where multiple exist)
data = {
    # Group E: DirCache 0 only (3 relays, data starts day4)
    'E': {
        'name': 'DirCache 0',
        'color': '#00d4aa',
        'values': [None, None, None, None, 0.43, 0.38, 0.33]  # avg of 3 relays
    },
    # Group B: Control (1 relay)
    'B': {
        'name': 'Control (glibc default)',
        'color': '#ff6b6b',
        'values': [None, 0.57, 5.15, 5.40, 5.41, 5.62, 5.14]
    },
    # Group C: MaxMem 2GB only (3 relays)
    'C': {
        'name': 'MaxMemInQueues 2GB',
        'color': '#ffd93d',
        'values': [None, 0.55, 0.55, 3.61, 3.80, 3.99, 4.17]  # avg of 3 relays
    },
    # Group D: MaxMem 4GB only (3 relays)
    'D': {
        'name': 'MaxMemInQueues 4GB',
        'color': '#6bcb77',
        'values': [None, 0.54, 0.54, 3.79, 4.21, 4.35, 4.76]  # avg of 3 relays
    },
}

def setup_dark_theme():
    plt.style.use('dark_background')
    plt.rcParams['figure.facecolor'] = '#0d1117'
    plt.rcParams['axes.facecolor'] = '#0d1117'
    plt.rcParams['axes.edgecolor'] = '#444444'
    plt.rcParams['axes.labelcolor'] = '#ffffff'
    plt.rcParams['text.color'] = '#ffffff'
    plt.rcParams['xtick.color'] = '#888888'
    plt.rcParams['ytick.color'] = '#888888'
    plt.rcParams['grid.color'] = '#444444'
    plt.rcParams['grid.alpha'] = 0.3

def create_chart(groups, output_path, title):
    """Create a line chart for specified groups."""
    setup_dark_theme()
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    for group_id in groups:
        group = data[group_id]
        # Filter out None values for plotting
        valid_days = []
        valid_values = []
        for i, v in enumerate(group['values']):
            if v is not None:
                valid_days.append(days[i])
                valid_values.append(v)
        
        ax.plot(valid_days, valid_values, 
                marker='o', 
                linewidth=2.5,
                markersize=8,
                label=group['name'],
                color=group['color'])
    
    ax.set_xlabel('Day', fontsize=12, fontweight='bold')
    ax.set_ylabel('Memory (GB)', fontsize=12, fontweight='bold')
    ax.set_title(title, fontsize=14, fontweight='bold', pad=15)
    
    ax.set_ylim(0, 6)
    ax.set_xlim(-0.5, 9.5)
    ax.set_xticks(days)
    ax.set_xticklabels([f'Day {d}' for d in days])
    
    ax.legend(loc='upper left', framealpha=0.9)
    ax.grid(True, alpha=0.3)
    
    # Add horizontal reference line at 1GB
    ax.axhline(y=1.0, color='#666666', linestyle='--', alpha=0.5, label='_nolegend_')
    
    plt.tight_layout()
    fig.savefig(output_path, facecolor='#0d1117', edgecolor='none', dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Created: {output_path}")

def create_bar_chart(groups, output_path, title):
    """Create a bar chart comparing final memory values."""
    setup_dark_theme()
    
    fig, ax = plt.subplots(figsize=(8, 6))
    
    names = []
    values = []
    colors = []
    
    for group_id in groups:
        group = data[group_id]
        names.append(group['name'])
        values.append(group['values'][-1])  # Day 9 value
        colors.append(group['color'])
    
    bars = ax.bar(names, values, color=colors, edgecolor='white', linewidth=1.5)
    
    # Add value labels on bars
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                f'{val:.2f} GB', ha='center', va='bottom', fontsize=11, fontweight='bold')
    
    ax.set_ylabel('Memory (GB)', fontsize=12, fontweight='bold')
    ax.set_title(title, fontsize=14, fontweight='bold', pad=15)
    
    ax.set_ylim(0, 6.5)
    ax.grid(True, axis='y', alpha=0.3)
    
    # Rotate x labels if needed
    plt.xticks(rotation=15, ha='right')
    
    plt.tight_layout()
    fig.savefig(output_path, facecolor='#0d1117', edgecolor='none', dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"Created: {output_path}")

if __name__ == '__main__':
    # Chart 1: DirCache only (Group E vs B)
    create_chart(
        groups=['E', 'B'],
        output_path='/workspace/memory/blogs/chart_dircache.png',
        title='DirCache 0 vs Control: Memory Over Time'
    )
    
    # Chart 2: MaxMemInQueues only (Groups C, D, B)
    create_chart(
        groups=['C', 'D', 'B'],
        output_path='/workspace/memory/blogs/chart_maxmem.png',
        title='MaxMemInQueues Settings: Memory Over Time'
    )
    
    # Bar chart for DirCache comparison
    create_bar_chart(
        groups=['E', 'B'],
        output_path='/workspace/memory/blogs/chart_dircache_bar.png',
        title='Final Memory Comparison: DirCache 0 vs Control (Day 9)'
    )
    
    # Bar chart for MaxMemInQueues comparison
    create_bar_chart(
        groups=['C', 'D', 'B'],
        output_path='/workspace/memory/blogs/chart_maxmem_bar.png',
        title='Final Memory Comparison: MaxMemInQueues Settings (Day 9)'
    )
    
    print("\nAll charts generated successfully!")
