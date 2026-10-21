<!-- Ready-to-paste new issue for https://gitlab.torproject.org/tpo/core/tor/-/issues/new
     Suggested labels: Metrics, Onion Services (or whatever the HSDir label is). Line numbers are tor-0.4.9.14 (8fe2745). -->

**Title:** MetricsPort: count onion service descriptor uploads on HSDirs by outcome

### Problem

While watching HSDirs during the tor#41339 flood, operators could see `tor_relay_streams_total{type="BEGIN_DIR"}` climb but had no way to tell what those directory requests turned into. On the upload side (`POST /tor/hs/3/publish`) in particular, nothing is counted at all, and every rejection looks the same to the client and to the operator:

- **A valid descriptor that is simply not newer looks the same as a forged or broken one.** Both get `400 "Invalid HS descriptor. Rejected."` (`src/feature/dircache/dircache.c:1617-1621`), because `hs_cache_store_as_dir()` returns -1 both when `hs_desc_decode_plaintext()` fails (`src/feature/hs/hs_cache.c:390-393`) and when the cached descriptor has a revision counter ≥ the uploaded one (`hs_cache.c:182-193`, logged only at info level). The second case is a correctly signed descriptor. A single C Tor instance always uploads increasing counters, because they are derived from the time (`src/feature/hs/hs_service.c:3248-3274`). But several instances publishing for the same onion address, or a clock stepping back, produce valid uploads that aren't newer. The service sees the same 400 and logs it as "Malformed hidden service descriptor?" (`src/feature/dirclient/dirclient.c:2809-2817`).
- **Single-hop / non-anonymous upload attempts are invisible.** `503 "Rejecting single hop HS descriptor post"` (`dircache.c:1609-1612`) isn't counted anywhere. `tor_relay_dos_total{type="single_hop_refused"}` only counts legacy introduction cells (`src/feature/rend/rendmid.c:53`).

### What a POST to `/tor/hs/` can turn into today

| Where | Result | Condition |
|-|-|-|
| `connection_edge.c:4191-4198`, `:4239-4247`, `:4317-4321` | `END` (`EXITPOLICY`, `NOTDIRECTORY` or `HIBERNATING`), no HTTP | Not a relay, not a directory cache, conflux circuit, circuit purpose isn't OR, or hibernating. All before the `BEGIN_DIR` stream counter at `connection_edge.c:4697`. |
| `dircache.c:1748-1754`, `:1772-1777` | stream closed, no HTTP response | Headers ≥ 50000 bytes, body ≥ 16 MB − 1 (`MAX_DIR_UL_SIZE`), a bad `Content-Length`, or an unknown method. A stream that closes before the request is complete is also closed without a response. |
| `dircache.c:1591-1597` | `503 Not acting as a public relay` | `!public_server_mode()`, checked before the URL is parsed |
| `dircache.c:1599-1602` | `400 Bad request` | The request line doesn't parse (`parse_http_command()`, `src/feature/dircommon/directory.c:304-351`). A URL without the `/tor/` prefix is rewritten, not rejected. |
| `dircache.c:1609-1612` | `503 Rejecting single hop HS descriptor post` | `!connection_dir_is_anonymous()` (`directory.c:201-265`): not tunneled, the previous hop is a client, or the stream or circuit is already closing. C Tor services, single onion services included, always upload over anonymous circuits, so for them this only happens if the stream or circuit closes at the wrong moment. |
| `dircache.c:1543-1552`, `:1562-1564` | `400 Invalid HS descriptor. Rejected.` | Bad URL: version isn't a number, the command doesn't start with `/publish` (a prefix match), or the version isn't 3 |
| `hs_cache.c:390-393` | `400 Invalid HS descriptor. Rejected.` | `hs_desc_decode_plaintext()` fails: size (≥ `HSV3MaxDescriptorSize`, default 50000), outer-layer format, lifetime, signing-key certificate, revision-counter field, superencrypted blob, or signature. The HSDir never decrypts the superencrypted layer. Services mint a fresh 54 h certificate for each upload, so an expired certificate means the HSDir's clock is about 54 h or more ahead. |
| `hs_cache.c:182-193` | `400 Invalid HS descriptor. Rejected.` | Valid descriptor, but the cached one has a revision counter ≥ this one |
| `dircache.c:1614-1621` | `200 HS descriptor stored successfully.` | Stored |

### Proposal

Add a counter modelled on `tor_relay_intro1_total` / `tor_relay_est_rend_total`: one `action` label, the counter array in `relay_metrics.c`, and a `relay_increment_hsdir_post_action()` call where each outcome is decided.

```
# HELP tor_relay_hsdir_post_total Total number of onion service descriptor uploads we received
# TYPE tor_relay_hsdir_post_total counter
tor_relay_hsdir_post_total{action="success"} 0      # 200
tor_relay_hsdir_post_total{action="bad_url"} 0      # 400
tor_relay_hsdir_post_total{action="invalid"} 0      # 400
tor_relay_hsdir_post_total{action="not_newer"} 0    # 400, valid but revision counter not greater
tor_relay_hsdir_post_total{action="single_hop"} 0   # 503
```

I have a patch (about 90 lines plus a unit test that reads the exported values). All the counting stays in `dircache.c`, which is only built with the relay module, so `--disable-module-relay` needs no stub. The only other change is that `hs_cache_store_as_dir()` returns -2 instead of -1 for the "not newer" case. Its only caller checks `< 0`, and two existing test assertions change from -1 to -2. It applies to `main`, and on top of the HSDir patches discussed in tor#41339. Their guard runs after the `single_hop` check and before the outcome is known. A request it refuses never gets an `action`. With enforcement off, which is the default, it only counts in `tor_relay_dos_total{type="hsdir_*"}`, and the request then gets its `action` as usual.

### How it fits with `BEGIN_DIR`

Each accepted `BEGIN_DIR` stream carries at most one HTTP request, so:

```
tor_relay_streams_total{type="BEGIN_DIR"}
  = streams still waiting for their request
  + streams closed before a full request (EOF, too large, unknown method)
  + answered GETs (HS descriptor fetches and everything else)
  + answered POSTs
```

With this counter, the HS part of "answered POSTs" becomes observable. On a non-authority, every other POST gets `400 Nonauthoritative directory does not accept posted server descriptors` (`dircache.c:1625-1631`). Two caveats: `single_hop` also counts non-tunneled (DirPort) uploads, which aren't `BEGIN_DIR` streams, and the `503 Not acting as a public relay` / `400 Bad request` responses happen before the URL is known, so they aren't counted here.

### Questions

1. **Name:** `tor_relay_hsdir_post_total`, or something like `tor_relay_hs_desc_upload_total`?
2. **Labels:** a single `action` label as for `intro1` / `est_rend`, or `status` (HTTP code) plus `reason`? Each reason maps to exactly one status, so `status` would be redundant, but it would make matching against HTTP codes easier.
3. **Granularity:** is `invalid` enough, or should it be split (for example certificate/clock-skew vs. signature vs. format)? Splitting means passing the decode status out of `hs_desc_decode_plaintext()`.
4. **`single_hop`:** count it here (it's checked only for `/tor/hs/`), or leave it out?
5. **GET:** would a matching `tor_relay_hsdir_get_total{action="success|not_found|bad_request|single_hop"}` for descriptor fetches be welcome, as a separate MR? During tor#41339 that is the side that carried the flood, and the `BEGIN_DIR` breakdown above needs it.
