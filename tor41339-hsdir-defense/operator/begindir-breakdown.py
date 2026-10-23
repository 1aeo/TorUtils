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
      [--cookie /var/lib/tor/control_auth_cookie | --password PW] \\
      [--cc-rate R --cc-burst B]

--interval 0 prints totals since the relay started instead of rates. Rates
are over the time between the two answers, which is longer than --interval
when the MetricsPort is slow to answer.
"""
import argparse
import binascii
import collections
import math
import re
import socket
import sys
import time
import urllib.request

LINE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+(\S+)$')
LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')
# Names the families had before the final +tor41339.7: in +tor41339.6, and
# in the first .7 build.
OLD_NAMES = {
    'tor_relay_hsdir_get_total': 'tor_relay_hsdir_fetch_total',
    'tor_relay_hsdir_post_total': 'tor_relay_hsdir_upload_total',
    'tor_relay_dir_requests_total': 'tor_relay_begindir_request_total',
    'tor_relay_begindir_requests_total': 'tor_relay_begindir_request_total',
    'tor_relay_dir_responses_total': 'tor_relay_begindir_response_total',
    'tor_relay_dir_server_conns': 'tor_relay_begindir_connections',
    'tor_relay_begindir_over_max_requests_total':
        'tor_relay_begindir_request_over_max_total',
    'tor_relay_hsdir_fetch_target_total':
        'tor_relay_hsdir_fetch_descriptor_total',
}
# The first .7 build called the "not_found" lookup "missing".
OLD_LOOKUPS = {'missing': 'not_found'}


def scrape(url, gauges=None):
    """Return {(name, frozenset(labels)): value} from a MetricsPort, under
    the final +tor41339.7 names, and add the names of its gauge families to
    <gauges> if given."""
    text = urllib.request.urlopen(url, timeout=30).read().decode()
    out = {}
    for line in text.splitlines():
        if line.startswith('# TYPE ') and gauges is not None:
            parts = line.split()
            if len(parts) == 4 and parts[3] == 'gauge':
                gauges.add(OLD_NAMES.get(parts[2], parts[2]))
        if not line or line.startswith('#'):
            continue
        m = LINE.match(line)
        if not m:
            continue
        name = OLD_NAMES.get(m.group(1), m.group(1))
        labels = LABEL.findall(m.group(2) or '')
        if name == 'tor_relay_hsdir_fetch_descriptor_total':
            labels = [(k, OLD_LOOKUPS.get(v, v) if k == 'lookup' else v)
                      for k, v in labels]
        try:
            out[(name, frozenset(labels))] = float(m.group(3))
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
    # round() + 0.0 turns a rounding error's -0.00 into 0.00.
    return ('%.2f/s' % (round(v, 2) + 0.0)) if rate else ('%d' % v)


# tor_relay_begindir_request_total types, in report order. "other" is only
# in lab builds of the proposed patches, before 0018 split it into
# "other_get" and "other_post"; +tor41339.6 has only "non_hs" and
# "unparsed".
REQUEST_TYPES = (('hs_get', 'onion service descriptor fetches'),
                 ('hs_post', 'onion service descriptor uploads'),
                 ('consensus', 'consensus'),
                 ('microdesc', 'microdescriptors'),
                 ('descriptor', 'relay descriptors'),
                 ('other_get', 'other GETs (including 404s)'),
                 ('other_post', 'other POSTs'),
                 ('other', 'other directory requests'),
                 ('unparsed', 'unparsable or incomplete'),
                 ('no_request', 'nothing sent'))
# Bands of the per-minute families: a cell's or fetch's place among its
# source's, or its descriptor's, in the same minute.
BANDS = ('1', '2_10', '11_100', '101_1000', '1001_plus')


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
                    'consensus); with --cc-burst, to bound the number of '
                    'client addresses')
    ap.add_argument('--cc-burst', type=float, default=None,
                    help='DoSCircuitCreationBurst in effect (from the '
                    'consensus)')
    args = ap.parse_args()

    gauges = set()
    a = scrape(args.metrics, gauges)
    t_a = time.monotonic()
    if not has(a, 'tor_relay_hsdir_fetch_total'):
        sys.exit('No tor_relay_hsdir_fetch_total on this MetricsPort: '
                 'the relay does not run the tor#41339 series.')
    rate = args.interval > 0
    if rate:
        time.sleep(args.interval)
        b = scrape(args.metrics)
        # The counters cover the time between the two answers.
        elapsed = time.monotonic() - t_a
        back = sorted(n for (n, ls), v in a.items()
                      if n.startswith('tor_relay_') and n not in gauges and
                      b.get((n, ls), v) < v)
        if back:
            sys.exit('%s went backwards between the two scrapes: the relay '
                     'restarted. Run the script again.' % back[0])
    else:
        b, a = a, {}
        elapsed = 0

    def d(name, **labels):
        v = get(b, name, **labels) - get(a, name, **labels)
        return v / elapsed if rate else v

    streams = d('tor_relay_streams_total', type='BEGIN_DIR')
    get_a = {x: d('tor_relay_hsdir_fetch_total', action=x) for x in
             ('success', 'not_found', 'single_hop', 'refused')}
    post_a = {x: d('tor_relay_hsdir_upload_total', action=x) for x in
              ('success', 'bad_url', 'invalid', 'not_newer', 'single_hop',
               'refused')}
    hs_get = d('tor_relay_hsdir_fetch_total')
    hs_post = d('tor_relay_hsdir_upload_total')
    # +tor41339.7 counts each accepted stream's request once, by type;
    # +tor41339.6 counts only those that are not onion service requests, as
    # "non_hs" or "unparsed".
    non_hs = sum(d('tor_relay_begindir_request_total', type=t)
                 for t in ('consensus', 'microdesc', 'descriptor',
                           'other_get', 'other_post', 'other', 'non_hs'))
    unparsed = sum(d('tor_relay_begindir_request_total', type=t)
                   for t in ('unparsed', 'no_request'))
    wait_now = get(b, 'tor_relay_begindir_connections', state='command_wait')
    wait_delta = wait_now - get(a, 'tor_relay_begindir_connections',
                                state='command_wait')
    if rate:
        wait_delta /= elapsed
    classified = hs_get + hs_post + non_hs + unparsed
    span = ('per second over %.1f s' % elapsed) if rate else \
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
    split = has(b, 'tor_relay_hsdir_fetch_total', action='circuit_dead')
    sh = get_a['single_hop'] + post_a['single_hop']
    dead = (d('tor_relay_hsdir_fetch_total', action='circuit_dead') +
            d('tor_relay_hsdir_upload_total', action='circuit_dead'))
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
    if has(b, 'tor_relay_dos_total', type='hsdir_descriptor_only_prev_hop'):
        desc_only = d('tor_relay_dos_total',
                      type='hsdir_descriptor_only_prev_hop')
        print('    authenticated, relay in our consensus: %s'
              % fmt(max(anon - unlisted - desc_only, 0), rate))
        print('    authenticated, relay known only by its descriptor (left '
              'the consensus in about the last two days): %s'
              % fmt(desc_only, rate))
    else:
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
        line('  requests (each accepted stream once)',
             'tor_relay_begindir_request_total')
        for t, what in REQUEST_TYPES:
            if has(b, 'tor_relay_begindir_request_total', type=t):
                line('    ' + what, 'tor_relay_begindir_request_total',
                     type=t)
        line('circuits that sent BEGIN_DIR',
             'tor_relay_begindir_cell_total', nth='1')
        per, past10, past100 = [], [], []
        for h in hops:
            v = [d('tor_relay_begindir_cell_total', prev_hop=h, nth=n)
                 for n in BANDS]
            cells = sum(v)
            per.append(('%.1f' % (cells / v[0])) if v[0] else '-')
            past10.append(('%.1f%%' % (100.0 * sum(v[2:]) / cells))
                          if cells else '-')
            past100.append(('%.1f%%' % (100.0 * sum(v[3:]) / cells))
                           if cells else '-')
        print(row % (('BEGIN_DIR cells per circuit',) + tuple(per)))
        print(row % (("cells past their circuit's 10th",) + tuple(past10)))
        print(row % (("cells past their circuit's 100th",) + tuple(past100)))
        line('CREATE cells (all circuits)', 'tor_relay_create_cell_total')
    else:
        print('    (other directory requests and empty streams are not split '
              'by previous hop by these metrics)')

    if has(b, 'tor_relay_begindir_response_bytes_total'):
        print('  Q6: response bytes read by their stream, by request type')
        for t, what in REQUEST_TYPES:
            if not has(b, 'tor_relay_begindir_response_bytes_total', type=t):
                continue
            by = d('tor_relay_begindir_response_bytes_total', type=t)
            n = d('tor_relay_begindir_request_total', type=t)
            if not by and not n:
                continue
            print('    %-38s %s  (%s per request)'
                  % (what, ('%.1f KB/s' % (by / 1000.0)) if rate else
                     ('%d bytes' % by),
                     ('%.0f bytes' % (by / n)) if n else '-'))

    print('  Q2: requests per circuit')
    # The anonymous onion service requests, which earlier builds also
    # exported as the dos type hsdir_request(_total).
    req = anon
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
    if has(b, 'tor_relay_begindir_request_over_max_total'):
        asked = [(what, d('tor_relay_begindir_request_over_max_total',
                          type=t)) for t, what in REQUEST_TYPES]
        if any(v for _, v in asked):
            print('      what those streams asked for (what '
                  'DoSBeginDirLimitEnabled would refuse; counted only while '
                  'it is off):')
        for what, v in asked:
            if v:
                print('        %-36s %s' % (what, fmt(v, rate)))
    if has(b, 'tor_relay_dos_total', type='begindir_over_stream_rate'):
        print('    BEGIN_DIR cells over their circuit\'s stream creation '
              'rate (DoSStreamCreationRate/Burst, if it applied): %s'
              % fmt(d('tor_relay_dos_total',
                      type='begindir_over_stream_rate'), rate))

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
        untracked = d('tor_relay_dos_total', type='circuit_untracked')
        client = d('tor_relay_create_cell_total', prev_hop='client')
        print('    client CREATE cells that found their address\'s '
              'DoSCircuitCreationRate/Burst bucket empty (marked or not; '
              'counted only while DoSCircuitCreationEnabled is on): %s of %s'
              % (fmt(over, rate), fmt(client, rate)))
        if has(b, 'tor_relay_dos_total', type='circuit_untracked'):
            print('    client CREATE cells from addresses tor no longer '
                  'tracks, which DoSCircuitCreation does not limit: %s'
                  % fmt(untracked, rate))
        if rate and args.cc_rate and args.cc_burst is not None:
            # Within its bucket, an address sends at most Rate cells for
            # each whole second that passes, plus Burst.
            per_addr = args.cc_rate * math.ceil(elapsed) + args.cc_burst
            print('      so at least %.0f tracked client addresses sent '
                  'CREATE cells, if DoSCircuitCreationEnabled was on '
                  'throughout'
                  % ((client - over - untracked) * elapsed / per_addr))
        elif rate and args.cc_rate:
            print('      (with --cc-burst too, a lower bound on client '
                  'addresses)')
    print('    open circuits now: %d'
          % get(b, 'tor_relay_circuits_total', state='opened'))

    def bands(name, what, unit, **labels):
        # Distinct sources (or descriptors) per clock minute, and the share
        # of cells (or fetches) past each one's 10th and 100th in a minute.
        v = [d(name, nth=n, **labels) for n in BANDS]
        total = sum(v)
        if not total:
            return
        if not rate:
            per_min = '%d %s-minutes' % (v[0], unit)
        elif args.interval % 60 == 0:
            per_min = '%.0f a minute' % (v[0] * 60)
        else:
            per_min = '(per minute: use an --interval of 60 or a multiple)'
        print('    %-28s %s; %.1f%% past their 10th, %.1f%% past their '
              '100th in a minute' % (what, per_min,
                                      100.0 * sum(v[2:]) / total,
                                      100.0 * sum(v[3:]) / total))
    if has(b, 'tor_relay_create_cell_source_total'):
        print('  Q3: sources (a client address tor tracks, else a client '
              'channel; or a relay channel; not counted on bridges)')
        for h in hops:
            bands('tor_relay_create_cell_source_total',
                  'CREATE from %s:' % h, 'source', prev_hop=h)
            bands('tor_relay_begindir_cell_source_total',
                  'BEGIN_DIR from %s:' % h, 'source', prev_hop=h)
    if has(b, 'tor_relay_hsdir_fetch_descriptor_total'):
        print('  descriptors fetched (distinct per minute; a fetch past the '
              '10th or 100th of its descriptor in a minute)')
        for lookup in ('found', 'not_found'):
            bands('tor_relay_hsdir_fetch_descriptor_total',
                  '%s:' % lookup, 'descriptor', lookup=lookup)

    if rate:
        # Little's law: mean number in a state / the rate of entering it.
        def mean_gauge(state):
            return (get(a, 'tor_relay_begindir_connections', state=state) +
                    get(b, 'tor_relay_begindir_connections',
                        state=state)) / 2.0
        hs_ok = get_a['success']
        print('  mean time per directory stream (from the state gauge, '
              'over this interval):')
        if streams:
            print('    waiting for a request: %.1f s'
                  % (mean_gauge('command_wait') / streams))
        if hs_ok:
            print('    writing an onion service descriptor: %.1f s'
                  % (mean_gauge('writing_hs_descriptor') / hs_ok))
            gone = hs_ok - d('tor_relay_begindir_response_total',
                             type='hs_descriptor') - (
                get(b, 'tor_relay_begindir_connections',
                    state='writing_hs_descriptor') -
                get(a, 'tor_relay_begindir_connections',
                    state='writing_hs_descriptor')) / elapsed
            print('    descriptors abandoned before their stream took them: '
                  '%s' % fmt(max(gone, 0), rate))

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
