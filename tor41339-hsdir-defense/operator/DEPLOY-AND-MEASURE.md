# Deploy the count-only build and measure the real tor#41339 flood

**Goal:** run the patched Tor in **count-only (observe) mode** on one of your own
HSDirs so it *measures* the flood it is already receiving, with **zero
behaviour change for users**. Count-only mode never closes a circuit and never
refuses a request; it only increments four counters you read on the relay's
MetricsPort. Pair this with the public-field-grounded
`capture-and-validate-playbook.md` (same directory) for the full rationale.

> **Safety gate — CLEARED (2026-10-14).** The crash-at-scale review
> (`patch-crash-at-scale-critique.md`, this directory) found **zero CRITICAL/HIGH
> crash, memory-safety, or unbounded-memory risks**; six crash theories were
> traced and rejected, and the **count-only observe build is green-lit for a
> production HSDir under flood**. Keep `MaxMemInQueues` at its normal value (the
> memory backstop for the 0005 change). Count-only mode does not execute the
> enforcement (circuit-close / 503) code paths at all. The later upstream-polish
> refactor (single-pass HS-request guard, cached consensus params) is
> behavior-preserving and was re-verified: targeted unit tests 113/113, full
> `dh_auto_test` in the `.deb` build, and an independent security review with no
> findings — see the addendum at the top of the critique. Still read the critique
> before deploying, and deploy to one canary first.

Everything here is on **your own relay** and is **metadata only** (no stream
content, no client IPs — those are structurally invisible on multi-hop
circuits). The examples use `CANARY` for the instance name; substitute yours.

---

## 0. Before you swap: the HSDir-flag / 96-hour cost (read first)

A binary swap is a process restart, and the HSDir flag's uptime gate uses the
relay's **self-reported** uptime (`voteflags.c` `dirserv_thinks_router_is_hs_dir`
-> `real_uptime`), which resets to ~0 on any restart. The dirauth default
`MinUptimeHidServDirectoryV2` is **96 hours**, so a swapped relay **loses the
HSDir flag for ~96 h** until it re-accumulates continuous uptime — and the flood
follows the flag, so it goes quiet on that relay meanwhile. This is unavoidable:
a fast restart doesn't help (it's the uptime reset, not the downtime), `SIGHUP`
reloads config not the binary, and the counters only exist in the new binary.
The relay KEEPS its identity/keys and long-term reputation (Stable/MTBF survive
a brief restart); only the HSDir uptime gate re-arms.

**So deploy on a CANARY:** pick ONE HSDir, keep its `DataDirectory`, and accept
~96 h (+ up to one hash-ring time period) before the flood can return and the
counters read real data. Every later restart of the canary re-arms the gate, so
restart it exactly once. Your other HSDirs are untouched **provided only the
canary's process changes** — which is why §1.1 switches one systemd instance
and never installs the package host-wide on a multi-instance host. The 96 h is
paid once per relay for ANY binary change, so decide up front whether the canary
runs count-only (to measure first) or enforcing (to act directly) — the lab
already cleared both; this runbook covers count-only.

## 1. Get the patched binary (nothing restarts yet)

The patch series is in `../patches/0001-*.patch … 0007-*.patch`; it is
`git am`-clean on the `tor-0.4.9.14` tag, upstream `main`, and `maint-0.4.9`.
Either unpack the attached package (Ubuntu 24.04 / noble, amd64) or build.

### Path A — unpack the attached `.deb` into `/opt` (preferred)

`../packages/tor_0.4.9.14-1~noble+1+tor41339.3_amd64.deb` is the
`deb.torproject.org` noble source with the 7 patches applied (provenance and
test result in `../packages/BUILD-INFO.txt`). `dpkg-deb -x` only unpacks files;
it runs no maintainer scripts, so nothing restarts:

```bash
cd tor41339-hsdir-defense/packages
sha256sum -c --ignore-missing SHA256SUMS        # the .deb line must say OK
sudo mkdir -p /opt/tor41339
sudo dpkg-deb -x tor_0.4.9.14-1~noble+1+tor41339.3_amd64.deb /opt/tor41339
/opt/tor41339/usr/bin/tor --version             # Tor version 0.4.9.14.
strings /opt/tor41339/usr/bin/tor | grep -c '^hsdir_\(circ_reused\|req_reused\|request_total\|unknown_prev_hop\)$'   # 4
```

The binary links the same libraries as stock tor on 24.04 (libevent, OpenSSL,
libsystemd, liblzma, libzstd, libseccomp); `tor-geoipdb` is unchanged data and
is not needed.

### Path B — build from source (any Ubuntu 24.04 amd64 build host)

```bash
sudo apt-get install -y build-essential automake autoconf pkg-config \
  libevent-dev liblzma-dev libscrypt-dev libseccomp-dev libssl-dev zlib1g-dev \
  libsystemd-dev libzstd-dev libcap-dev
curl -fsSLO https://dist.torproject.org/tor-0.4.9.14.tar.gz
echo "182449ac1c8ff43278da27b69b02040e11d03d0327db6d9126e4190ec6235e4a  tor-0.4.9.14.tar.gz" | sha256sum -c
tar xf tor-0.4.9.14.tar.gz && cd tor-0.4.9.14
for p in /path/to/branch/tor41339-hsdir-defense/patches/000[1-7]-*.patch; do
  patch -p1 < "$p"      # the 7 patches, in order
done
# Same feature set as the .deb. --enable-systemd matters: the units are
# Type=notify, and a build without it never signals READY, so systemd
# kills it at TimeoutStartSec.
./configure --disable-asciidoc --enable-gpl --enable-systemd --enable-zstd
make -j"$(nproc)" src/app/tor
sudo install -D -m 0755 src/app/tor /opt/tor41339/usr/bin/tor
```

Then continue with §1.1 exactly as for Path A.

### 1.1 Point ONE instance at the patched binary (any host)

On Debian/Ubuntu every relay runs as a `tor@NAME` systemd instance (a
single-instance host's relay is `tor@default`; `tor.service` is only the
multi-instance master). All instances run `/usr/bin/tor` and are
`PartOf=tor.service`. So: leave the stock package in place and override the
start command of the canary's unit only.

```bash
# 1. Nothing may restart the canary during the measurement (~11 days). A stock
#    tor upgrade's postinst restarts tor.service, and with it every instance;
#    a library upgrade (OpenSSL, libevent) can make needrestart restart it; an
#    automatic reboot restarts everything.
sudo apt-mark hold tor tor-geoipdb
echo '$nrconf{override_rc}{qr(^tor\@CANARY\.service$)} = 0;' | sudo tee /etc/needrestart/conf.d/tor41339.conf   # keep the \@
grep -rs 'Automatic-Reboot "true"' /etc/apt/apt.conf.d/   # if set, plan around it

# 2. Read the canary's EFFECTIVE start command (the LAST ExecStart= line).
systemctl cat tor@CANARY | grep '^ExecStart='
#    Stock tor@NAME:   /usr/bin/tor --defaults-torrc /run/tor-instances/%i.defaults -f /etc/tor/instances/%i/torrc
#    Stock tor@default: /usr/bin/tor --defaults-torrc /usr/share/tor/tor-service-defaults-torrc -f /etc/tor/torrc --RunAsDaemon 0
#    If an override.conf already changes it, copy THAT line instead.

# 3. Write a drop-in that repeats that line verbatim with only the binary path
#    changed (shown: the stock tor@NAME line). "zz-" sorts after any existing
#    override.conf, so it wins.
sudo mkdir -p /etc/systemd/system/tor@CANARY.service.d
sudo tee /etc/systemd/system/tor@CANARY.service.d/zz-tor41339.conf >/dev/null <<'EOF'
[Service]
ExecStart=
ExecStart=/opt/tor41339/usr/bin/tor --defaults-torrc /run/tor-instances/%i.defaults -f /etc/tor/instances/%i/torrc
EOF
sudo systemctl daemon-reload
systemctl cat tor@CANARY | grep '^ExecStart=' | tail -1   # must start with /opt/tor41339/

# 4. Validate the canary's config with the patched binary, as root, exactly as
#    the unit's own ExecStartPre does (/run/tor-instances/CANARY.defaults exists
#    while the instance is running). Must print "Configuration was valid".
sudo /opt/tor41339/usr/bin/tor --defaults-torrc /run/tor-instances/CANARY.defaults \
  -f /etc/tor/instances/CANARY/torrc --verify-config

# 5. Restart ONLY the canary. This is the one restart that costs the ~96 h.
date -u +%FT%TZ                                   # record T0
OLD=$(systemctl show -p MainPID --value tor@CANARY)
sudo systemctl restart tor@CANARY
NEW=$(systemctl show -p MainPID --value tor@CANARY)
echo "$OLD -> $NEW"                               # must differ
sudo readlink /proc/$NEW/exe                      # /opt/tor41339/usr/bin/tor
```

- Leave the two `HSDir*` options **out** of the canary's torrc. They default to
  `auto` (count-only) in the patched binary, and the unit's stock
  `ExecStartPre=/usr/bin/tor … --verify-config` still runs the stock binary,
  which rejects options it does not know — the next start would fail.
- Nothing else in the unit changes: same user (`_tor-NAME`), DataDirectory,
  keys, sandboxing and `Restart=` policy.
- If your units set `AppArmorProfile=system_tor` (the stock `tor@.service` does
  not), add `/opt/tor41339/usr/bin/tor mr,` to `/etc/apparmor.d/local/system_tor`
  and reload that profile first.
- The restart takes ~30 s (a relay's graceful `ShutdownWaitLength`). Under
  `Sandbox 1` it can take the full `TimeoutStopSec` (60 s) before systemd kills
  the old process — the pre-existing tor#41060, see §6. That is why step 5
  checks that the PID changed.
- `Restart=on-failure` stays in force: if tor ever exits abnormally, systemd
  restarts it, which re-arms the 96 h gate. Watch for that (§4.1 `resets()`).

### 1.2 Alternative for a single-instance host only: install the package

On a host whose **only** relay is `tor@default`, installing the package is also
fine, but its postinst restarts tor immediately, so validate first:

```bash
sudo /opt/tor41339/usr/bin/tor --defaults-torrc /usr/share/tor/tor-service-defaults-torrc \
  -f /etc/tor/torrc --verify-config                    # Path A unpack, then this
mkdir -p ~/tor41339-rollback && cd ~/tor41339-rollback
apt-get download tor=$(dpkg-query -W -f='${Version}' tor)   # keep the stock .deb (must succeed)
sudo dpkg -i /path/to/tor_0.4.9.14-1~noble+1+tor41339.3_amd64.deb   # restarts tor: T0
sudo apt-mark hold tor tor-geoipdb
```

Never do this on a host with more than one `tor@NAME` instance.

---

## 2. Configure count-only (observe) mode

**There is nothing to add.** Both options are `AUTOBOOL` with default `auto`,
and `auto` with the consensus silent on `hsdir_one_request_per_circ` /
`hsdir_refuse_unknown_prev_hop` (it is: no directory authority votes these
unmerged parameters) means *count only*. Nothing is closed, nothing is refused.

Keep the canary's existing `MetricsPort` / `MetricsPortPolicy` (the one your
Prometheus already scrapes). Optional: a finer DoS heartbeat in the log —
`HeartbeatPeriod 30 minutes` (30 min is tor's minimum; smaller values are raised
to it with a warning; the default is 6 hours, and the first heartbeat after a
start is skipped). Make any torrc edit **before** the §1.1 restart, so it costs
no extra restart.

**Activating the binary needs a restart; nothing after that does.** A
`reload`/`SIGHUP` only re-reads `torrc` — it does **not** load a new binary. Once
the patched binary is running, the enforcement options are read per request, so
enforcement on/off later is a live `SETCONF` with no further restart (§8).

---

## 3. Verify it is running count-only

```bash
# torrc: /etc/tor/instances/CANARY/torrc (/etc/tor/torrc for tor@default)
MP=$(awk 'tolower($1)=="metricsport"{print $2; exit}' /etc/tor/instances/CANARY/torrc)
curl -s "http://$MP/metrics" | grep 'tor_relay_dos_total{type="hsdir'
# expect exactly four lines (values may be 0 until the relay is an HSDir again):
#   tor_relay_dos_total{type="hsdir_circ_reused"} N
#   tor_relay_dos_total{type="hsdir_req_reused"} N
#   tor_relay_dos_total{type="hsdir_request_total"} N
#   tor_relay_dos_total{type="hsdir_unknown_prev_hop"} N
```

Confirm **no enforcement** from configuration, not from logs (the enforcement
log lines are `LOG_PROTOCOL_WARN`, invisible at `notice`):

```bash
D=/var/lib/tor-instances/CANARY          # DataDirectory (/var/lib/tor for tor@default)
# a) torrc: no HSDir* lines (expect no output)
grep -Ei '^[[:space:]]*HSDir(OneRequestPerCircuit|RefuseUnknownPrevHop)' /etc/tor/instances/CANARY/torrc
# b) consensus: neither parameter set (expect no output)
sudo grep -h -m1 '^params ' $D/cached-consensus $D/cached-microdesc-consensus 2>/dev/null \
  | grep -Eo 'hsdir_(one_request_per_circ|refuse_unknown_prev_hop)=[0-9]+'
```

If (a) or (b) prints a value of `1`, enforcement is on: switch it off live on
the canary's ControlPort with `SETCONF HSDirOneRequestPerCircuit=0
HSDirRefuseUnknownPrevHop=0` (`0` = never enforce, regardless of consensus;
`auto` would follow the consensus) and report it. Remove any torrc line; don't
add one (§1.1). `SETCONF` lasts until the next reload or restart.

A dependency-free control-port helper (Debian's per-instance defaults enable
cookie auth at `/run/tor-instances/NAME/control.authcookie`, alongside any
`HashedControlPassword`; set `CP` to the canary's `ControlPort`):

```bash
CP=PORT; CK=/run/tor-instances/CANARY/control.authcookie
ctl(){ exec 3<>/dev/tcp/127.0.0.1/$CP
       printf 'AUTHENTICATE %s\r\n%s\r\nQUIT\r\n' "$(sudo od -An -tx1 -v $CK | tr -d ' \n')" "$1" >&3
       cat <&3; exec 3<&-; }
ctl "GETCONF HSDirOneRequestPerCircuit HSDirRefuseUnknownPrevHop"   # both =auto
```

Is the canary an HSDir again? Read its flags from its own cached consensus (no
control port needed; prints nothing while it is not in the consensus):

```bash
FP=$(sudo awk '{print $2}' $D/fingerprint)
ID=$(python3 -c 'import sys,base64;print(base64.b64encode(bytes.fromhex(sys.argv[1])).decode().rstrip("="))' "$FP")
sudo awk -v id="$ID" '$1=="r"{f=($3==id)} f&&$1=="s"{print; exit}' $D/cached-microdesc-consensus
# e.g. "s Fast Guard HSDir Running Stable V2Dir Valid" -> HSDir is back
```

At the first DoS heartbeat (one `HeartbeatPeriod` after the restart), the
`DoS mitigation since startup:` line also contains
`… circuits with repeated HSDir requests, … HSDir requests with an unknown
previous hop`.

---

## 4. Capture over a flood window

### 4.1 Prometheus (preferred if you already run it)

tor's `MetricsPort` serves Prometheus exposition format at `/metrics`, so if you
already scrape the canary you need **no new job**: the four series are new
`type` values of the existing `tor_relay_dos_total` counter. Check that nothing
drops them:

```promql
count(tor_relay_dos_total{type=~"hsdir_.*", <your canary selector>})   # 4
```

If you have no scrape yet, keep the MetricsPort on loopback and reach it over
SSH (a tunnel, or Prometheus on the relay host); never expose it publicly and
never `MetricsPortPolicy accept *`. A 10–15 s scrape interval resolves the
flood waves; keep relay fingerprints, IPs and nicknames out of labels.
Retention must cover the canary's whole measurement (~4 days to the flag plus up
to a week of waiting: Prometheus' 15-day default is enough), or export each
window before it ages out.

Useful queries (every series here is a counter; `ignoring(type)` is needed
because the two sides carry different `type` labels):

```promql
rate(tor_relay_streams_total{type="BEGIN_DIR"}[5m])              # BEGIN_DIR/s (flood indicator)
rate(tor_relay_dos_total{type="hsdir_request_total"}[5m])        # HS dir requests/s
# r_hs: share of HS requests that rode an already-used circuit (patch 0002's target)
  rate(tor_relay_dos_total{type="hsdir_req_reused"}[5m])
/ ignoring(type) rate(tor_relay_dos_total{type="hsdir_request_total"}[5m])
# phi: share of HS requests from an unknown previous hop (patch 0001's target)
  rate(tor_relay_dos_total{type="hsdir_unknown_prev_hop"}[5m])
/ ignoring(type) rate(tor_relay_dos_total{type="hsdir_request_total"}[5m])
# hs_share: share of BEGIN_DIR streams that were HS dir requests
  rate(tor_relay_dos_total{type="hsdir_request_total"}[5m])
/ ignoring(type) rate(tor_relay_streams_total{type="BEGIN_DIR"}[5m])
# restarts inside a window (any value > 0 = the relay restarted)
resets(tor_relay_traffic_bytes{direction="read"}[1h])
```

`rate()`/`increase()` silently stitch across a counter reset, so always check
`resets()` for a window before trusting its numbers.

### 4.2 Without Prometheus

Sample the loopback MetricsPort into an operator-private file:

```bash
sudo install -d -m 0700 /var/operator-private
MP=127.0.0.1:PORT        # the canary's MetricsPort
while true; do
  printf '%s ' "$(date -u +%s)"
  curl -s "http://$MP/metrics" | grep -E 'tor_relay_(streams_total\{type="BEGIN_DIR"|traffic_bytes|load_onionskins_total\{type="ntor_v3"|congestion_control_total\{state="cc_circuits",action="circs_created"|dos_total\{type="hsdir_)' | tr '\n' ' '
  echo
  sleep 10
done | sudo tee -a /var/operator-private/41339-capture.log >/dev/null
```

The counters are cumulative; rates are deltas between samples. A decrease means
the relay restarted — segment there.

---

## 5. Produce the decisive ratios + shape

Over a window `W` (a quiet baseline after the flag returns, and the flood's
peak hour), take the counter increases: `B` = BEGIN_DIR streams, `C` =
`circs_created`, `T` = `hsdir_request_total`, `R` = `hsdir_req_reused`, `K` =
`hsdir_circ_reused`, `U` = `hsdir_unknown_prev_hop`. Then:

- **`r_hs = R / T`** — share of HS requests that arrived on a circuit that had
  already carried one: exactly what patch 0002 would refuse.
  **`rho_hs = T / (T − R)`** — HS requests per HS circuit (`T − R` circuits
  carried at least one HS request). **`K / (T − R)`** — share of those circuits
  that carried two or more.
- **`phi = U / T`** — share of HS requests whose previous hop is not a known
  relay: what patch 0001 would refuse (as 503s).
- **`hs_share = T / B`** — how much of the BEGIN_DIR load is HS descriptor
  traffic at all.
- Volume/shape: BEGIN_DIR/s and HS requests/s (median, p95, peak),
  write:read bytes, bytes per BEGIN_DIR, ntor_v3 onionskins processed/dropped
  per second — flood window vs baseline. **`rho = B / C`** is a whole-relay
  streams-per-circuit proxy only (relay A measured ≈5.69 in the earlier
  capture).

Caveats: a window cuts circuits at its edges, so `rho_hs` and `K / (T − R)` are
approximate (use ≥1 h windows); `C` counts only congestion-control circuits and
`B`, the byte counters and onionskins are whole-relay, not directory-only.

These decide everything: **`r_hs` ≈ 0 → patch 0002 has nothing to refuse;
`phi` high → 0001 is the lever; both ≈ 0 → neither patch addresses this
flood.** Report them honestly (playbook §6.1 gates A/B).

---

## 6. Rollback

Count-only changes no behaviour, so there is nothing to switch off. To return
the canary to the stock binary (another restart, so another ~96 h without the
flag):

- **§1.1 drop-in:**
  `sudo rm /etc/systemd/system/tor@CANARY.service.d/zz-tor41339.conf && sudo systemctl daemon-reload && sudo systemctl restart tor@CANARY`,
  check the PID changed and `readlink /proc/<pid>/exe` is `/usr/bin/tor`, then
  `sudo apt-mark unhold tor tor-geoipdb && sudo rm -f /etc/needrestart/conf.d/tor41339.conf`.
- **§1.2 package:**
  `sudo apt-mark unhold tor tor-geoipdb && sudo dpkg -i ~/tor41339-rollback/tor_*.deb`
  (its postinst restarts tor; `dpkg` accepts the downgrade).

A `reload` never changes the running binary.

### Sandbox 1 caveat (pre-existing upstream tor#41060 — NOT these patches)

If your relay runs with `Sandbox 1` on Ubuntu 24.04 (glibc 2.39), tor's main
thread can end up ignoring `SIGTERM`/`SIGINT` after the seccomp filter installs
— a **pre-existing upstream bug (tor#41060)** that reproduces identically on
stock Tor 0.4.9.14 and is unrelated to this series (confirmed 15/15 on stock and
patched; `Sandbox 0` exits cleanly; in the two `+tor41339.3` install runs, on a
current Ubuntu 24.04.5 container, tor did exit, so it is environment-dependent).
Practical effect: `systemctl stop`/`restart` may wait for `TimeoutStopSec`
before systemd `SIGKILL`s the process. It still restarts — confirm the PID
changed. The count-only patches add nothing to this behaviour.

## 7. Privacy

Keep the raw capture (and anything with fingerprints/IPs) operator-private.
Share back only the derived aggregates — the ratios and the shape — with no
relay fingerprints, IPs, hostnames, nicknames, Prometheus labels or onion
addresses.

## 8. Enforcement is a LIVE toggle; logging is counter-based (constant volume)

**The 96 h is paid once, for the binary swap only.** Turning enforcement on/off
afterward reads the option at request time, so it flips on the *running*
process with no restart, no uptime reset, and no HSDir-flag loss:
`SETCONF HSDirOneRequestPerCircuit=1` / `HSDirRefuseUnknownPrevHop=1` on the
canary's ControlPort (and `=0` to flip back). `SETCONF` lasts until the next
reload or restart. Making it persistent in the torrc of a §1.1 canary also needs
the drop-in to override the unit's stock `ExecStartPre` verify line (stock tor
rejects the option), so treat that as part of the later enforcement decision.
Reload one instance with `systemctl reload tor@CANARY`; `systemctl reload tor`
reloads every instance on the host. This enables the reactive model: run
**count-only** as the baseline, let the counters detect an active flood, flip
enforcement **on** for its duration, then **off** when it subsides. (Verified: a
`SETCONF` toggle flips the 0001 503 live.)

**Logging volume does NOT scale with the flood** — the patches measure with
counters, not per-request logs. Read the MetricsPort counters and the one-line
DoS heartbeat; do NOT enable per-request logging. CPU per HS request is at most
four `uint64` increments plus one known-relay lookup; the enforcement check
reads the option or a consensus value cached in `set_dos_parameters()`, so it is
O(1). RAM is O(1): four global counters and a 2-bit field on the existing
`or_circuit_t`. Storage is just your scrape samples (<1 MB/day/relay at 10 s).
Keep the log level at `notice` (info/debug WOULD explode under a flood) and
`SafeLogging` on.

The log lines the series adds or changes, all rate-limited to one per 10
minutes each:
- 0003: "Oversized or malformed directory request from … Closing." —
  `LOG_WARN`, so **visible at `notice` in count-only mode**. It replaces stock
  tor's unthrottled warnings for the same requests, so a flood that sends
  malformed HTTP now logs one line per 10 minutes instead of one per request.
- 0001/0002: "Refusing HS directory request from unknown previous hop …" and
  "Closing circuit after repeated HS directory request …" — only when
  enforcing, and `LOG_PROTOCOL_WARN` (info level unless `ProtocolWarnings 1`,
  so silent at `notice`).

A 1 req/s relay and a 1000 req/s relay log the same volume.
