# Arti onion-service client for the private chutney lab

Every tor and arti process here runs inside a `docker run --network none`
container (loopback only, own directory authorities). Nothing contacts the
public Tor network. `<work>` stands for the local working directory the build and runs used.

## Binary

| | |
|---|---|
| Source | `https://gitlab.torproject.org/tpo/core/arti.git`, shallow clone of tag **arti-v2.7.0** |
| Commit | `ce8bc6e0998bd5a4efdf06dd62dce53c98ea1087` (2026-10-01) |
| Build | `cargo build --locked --release -p arti --features onion-service-client -j3` (rustc/cargo 1.97.0, 6m51s) |
| Features | the crate defaults: default-runtime (tokio + native-tls), dns-proxy, harden, compression, bridge-client, pt-client, **onion-service-client**, vanguards, flowctl-cc. `onion-service-client` is already a default; it is named explicitly only for clarity. No feature gates custom networks: `[tor_network]` and `[override_net_params]` are in the default config schema. |
| Output | `<work>/arti-build/bin/arti`, 14,854,152 bytes |
| sha256 | `b2867768f9c9da3b3eaff04ad2c0c584c54201d12b53f215d4dfe6909871a11b` |
| `--version` | `Arti 2.7.0` / `using runtime: TokioNativeTlsRuntime { .. }` / `optional features: <none>` (that list only ever names journald/static-*) |
| Shared libs | libsqlite3.so.0, libssl.so.3, libcrypto.so.3, libc; all present in the 24.04 and 26.04 lab images (`--version` checked in both) |

`target/` and the extracted crate sources were deleted after the copy.
To rebuild: `CARGO_HOME=<work>/arti-build/cargo-home` plus the same command in
`<work>/arti-build/arti`.

## Files

- `mkconf.py NODES_DIR --state DIR --socks-port N [...]` writes an arti.toml
  for a chutney net, using only the node dirs (see "Config keys"). Its
  authorities, fallbacks and `hsdir_interval` match the `nodes/arti.toml`
  that chutney writes itself (checked with tomllib).
- `in-lab-arti.sh` runs in the container. It starts the chutney net the same
  way as the live-controls lab (`--net hsflood41339`, phase 1 then phase 2),
  serves `clientlab-ok` over HTTP on 127.0.0.1:4747, starts Arti and runs
  `arti_probe.py`.
- `run-arti-lab.sh` is the host driver (`docker run --rm --network none ...`).
- `arti_probe.py` runs these experiments: `proof`, `isolation`,
  `retry-partial`, `retry-all`, `retry-sameiso` and `prober`. It also has
  an importable `ArtiProber` thread (a fresh SOCKS isolation per request, so
  each request makes one descriptor fetch; it records success, latency and
  how many HSDirs each request tried).

The chutney checkout used must contain the `hsflood41339` network. In the
checkout the controls lab used, it holds 4 authorities, 6 relays
(`004r`..`009r`), 2 C tor clients and 3 onion services, and every relay
including the authorities is an HSDir. The scripts find nodes by reading the
nodes dir, so they do not depend on these counts.

## Commands that worked

```
ARTI=<work>/arti-build/bin/arti CHUTNEY=<chutney checkout with hsflood41339> \
SIM=<tor41339-hsdir-defense/simulator/scripts> OUT=<work>/lab-clients/arti/results/run4 \
PROBE_ARGS="--proof-tries 3 --prober-duration 40" \
  <work>/lab-clients/arti/run-arti-lab.sh          # IMAGE=lab24v5 by default
```

Inside the container (`in-lab-arti.sh`):

```
python3 /harness/mkconf.py "$NODES" --state /work/arti1 --socks-port 9400 --out /work/arti1/arti.toml
/arti/arti proxy -c /work/arti1/arti.toml --disable-fs-permission-checks &
# wait for "Sufficiently bootstrapped; proxy now functional." in /work/arti1/arti.log (about 2 s)
curl -sS -x socks5h://user:pass@127.0.0.1:9400 http://<onion>.onion:5858/
```

Chutney onion services map virtual port **5858** to `127.0.0.1:4747`
(`hs_virtport` / `hs_targetport` in chutney's TorNet.py; 4747 is
`network_tests/verify.py: LISTEN_PORT`).

## Config keys (what mkconf.py writes, and why)

| Key | Value | Why |
|---|---|---|
| `tor_network.authorities.v3idents` | `fingerprint` line of each authority's `keys/authority_certificate` | Arti only trusts consensuses that these keys sign |
| `tor_network.authorities.{uploads,downloads,votes}` | one `[ "127.0.0.1:<DirPort>" ]` per authority, from the torrc | new (2.x) struct form. All three lists must be present and aligned with v3idents |
| `[[tor_network.fallback_caches]]` | `rsa_identity` (`fingerprint`), `ed_identity` (`fingerprint-ed25519`), `orports` (torrc `OrPort`) | bootstrap directory sources. By default these are the authorities, as chutney does. `--fallbacks all` adds every relay |
| `override_net_params.hsdir_interval` | `12*2*V3AuthVotingInterval/60` = **8** (minutes) | C tor with TestingTorNetwork shortens the time period to one SR protocol run. Arti does not know about TestingTorNetwork. Without this, Arti computes other blinded keys and other HSDirs, so it never finds a descriptor |
| `override_net_params.cbtmintimeout` | **2000** (ms), `--cbt-min-timeout-ms 0` to drop | lab realism, see Gotcha 2 |
| `path_rules.ipv4_subnet_family_prefix` / `ipv6_...` | 33 / 129 | turns off the same-/16 rule, so that relays all on 127.0.0.1 can share a path |
| `address_filter.allow_local_addrs`, `allow_onion_addrs` | true, true | local addresses are allowed. Onion addresses are on by default but set explicitly |
| `proxy.socks_listen` | `"127.0.0.1:9400"` | a bare port also tries `[::1]`, which fails in the container (WARN) |
| `proxy.dns_listen` | 0 | not needed |
| `logging.files` | `{path=<state>/arti.log, filter="info,tor_hsclient=trace,tor_dirclient=debug,tor_circmgr=debug,arti::proxy=debug"}` | `tor_hsclient` trace shows every HSDir attempt ("hsdir for X, trying ed/$rsa"), and debug shows each failure with its cause. About 200 KB per 5-minute run |
| `logging.log_sensitive_information`, `protocol_warnings`, `time_granularity="1ms"` | true, true, 1ms | full onion addresses and relay ids, and sub-second attempt timing. **For the lab only** |
| `logging.console` | "warn" | |
| `storage.{cache_dir,state_dir}` + `storage.permissions.dangerously_trust_everyone` | per-instance dir | separate state for each Arti instance. Run the binary with `--disable-fs-permission-checks` (a CLI-only flag) |
| `application.allow_running_as_root`, `permit_debugging`, `watch_configuration=false` | | the containers run as root |
| `circuit_timing.hs_desc_fetch_attempts`, `hs_intro_rend_attempts`, `hs_dir_requery_interval` | Arti defaults (6, 6, 15 min) unless `--hs-...` is passed | knobs for sensitivity runs |

## Results (lab24v5 image, tor 0.4.9.14 +tor41339.5, Arti 2.7.0)

The proof (run4) fetched all 3 onion services: `rc=0 http=200 body='clientlab-ok'` in 0.3 to 0.4 s, with one HSDir attempt each.

The isolation runs (run1 and run4 gave the same result) counted relay
`tor_relay_hsdir_get_total` deltas summed over all relays:

| step | Arti HSDir attempts | relay GET delta |
|---|---|---|
| credentials A, first | 1 | success +1 |
| A again | 0 | 0 |
| new credentials B | 1 | success +1 |
| no SOCKS auth | 1 | success +1 |
| A once more | 0 | 0 |
| new credentials C | 1 | success +1 |

For the retry runs (run2 and run4, 30 requests), the descriptor's holders got
`HSDirDescriptorFetchLimit=1 HSDirDescriptorFetchRate=1 HSDirDescriptorFetchBurst=1`
(.5 semantics: a fetch over the bucket closes the circuit with
RESOURCELIMIT and sends no HTTP reply). A C tor client in the lab refetched
the descriptor from those HSDirs every 0.25 s to keep their buckets empty.

- 11 requests failed. Each failure tried **exactly 6 attempts at 6 distinct
  HSDirs**, sent the SOCKS reply GENERAL_FAILURE (curl exit 97, "(1)"), and
  ended 0.24 to 0.60 s after the request.
- Attempts per request: {1: 11, 2: 3, 3: 4, 5: 1, 6: 11}. When some holders
  refused (partial), Arti moved straight to another HSDir and succeeded.
- The gaps between consecutive attempts were 12 ms min, 62 ms median and
  192 ms max (n=70). That is only the time to extend a pre-built circuit.
  There is no backoff.
- Every refused attempt was logged at DEBUG as `failed hsdir desc fetch ... error=error: directory error: IO error: Stream not connected` (48 of 48).
- `retry-sameiso`: after a failure, the next request with the **same**
  SOCKS credentials again made 6 fresh attempts, at the same HSDirs
  (4 times in a row).

The prober (run4, no refusals, `cbtmintimeout=2000`) made 40 requests with
a fresh isolation each. All 40 succeeded with 1 attempt each, and the relays
counted exactly 40 successful GETs. Mean latency was 0.30 s, p95 0.46 s.

## Isolation: the descriptor cache is per SOCKS isolation (arti-v2.7.0)

- SOCKS auth becomes the stream isolation. `crates/arti/src/proxy/socks.rs:150-182`
  maps any plain username/password (and no-auth) to
  `ProvidedIsolation::LegacySocks(auth)`. Then `socks.rs:213` sets
  `StreamIsolationKey(listener+client-IP, that)`. Two keys are compatible
  only when they are equal (`crates/arti/src/proxy.rs:76-104`). So a
  different username **or** password is a different isolation, and no-auth
  is one more isolation of its own.
- `crates/arti-client/src/client.rs:1677-1684` passes `self.isolation(prefs)`
  to `hsclient.get_or_launch_tunnel` (`crates/tor-hsclient/src/lib.rs:167-185`).
- `crates/tor-hsclient/src/state.rs:126-150`: the HS state table is keyed by
  (HsId, client keys, **isolation**). `isol_map.rs:115-138` reuses a record
  only if its isolation can `join` the new one. Otherwise it inserts a blank
  record. Each record owns its `Data` (descriptor, intro-point history,
  HSDir requery map). So the **descriptor cache is per isolation**, and a new
  isolation always fetches the descriptor again. This matches what the
  relays counted above. (C tor differs: its client descriptor cache is
  global.)
- Within one isolation, the descriptor is kept until its own lifetime ends
  (`connect.rs:557-585`). It is fetched early only after an INTRODUCE NACK
  (`connect.rs:470-505`, once, skipping HSDirs it asked within
  `hs_dir_requery_interval`). An idle record is dropped after 48 h
  (`state.rs:124`).

## Retry: what Arti does when an HSDir closes the circuit mid-fetch

- `crates/tor-hsclient/src/connect.rs:531-742`, `descriptor_ensure`:
  - It takes the candidate list from `netdir.hs_dirs_download()`
    (`connect.rs:605`). That is `hsdir_spread_fetch` (3) × `hsdir_n_replicas`
    (2) = up to **6** HSDirs, **shuffled** (`crates/tor-netdir/src/lib.rs:1884-1924`).
  - `attempts = hs_dirs.iter().cycle().take(max_total_attempts)`
    (`connect.rs:653`). `max_total_attempts` is
    `circuit_timing.hs_desc_fetch_attempts`, **default 6**
    (`connect.rs:538-544`, `crates/tor-circmgr/src/config.rs:221-223,286-291`).
    With 6 candidates, each HSDir is tried once. It cycles back to an HSDir
    only if fewer than 6 are left.
  - The attempts run **one after another, never in parallel**
    (`connect.rs:647-652`), with **no delay or backoff** between them
    (`connect.rs:655-706`). On any error it logs at DEBUG (`connect.rs:688-694`;
    WARN only if the error looks like a tagging attack, `err.rs:512-524`) and
    moves to the next HSDir. After the last one it returns
    `CE::DescriptorDownload` (`connect.rs:657-664`).
  - Each attempt records the HSDir in `recent_hsdirs` with
    `now + hs_dir_requery_interval` (15 min, `connect.rs:669-671`,
    `config.rs:296-298`). But when there is no valid cached descriptor,
    the map is cleared first (`connect.rs:588-593`). So this memory only
    matters for the NACK refetch.
- Per attempt (`connect.rs:753-839`): Arti takes a pre-built stem circuit from
  the HS pool and extends it to the HSDir (`HsCircKind::ClientHsDir`,
  `crates/tor-circmgr/src/hspool.rs:227-240,537-540`). The reply is capped at
  `hsdir_dl_max_reply_cells` (`hspool.rs:559-560`). It sends BEGIN_DIR and
  the GET at once, and allows `timeout_roundtrip` (an estimate from the
  learned circuit-build timeouts) for each of the begin and the response
  (`connect.rs:794-812`). A circuit the HSDir closes surfaces as
  `Directory(IO error: Stream not connected)`. A slow HSDir surfaces as
  `Timeout`.
- After a failure, the connect task owns `Data` and stores back only the
  error (`state.rs:386-457`). The next request on that isolation sees a
  finished `Working` state and starts from a blank state (`state.rs:340-351`).
  So an application retry makes **another full round of 6 attempts**
  straight away, which retry-sameiso confirmed.
- What the application sees: SOCKS reply 0x01 GENERAL_FAILURE
  (`crates/arti/src/proxy/socks.rs:458`). Only a 404 from the HSDirs becomes
  0xF0 HS_DESC_NOT_FOUND (`err.rs:421`, `socks.rs:440`). At proxy level it
  logs `WARN arti::proxy: Connection exited (cause: directory fetch or upload attempt failed)` (rate-limited).

## Gotchas

1. **hsdir_interval.** Without the override Arti cannot find any descriptor
   in a TestingTorNetwork chutney net. mkconf.py derives the value from the
   authorities' `V3AuthVotingInterval`. The time period lasts **8 minutes**,
   so the set of HSDirs holding a descriptor changes during long phases.
   Probe the holders again for each phase.
2. **Timeouts learned on loopback.** Arti learns circuit-build timeouts from
   loopback (tens of ms). The per-attempt HSDir round-trip timeout is half
   the 3-hop build timeout, about 50 ms. When the lab CPUs are busy, Arti
   reports `timed out` even though the HSDir served the descriptor. In
   run3, without the floor, 4 of 30 prober requests failed after 6 timeouts
   of about 50 ms each, while the relays counted 48 successful GETs for
   26 OK requests. `cbtmintimeout=2000` floors the build timeout at 2 s and
   the round trip at 1 s (run4: 40/40, GETs = requests). Keep the floor when
   measuring shedding, or Arti numbers mix "shed" with "slow". Report it as
   a lab setting.
3. HSDirs **holding** a descriptor: the service uploads to spread_store 4 ×
   2 replicas = 8. HSDirs Arti **fetches** from: spread_fetch 3 × 2 = 6. To
   refuse every Arti attempt, act on all holders.
4. `--disable-fs-permission-checks` exists only on the command line. Root
   also needs `allow_running_as_root`.
5. A small net gives harmless WARNs on stdout about once a second:
   `Requested 39 relays, but only 0 were usable ... role=Guard` (guard-sample
   top-up). Logs go to the file; stdout is only for start-up problems.
6. Arti also makes its own BEGIN_DIR streams (consensus/microdescs) to its
   guards. Attribute HS load with `tor_relay_hsdir_get_total{action=...}`,
   not `tor_relay_streams_total{type="BEGIN_DIR"}`.
7. Per-isolation caching means a client that changes SOCKS credentials per
   request (as `ArtiProber` does) makes one HSDir fetch per request. A client
   that keeps its credentials makes one fetch per descriptor lifetime.
   Pick the prober's isolation policy for what the phase should model.
8. Unconfirmed, for the C tor harness: while refetching to empty the buckets,
   the C tor client (HSFETCH with SERVER=) produced `HS_DESC RECEIVED`
   events but **no** `HS_DESC FAILED` events for fetches whose circuit the
   HSDir closed (688 issued, 176 received, 0 failed). Count refusals from
   relay metrics, not from that event.
