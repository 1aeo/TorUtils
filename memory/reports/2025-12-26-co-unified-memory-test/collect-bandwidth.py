#!/usr/bin/env python3
"""
Collect bandwidth data from Onionoo API for experiment relays.

Usage:
    ./collect-bandwidth.py              # Collect current bandwidth (observed/advertised)
    ./collect-bandwidth.py --history    # Collect historical time-series (write_mbps)
    ./collect-bandwidth.py --both       # Collect both current and historical

Output:
    bandwidth_measurements.csv - Unified bandwidth data file
"""

import argparse
import csv
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
import time
import os

# Use script directory for relative paths
EXP_DIR = Path(__file__).parent
RELAY_CONFIG = EXP_DIR / "relay_config.csv"
BANDWIDTH_CSV = EXP_DIR / "bandwidth_measurements.csv"

ONIONOO_DETAILS_URL = "https://onionoo.torproject.org/details"
ONIONOO_BANDWIDTH_URL = "https://onionoo.torproject.org/bandwidth"

# Unified schema for bandwidth_measurements.csv
FIELDNAMES = [
    'timestamp', 'fingerprint', 'nickname', 'group',
    'observed_bps', 'advertised_bps', 'observed_mbps', 'advertised_mbps',
    'write_bps', 'write_mbps',
    'flags', 'running'
]

# Group configuration
GROUP_CONFIG = {
    'A': 'jemalloc',
    'B': 'mimalloc', 
    'C': 'tcmalloc',
    'D': 'consensus-4h',
    'E': 'consensus-8h',
    'F': 'restart-24h',
    'G': 'restart-48h',
    'H': 'restart-72h',
    'I': 'mimalloc3',
    'Z': 'control',
}


def load_relay_config():
    """Load relay fingerprints and groups from config."""
    relays = []
    with open(RELAY_CONFIG, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['fingerprint'] and row['group']:
                relays.append({
                    'fingerprint': row['fingerprint'],
                    'nickname': row['nickname'],
                    'group': row['group']
                })
    return relays


def query_onionoo_details(fingerprints):
    """Query Onionoo API for relay details (current bandwidth)."""
    batch_size = 50
    all_relays = []
    
    for i in range(0, len(fingerprints), batch_size):
        batch = fingerprints[i:i+batch_size]
        fp_param = ','.join(batch)
        url = f"{ONIONOO_DETAILS_URL}?lookup={fp_param}"
        
        print(f"  Querying batch {i//batch_size + 1} ({len(batch)} relays)...")
        
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'TorUtils-BandwidthCheck/1.0'})
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
                all_relays.extend(data.get('relays', []))
        except urllib.error.URLError as e:
            print(f"  Error querying Onionoo: {e}")
        except json.JSONDecodeError as e:
            print(f"  Error parsing response: {e}")
        
        if i + batch_size < len(fingerprints):
            time.sleep(1)
    
    return all_relays


def query_onionoo_bandwidth(fingerprints):
    """Query Onionoo bandwidth API for relay history."""
    all_relays = []
    
    for i, fp in enumerate(fingerprints):
        url = f"{ONIONOO_BANDWIDTH_URL}?lookup={fp}"
        
        if i % 10 == 0:
            print(f"  Querying relay {i+1}/{len(fingerprints)}...")
        
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'TorUtils-BandwidthCheck/1.0'})
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
                relays = data.get('relays', [])
                if relays:
                    all_relays.append(relays[0])
        except urllib.error.URLError as e:
            print(f"  Error querying {fp[:8]}: {e}")
        except json.JSONDecodeError as e:
            print(f"  Error parsing response for {fp[:8]}: {e}")
        
        time.sleep(0.2)  # Rate limit
    
    return all_relays


def parse_bandwidth_history(relay_data, history_key='write_history'):
    """Parse bandwidth history from Onionoo response."""
    history = relay_data.get(history_key, {})
    
    for period in ['3_days', '1_week', '1_month']:
        if period in history:
            period_data = history[period]
            first_ts = datetime.fromisoformat(period_data['first'].replace('Z', '+00:00'))
            interval = period_data['interval']
            values = period_data['values']
            factor = period_data['factor']
            
            data_points = []
            current_ts = first_ts
            for val in values:
                if val is not None:
                    bytes_per_sec = val * factor
                    data_points.append((current_ts, bytes_per_sec))
                current_ts += timedelta(seconds=interval)
            
            return data_points
    
    return []


def ensure_csv_header():
    """Ensure the CSV file exists with header."""
    if not BANDWIDTH_CSV.exists():
        with open(BANDWIDTH_CSV, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
        print(f"Created {BANDWIDTH_CSV}")


def append_rows(rows):
    """Append rows to the CSV file."""
    with open(BANDWIDTH_CSV, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writerows(rows)


def collect_current(fp_to_info):
    """Collect current bandwidth snapshot (observed/advertised)."""
    print("=== Collecting Current Bandwidth from Onionoo ===")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()
    
    fingerprints = list(fp_to_info.keys())
    
    print("Querying Onionoo API...")
    onionoo_data = query_onionoo_details(fingerprints)
    print(f"  Received data for {len(onionoo_data)} relays")
    
    print("\nProcessing bandwidth data...")
    rows = []
    group_bandwidth = defaultdict(list)
    timestamp = datetime.now().isoformat()
    
    for relay in onionoo_data:
        fp = relay.get('fingerprint', '')
        if fp not in fp_to_info:
            continue
        
        info = fp_to_info[fp]
        observed_bw = relay.get('observed_bandwidth', 0)
        advertised_bw = relay.get('advertised_bandwidth', 0)
        observed_mbps = observed_bw * 8 / 1_000_000
        advertised_mbps = advertised_bw * 8 / 1_000_000
        
        rows.append({
            'timestamp': timestamp,
            'fingerprint': fp,
            'nickname': info['nickname'],
            'group': info['group'],
            'observed_bps': observed_bw,
            'advertised_bps': advertised_bw,
            'observed_mbps': observed_mbps,
            'advertised_mbps': advertised_mbps,
            'write_bps': '',
            'write_mbps': '',
            'flags': ','.join(relay.get('flags', [])),
            'running': relay.get('running', False),
        })
        
        group_bandwidth[info['group']].append(observed_mbps)
    
    append_rows(rows)
    
    print("\n=== Bandwidth by Group (Observed Mbps) ===")
    print(f"{'Group':<8} {'Name':<15} {'Avg Mbps':>10} {'Min':>10} {'Max':>10} {'Relays':>8}")
    print("-" * 65)
    
    for group in sorted(GROUP_CONFIG.keys()):
        if group in group_bandwidth and group_bandwidth[group]:
            bw_list = group_bandwidth[group]
            avg_bw = sum(bw_list) / len(bw_list)
            min_bw = min(bw_list)
            max_bw = max(bw_list)
            name = GROUP_CONFIG.get(group, group)
            print(f"{group:<8} {name:<15} {avg_bw:>10.1f} {min_bw:>10.1f} {max_bw:>10.1f} {len(bw_list):>8}")
    
    print(f"\nAppended {len(rows)} rows to {BANDWIDTH_CSV}")
    return len(rows)


def collect_history(fp_to_info):
    """Collect historical bandwidth time-series (write_mbps)."""
    print("=== Collecting Historical Bandwidth from Onionoo ===")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()
    
    fingerprints = list(fp_to_info.keys())
    
    print("Querying Onionoo Bandwidth API (this takes a few minutes)...")
    onionoo_data = query_onionoo_bandwidth(fingerprints)
    print(f"  Received data for {len(onionoo_data)} relays")
    
    print("\nProcessing bandwidth history...")
    rows = []
    grouped_data = defaultdict(lambda: defaultdict(list))
    
    for relay in onionoo_data:
        fp = relay.get('fingerprint', '')
        if fp not in fp_to_info:
            continue
        
        info = fp_to_info[fp]
        group = info['group']
        nickname = info['nickname']
        
        history = parse_bandwidth_history(relay, 'write_history')
        
        for ts, bps in history:
            ts_hour = ts.replace(minute=0, second=0, microsecond=0)
            ts_str = ts_hour.strftime('%Y-%m-%dT%H:00:00')
            mbps = bps * 8 / 1_000_000
            grouped_data[ts_str][group].append(mbps)
            
            rows.append({
                'timestamp': ts_str,
                'fingerprint': fp,
                'nickname': nickname,
                'group': group,
                'observed_bps': '',
                'advertised_bps': '',
                'observed_mbps': '',
                'advertised_mbps': '',
                'write_bps': bps,
                'write_mbps': mbps,
                'flags': '',
                'running': '',
            })
    
    # Sort before appending
    rows.sort(key=lambda x: (x['timestamp'], x['group'], x['nickname']))
    append_rows(rows)
    
    print(f"  Appended {len(rows)} rows")
    
    if grouped_data:
        unique_timestamps = sorted(grouped_data.keys())
        print(f"\nTime range: {unique_timestamps[0]} to {unique_timestamps[-1]}")
        print(f"Unique timestamps: {len(unique_timestamps)}")
    
    print(f"\nAppended {len(rows)} rows to {BANDWIDTH_CSV}")
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description='Collect bandwidth data from Onionoo API')
    parser.add_argument('--history', action='store_true', 
                        help='Collect historical time-series data (write_mbps)')
    parser.add_argument('--both', action='store_true',
                        help='Collect both current and historical data')
    args = parser.parse_args()
    
    print("Loading relay configuration...")
    relays = load_relay_config()
    print(f"  Found {len(relays)} relays in config")
    
    fp_to_info = {r['fingerprint']: r for r in relays}
    
    ensure_csv_header()
    
    total_rows = 0
    
    if args.both:
        total_rows += collect_current(fp_to_info)
        print()
        total_rows += collect_history(fp_to_info)
    elif args.history:
        total_rows = collect_history(fp_to_info)
    else:
        total_rows = collect_current(fp_to_info)
    
    print(f"\n=== Done! Total rows added: {total_rows} ===")
    print("Run chart-bandwidth.py and chart-bandwidth-history.py to update charts")


if __name__ == '__main__':
    main()
