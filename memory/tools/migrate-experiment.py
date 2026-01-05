#!/usr/bin/env python3
"""
Migrate Legacy Experiment Data to New Format

Converts experiment data from the old day-column format to the new
timestamped row format.

Old format (data.csv):
  group,relay,day0,day1,day2,...,dayN
  A,22gz,5.03,0.28,0.32,...

New format (memory_measurements.csv):
  timestamp,server,type,fingerprint,nickname,group,rss_kb,vmsize_kb,hwm_kb,frag_ratio,count,total_kb,avg_kb,min_kb,max_kb

Usage:
    python3 migrate-experiment.py --input reports/old-experiment/data.csv --output reports/old-experiment/memory_measurements.csv
    python3 migrate-experiment.py --experiment reports/old-experiment/

Requirements:
    None (standard library only)
"""

import argparse
import csv
import re
from datetime import datetime, timedelta
from pathlib import Path
import json


def parse_group_definitions(lines: list[str]) -> dict:
    """Parse group definitions from comment lines."""
    groups = {}
    
    for line in lines:
        if not line.startswith('#'):
            continue
        
        # Match: # group,relay,config,dircache,maxmem
        # Example: # A,22gz,DirCache 0 + MaxMem 2GB,0,2GB
        match = re.match(r'#\s*([A-Z]),([^,]+),([^,]+),([^,]+),(.+)', line)
        if match:
            group, relay, config, dircache, maxmem = match.groups()
            if group not in groups:
                groups[group] = {
                    'name': config.strip(),
                    'config': {
                        'dircache': dircache.strip(),
                        'maxmem': maxmem.strip(),
                    },
                    'relays': []
                }
            groups[group]['relays'].append(relay.strip())
    
    return groups


def parse_day_columns(header: str) -> list[int]:
    """Extract day numbers from column headers like day0, day1, day9."""
    days = []
    for col in header.split(','):
        match = re.match(r'day(\d+)', col.strip())
        if match:
            days.append(int(match.group(1)))
    return days


def gb_to_kb(gb_str: str) -> int:
    """Convert GB string to KB integer."""
    if not gb_str or gb_str.strip() == '':
        return 0
    try:
        return int(float(gb_str) * 1048576)
    except ValueError:
        return 0


def migrate_experiment(input_path: Path, output_path: Path, start_date: datetime, server: str):
    """Migrate experiment data from old to new format."""
    
    # Read all lines
    with open(input_path, 'r') as f:
        lines = f.readlines()
    
    # Parse group definitions from comments
    groups = parse_group_definitions(lines)
    
    # Find data header and parse day columns
    data_started = False
    header_line = None
    data_rows = []
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        if line.startswith('group,relay'):
            header_line = line
            data_started = True
            continue
        
        if data_started and ',' in line:
            data_rows.append(line)
    
    if not header_line:
        print("Error: Could not find data header (group,relay,...)")
        return False
    
    days = parse_day_columns(header_line)
    print(f"Found day columns: {days}")
    
    # Build measurements
    measurements = []
    
    for row_str in data_rows:
        parts = row_str.split(',')
        if len(parts) < 3:
            continue
        
        group = parts[0].strip()
        relay = parts[1].strip()
        
        # Get day values
        for i, day_num in enumerate(days):
            col_idx = i + 2  # Skip group and relay columns
            if col_idx >= len(parts):
                continue
            
            value = parts[col_idx].strip()
            rss_kb = gb_to_kb(value)
            
            if rss_kb == 0:
                continue  # Skip empty values
            
            # Calculate date
            date = start_date + timedelta(days=day_num)
            timestamp = date.strftime('%Y-%m-%dT00:00:00')
            
            measurements.append({
                'timestamp': timestamp,
                'server': server,
                'type': 'relay',
                'fingerprint': '',  # Not available in old format
                'nickname': relay,
                'group': group,
                'rss_kb': rss_kb,
                'vmsize_kb': '',
                'hwm_kb': '',
                'frag_ratio': '',
                'count': '',
                'total_kb': '',
                'avg_kb': '',
                'min_kb': '',
                'max_kb': '',
            })
    
    # Sort by timestamp
    measurements.sort(key=lambda x: x['timestamp'])
    
    # Calculate aggregate rows for each timestamp
    timestamps = sorted(set(m['timestamp'] for m in measurements))
    aggregates = []
    
    for ts in timestamps:
        ts_measurements = [m for m in measurements if m['timestamp'] == ts]
        rss_values = [m['rss_kb'] for m in ts_measurements]
        
        if rss_values:
            aggregates.append({
                'timestamp': ts,
                'server': server,
                'type': 'aggregate',
                'fingerprint': '',
                'nickname': '',
                'group': '',
                'rss_kb': '',
                'vmsize_kb': '',
                'hwm_kb': '',
                'frag_ratio': '',
                'count': len(rss_values),
                'total_kb': sum(rss_values),
                'avg_kb': sum(rss_values) // len(rss_values),
                'min_kb': min(rss_values),
                'max_kb': max(rss_values),
            })
    
    # Combine and sort all rows
    all_rows = aggregates + measurements
    all_rows.sort(key=lambda x: (x['timestamp'], x['type'] == 'relay'))
    
    # Write output
    with open(output_path, 'w', newline='') as f:
        fieldnames = ['timestamp', 'server', 'type', 'fingerprint', 'nickname', 'group',
                      'rss_kb', 'vmsize_kb', 'hwm_kb', 'frag_ratio',
                      'count', 'total_kb', 'avg_kb', 'min_kb', 'max_kb']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)
    
    print(f"✓ Migrated {len(measurements)} relay measurements")
    print(f"✓ Generated {len(aggregates)} aggregate rows")
    print(f"✓ Output: {output_path}")
    
    return groups


def create_experiment_json(exp_dir: Path, groups: dict, start_date: datetime, server: str):
    """Create experiment.json from parsed group definitions."""
    json_path = exp_dir / 'experiment.json'
    
    # Convert groups to JSON format
    groups_json = {}
    for group_name, group_data in groups.items():
        groups_json[group_name] = {
            'name': group_data['name'],
            'config': group_data.get('config', {}),
        }
    
    experiment = {
        'id': exp_dir.name,
        'name': f"Migrated: {exp_dir.name}",
        'server': server,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': '',
        'hypothesis': '',
        'description': 'Migrated from legacy data.csv format',
        'groups': groups_json,
        'tor_version': 'unknown',
        'allocator': 'glibc',
    }
    
    with open(json_path, 'w') as f:
        json.dump(experiment, f, indent=2)
    
    print(f"✓ Created: {json_path}")


def create_relay_config(exp_dir: Path, groups: dict):
    """Create relay_config.csv from parsed group definitions."""
    config_path = exp_dir / 'relay_config.csv'
    
    with open(config_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['fingerprint', 'nickname', 'group', 'dircache', 'maxmem', 'notes'])
        
        for group_name, group_data in groups.items():
            config = group_data.get('config', {})
            for relay in group_data.get('relays', []):
                writer.writerow([
                    '',  # fingerprint not available
                    relay,
                    group_name,
                    config.get('dircache', 'default'),
                    config.get('maxmem', 'default'),
                    group_data.get('name', ''),
                ])
    
    print(f"✓ Created: {config_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Migrate legacy experiment data to new format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python3 migrate-experiment.py --experiment reports/2025-09-18-co-guard-fragmentation/
    python3 migrate-experiment.py --input data.csv --output memory_measurements.csv --start-date 2025-09-09

The migration will:
  1. Convert day-column data to timestamped rows
  2. Generate aggregate rows for each timestamp
  3. Create experiment.json from group definitions in comments
  4. Create relay_config.csv from group assignments
        """
    )
    parser.add_argument('--experiment', '-e',
                        help='Experiment directory (will process data.csv)')
    parser.add_argument('--input', '-i',
                        help='Input CSV file (legacy format)')
    parser.add_argument('--output', '-o',
                        help='Output CSV file (new format)')
    parser.add_argument('--start-date', '-d', default='2025-09-09',
                        help='Start date for day0 (YYYY-MM-DD, default: 2025-09-09)')
    parser.add_argument('--server', '-s', default='',
                        help='Server name (default: extracted from directory name)')
    
    args = parser.parse_args()
    
    # Determine paths
    if args.experiment:
        exp_dir = Path(args.experiment)
        input_path = exp_dir / 'data.csv'
        output_path = exp_dir / 'memory_measurements.csv'
        
        # Extract server from directory name (e.g., "2025-09-18-co-guard-fragmentation" -> "co")
        parts = exp_dir.name.split('-')
        server = parts[3] if len(parts) > 3 else 'unknown'
    else:
        if not args.input or not args.output:
            print("Error: Must specify --experiment or both --input and --output")
            parser.print_help()
            return
        input_path = Path(args.input)
        output_path = Path(args.output)
        exp_dir = output_path.parent
        server = args.server or 'unknown'
    
    if args.server:
        server = args.server
    
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        return
    
    # Parse start date
    try:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
    except ValueError:
        print(f"Error: Invalid date format: {args.start_date}")
        return
    
    print(f"=== Migrating Experiment Data ===")
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Start date: {start_date.strftime('%Y-%m-%d')}")
    print(f"Server: {server}")
    print()
    
    # Migrate data
    groups = migrate_experiment(input_path, output_path, start_date, server)
    
    if groups:
        print()
        create_experiment_json(exp_dir, groups, start_date, server)
        create_relay_config(exp_dir, groups)
    
    print(f"\n✓ Migration complete!")


if __name__ == '__main__':
    main()

