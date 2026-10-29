#!/usr/bin/env python3
"""Break down a relay's BEGIN_DIR traffic from its MetricsPort (tor#41339).

Reads the MetricsPort of a relay running the tor#41339 series (+tor41339.6
or later), optionally twice to get rates over an interval, and prints what
the BEGIN_DIR streams were: onion service descriptor fetches and uploads,
other directory requests, or streams that never sent a request. On
+tor41339.8 and later (tor 0.4.9.15) it also shows what tor's own BEGIN_DIR limits
refused: a second onion service request on a circuit, which tor 0.4.9.15
always refuses, and BEGIN_DIR cells over the per-circuit rate. With
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
import textwrap
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
# "unparsed"; "circuit_dead" is new in +tor41339.8.
REQUEST_TYPES = (('hs_get', 'onion service descriptor fetches'),
                 ('hs_post', 'onion service descriptor uploads'),
                 ('consensus', 'consensus'),
                 ('microdesc', 'microdescriptors'),
                 ('descriptor', 'relay descriptors'),
                 ('other_get', 'other GETs (including 404s)'),
                 ('other_post', 'other POSTs'),
                 ('other', 'other directory requests'),
                 ('unparsed', 'unparsable or incomplete'),
                 ('no_request', 'nothing sent'),
                 ('circuit_dead', 'dropped unread: circuit closing'))
# Bands of the per-minute families: a cell's or fetch's place among its
# source's, or its descriptor's, in the same minute.
BANDS = ('1', '2_10', '11_100', '101_1000', '1001_plus')
HOPS = ('client', 'known_relay', 'unknown_relay')
# The kinds of request the conclusions name, as groups of
# tor_relay_begindir_request_total types: a short name, what they were, and
# their types.
GROUPS = (('descriptor fetches', 'onion service descriptor fetches',
           ('hs_get',)),
          ('descriptor uploads', 'onion service descriptor uploads',
           ('hs_post',)),
          ('other directory requests', 'other directory requests',
           ('consensus', 'microdesc', 'descriptor', 'other_get',
            'other_post', 'other')),
          ('unparsable requests', 'unparsable or incomplete requests',
           ('unparsed',)),
          ('requests on closing circuits', 'requests we dropped unread '
           'because their stream or circuit was closing',
           ('circuit_dead',)),
          ('empty streams', 'empty: they never sent a request',
           ('no_request',)))
HOP_WORDS = {'client': 'one hop from a client or bridge (never '
                       'authenticated)',
             'known_relay': 'through a relay we know',
             'unknown_relay': 'from a relay identity we do not know'}
# A cell on the wire, with a 4-byte circuit ID, and the response bytes a
# DATA cell carries.
CELL_BYTES = 514
DATA_BYTES = 498
# TestingDirConnectionMaxStall's default: we close a directory connection
# that has written nothing for this long.
STALL_SECONDS = 300
# Labels of the families in the proposed metrics (analysis/
# v8-metrics-proposal.md), shown when a relay exports them.
REACHED = ('1', '2', '4', '11', '31', '101', '301', '1001')
AGES = ('0', '1_9', '10_59', '60_plus')
ENDED = (('client', 'by the client (END)'),
         ('circuit', 'with their circuit'),
         ('relay', 'by us (our stall timeout, mostly)'))
# The DoS rules that can refuse a tunneled directory request: their
# tor_relay_dos_total type, the option, and what they refuse. Only the types
# a relay exports are shown: tor 0.4.9.15 (+tor41339.8) added the
# begindir_* rejection counts, which count only while their rule is on;
# +tor41339.8 dropped the .7 counts of the two rules it replaced, and of the
# open-stream cap, which never fired in .7's floods.
RULES = (('begindir_hsdir_rejected', 'one HSDir request per circuit',
          'onion service requests'),
         ('hsdir_req_reused', 'HSDirOneRequestPerCircuit (.7)',
          'onion service requests'),
         ('hsdir_unknown_prev_hop', 'HSDirRefuseUnknownPrevHop',
          'onion service requests'),
         ('hsdir_fetch_shed', 'HSDirFetchShedding', 'descriptor fetches'),
         ('begindir_over_max', 'DoSBeginDirMaxStreams (.7)',
          'BEGIN_DIR cells'),
         ('begindir_rate_rejected', 'DoSBeginDirRateEnabled',
          'BEGIN_DIR cells'),
         ('begindir_rejected', 'DoSBeginDirLimitEnabled (consensus)',
          'BEGIN_DIR cells'),
         ('begindir_over_stream_rate', 'a BEGIN_DIR stream rate (.7)',
          'BEGIN_DIR cells'))


def mean_gauge(a, b, name, **labels):
    """The mean of gauge <name> over an interval, from its two samples."""
    return (get(a, name, **labels) + get(b, name, **labels)) / 2.0


def pct(part, whole):
    return 100.0 * part / whole if whole else 0.0


def size(v, rate):
    """Bytes, as a rate or a total."""
    if rate:
        return '%.1f KB/s' % (v / 1000.0)
    return '%.1f MB' % (v / 1e6)


def conclude(d, a, b, rate, elapsed, streams, anon):
    """Print, in sentences, what the counts above say."""
    says = []
    say = says.append

    def r(v):
        return fmt(v, rate)

    req = 'tor_relay_begindir_request_total'
    if not has(b, req, type='no_request'):
        print('What this says: the conclusions need +tor41339.7 or later.')
        return
    groups = [(short, what, types, sum(d(req, type=t) for t in types))
              for short, what, types in GROUPS]
    total = sum(g[3] for g in groups)
    if total <= 0:
        print('What this says: no tunneled directory requests %s.'
              % ('in this interval' if rate else 'since the relay started'))
        return
    proposed = has(b, 'tor_relay_begindir_empty_stream_total')

    # What the streams asked for, and who sent them.
    ranked = sorted(groups, key=lambda g: -g[3])
    _, top_what, top_types, top_v = ranked[0]
    share = pct(top_v, total)
    if share >= 50:
        say('%s BEGIN_DIR streams (%.1f%%, %s) were %s.'
            % ('Nearly all' if share >= 95 else 'Most', share, r(top_v),
               top_what))
    else:
        say('No kind of BEGIN_DIR stream dominated: %s.'
            % '; '.join('%s %.1f%%' % (short, pct(v, total))
                        for short, _, _, v in ranked if v > 0))
    by_hop = {h: sum(d(req, type=t, prev_hop=h) for t in top_types)
              for h in HOPS}
    parts = ['%.0f%% came %s' % (pct(v, top_v), HOP_WORDS[h])
             for h, v in sorted(by_hop.items(), key=lambda x: -x[1])
             if v > 0]
    if parts:
        line = 'Of those, %s.' % '; '.join(parts)
        main_hop = max(by_hop, key=by_hop.get)
        if pct(by_hop[main_hop], top_v) >= 50:
            if main_hop == 'known_relay':
                line += (' That previous hop relays circuits of other '
                         'senders: no rule on previous hops refuses them.')
            elif main_hop == 'unknown_relay' and top_types[0] in (
                    'hs_get', 'hs_post'):
                line += ' HSDirRefuseUnknownPrevHop refuses those.'
            elif main_hop == 'client':
                line += (' Their senders connect to us directly.' +
                         (' Stock tor already refuses such onion service '
                          'requests (503).'
                          if top_types[0] in ('hs_get', 'hs_post') else ''))
        say(line)

    # How deep their circuits go.
    cells = {h: [d('tor_relay_begindir_cell_total', prev_hop=h, nth=n)
                 for n in BANDS] for h in HOPS}
    all_cells = sum(sum(v) for v in cells.values())
    if all_cells > 0:
        h = max(cells, key=lambda x: sum(cells[x]))
        v = cells[h]
        line = ('%.0f%% of BEGIN_DIR cells came %s; %.1f%% of those were '
                "past their circuit's 10th, %.1f%% past its 100th and %.1f%% "
                'past its 1000th. Stock tor and Arti send one per onion '
                'service circuit, and about 30 or fewer on a directory '
                'circuit.' % (pct(sum(v), all_cells), HOP_WORDS[h],
                              pct(sum(v[2:]), sum(v)),
                              pct(sum(v[3:]), sum(v)), pct(v[4], sum(v))))
        if has(b, 'tor_relay_begindir_circuit_total'):
            def reached(x):
                return d('tor_relay_begindir_circuit_total', prev_hop=h,
                         reached=x)
            if rate:
                # A circuit is counted when it reaches each number, maybe
                # before this interval began.
                line += (' Their circuits passing 30 BEGIN_DIR cells: %s; '
                         'passing 1000: %s.' % (r(reached('31')),
                                                r(reached('1001'))))
            else:
                line += (' Of their %s circuits, %s carried more than 30, '
                         'and %s more than 1000.'
                         % (r(reached('1')), r(reached('31')),
                            r(reached('1001'))))
        say(line)
    if has(b, 'tor_relay_begindir_request_position_total'):
        deep = []
        for short, _, types, v in ranked[:2]:
            past10 = sum(d('tor_relay_begindir_request_position_total',
                           type=t, nth=n) for t in types for n in BANDS[2:])
            if v > 0:
                deep.append('%.1f%% of %s' % (pct(past10, v), short))
        if deep:
            say("By kind, %s were past their circuit's 10th BEGIN_DIR cell."
                % ' and '.join(deep))
    if anon > 0 and has(b, 'tor_relay_dos_total',
                        type='begindir_hsdir_rejected'):
        second = d('tor_relay_dos_total', type='begindir_hsdir_rejected')
        say('%.1f%% of onion service requests (%s) were the second on their '
            'circuit: tor refuses those and closes the circuit, since stock '
            'clients make one per circuit.' % (pct(second, anon), r(second)))
    elif anon > 0:
        reused = d('tor_relay_dos_total', type='hsdir_req_reused')
        say('%.1f%% of onion service requests (%s) came on a circuit that '
            'had already made one; stock clients make one per circuit.'
            % (pct(reused, anon), r(reused)))

    # What each rule refuses, or would.
    of = {'onion service requests': anon,
          'descriptor fetches': d('tor_relay_hsdir_fetch_total'),
          'BEGIN_DIR cells': all_cells}
    rules = [(pct(d('tor_relay_dos_total', type=t), of[what]), t, option,
              what) for t, option, what in RULES
             if of[what] > 0 and has(b, 'tor_relay_dos_total', type=t)]
    if rules:
        line = ('Each rule counts what it refuses; ours also what they would '
                'refuse while off, tor\'s own begindir_* rules only while '
                'on:')
        bytes_too = has(b, 'tor_relay_dos_response_bytes_total')
        if bytes_too:
            line += '\n|%-59s %s' % ('', 'responses')
        for p, t, option, what in sorted(rules, reverse=True):
            line += '\n|%-26s %5.1f%% of %-22s' % (option, p, what)
            if bytes_too:
                line += ' %s' % size(
                    d('tor_relay_dos_response_bytes_total', type=t), rate)
        line += ('\nA client refused can retry on a new circuit: refusing a '
                 'share of requests saves less than that share of '
                 'bandwidth.')
        say(line)

    # What they cost.
    rb = 'tor_relay_begindir_response_bytes_total'
    by = {t: d(rb, type=t) for t, _ in REQUEST_TYPES if has(b, rb, type=t)}
    sent = sum(by.values())
    if by:
        line = 'Responses took %s, read by their streams' % size(sent, rate)
        t = max(by, key=by.get)
        # Per descriptor served, for fetches: their 404s and 503s are small.
        n = (d('tor_relay_hsdir_fetch_total', action='success')
             if t == 'hs_get' else d(req, type=t))
        if by[t] > 0 and n > 0:
            per = by[t] / n
            line += ('; %.0f%% of it for %s, %.0f bytes per %s, about %d '
                     'cells with their CONNECTED and END cells'
                     % (pct(by[t], sent), dict(REQUEST_TYPES)[t], per,
                        'descriptor served' if t == 'hs_get' else 'request',
                        math.ceil(per / DATA_BYTES) + 2))
        line += ('. Each accepted stream also cost a CONNECTED cell of %d '
                 'bytes: %s.' % (CELL_BYTES, size(streams * CELL_BYTES, rate)))
        written = d('tor_relay_traffic_bytes', direction='written')
        if written > 0:
            wire = sent * CELL_BYTES / DATA_BYTES + streams * CELL_BYTES
            line += (' As cells, that is about %.0f%% of the bytes the '
                     'relay wrote.' % pct(wire, written))
        if has(b, 'tor_relay_hsdir_descriptor_bytes_total') and by.get(
                'hs_get'):
            found = pct(d('tor_relay_hsdir_descriptor_bytes_total'),
                        by['hs_get'])
            line += (' Of the descriptor fetches\' %s, %.0f%% carried a '
                     'descriptor%s' % (size(by['hs_get'], rate), found,
                                       '.' if found >= 99.5 else
                                       '; the rest were not found or '
                                       'refused.'))
        if has(b, 'tor_relay_begindir_discarded_bytes_total'):
            dropped = d('tor_relay_begindir_discarded_bytes_total')
            if dropped > 0:
                line += (' %s (%.1f%% of what was produced) was dropped when '
                         'its stream or connection closed, never sent.'
                         % (size(dropped, rate),
                            pct(dropped, sent + d(
                                'tor_relay_begindir_discarded_bytes_total',
                                where='directory'))))
            else:
                line += ' No response bytes were dropped at close.'
        say(line)

    # Streams that sent nothing.
    empty = d(req, type='no_request')
    if empty > 0:
        line = ('Empty streams: %s (%.1f%% of BEGIN_DIR streams); their '
                'CONNECTED cells alone cost %s.'
                % (r(empty), pct(empty, total),
                   size(empty * CELL_BYTES, rate)))
        if rate:
            life = mean_gauge(a, b, 'tor_relay_begindir_connections',
                              state='command_wait') / empty
            # The gauge also holds streams about to send a request, so
            # this is an upper bound on their mean life.
            line += (' Their mean life was at most %.0f s (from the gauge of '
                     'streams waiting for a request)' % life)
            if life < 10:
                # Markov's inequality.
                line += (', so at least %.0f%% closed within 10 s, before '
                         'our stall timeout could close them.'
                         % (100 * (1 - life / 10.0)))
            elif life >= 0.8 * STALL_SECONDS:
                line += (': near our stall timeout (TestingDirConnection'
                         'MaxStall, 5 minutes by default), as when streams '
                         'are held open until we close them.')
            else:
                line += '.'
        if proposed:
            es = 'tor_relay_begindir_empty_stream_total'
            line += ' They ended: %s.' % '; '.join(
                '%.0f%% %s' % (pct(d(es, ended=e), empty), words)
                for e, words in ENDED)
            line += (' Ages: %s seconds. %.0f%% were on a circuit that made '
                     'an onion service request.'
                     % (', '.join('%.0f%% %s' % (pct(d(es, age=x), empty),
                                                 x.replace('_plus', '+')
                                                 .replace('_', '-'))
                                  for x in AGES),
                        pct(d(es, circuit='hsdir'), empty)))
        say(line)

    if not proposed:
        say('Not in these metrics (see analysis/v8-metrics-proposal.md): '
            'which kinds of request sit deep in their circuits, how empty '
            'streams end and on which circuits, the response bytes each '
            'rule would avoid, descriptor and not-found bytes apart, and '
            'bytes dropped at close.')

    print('What this says (%s):' % ('rates over %.1f s' % elapsed if rate
                                    else 'since the relay started'))
    for i, text in enumerate(says, 1):
        for j, para in enumerate(text.split('\n')):
            if para.startswith('|'):    # a table row, as it is
                print(('       ' + para[1:]).rstrip())
                continue
            lines = textwrap.wrap(para, 73)
            print((('  %d. ' % i) if j == 0 else '     ') + lines[0])
            for l in lines[1:]:
                print('     ' + l)


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
    # +tor41339.8: requests dropped unread because their stream or circuit
    # was closing, such as those queued on a circuit closed for its second
    # onion service request.
    dropped = d('tor_relay_begindir_request_total', type='circuit_dead')
    wait_now = get(b, 'tor_relay_begindir_connections', state='command_wait')
    wait_delta = wait_now - get(a, 'tor_relay_begindir_connections',
                                state='command_wait')
    if rate:
        wait_delta /= elapsed
    classified = hs_get + hs_post + non_hs + unparsed + dropped
    span = ('per second over %.1f s' % elapsed) if rate else \
        'since the relay started'

    print('BEGIN_DIR streams, %s' % span)
    print('  opened (tor_relay_streams_total{type="BEGIN_DIR"}): %s'
          % fmt(streams, rate))

    def share(v):
        if not classified:
            return '   - '
        return '%5.1f%%' % (100.0 * v / classified)
    print('  Q1: what they asked for')
    print('    onion service descriptor fetches  %s  %s' % (share(hs_get),
                                                          fmt(hs_get, rate)))
    print('    onion service descriptor uploads  %s  %s' % (share(hs_post),
                                                          fmt(hs_post, rate)))
    print('    other directory requests          %s  %s' % (share(non_hs),
                                                          fmt(non_hs, rate)))
    print('    no request, or unparsable         %s  %s' % (share(unparsed),
                                                          fmt(unparsed, rate)))
    if has(b, 'tor_relay_begindir_request_total', type='circuit_dead'):
        print('    dropped unread, circuit closing   %s  %s'
              % (share(dropped), fmt(dropped, rate)))
    print('    still waiting for a request now   %d' % wait_now)
    print('    unaccounted (opened - classified - change in waiting): %s'
          % fmt(streams - classified - wait_delta, rate))

    print('  Q4: onion service requests by previous hop')
    # .7 counted requests on a closing circuit as action circuit_dead (503);
    # tor 0.4.9.15 drops them before reading them (Q1's "dropped unread").
    split = has(b, 'tor_relay_hsdir_fetch_total', action='circuit_dead')
    v8 = has(b, 'tor_relay_dos_total', type='begindir_hsdir_rejected')
    sh = get_a['single_hop'] + post_a['single_hop']
    dead = (d('tor_relay_hsdir_fetch_total', action='circuit_dead') +
            d('tor_relay_hsdir_upload_total', action='circuit_dead'))
    anon = hs_get + hs_post - sh - dead
    unlisted = d('tor_relay_dos_total', type='hsdir_unknown_prev_hop')
    # .8 counts the previous hop only of the requests that tor's limit of
    # one per circuit accepts, so the requests it refuses are a class apart.
    second = (d('tor_relay_dos_total', type='begindir_hsdir_rejected')
              if v8 else 0)
    if split or v8:
        print('    unauthenticated client or bridge, one hop (503, '
              'single_hop): %s' % fmt(sh, rate))
    if split:
        print('    circuit already closing (503, circuit_dead): %s'
              % fmt(dead, rate))
    elif not v8:
        print('    unauthenticated client, or circuit already closing (503, '
              'single_hop): %s' % fmt(sh, rate))
    if v8:
        print('    second on its circuit, refused before its previous hop is '
              'looked up: %s' % fmt(second, rate))
    if has(b, 'tor_relay_dos_total', type='hsdir_descriptor_only_prev_hop'):
        desc_only = d('tor_relay_dos_total',
                      type='hsdir_descriptor_only_prev_hop')
        print('    authenticated, relay in our consensus: %s'
              % fmt(max(anon - second - unlisted - desc_only, 0), rate))
        print('    authenticated, relay known only by its descriptor (left '
              'the consensus in about the last two days): %s'
              % fmt(desc_only, rate))
    else:
        print('    authenticated, relay we know (consensus or descriptors): %s'
              % fmt(max(anon - second - unlisted, 0), rate))
    print('    authenticated, relay identity we do not know: %s'
          % fmt(unlisted, rate))
    hops = HOPS
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

    if has(b, 'tor_relay_begindir_request_position_total'):
        print("  Q1 x place: requests by their BEGIN_DIR cell's place on its "
              'circuit')
        row = '    %-38s' + ' %10s' * len(BANDS)
        print(row % (('',) + BANDS))
        for t, what in REQUEST_TYPES:
            v = [d('tor_relay_begindir_request_position_total', type=t, nth=n)
                 for n in BANDS]
            if any(v):
                print(row % ((what,) + tuple(fmt(x, rate) for x in v)))
    if has(b, 'tor_relay_begindir_circuit_total'):
        print('  circuits that reached each number of BEGIN_DIR cells')
        row = '    %-14s' + ' %9s' * len(REACHED)
        print(row % (('',) + REACHED))
        for h in hops:
            print(row % ((h,) + tuple(
                fmt(d('tor_relay_begindir_circuit_total', prev_hop=h,
                      reached=x), rate) for x in REACHED)))
    if has(b, 'tor_relay_begindir_empty_stream_total'):
        print('  empty streams, by how they ended, their circuit, and their '
              'age in seconds')
        row = '    %-36s' + ' %10s' * len(AGES)
        print(row % (('',) + AGES))
        for e, words in ENDED:
            for c, cwords in (('hsdir', 'onion service'), ('other', 'other')):
                v = [d('tor_relay_begindir_empty_stream_total', ended=e,
                       circuit=c, age=x) for x in AGES]
                if any(v):
                    print(row % (('ended %s, %s circuit'
                                  % (e, cwords),) +
                                 tuple(fmt(x, rate) for x in v)))
    if has(b, 'tor_relay_dos_response_bytes_total'):
        print('  Q6 x rules: response bytes of requests each rule refuses, or '
              'would refuse while off')
        for t, option, _ in RULES:
            if not has(b, 'tor_relay_dos_response_bytes_total', type=t):
                continue
            by = d('tor_relay_dos_response_bytes_total', type=t)
            n = d('tor_relay_dos_total', type=t)
            print('    %-40s %s  (%s per request counted)'
                  % (option, size(by, rate),
                     ('%.0f bytes' % (by / n)) if n else '-'))
    if has(b, 'tor_relay_hsdir_descriptor_bytes_total'):
        found = d('tor_relay_hsdir_descriptor_bytes_total')
        print('    descriptor fetch responses that carried a descriptor: %s; '
              'not found or refused: %s'
              % (size(found, rate),
                 size(d('tor_relay_begindir_response_bytes_total',
                        type='hs_get') - found, rate)))
    if has(b, 'tor_relay_begindir_discarded_bytes_total'):
        print('  response bytes dropped at close, never sent: left in the '
              'directory connection %s, taken by the stream %s; waiting now: '
              '%d and %d bytes'
              % (size(d('tor_relay_begindir_discarded_bytes_total',
                        where='directory'), rate),
                 size(d('tor_relay_begindir_discarded_bytes_total',
                        where='stream'), rate),
                 get(b, 'tor_relay_begindir_pending_bytes',
                     where='directory'),
                 get(b, 'tor_relay_begindir_pending_bytes', where='stream')))

    print('  Q2: requests per circuit')
    # The anonymous onion service requests, which earlier builds also
    # exported as the dos type hsdir_request(_total).
    req = anon
    if v8:
        print('    onion service requests refused as the second on their '
              'circuit, which closes it: %s of %s'
              % (fmt(d('tor_relay_dos_total', type='begindir_hsdir_rejected'),
                     rate), fmt(req, rate)))
        print('    requests dropped unread on a closing circuit: %s'
              % fmt(dropped, rate))
    else:
        reused = d('tor_relay_dos_total', type='hsdir_req_reused')
        circs = d('tor_relay_dos_total', type='hsdir_circ_reused')
        print('    onion service requests on a circuit that already made '
              'one: %s of %s' % (fmt(reused, rate), fmt(req, rate)))
        if circs:
            print('    circuits that made more than one: %s, %.1f requests '
                  'each on average' % (fmt(circs, rate),
                                       (reused + circs) / circs))
    if has(b, 'tor_relay_dos_total', type='begindir_over_max'):
        print('    BEGIN_DIR cells on a circuit already holding '
              'DoSBeginDirMaxStreams open directory streams (.7): %s'
              % fmt(d('tor_relay_dos_total', type='begindir_over_max'), rate))
    if has(b, 'tor_relay_begindir_request_over_max_total'):
        asked = [(what, d('tor_relay_begindir_request_over_max_total',
                          type=t)) for t, what in REQUEST_TYPES]
        if any(v for _, v in asked):
            print('      what those streams asked for (what '
                  'DoSBeginDirLimitEnabled would refuse; counted only '
                  'while it is off):')
        for what, v in asked:
            if v:
                print('        %-36s %s' % (what, fmt(v, rate)))
    if has(b, 'tor_relay_dos_total', type='begindir_over_stream_rate'):
        print('    BEGIN_DIR cells over their circuit\'s stream creation '
              'rate (DoSStreamCreationRate/Burst, if it applied): %s'
              % fmt(d('tor_relay_dos_total',
                      type='begindir_over_stream_rate'), rate))
    if v8:
        print('    BEGIN_DIR cells over their circuit\'s BEGIN_DIR rate '
              '(DoSBeginDirRate/Burst; counted while DoSBeginDirRateEnabled '
              'is on, the default): %s'
              % fmt(d('tor_relay_dos_total', type='begindir_rate_rejected'),
                    rate))
        print('    BEGIN_DIR cells refused as the second on a relay\'s '
              'circuit (counted while the consensus enables '
              'DoSBeginDirLimitEnabled): %s'
              % fmt(d('tor_relay_dos_total', type='begindir_rejected'), rate))

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
        def conns(state):
            return mean_gauge(a, b, 'tor_relay_begindir_connections',
                              state=state)
        hs_ok = get_a['success']
        print('  mean time per directory stream (from the state gauge, '
              'over this interval):')
        if streams:
            print('    waiting for a request: %.1f s'
                  % (conns('command_wait') / streams))
        if hs_ok:
            print('    writing an onion service descriptor: %.1f s'
                  % (conns('writing_hs_descriptor') / hs_ok))
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
        print_orconns(args)
    print()
    conclude(d, a, b, rate, elapsed, streams, anon)


def print_orconns(args):
    """Print the open OR connections by kind of peer, from the ControlPort."""
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
    print('    relay named in our node list            %d' % kinds['named'])
    print('    authenticated identity with no name     %d'
          % kinds['unnamed'])
    print('      of their %d identities, in our consensus or '
          'descriptors: %d' % (len(unnamed), known))
    print('    client (never authenticated)            %d' % kinds['client'])
    if per_ip:
        print('    distinct client addresses: %d, most connections from '
              'one address: %d' % (len(per_ip), max(per_ip.values())))


if __name__ == '__main__':
    main()
