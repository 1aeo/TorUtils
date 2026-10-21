<!-- Ready-to-paste new issue for https://gitlab.torproject.org/tpo/core/tor/-/issues/new
     Suggested label: Metrics. Line numbers are tor-0.4.9.14 (8fe2745). -->

**Title:** MetricsPort: count HS descriptor uploads on HSDirs by outcome

HSDir `POST /tor/hs/3/publish` outcomes aren't counted anywhere. Every rejection that `handle_post_hs_descriptor()` makes returns the same `400 "Invalid HS descriptor. Rejected."` (`dircache.c:1617-1621`). Underneath, `hs_cache_store_as_dir()` returns −1 both for an invalid descriptor and for a valid one that isn't newer than the cached copy (`hs_cache.c:378-411`).

Outcomes in 0.4.9.14:

| Response | Where | Condition |
|-|-|-|
| `503 Rejecting single hop HS descriptor post` | `dircache.c:1609-1612` | `!connection_dir_is_anonymous()` (`directory.c:201-265`) |
| `400 Invalid HS descriptor. Rejected.` | `dircache.c:1543-1564` | Bad version or command in the URL |
| same | `hs_cache.c:390-393` | `hs_desc_decode_plaintext()` fails (plaintext layer only) |
| same | `hs_cache.c:182-193` | Valid, but the cached revision counter is ≥ the uploaded one |
| `200 HS descriptor stored successfully.` | `dircache.c:1614-1621` | Stored |

- **"Not newer" is a valid, signed descriptor.** One C Tor instance only ever uploads increasing counters: an OPE of the seconds since the period start, recomputed per upload (`hs_service.c:3248-3274`, `:3550`). So a "not newer" upload is a stale duplicate, for example from several instances sharing a key. The service logs it as "Malformed hidden service descriptor?" (`dirclient.c:2809-2817`).
- **The single-hop 503 isn't counted either.** `single_hop_refused` is only bumped at `rendmid.c:53`. C Tor services always upload with `DIRIND_ANONYMOUS` (`hs_service.c:4051`).

**Proposal** (patch ready, about 90 lines plus a test):

```
tor_relay_hsdir_post_total{action="success"}     # 200
tor_relay_hsdir_post_total{action="bad_url"}     # 400
tor_relay_hsdir_post_total{action="invalid"}     # 400
tor_relay_hsdir_post_total{action="not_newer"}   # 400
tor_relay_hsdir_post_total{action="single_hop"}  # 503
```

- Same shape as `tor_relay_intro1_total`: an enum, `relay_increment_hsdir_post_action()`, and a static array in `relay_metrics.c`.
- All counting happens in `dircache.c`. It's built only with the relay module, so `--disable-module-relay` needs no `relay_stub.c` stub.
- `hs_cache_store_as_dir()` returns −2 for "not newer". Its only caller checks `< 0`, and two test assertions change from −1 to −2.
- Applies to `main`, and on top of the tor#41339 HSDir patches.

Questions:

1. Name: `tor_relay_hsdir_post_total` or `tor_relay_hs_desc_upload_total`?
2. Labels: one `action` label (like `intro1`), or `status` plus `reason`?
3. Split `invalid` into certificate/expiry, signature and format?
4. Return value: −2, or an enum like `hs_cache_store_as_client()`'s `hs_desc_decode_status_t` (`hs_cache.h:106`)?
5. Add a GET sibling, `tor_relay_hsdir_get_total{action="success|not_found|single_hop"}`, as a separate MR?
