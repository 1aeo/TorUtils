# Deploy the count-only build and measure the real tor#41339 flood

**Goal:** run the patched Tor in **count-only (observe) mode** on one of your own
HSDirs so it *measures* the flood it is already receiving — with **zero
behaviour change for users** and **instant rollback**. Count-only mode never
closes a circuit and never refuses a request; it only increments two counters
you can read on a loopback MetricsPort. Pair this with the public-field-grounded
`capture-and-validate-playbook.md` (same branch) for the full rationale.

> **Safety gate — CLEARED (2026-10-14).** The crash-at-scale review
> (`patch-crash-at-scale-critique.md`, this directory) found **zero CRITICAL/HIGH
> crash, memory-safety, or unbounded-memory risks**; six crash theories were
> traced and rejected, and the **count-only observe build is green-lit for a
> production HSDir under flood**. Keep `MaxMemInQueues` at its normal value (the
> memory backstop for the 0005 change). Count-only mode does not execute the
> enforcement (circuit-close / 503) code paths at all. Still read the critique
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
real data. Your other HSDirs are untouched. The 96 h is paid once per relay for
ANY binary change, so decide up front whether the canary runs count-only (to
measure first) or enforcing (to act directly) — the lab already cleared both.

## 1. Get the patched Tor

The patch series is in `../patches/0001-*.patch … 0007-*.patch` on this branch;
it is `git am`-clean on the `tor-0.4.9.14` tag, upstream `main`, and
`maint-0.4.9`. Two deploy paths:

### Path A — the Debian/Ubuntu package (preferred, Ubuntu 24.04 / noble)
An amd64 `.deb` built from the `deb.torproject.org` noble source with the 7
patches applied (version `0.4.9.14-1~noble+1+tor41339.1`) is the clean install.
*(Being install-verified now; if it is not yet attached to this branch, use
Path B.)* Install it over the stock `deb.torproject.org` package, keep the
stock `.deb` for rollback.

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
# Expose the two counters on loopback only:
MetricsPort 127.0.0.1:9035
MetricsPortPolicy accept 127.0.0.1
# Finer heartbeat during the incident (default 6h is too coarse to see a wave):
HeartbeatPeriod 60 seconds
```
Reload (not restart, to avoid dropping circuits) onto the patched binary:
`systemctl reload tor@<instance>` or send `SIGHUP`. If you swapped the binary,
a `reload` after the swap is enough for most setups; a brief `restart` is also
fine on a single canary.

**`auto` is the safe default:** with the consensus silent on
`hsdir_one_request_per_circ` / `hsdir_refuse_unknown_prev_hop` (it is, upstream),
`auto` means *count only*. Nothing is closed, nothing is refused.

---

## 3. Verify it is observe-only (not enforcing)

```bash
curl -s http://127.0.0.1:9035/metrics | grep 'tor_relay_dos_total{type="hsdir'
# expect the two lines to be PRESENT (value may be 0 until the flood hits):
#   tor_relay_dos_total{type="hsdir_circ_reused"} N
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
echo "ts,begin_dir,bytes_written,bytes_read,circs_created,onionskins,hsdir_circ_reused,hsdir_unknown_prev_hop" > "$OUT"
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
$(get 'tor_relay_dos_total{type=\"hsdir_unknown_prev_hop\"}')" >> "$OUT"
  sleep 10
done
```
(Your existing MetricsPort capture pipeline is fine too — you just need these
keys sampled over time.) The counters are cumulative; rates are deltas between
samples. A tor restart resets them to 0 — watch for a decrease and segment.

---

## 5. Produce the two decisive ratios + shape

From the capture, compute (see the playbook §5–6 for the full mapping):
- **ρ = requests per circuit** — on the count-only build this is read directly:
  `reuse_fraction = Δ hsdir_circ_reused / Δ BEGIN_DIR`, and the multiplier the
  flood uses. (On a stock relay you only get the proxy `Δ BEGIN_DIR / Δ
  circs_created`.)
- **φ = unknown-prev-hop fraction** = `Δ hsdir_unknown_prev_hop / Δ BEGIN_DIR`.
- Volume/shape: BEGIN_DIR/s (median, p95, peak), write:read byte ratio,
  bytes/BEGIN_DIR, onionskins/s — flood window vs quiet baseline.

These decide everything: **ρ≈1 → patch 0001 can't help; φ high → 0002 is the
lever; both ≈0 → neither patch addresses this flood.** Report them honestly.

---

## 6. Rollback (instant)
Remove the two `HSDir*` torrc lines (or set them to `0`) and reload — you are
back to stock behaviour immediately. To revert the binary, copy the stock binary
back and reload. Nothing persistent was changed.

### Sandbox 1 caveat (pre-existing upstream tor#41060 — NOT these patches)
If your relay runs with `Sandbox 1` on Ubuntu 24.04 (glibc 2.39), tor's main
thread can end up ignoring `SIGTERM`/`SIGINT` after the seccomp filter installs
— a **pre-existing upstream bug (tor#41060)** that reproduces identically on
stock Tor 0.4.9.14 and is unrelated to this series (confirmed 15/15 on stock and
patched; `Sandbox 0` exits cleanly). Practical effect: `systemctl stop`/`reload`
via signals may not take, and systemd `SIGKILL`s the process at `TimeoutStopSec`.
For this observe deployment: either run the canary **without** `Sandbox 1`
(observe mode needs no sandbox), or, if you keep `Sandbox 1`, roll back with
`systemctl restart` and verify the PID actually changed. The count-only patches
add nothing to this behaviour.

## 7. Privacy
Keep the raw capture (and anything with fingerprints/IPs) operator-private.
Share back only the derived aggregates — the ratios and the shape — with no
relay fingerprints, IPs, hostnames, or onion addresses.
