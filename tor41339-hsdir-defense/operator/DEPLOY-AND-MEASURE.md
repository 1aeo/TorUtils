# Deploy the count-only build and measure the real tor#41339 flood

**Goal:** run the patched Tor in **count-only (observe) mode** on one of your own
HSDirs so it *measures* the flood it is already receiving — with **zero
behaviour change for users** and **instant rollback**. Count-only mode never
closes a circuit and never refuses a request; it only increments count-only counters
you can read on a loopback MetricsPort. Pair this with the public-field-grounded
`capture-and-validate-playbook.md` (same branch) for the full rationale.

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


Everything here is on **your own relay**, is **metadata only** (no stream
content, no client IPs — those are structurally invisible on multi-hop
circuits), and is **reversible in seconds**.

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

**So deploy on a CANARY:** pick ONE HSDir (ideally one not currently in the
flood's rotating hit-set), keep its `DataDirectory`, and accept ~96 h (+ up to
one hashring time-period cycle) before the flood returns and the counters read
real data. Your other HSDirs are untouched **provided only the canary's binary
changes** — on a multi-instance host use §1.1, because installing the package
restarts every instance on that host. The 96 h is paid once per relay for
ANY binary change, so decide up front whether the canary runs count-only (to
measure first) or enforcing (to act directly) — the lab already cleared both.

## 1. Get the patched Tor

The patch series is in `../patches/0001-*.patch … 0007-*.patch` on this branch;
it is `git am`-clean on the `tor-0.4.9.14` tag, upstream `main`, and
`maint-0.4.9`. Two deploy paths:

### Path A — the Debian/Ubuntu package (preferred, Ubuntu 24.04 / noble)
An amd64 `.deb` built from the `deb.torproject.org` noble source with the 7
patches applied (version `0.4.9.14-1~noble+1+tor41339.3`, built from the
current series and exposing all four `hsdir_*` counters) is the clean install.
*(The built `.deb` is attached in `../packages/`.)* Install just the `tor`
package over the stock `deb.torproject.org` one (`tor-geoipdb` is optional,
unchanged data) and keep the stock `.deb` for rollback.

### Path B — build from source (always available)
On a build host matching the relay (Ubuntu 24.04):
```bash
apt-get install -y build-essential automake autoconf pkg-config git \
  libevent-dev liblzma-dev libscrypt-dev libseccomp-dev libssl-dev \
  zlib1g-dev libnss3-dev
# tor 0.4.9.14 source, verified:
curl -fsSLO https://dist.torproject.org/tor-0.4.9.14.tar.gz
echo "182449ac1c8ff43278da27b69b02040e11d03d0327db6d9126e4190ec6235e4a  tor-0.4.9.14.tar.gz" | sha256sum -c
tar xf tor-0.4.9.14.tar.gz && cd tor-0.4.9.14
for p in /path/to/branch/patches/0001-*.patch /path/to/branch/patches/000[2-7]-*.patch; do
  patch -p1 < "$p"        # apply the 7 patches in order
done
./configure --disable-asciidoc --enable-nss   # match the deb's crypto backend
make -j"$(nproc)" src/app/tor
./src/app/tor --version    # expect 0.4.9.14 with your local git tag
```
Keep the **stock binary backed up** (`cp $(command -v tor) /root/tor.stock`) so
rollback is a single copy-back + reload.

### 1.1 Multi-instance hosts (`tor-instance-create`, `tor@NAME`) — switch ONE instance

Every `tor@NAME` instance on a host runs `/usr/bin/tor` and is
`PartOf=tor.service`. Installing the `.deb` replaces `/usr/bin/tor`, and its
postinst restarts `tor.service`, which restarts **every** instance — each one
then loses its HSDir flag for ~96 h. To canary a single relay, leave the stock
package in place and point only that instance at the patched binary:

```bash
# 1. Unpack the patched binary beside stock (nothing else changes).
sudo mkdir -p /opt/tor41339
sudo dpkg-deb -x tor_0.4.9.14-1~noble+1+tor41339.3_amd64.deb /opt/tor41339
/opt/tor41339/usr/bin/tor --version

# 2. Freeze the stock package for the whole measurement: a stock tor upgrade
#    restarts tor.service, and with it every instance (the canary included).
sudo apt-mark hold tor tor-geoipdb

# 3. Point ONLY the canary at the patched binary. Copy the ExecStart line from
#    your existing /etc/systemd/system/tor@CANARY.service.d/override.conf and
#    change only the binary path (the line below is what
#    relay-setup/create-relays.sh writes). The new file sorts after
#    override.conf, so it wins.
sudo tee /etc/systemd/system/tor@CANARY.service.d/zz-tor41339.conf >/dev/null <<'EOF'
[Service]
ExecStart=
ExecStart=/opt/tor41339/usr/bin/tor --defaults-torrc /usr/share/tor/tor-service-defaults-torrc -f /etc/tor/instances/CANARY/torrc
EOF
sudo systemctl daemon-reload
systemctl cat tor@CANARY | grep '^ExecStart='   # last line must be /opt/tor41339/...

# 4. Validate with the patched binary, then restart ONLY the canary.
#    This is the one restart that costs the ~96 h HSDir gate.
sudo -u _tor-CANARY /opt/tor41339/usr/bin/tor --defaults-torrc /usr/share/tor/tor-service-defaults-torrc -f /etc/tor/instances/CANARY/torrc --verify-config
sudo systemctl restart tor@CANARY
sudo readlink /proc/$(systemctl show -p MainPID --value tor@CANARY)/exe   # -> /opt/tor41339/usr/bin/tor
```

- Leave the two `HSDir*` options **out** of this instance's torrc. They already
  default to `auto` (count-only) in the patched binary, and the stock
  `ExecStartPre=… --verify-config` still runs `/usr/bin/tor`, which would reject
  options it does not know.
- If your units set `AppArmorProfile=system_tor` (the stock `tor@.service` does
  not), add `/opt/tor41339/usr/bin/tor mr,` to `/etc/apparmor.d/local/system_tor`
  and reload that profile first.
- Rollback: `sudo rm /etc/systemd/system/tor@CANARY.service.d/zz-tor41339.conf &&
  sudo systemctl daemon-reload && sudo systemctl restart tor@CANARY`, then
  `sudo apt-mark unhold tor tor-geoipdb`.
- Single-instance host: install the `tor` package (Path A) and
  `sudo apt-mark hold tor` for the measurement period.

**Validate the binary before production:** `tor --verify-config -f <your torrc>`,
then run it on a **canary** (one relay, or a throwaway instance) first — not the
whole fleet.

---

## 2. Configure count-only (observe) mode

Add to the relay's `torrc` (these are the only additions):
```
# --- tor#41339 observe-only: COUNT the flood, change nothing ---
# Both options are AUTOBOOL and default to "auto"; auto + no consensus opinion
# = count-only. Stated explicitly here so there is no ambiguity:
HSDirOneRequestPerCircuit auto
HSDirRefuseUnknownPrevHop auto
# Expose the counters on loopback only:
MetricsPort 127.0.0.1:9035
MetricsPortPolicy accept 127.0.0.1
# Finer heartbeat during the incident (default 6h is too coarse to see a wave):
HeartbeatPeriod 60 seconds
```
On a §1.1 per-instance canary, drop the two `HSDir*` lines (they already
default to `auto`) and keep whatever `MetricsPort` your instance already
exposes to Prometheus.
**Activate the patched binary with a restart.** A `reload`/`SIGHUP` only
re-reads `torrc` — it does **not** load a new on-disk binary, so the process must
re-exec to run patched code: `systemctl restart tor@<instance>`. This is the one
restart that incurs the 96 h HSDir-flag reset (§0); do it once, on the canary.
(Installing the `.deb` does this for you — its postinst restarts tor.) Dropping a
few circuits on a single restart is expected. **After** the patched binary is
running, the two enforcement torrc options are read per request, so flipping
enforcement on/off later is a live `reload`/`SETCONF` with **no** further restart
(§8).

**`auto` is the safe default:** with the consensus silent on
`hsdir_one_request_per_circ` / `hsdir_refuse_unknown_prev_hop` (it is, upstream),
`auto` means *count only*. Nothing is closed, nothing is refused.

---

## 3. Verify it is observe-only (not enforcing)

```bash
curl -s http://127.0.0.1:9035/metrics | grep 'tor_relay_dos_total{type="hsdir'
# expect the four lines to be PRESENT (value may be 0 until the flood hits):
#   tor_relay_dos_total{type="hsdir_circ_reused"} N
#   tor_relay_dos_total{type="hsdir_req_reused"} N
#   tor_relay_dos_total{type="hsdir_request_total"} N
#   tor_relay_dos_total{type="hsdir_unknown_prev_hop"} N
```
Confirm **no enforcement**: the relay log shows **no** `RESOURCELIMIT` circuit
closes attributable to these options and **no** new HS-dir 503s; legitimate
fetches/uploads succeed exactly as before. If you see either, an override is set
— make sure the two torrc lines read `auto` (or `0`) and reload.

---

## 4. Capture over a flood window

Scrape the loopback MetricsPort every 10 s across a window that spans the flood,
plus a quiet baseline window. A minimal loop (run on the relay host):
```bash
OUT=/root/tor41339-capture.csv
echo "ts,begin_dir,bytes_written,bytes_read,circs_created,onionskins,hsdir_circ_reused,hsdir_req_reused,hsdir_request_total,hsdir_unknown_prev_hop" > "$OUT"
while true; do
  m=$(curl -s http://127.0.0.1:9035/metrics)
  get(){ printf '%s\n' "$m" | sed -n "s/.*$1[^ ]* \\([0-9]\\+\\).*/\\1/p" | head -1; }
  echo "$(date +%s),\
$(get 'tor_relay_streams_total{type=\"BEGIN_DIR\"}'),\
$(get 'tor_relay_traffic_bytes{direction=\"written\"}'),\
$(get 'tor_relay_traffic_bytes{direction=\"read\"}'),\
$(get 'tor_relay_congestion_control_total{state=\"cc_circuits\",action=\"circs_created\"}'),\
$(get 'tor_relay_load_onionskins_total{type=\"ntor_v3\",action=\"processed\"}'),\
$(get 'tor_relay_dos_total{type=\"hsdir_circ_reused\"}'),\
$(get 'tor_relay_dos_total{type=\"hsdir_req_reused\"}'),\
$(get 'tor_relay_dos_total{type=\"hsdir_request_total\"}'),\
$(get 'tor_relay_dos_total{type=\"hsdir_unknown_prev_hop\"}')" >> "$OUT"
  sleep 10
done
```
(Your existing MetricsPort capture pipeline is fine too — you just need these
keys sampled over time.) The counters are cumulative; rates are deltas between
samples. A tor restart resets them to 0 — watch for a decrease and segment.

### 4.1 Prometheus (preferred if you already run it)

tor's `MetricsPort` already serves Prometheus exposition format at
`/metrics`, so Prometheus scrapes it directly — no exporter needed. The one
catch is that the port is **loopback-only** (`accept 127.0.0.1`), so decide how
Prometheus reaches it, cheapest-and-safest first:

1. **Prometheus on the relay host** (simplest for a single canary): scrape
   `127.0.0.1:9035`, nothing else to open.
2. **Prometheus on another host:** do **not** expose 9035 to the internet.
   Either tunnel it (`ssh -N -L 9035:127.0.0.1:9035 relay-host`, scrape
   `127.0.0.1:9035` on the Prometheus side), or bind the MetricsPort to a
   private/VPN interface (`MetricsPort <priv-ip>:9035` +
   `MetricsPortPolicy accept <prometheus-ip>` + a host firewall rule limiting
   9035 to that IP). Never `accept *`.

Scrape config (counters are monotonic — rate them in PromQL, don't log per
request):
```yaml
scrape_configs:
  - job_name: tor-hsdir-canary
    scrape_interval: 10s
    static_configs:
      - targets: ['127.0.0.1:9035']
        labels: { role: hsdir-canary }   # no fingerprint / IP / nickname in labels
```
Useful queries (all `tor_relay_dos_total` series are counters):
```promql
rate(tor_relay_streams_total{type="BEGIN_DIR"}[1m])          # flood rate
rate(tor_relay_dos_total{type="hsdir_request_total"}[5m])     # total HS requests/s
# HS-only repeat-request fraction r_hs (needs the current-series build):
  rate(tor_relay_dos_total{type="hsdir_req_reused"}[5m])
/ rate(tor_relay_dos_total{type="hsdir_request_total"}[5m])
# unknown-prev-hop fraction phi (exact HS-only denominator):
  rate(tor_relay_dos_total{type="hsdir_unknown_prev_hop"}[5m])
/ rate(tor_relay_dos_total{type="hsdir_request_total"}[5m])
```
Confidentiality: keep relay fingerprint/IP/nickname out of Prometheus labels and
out of any dashboard you share — role labels only.

---

## 5. Produce the two decisive ratios + shape

From the capture, compute (see the playbook §5–6 for the full mapping):
- **ρ = whole-relay requests-per-circuit multiplier** =
  `Δ BEGIN_DIR / Δ circs_created` on BOTH stock and the count-only build
  (relay A measured ≈5.69 during the flood; because `circs_created` includes
  non-directory circuits, `ρ` need not be ≥1 in general and acts as a proxy
  when HS-dir flood traffic dominates). On the count-only build, use the exact
  **HS-only repeat-request fraction**
  `r_hs = Δ hsdir_req_reused / Δ hsdir_request_total` (every repeat HS request
  on a circuit divided by total anonymous HS requests) alongside
  `Δ hsdir_circ_reused` (circuits that carried ≥2 HS-dir requests, incremented
  once per reused circuit). In observe mode over a steady window where
  pre-existing circuits are negligible,
  `Δ hs_circs = Δ hsdir_request_total − Δ hsdir_req_reused` circuits carry at
  least one HS request and the HS-only multiplier is
  $\rho_{\text{hs}} = \Delta\text{hsdir\_request\_total} / \Delta\text{hs\_circs} = 1 / (1 - r_{\text{hs}})$.
- **φ = unknown-prev-hop fraction** = `Δ hsdir_unknown_prev_hop / Δ hsdir_request_total`
  against the exact HS-only denominator `Δ hsdir_request_total` (or
  `Δ hsdir_unknown_prev_hop / Δ BEGIN_DIR` as a lower-bound proxy when comparing
  against total directory streams).
- Volume/shape: BEGIN_DIR/s (median, p95, peak), write:read byte ratio,
  bytes/BEGIN_DIR, onionskins/s — flood window vs quiet baseline.

These decide everything: **`r_hs = Δ hsdir_req_reused / Δ hsdir_request_total ≈ 0`
(`ρ≈1` when flood traffic dominates) → patch 0002 can't help; φ high → 0001 is
the lever; both ≈0 → neither patch addresses this flood.** Report them honestly.

---

## 6. Rollback (instant)
On a §1.1 per-instance canary, remove the `zz-tor41339.conf` drop-in as shown
there. Otherwise: remove the two `HSDir*` torrc lines (or set them to `0`) and reload — you are
back to stock behaviour immediately. To revert the binary, copy the stock binary
back and reload. Nothing persistent was changed.

### Sandbox 1 caveat (pre-existing upstream tor#41060 — NOT these patches)
If your relay runs with `Sandbox 1` on Ubuntu 24.04 (glibc 2.39), tor's main
thread can end up ignoring `SIGTERM`/`SIGINT` after the seccomp filter installs
— a **pre-existing upstream bug (tor#41060)** that reproduces identically on
stock Tor 0.4.9.14 and is unrelated to this series (confirmed 15/15 on stock and
patched; `Sandbox 0` exits cleanly; in the two `+tor41339.3` install runs, on a
current Ubuntu 24.04.5 container, tor did exit, so it is environment-dependent).
Practical effect: `systemctl stop`/`reload`
via signals may not take, and systemd `SIGKILL`s the process at `TimeoutStopSec`.
For this observe deployment: either run the canary **without** `Sandbox 1`
(observe mode needs no sandbox), or, if you keep `Sandbox 1`, roll back with
`systemctl restart` and verify the PID actually changed. The count-only patches
add nothing to this behaviour.

## 7. Privacy
Keep the raw capture (and anything with fingerprints/IPs) operator-private.
Share back only the derived aggregates — the ratios and the shape — with no
relay fingerprints, IPs, hostnames, or onion addresses.

## 8. Enforcement is a LIVE toggle; logging is counter-based (constant volume)
**The 96 h is paid once, for the binary swap only.** Turning enforcement on/off
afterward is a torrc AUTOBOOL read at request time, so it flips on the *running*
process with no restart, no uptime reset, and no HSDir-flag loss:
- live, non-persistent (reactive): `SETCONF HSDirOneRequestPerCircuit=1` /
  `HSDirRefuseUnknownPrevHop=1` over the control port (and `=0` to flip back);
- persistent: edit the torrc values and `systemctl reload tor` (SIGHUP).
This enables the reactive model: run **count-only** as the baseline, let the
counters/heartbeat detect an active flood, flip enforcement **on** for its
duration, then **off** when it subsides. (Verified: a SETCONF toggle flips the
0001 503 live.)

**Logging volume does NOT scale with the flood** — the patch measures with
counters, not per-request logs. Read the MetricsPort counters + the one-line
DoS heartbeat; do NOT enable per-request logging. CPU per HS request is at
most four uint64 increments plus one known-relay lookup; the enforcement
check reads the torrc option or a consensus value cached in
`set_dos_parameters()`, so it is O(1). RAM is O(1): four global counters and a
2-bit field on the existing `or_circuit_t`. Storage is just your scrape samples
(<1 MB/day/relay at 10 s). Keep the log level at `notice` (info/debug WOULD
explode under a flood) and `SafeLogging` on. Patch 0003 rate-limits the
malformed-HTTP warnings, and the only new log lines — "Refusing HS directory
request from unknown previous hop …" and "Closing circuit after repeated HS
directory request …" — fire only when enforcing, are `LOG_PROTOCOL_WARN`
(info-level unless you set `ProtocolWarnings 1`, so silent at `notice`), and
are rate-limited to one per 10 minutes each. A 1 req/s relay and a 1000 req/s
relay log the same volume.
