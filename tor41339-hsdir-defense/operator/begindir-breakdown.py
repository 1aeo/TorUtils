#!/usr/bin/env python3
"""Break down a relay's BEGIN_DIR traffic from its MetricsPort (tor#41339).

Reads the MetricsPort of a relay running the tor#41339 series (+tor41339.6
or later), optionally twice to get rates over an interval, and prints what
the BEGIN_DIR streams were: onion service descriptor fetches and uploads,
other directory requests, or streams that never sent a request. With
--control it also counts the relay's open OR connections by kind of peer
(relay we know, unlisted relay identity, or unauthenticated client)
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


class Control:
    """A ControlPort session: authenticate, then GETINFO."""

    def __init__(self, args):
        if args.control_socket:
            self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.s.connect(args.control_socket)
        else:
            host, port = args.control.rsplit(':', 1)
            self.s = socket.create_connection((host, int(port)), timeout=30)
        self.f = self.s.makefile('rwb')
        if args.cookie:
            cookie = binascii.hexlify(open(args.cookie, 'rb').read()).decode()
            r = self.cmd('AUTHENTICATE ' + cookie)
        elif args.password is not None:
            r = self.cmd('AUTHENTICATE "%s"'
                         % args.password.replace('"', '\\"'))
        else:
            r = self.cmd('AUTHENTICATE')
        if not r[-1].startswith('250'):
            raise RuntimeError('authentication failed: ' + r[-1])

    def cmd(self, line):
        self.f.write(line.encode() + b'\r\n')
        self.f.flush()
        lines = []
        while True:
            r = self.f.readline().decode(errors='replace').rstrip('\r\n')
            if not r:
                raise RuntimeError('control connection closed')
            lines.append(r)
            if r[3:4] == '+':          # data block follows, ends with "."
                while True:
                    d = self.f.readline().decode(errors='replace')
                    d = d.rstrip('\r\n')
                    if d == '.':
                        break
                    lines.append(d)
            elif r[3:4] == ' ':
                return lines

    def getinfo(self, key):
        """Return the reply lines to GETINFO key, or None on an error."""
        r = self.cmd('GETINFO ' + key)
        if not r[-1].startswith('250'):
            return None
        return [l for l in r if not l.startswith('250')]

    def close(self):
        self.f.write(b'QUIT\r\n')
        self.f.flush()
        self.s.close()


def classify_orconns(lines):
    """Count open OR connections by kind of peer.

    orconn-status names a peer "$FP~nick" if our node list has a name for
    it (from our consensus or its descriptor), "$FP" if it authenticated
    with an identity our node list has no name for, and "IP:port" if it
    never authenticated (a tor client or a bridge). Return the counts, the
    connections per client address, and the unnamed identities, which the
    caller checks against the HSDir test without printing them."""
    kinds = collections.Counter()
    per_ip = collections.Counter()
    unnamed = set()
    for l in lines:
        parts = l.split()
        if len(parts) < 2 or parts[-1] != 'CONNECTED':
            continue
        name = parts[0]
        if name.startswith('$') and '~' in name:
            kinds['named'] += 1
        elif name.startswith('$'):
            kinds['unnamed'] += 1
            unnamed.add(name[1:41])
        else:
            kinds['client'] += 1
            per_ip[name.rsplit(':', 1)[0]] += 1
    return kinds, per_ip, unnamed


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
    ap.add_argument('--cc-rate', type=float, default=0,
                    help='DoSCircuitCreationRate in effect (from the '
                    'consensus), to bound the number of client addresses')
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
    split = has(b, 'tor_relay_hsdir_get_total', action='circuit_dead')
    sh = get_a['single_hop'] + post_a['single_hop']
    dead = (d('tor_relay_hsdir_get_total', action='circuit_dead') +
            d('tor_relay_hsdir_post_total', action='circuit_dead'))
    anon = hs_get + hs_post - sh - dead
    unlisted = d('tor_relay_dos_total', type='hsdir_unknown_prev_hop')
    if split:
        print('    unauthenticated client or bridge, one hop (503, '
              'single_hop): %s' % fmt(sh, rate))
        print('    circuit already closing (503, circuit_dead): %s'
              % fmt(dead, rate))
    else:
        print('    unauthenticated client, or circuit already closing (503, '
              'single_hop): %s' % fmt(sh, rate))
    print('    authenticated, relay we know (consensus or descriptors): %s'
          % fmt(max(anon - unlisted, 0), rate))
    print('    authenticated, relay identity we do not know: %s'
          % fmt(unlisted, rate))
    hops = ('client', 'known_relay', 'unknown_relay')
    if has(b, 'tor_relay_begindir_cell_total'):
        print('  Q1 x Q4: all BEGIN_DIR by previous hop: client (never '
              'authenticated: one hop from a client or bridge), relay we '
              'know, relay identity we do not know')
        row = '    %-38s' + ' %14s' * 3
        print(row % (('',) + hops))

        def line(what, name, **labels):
            print(row % ((what,) + tuple(
                fmt(d(name, prev_hop=h, **labels), rate) for h in hops)))
        line('BEGIN_DIR cells', 'tor_relay_begindir_cell_total')
        line('  accepted as streams', 'tor_relay_begindir_streams_total')
        for t, what in (('hs_get', 'onion service descriptor fetches'),
                        ('hs_post', 'onion service descriptor uploads'),
                        ('consensus', 'consensus'),
                        ('microdesc', 'microdescriptors'),
                        ('descriptor', 'relay descriptors'),
                        ('other', 'other directory requests'),
                        ('unparsed', 'unparsable or incomplete'),
                        ('no_request', 'nothing sent')):
            line('    ' + what, 'tor_relay_begindir_requests_total', type=t)
        line('circuits that sent BEGIN_DIR',
             'tor_relay_begindir_cell_total', nth='1')
        per, late = [], []
        for h in hops:
            c = d('tor_relay_begindir_cell_total', prev_hop=h, nth='1')
            cells = d('tor_relay_begindir_cell_total', prev_hop=h)
            per.append(('%.1f' % (cells / c)) if c else '-')
            late.append(('%.1f%%' % (100.0 * d(
                'tor_relay_begindir_cell_total', prev_hop=h, nth='50_plus')
                / cells)) if cells else '-')
        print(row % (('BEGIN_DIR cells per circuit',) + tuple(per)))
        print(row % (('cells that were 50th or later',) + tuple(late)))
        line('CREATE cells (all circuits)', 'tor_relay_create_cell_total')
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
        print('    circuits that made more than one: %s, %.1f requests each '
              'on average' % (fmt(circs, rate), (reused + circs) / circs))
    print('    BEGIN_DIR cells on a circuit already holding '
          'DoSBeginDirMaxStreams open directory streams: %s'
          % fmt(d('tor_relay_dos_total', type='begindir_over_max'), rate))

    print('  Q3: circuits')
    for act in ('processed', 'dropped'):
        v = d('tor_relay_load_onionskins_total', action=act)
        print('    CREATE handshakes %s, from authenticated previous hops '
              'only (stock leaves clients out): %s' % (act, fmt(v, rate)))
    # Congestion-control circuits are counted from every kind of previous
    # hop (and for the relay's own circuits), onionskins only from
    # authenticated ones; the difference is clients' congestion-control
    # circuits plus the relay's own, roughly.
    cc = d('tor_relay_congestion_control_total', state='cc_circuits',
           action='circs_created')
    v3 = d('tor_relay_load_onionskins_total', type='ntor_v3',
           action='processed')
    print('    congestion-control circuits created, from every kind of '
          'previous hop: %s' % fmt(cc, rate))
    print('      minus authenticated ntor_v3 handshakes (clients\' '
          'circuits plus the relay\'s own, roughly): %s' % fmt(cc - v3, rate))
    print('    rejected by the per-address circuit limit (client channels '
          'only): %s' % fmt(d('tor_relay_dos_total', type='circuit_rejected'),
                             rate))
    if has(b, 'tor_relay_dos_total', type='circuit_over_rate'):
        over = d('tor_relay_dos_total', type='circuit_over_rate')
        client = d('tor_relay_create_cell_total', prev_hop='client')
        print('    client CREATE cells over their address\'s '
              'DoSCircuitCreationRate (marked or not): %s of %s'
              % (fmt(over, rate), fmt(client, rate)))
        if rate and args.cc_rate:
            print('      so at least %.0f client addresses sent CREATE cells'
                  % ((client - over) / args.cc_rate))
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
            ctl = Control(args)
            lines = ctl.getinfo('orconn-status')
            if lines is None:
                raise RuntimeError('GETINFO orconn-status failed')
            kinds, per_ip, unnamed = classify_orconns(lines)
            # The HSDir check: in our consensus, or a descriptor we have.
            # Done in memory; identities are never printed.
            known = sum(1 for fp in unnamed
                        if ctl.getinfo('ns/id/' + fp) is not None or
                        ctl.getinfo('desc/id/' + fp) is not None)
            ctl.close()
        except Exception as e:  # noqa: BLE001 - report and carry on
            print('  open OR connections: ControlPort query failed: %s' % e)
            return
        print('  open OR connections by peer (GETINFO orconn-status), now')
        print('    relay named in our node list            %d'
              % kinds['named'])
        print('    authenticated identity with no name     %d'
              % kinds['unnamed'])
        print('      of their %d identities, in our consensus or '
              'descriptors: %d' % (len(unnamed), known))
        print('    client (never authenticated)            %d'
              % kinds['client'])
        if per_ip:
            print('    distinct client addresses: %d, most connections from '
                  'one address: %d' % (len(per_ip), max(per_ip.values())))


if __name__ == '__main__':
    main()
