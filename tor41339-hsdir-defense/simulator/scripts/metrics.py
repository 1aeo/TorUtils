#!/usr/bin/env python3
"""Scrape a tor MetricsPort (Prometheus text) and return the ticket-41339
counters of interest.  Loopback only."""
import re
import urllib.request

KEYS = {
    "begin_dir": r'tor_relay_streams_total\{type="BEGIN_DIR"\}\s+(\d+)',
    "begin": r'tor_relay_streams_total\{type="BEGIN"\}\s+(\d+)',
    "bytes_read": r'tor_relay_traffic_bytes\{direction="read"\}\s+(\d+)',
    "bytes_written": r'tor_relay_traffic_bytes\{direction="written"\}\s+(\d+)',
    "hsdir_circ_reused": r'tor_relay_dos_total\{type="hsdir_circ_reused"\}\s+(\d+)',
    "hsdir_unknown_prev_hop": r'tor_relay_dos_total\{type="hsdir_unknown_prev_hop"\}\s+(\d+)',
    "hsdir_req_reused": r'tor_relay_dos_total\{type="hsdir_req_reused"\}\s+(\d+)',
    "hsdir_request_total": r'tor_relay_dos_total\{type="hsdir_request_total"\}\s+(\d+)',
    "circs_created": r'tor_relay_congestion_control_total\{state="cc_circuits",action="circs_created"\}\s+(\d+)',
    "circs_closed": r'tor_relay_congestion_control_total\{state="cc_circuits",action="circs_closed"\}\s+(\d+)',
    "circuits_opened_gauge": r'tor_relay_circuits_total\{state="opened"\}\s+(\d+)',
    "onionskins_ntor_v3": r'tor_relay_load_onionskins_total\{type="ntor_v3",action="processed"\}\s+(\d+)',
    # tor files ntor_v3 drops under type="ntor" (onion_queue.c), so this is
    # ntor plus ntor_v3; type="ntor_v3",action="dropped" is always 0.
    "onionskins_ntor_dropped": r'tor_relay_load_onionskins_total\{type="ntor",action="dropped"\}\s+(\d+)',
}


def scrape(port, host="127.0.0.1", timeout=5.0):
    url = f"http://{host}:{port}/metrics"
    txt = urllib.request.urlopen(url, timeout=timeout).read().decode()
    out = {}
    for name, pat in KEYS.items():
        m = re.search(pat, txt)
        out[name] = int(m.group(1)) if m else None  # None = metric absent
    return out


if __name__ == "__main__":
    import sys
    print(scrape(int(sys.argv[1])))
