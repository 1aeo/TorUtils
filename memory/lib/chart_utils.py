#!/usr/bin/env python3
"""
chart_utils.py - Shared utilities for Tor memory chart generation

Usage:
    from lib.chart_utils import check_matplotlib, setup_dark_theme, style_axis
"""

import sys


def check_dependencies(required: list[str]) -> None:
    """
    Check if required packages are installed.
    
    Args:
        required: List of package names to check (e.g., ['matplotlib', 'pandas'])
    """
    missing = []
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    
    if missing:
        print(f"ERROR: Missing required Python packages: {', '.join(missing)}")
        print("\nInstall with:")
        print(f"  pip install {' '.join(missing)}")
        print(f"  # or: sudo apt install {' '.join(f'python3-{p}' for p in missing)}")
        sys.exit(1)


def check_matplotlib() -> None:
    """Check if matplotlib is installed."""
    check_dependencies(['matplotlib'])


# Dark theme colors
THEME = {
    'background': '#0d1117',
    'text': '#ffffff',
    'text_secondary': '#aaaaaa',
    'grid': '#444444',
    'spine': '#444444',
    'tick': '#888888',
    # Chart colors
    'primary': '#00d4aa',
    'secondary': '#ff6b6b',
    'accent': '#ffd93d',
    'success': '#6bcb77',
    'warning': '#f39c12',
    'danger': '#e74c3c',
}


def setup_dark_theme():
    """Apply dark theme to matplotlib."""
    import matplotlib.pyplot as plt
    plt.style.use('dark_background')


def style_axis(ax, show_grid: bool = True):
    """
    Apply consistent dark theme styling to an axis.
    
    Args:
        ax: Matplotlib axis object
        show_grid: Whether to show gridlines
    """
    ax.set_facecolor(THEME['background'])
    
    for spine in ax.spines.values():
        spine.set_color(THEME['spine'])
    
    ax.tick_params(colors=THEME['tick'])
    
    if show_grid:
        ax.grid(True, alpha=0.3, color=THEME['grid'])


def style_figure(fig):
    """Apply dark theme to figure background."""
    fig.set_facecolor(THEME['background'])


def save_chart(fig, output_path, dpi: int = 150, facecolor: str | None = None):
    """
    Save chart with consistent settings.
    
    Args:
        fig: Matplotlib figure object
        output_path: Path to save the chart
        dpi: Resolution (default 150)
        facecolor: Background color. If None, uses figure's current facecolor.
                   Use THEME['background'] for dark theme charts.
    """
    import matplotlib.pyplot as plt
    save_kwargs = {
        'bbox_inches': 'tight',
        'dpi': dpi,
        'edgecolor': 'none',
    }
    if facecolor is not None:
        save_kwargs['facecolor'] = facecolor
    fig.savefig(output_path, **save_kwargs)
    plt.close(fig)


def format_date_axis(ax, rotation: int = 45, interval: int = 1, daily_ticks: bool = True):
    """
    Format x-axis for date display.
    
    Args:
        ax: Matplotlib axis object
        rotation: Label rotation angle
        interval: Weeks between major tick labels
        daily_ticks: Whether to show minor ticks for each day
    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    
    # Major ticks: weekly labels
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=interval))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=rotation, ha='right')
    
    # Minor ticks: daily (no labels)
    if daily_ticks:
        ax.xaxis.set_minor_locator(mdates.DayLocator())
        ax.tick_params(axis='x', which='minor', length=3, color='#666666')


def calculate_weekly_averages(dates: list, values: list) -> tuple[list, list]:
    """
    Calculate weekly averages from daily data.
    
    Args:
        dates: List of datetime objects
        values: List of corresponding values
    
    Returns:
        Tuple of (week_numbers, week_averages)
    """
    weeks = []
    week_avgs = []
    current_week = []
    current_week_num = None
    
    for i, d in enumerate(dates):
        week_num = d.isocalendar()[1]
        if current_week_num is None or week_num != current_week_num:
            if current_week:
                weeks.append(current_week_num)
                week_avgs.append(sum(current_week) / len(current_week))
            current_week = [values[i]]
            current_week_num = week_num
        else:
            current_week.append(values[i])
    
    # Don't forget last week
    if current_week:
        weeks.append(current_week_num)
        week_avgs.append(sum(current_week) / len(current_week))
    
    return weeks, week_avgs


def calculate_weekly_max(dates: list, values: list) -> tuple[list, list]:
    """
    Calculate weekly maximum values from daily data.
    
    Args:
        dates: List of datetime objects
        values: List of corresponding values
    
    Returns:
        Tuple of (week_numbers, week_max_values)
    """
    weeks = []
    week_maxes = []
    current_week = []
    current_week_num = None
    
    for i, d in enumerate(dates):
        week_num = d.isocalendar()[1]
        if current_week_num is None or week_num != current_week_num:
            if current_week:
                weeks.append(current_week_num)
                week_maxes.append(max(current_week))
            current_week = [values[i]]
            current_week_num = week_num
        else:
            current_week.append(values[i])
    
    # Don't forget last week
    if current_week:
        weeks.append(current_week_num)
        week_maxes.append(max(current_week))
    
    return weeks, week_maxes


def load_csv_data(csv_path: str, columns: list[str]) -> dict:
    """
    Load CSV data into a dictionary of lists.
    
    Args:
        csv_path: Path to CSV file
        columns: List of column names to extract
    
    Returns:
        Dictionary with column names as keys and lists of values
    """
    import csv
    
    data = {col: [] for col in columns}
    
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip comment rows
            if any(row.get(col, '').startswith('#') for col in columns):
                continue
            for col in columns:
                if col in row:
                    data[col].append(row[col])
    
    return data

