#!/usr/bin/env python3
"""Break down a relay's BEGIN_DIR traffic from its MetricsPort (tor#41339).

Reads the MetricsPort of a relay running the tor#41339 series (+tor41339.6
or later), optionally twice to get rates over an interval, and prints what
the BEGIN_DIR streams were: onion service descriptor fetches and uploads,
other directory requests, or streams that never sent a request. With
--control it also counts the relay's open OR connections by kind of peer
(relay in our consensus, unlisted relay identity, or unauthenticated client)
from GETINFO orconn-status.

It only reads, and prints counts: never an address, a fingerprint or a
nickname. Usage:

  begindir-breakdown.py --metrics http://127.0.0.1:9035/metrics \\
      [--interval 60] [--control 127.0.0.1:9051 | --control-socket PATH] \\
      [--cookie /var/lib/tor/control_auth_cookie | --password PW]

--interval 0 prints totals since the relay started instead of rates.
"""
import argparse
import binascii
import collections
import re
import socket
import sys
import time
import urllib.request

LINE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+(\S+)$')
LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')


def scrape(url):
    """Return {(name, frozenset(labels)): value} from a MetricsPort."""
    text = urllib.request.urlopen(url, timeout=30).read().decode()
    out = {}
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        m = LINE.match(line)
        if not m:
            continue
        labels = frozenset(LABEL.findall(m.group(2) or ''))
        try:
            out[(m.group(1), labels)] = float(m.group(3))
        except ValueError:
            pass
    return out


def get(snap, name, **labels):
    """Sum of the series of family <name> whose labels include <labels>."""
    want = set(labels.items())
    return sum(v for (n, ls), v in snap.items() if n == name and want <= ls)


def has(snap, name, **labels):
    want = set(labels.items())
    return any(n == name and want <= ls for (n, ls) in snap)


def control_orconns(args):
    """Return the lines of GETINFO orconn-status, or raise."""
    if args.control_socket:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(args.control_socket)
    else:
        host, port = args.control.rsplit(':', 1)
        s = socket.create_connection((host, int(port)), timeout=30)
    f = s.makefile('rwb')

    def cmd(line):
        f.write(line.encode() + b'\r\n')
        f.flush()
        lines = []
        while True:
            r = f.readline().decode(errors='replace').rstrip('\r\n')
            if not r:
                raise RuntimeError('control connection closed')
            lines.append(r)
            if r[3:4] == '+':          # data block follows, ends with "."
                while True:
                    d = f.readline().decode(errors='replace').rstrip('\r\n')
                    if d == '.':
                        break
                    lines.append(d)
            elif r[3:4] == ' ':
                return lines

    if args.cookie:
        cookie = binascii.hexlify(open(args.cookie, 'rb').read()).decode()
        r = cmd('AUTHENTICATE ' + cookie)
    elif args.password is not None:
        r = cmd('AUTHENTICATE "%s"' % args.password.replace('"', '\\"'))
    else:
        r = cmd('AUTHENTICATE')
    if not r[-1].startswith('250'):
        raise RuntimeError('authentication failed: ' + r[-1])
    r = cmd('GETINFO orconn-status')
    f.write(b'QUIT\r\n')
    f.flush()
    s.close()
    if not r[-1].startswith('250'):
        raise RuntimeError('GETINFO failed: ' + r[-1])
    return [l for l in r if not l.startswith('250')]


def classify_orconns(lines):
    """Count open OR connections by kind of peer.

    orconn-status names a peer "$FP~nick" if it is in our nodelist, "$FP"
    if it authenticated with a relay identity we don't know, and "IP:port"
    if it never authenticated (a tor client or a bridge)."""
    kinds = collections.Counter()
    per_ip = collections.Counter()
    for l in lines:
        parts = l.split()
        if len(parts) < 2 or parts[-1] != 'CONNECTED':
            continue
        name = parts[0]
        if name.startswith('$') and '~' in name:
            kinds['relay'] += 1
        elif name.startswith('$'):
            kinds['unlisted relay identity'] += 1
        else:
            kinds['client (unauthenticated)'] += 1
            per_ip[name.rsplit(':', 1)[0]] += 1
    return kinds, per_ip


def fmt(v, rate):
    return ('%.2f/s' % v) if rate else ('%d' % v)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--metrics', required=True, help='MetricsPort URL')
    ap.add_argument('--interval', type=float, default=60,
                    help='seconds between two scrapes (0: totals)')
    ap.add_argument('--control', help='ControlPort host:port')
    ap.add_argument('--control-socket', help='ControlSocket path')
    ap.add_argument('--cookie', help='control_auth_cookie path')
    ap.add_argument('--password', help='HashedControlPassword password')
    args = ap.parse_args()

    a = scrape(args.metrics)
    rate = args.interval > 0
    if rate:
        time.sleep(args.interval)
        b = scrape(args.metrics)
    else:
        b, a = a, {}

    def d(name, **labels):
        v = get(b, name, **labels) - get(a, name, **labels)
        return v / args.interval if rate else v

    if not has(b, 'tor_relay_hsdir_get_total'):
        sys.exit('No tor_relay_hsdir_get_total on this MetricsPort: '
                 'the relay does not run the tor#41339 series.')

    streams = d('tor_relay_streams_total', type='BEGIN_DIR')
    get_a = {x: d('tor_relay_hsdir_get_total', action=x) for x in
             ('success', 'not_found', 'single_hop', 'refused')}
    post_a = {x: d('tor_relay_hsdir_post_total', action=x) for x in
              ('success', 'bad_url', 'invalid', 'not_newer', 'single_hop',
               'refused')}
    hs_get = d('tor_relay_hsdir_get_total')
    hs_post = d('tor_relay_hsdir_post_total')
    non_hs = d('tor_relay_dir_requests_total', type='non_hs')
    unparsed = d('tor_relay_dir_requests_total', type='unparsed')
    wait_now = get(b, 'tor_relay_dir_server_conns', state='command_wait')
    wait_delta = wait_now - get(a, 'tor_relay_dir_server_conns',
                                state='command_wait')
    if rate:
        wait_delta /= args.interval
    classified = hs_get + hs_post + non_hs + unparsed
    span = ('per second over %g s' % args.interval) if rate else \
        'since the relay started'

    print('BEGIN_DIR streams, %s' % span)
    print('  opened (tor_relay_streams_total{type="BEGIN_DIR"}): %s'
          % fmt(streams, rate))

    def share(v):
        return ('%5.1f%%' % (100.0 * v / classified)) if classified else '   - '
    print('  Q1: what they asked for')
    print('    onion service descriptor fetches  %s  %s' % (share(hs_get),
                                                          fmt(hs_get, rate)))
    print('    onion service descriptor uploads  %s  %s' % (share(hs_post),
                                                          fmt(hs_post, rate)))
    print('    other directory requests          %s  %s' % (share(non_hs),
                                                          fmt(non_hs, rate)))
    print('    no request, or unparsable         %s  %s' % (share(unparsed),
                                                          fmt(unparsed, rate)))
    print('    still waiting for a request now   %d' % wait_now)
    print('    unaccounted (opened - classified - change in waiting): %s'
          % fmt(streams - classified - wait_delta, rate))

    print('  Q4: onion service requests by previous hop')
    split = has(b, 'tor_relay_hsdir_get_total', action='closing')
    sh = get_a['single_hop'] + post_a['single_hop']
    closing = (d('tor_relay_hsdir_get_total', action='closing') +
               d('tor_relay_hsdir_post_total', action='closing'))
    anon = hs_get + hs_post - sh - closing
    unlisted = d('tor_relay_dos_total', type='hsdir_unknown_prev_hop')
    if split:
        print('    unauthenticated client or bridge, one hop (503, '
              'single_hop): %s' % fmt(sh, rate))
        print('    circuit already closing (503, closing): %s'
              % fmt(closing, rate))
    else:
        print('    unauthenticated client, or circuit already closing (503, '
              'single_hop): %s' % fmt(sh, rate))
    print('    authenticated, relay in our consensus: %s'
          % fmt(max(anon - unlisted, 0), rate))
    print('    authenticated, relay identity we do not know: %s'
          % fmt(unlisted, rate))
    hops = ('client', 'relay', 'unknown_relay')
    if has(b, 'tor_relay_begindir_cells_total'):
        print('  all BEGIN_DIR by previous hop: client (unauthenticated, one '
              'hop) / relay we know / relay identity we do not know')
        row = '    %-34s' + ' %14s' * 3
        print(row % (('',) + hops))
        print(row % (('BEGIN_DIR cells',) + tuple(
            fmt(d('tor_relay_begindir_cells_total', prev_hop=h), rate)
            for h in hops)))
        print(row % (('circuits that sent BEGIN_DIR',) + tuple(
            fmt(d('tor_relay_begindir_circuits_total', prev_hop=h), rate)
            for h in hops)))
        per = []
        for h in hops:
            c = d('tor_relay_begindir_circuits_total', prev_hop=h)
            per.append(('%.1f' % (d('tor_relay_begindir_cells_total',
                                    prev_hop=h) / c)) if c else '-')
        print(row % (('BEGIN_DIR cells per circuit',) + tuple(per)))
        for t, what in (('non_hs', 'other directory requests'),
                        ('unparsed', 'no request, or unparsable')):
            print(row % ((what,) + tuple(
                fmt(d('tor_relay_dir_requests_total', type=t, prev_hop=h),
                    rate) for h in hops)))
        print(row % (('CREATE cells',) + tuple(
            fmt(d('tor_relay_create_cells_total', prev_hop=h), rate)
            for h in hops)))
    else:
        print('    (other directory requests and empty streams are not split '
              'by previous hop by these metrics)')

    print('  Q2: requests per circuit')
    req = d('tor_relay_dos_total', type='hsdir_request_total')
    reused = d('tor_relay_dos_total', type='hsdir_req_reused')
    circs = d('tor_relay_dos_total', type='hsdir_circ_reused')
    print('    onion service requests on a circuit that already made one: '
          '%s of %s' % (fmt(reused, rate), fmt(req, rate)))
    if circs:
        print('    circuits that made more than one: %s, %.1f requests each'
              % (fmt(circs, rate), (reused + circs) / circs))
    print('    BEGIN_DIR cells on a circuit already holding '
          'DoSBeginDirMaxStreams open directory streams: %s'
          % fmt(d('tor_relay_dos_total', type='begindir_over_max'), rate))

    print('  Q3: circuits')
    for act in ('processed', 'dropped'):
        v = d('tor_relay_load_onionskins_total', action=act)
        print('    CREATE handshakes %s, from authenticated previous hops '
              'only (stock leaves clients out): %s' % (act, fmt(v, rate)))
    print('    rejected by the per-address circuit limit (client channels '
          'only): %s' % fmt(d('tor_relay_dos_total', type='circuit_rejected'),
                             rate))
    print('    open circuits now: %d'
          % get(b, 'tor_relay_circuits_total', state='opened'))

    if has(b, 'tor_relay_dos_total', type='hsdir_fetch_pressure'):
        print('  descriptor fetches over HSDirFetchBudget: %s, shed or would '
              'be shed: %s, refused: %s'
              % (fmt(d('tor_relay_dos_total', type='hsdir_fetch_pressure'),
                     rate),
                 fmt(d('tor_relay_dos_total', type='hsdir_fetch_shed'), rate),
                 fmt(get_a['refused'], rate)))

    if args.control or args.control_socket:
        try:
            kinds, per_ip = classify_orconns(control_orconns(args))
        except Exception as e:  # noqa: BLE001 - report and carry on
            print('  open OR connections: ControlPort query failed: %s' % e)
            return
        print('  open OR connections by peer (GETINFO orconn-status), now')
        for k in ('relay', 'unlisted relay identity',
                  'client (unauthenticated)'):
            print('    %-26s %d' % (k, kinds[k]))
        if per_ip:
            print('    distinct client addresses: %d, most connections from '
                  'one address: %d' % (len(per_ip), max(per_ip.values())))


if __name__ == '__main__':
    main()
