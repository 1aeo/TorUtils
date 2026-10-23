#!/usr/bin/env python3
"""Emit an arti.toml that points an Arti client at a private chutney network.

Reads only the chutney nodes directory (no network access):
  <node>/torrc                        ORPort, DirPort, Address, authority role,
                                      V3AuthVotingInterval
  <node>/fingerprint                  "<nick> <RSA identity hex>"
  <node>/fingerprint-ed25519          "<nick> <ed25519 identity base64>"
  <node>/keys/authority_certificate   "fingerprint <v3 identity hex>"
and cross-checks the result against the DirAuthority lines chutney writes into
every torrc.

Usage:
  mkconf.py NODES_DIR --state DIR --socks-port N [--log FILE]
            [--log-filter EXPR] [--fallbacks auth|all]
            [--hs-desc-fetch-attempts N] [--hs-dir-requery-interval DUR]
            [--hsdir-interval MIN] [--out FILE]

All addresses come from the chutney torrcs (normally 127.0.0.1). The output
is meant for an arti process that runs inside a --network none container,
together with the chutney net.
"""
import argparse
import glob
import os
import re
import sys

# C tor with TestingTorNetwork 1 shortens the onion-service time period to one
# shared-random protocol run: SHARED_RANDOM_N_ROUNDS * SHARED_RANDOM_N_PHASES
# voting intervals (hs_common.c / shared_random_client.h). Arti does not know
# about TestingTorNetwork, so it must be told via override_net_params, or it
# computes different blinded keys and HSDir positions and never finds a
# descriptor.
SR_N_ROUNDS = 12
SR_N_PHASES = 2

DEFAULT_LOG_FILTER = ("info,tor_hsclient=trace,tor_dirclient=debug,"
                      "tor_circmgr=debug,arti::proxy=debug")


def die(msg):
    sys.exit("mkconf: " + msg)


def read_torrc(path):
    """Return list of (key_lower, value) pairs, comments stripped."""
    out = []
    with open(path) as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split(None, 1)
            out.append((parts[0].lower(), parts[1] if len(parts) > 1 else ""))
    return out


def opt(torrc, key, default=None):
    vals = [v for k, v in torrc if k == key.lower()]
    return vals[-1] if vals else default


def second_field(path):
    with open(path) as f:
        parts = f.read().split()
    if len(parts) < 2:
        die("unexpected content in %s" % path)
    return parts[1]


def port_addr(value, address):
    """'127.0.0.1:5100' or '5100' (+Address) -> '127.0.0.1:5100'."""
    value = value.split()[0]
    if ":" in value:
        return value
    return "%s:%s" % (address, value)


def node_info(ndir):
    torrc = read_torrc(os.path.join(ndir, "torrc"))
    nick = opt(torrc, "Nickname", os.path.basename(ndir))
    address = opt(torrc, "Address", "127.0.0.1")
    orport = opt(torrc, "ORPort")
    dirport = opt(torrc, "DirPort")
    is_auth = (opt(torrc, "AuthoritativeDirectory", "0") == "1" or
               opt(torrc, "V3AuthoritativeDirectory", "0") == "1")
    info = {"dir": ndir, "nick": nick, "torrc": torrc, "authority": is_auth}
    if orport and orport.split()[0] not in ("0", "auto"):
        info["orport"] = port_addr(orport, address)
    if dirport and dirport.split()[0] not in ("0", "auto"):
        info["dirport"] = port_addr(dirport, address)
    fp = os.path.join(ndir, "fingerprint")
    fp_ed = os.path.join(ndir, "fingerprint-ed25519")
    if os.path.exists(fp):
        info["rsa"] = second_field(fp)
    if os.path.exists(fp_ed):
        info["ed"] = second_field(fp_ed)
    cert = os.path.join(ndir, "keys", "authority_certificate")
    if is_auth:
        if not os.path.exists(cert):
            die("authority %s has no keys/authority_certificate" % nick)
        with open(cert) as f:
            m = re.search(r"^fingerprint ([0-9A-F]{40})$", f.read(), re.M)
        if not m:
            die("no v3 fingerprint in %s" % cert)
        info["v3ident"] = m.group(1)
    return info


def dirauthority_lines(nodes):
    """Parse chutney's DirAuthority lines (from the first torrc that has them)."""
    pat = re.compile(r"^(\S+)\s.*orport=(\d+).*v3ident=([0-9A-F]{40})\s+"
                     r"(\S+:\d+)\s+([0-9A-F ]{40,})$")
    for n in nodes:
        lines = [v for k, v in n["torrc"] if k == "dirauthority"]
        if lines:
            out = {}
            for v in lines:
                m = pat.match(v.strip())
                if m:
                    out[m.group(1)] = {
                        "orport": m.group(2), "v3ident": m.group(3),
                        "dirport": m.group(4),
                        "rsa": m.group(5).replace(" ", "")}
            return out
    return {}


def q(s):
    return '"%s"' % str(s).replace("\\", "\\\\").replace('"', '\\"')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("nodes_dir")
    ap.add_argument("--state", required=True,
                    help="directory for Arti cache/ and state/ (per instance)")
    ap.add_argument("--socks-port", type=int, required=True)
    ap.add_argument("--log", help="log file path (default STATE/arti.log)")
    ap.add_argument("--log-filter", default=DEFAULT_LOG_FILTER)
    ap.add_argument("--console-filter", default="warn")
    ap.add_argument("--time-granularity", default="1ms",
                    help='logging.time_granularity (Arti default "1s")')
    ap.add_argument("--fallbacks", choices=("auth", "all"), default="auth",
                    help="fallback caches: authorities only (as chutney "
                         "does) or every relay with an ORPort")
    ap.add_argument("--hs-desc-fetch-attempts", type=int,
                    help="circuit_timing.hs_desc_fetch_attempts (Arti default 6)")
    ap.add_argument("--hs-intro-rend-attempts", type=int,
                    help="circuit_timing.hs_intro_rend_attempts (Arti default 6)")
    ap.add_argument("--hs-dir-requery-interval",
                    help='circuit_timing.hs_dir_requery_interval, e.g. "15 min"')
    ap.add_argument("--hsdir-interval", type=int,
                    help="override_net_params.hsdir_interval in minutes "
                         "(default: derived from V3AuthVotingInterval)")
    ap.add_argument("--cbt-min-timeout-ms", type=int, default=2000,
                    help="override_net_params.cbtmintimeout (Arti default 10). "
                         "On loopback Arti learns ~50 ms timeouts, and its "
                         "per-attempt HSDir round-trip timeout is half the "
                         "circuit-build timeout, so a busy lab relay looks "
                         "like a dead one. 0 keeps Arti's default.")
    ap.add_argument("--net-param", action="append", default=[],
                    metavar="NAME=INT", help="extra override_net_params entry")
    ap.add_argument("--out", help="output file (default stdout)")
    a = ap.parse_args()

    ndirs = sorted(d for d in glob.glob(os.path.join(a.nodes_dir, "*"))
                   if os.path.isdir(d) and
                   re.fullmatch(r"\d+[a-z]+", os.path.basename(d)) and
                   os.path.exists(os.path.join(d, "torrc")))
    if not ndirs:
        die("no chutney node dirs with a torrc under %s" % a.nodes_dir)
    nodes = [node_info(d) for d in ndirs]
    auths = [n for n in nodes if n["authority"]]
    if not auths:
        die("no authorities found")
    for n in auths:
        for k in ("rsa", "ed", "orport", "dirport", "v3ident"):
            if k not in n:
                die("authority %s lacks %s" % (n["nick"], k))

    # Cross-check with the DirAuthority lines every chutney torrc carries.
    da = dirauthority_lines(nodes)
    for n in auths:
        d = da.get(n["nick"])
        if d is None:
            print("mkconf: warning: no DirAuthority line for %s" % n["nick"],
                  file=sys.stderr)
            continue
        if (d["v3ident"] != n["v3ident"] or d["rsa"] != n["rsa"] or
                d["dirport"] != n["dirport"] or
                not n["orport"].endswith(":" + d["orport"])):
            die("DirAuthority line for %s disagrees with its node dir: %r vs %r"
                % (n["nick"], d, {k: n[k] for k in
                                  ("v3ident", "rsa", "dirport", "orport")}))

    if a.hsdir_interval is None:
        vi = opt(auths[0]["torrc"], "V3AuthVotingInterval")
        tor_testing = opt(auths[0]["torrc"], "TestingTorNetwork", "0") == "1"
        if vi and tor_testing:
            a.hsdir_interval = int(SR_N_ROUNDS * SR_N_PHASES * float(vi) / 60)
    fallbacks = auths if a.fallbacks == "auth" else \
        [n for n in nodes if "orport" in n and "rsa" in n and "ed" in n]

    state = os.path.abspath(a.state)
    log = os.path.abspath(a.log or os.path.join(state, "arti.log"))
    L = []
    w = L.append
    w("# Generated by mkconf.py from %s" % os.path.abspath(a.nodes_dir))
    w("# Private chutney test network only. Run arti with")
    w("#   arti proxy -c <this file> --disable-fs-permission-checks")
    w("")
    w("[application]")
    w("allow_running_as_root = true   # lab containers run as root")
    w("permit_debugging = true")
    w("watch_configuration = false")
    w("")
    w("[proxy]")
    w("socks_listen = \"127.0.0.1:%d\"   # IPv4 loopback only" % a.socks_port)
    w("dns_listen = 0")
    w("")
    w("[logging]")
    w("console = %s" % q(a.console_filter))
    w("log_sensitive_information = true   # show onion addrs + relay ids")
    w("protocol_warnings = true")
    w("time_granularity = %s   # lab only: sub-second attempt timing" % q(a.time_granularity))
    w("files = [ { path = %s, filter = %s } ]" % (q(log), q(a.log_filter)))
    w("")
    w("[storage]")
    w("cache_dir = %s" % q(os.path.join(state, "cache")))
    w("state_dir = %s" % q(os.path.join(state, "state")))
    w("")
    w("[storage.permissions]")
    w("dangerously_trust_everyone = true")
    w("")
    w("[path_rules]")
    w("# Disable the same-subnet rule so loopback relays can share a path.")
    w("ipv4_subnet_family_prefix = 33")
    w("ipv6_subnet_family_prefix = 129")
    w("")
    w("[address_filter]")
    w("allow_local_addrs = true")
    w("allow_onion_addrs = true")
    w("")
    w("[circuit_timing]")
    if a.hs_desc_fetch_attempts is not None:
        w("hs_desc_fetch_attempts = %d" % a.hs_desc_fetch_attempts)
    if a.hs_intro_rend_attempts is not None:
        w("hs_intro_rend_attempts = %d" % a.hs_intro_rend_attempts)
    if a.hs_dir_requery_interval:
        w("hs_dir_requery_interval = %s" % q(a.hs_dir_requery_interval))
    w("")
    w("[override_net_params]")
    if a.hsdir_interval:
        w("# = SR rounds(12) * phases(2) * V3AuthVotingInterval / 60, as C tor")
        w("# computes it under TestingTorNetwork.")
        w("hsdir_interval = %d" % a.hsdir_interval)
    if a.cbt_min_timeout_ms:
        w("# Floor for learned circuit timeouts (lab realism, see --help).")
        w("cbtmintimeout = %d" % a.cbt_min_timeout_ms)
    for kv in a.net_param:
        k, v = kv.split("=", 1)
        w("%s = %d" % (k.strip(), int(v)))
    w("")
    w("[tor_network.authorities]")
    w("v3idents = [ %s ]" % ", ".join(q(n["v3ident"]) for n in auths))
    for kind in ("uploads", "downloads", "votes"):
        w("%s = [ %s ]" % (kind, ", ".join("[ %s ]" % q(n["dirport"])
                                          for n in auths)))
    w("")
    for n in fallbacks:
        w("[[tor_network.fallback_caches]]   # %s" % n["nick"])
        w("rsa_identity = %s" % q(n["rsa"]))
        w("ed_identity = %s" % q(n["ed"]))
        w("orports = [ %s ]" % q(n["orport"]))
        w("")
    text = "\n".join(L)
    if a.out:
        with open(a.out, "w") as f:
            f.write(text)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
