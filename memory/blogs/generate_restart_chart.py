#!/usr/bin/env python3
"""
Generate chart for periodic restarts blog post.
Data from Dec 2025 unified memory experiment (Groups F, G, H, Z).
"""

import matplotlib.pyplot as plt
import numpy as np

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

def create_restart_bar_chart():
    """Create a bar chart comparing restart intervals."""
    setup_dark_theme()
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Data from unified experiment
    configs = ['24h Restarts', '48h Restarts', '72h Restarts', 'No Restarts\n(Control)']
    values = [4.88, 4.56, 5.29, 5.64]
    colors = ['#ffd93d', '#00d4aa', '#6bcb77', '#ff6b6b']
    
    x = np.arange(len(configs))
    bars = ax.bar(x, values, color=colors, edgecolor='white', linewidth=1.5, width=0.6)
    
    # Add value labels on bars
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.08,
                f'{val:.2f} GB', ha='center', va='bottom', fontsize=12, fontweight='bold')
    
    # Add reduction percentages
    reductions = ['-13%', '-19%', '-6%', '—']
    for i, (bar, red) in enumerate(zip(bars, reductions)):
        if red != '—':
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() - 0.5,
                    red, ha='center', va='top', fontsize=10, color='white', alpha=0.8)
    
    ax.set_ylabel('Average Memory (GB)', fontsize=12, fontweight='bold')
    ax.set_title('Periodic Restart Intervals: Memory Comparison', fontsize=14, fontweight='bold', pad=15)
    
    ax.set_xticks(x)
    ax.set_xticklabels(configs, fontsize=11)
    ax.set_ylim(0, 6.5)
    ax.grid(True, axis='y', alpha=0.3)
    
    # Add horizontal reference line for allocator performance
    ax.axhline(y=1.5, color='#00d4aa', linestyle='--', alpha=0.5, linewidth=2)
    ax.text(3.5, 1.65, 'mimalloc/jemalloc range', fontsize=9, color='#00d4aa', alpha=0.8, ha='right')
    
    plt.tight_layout()
    fig.savefig('/workspace/memory/blogs/chart_restarts.png', 
                facecolor='#0d1117', edgecolor='none', dpi=150, bbox_inches='tight')
    plt.close(fig)
    print("Created: /workspace/memory/blogs/chart_restarts.png")

if __name__ == '__main__':
    create_restart_bar_chart()
