**Title:** MetricsPort: count tunneled directory requests and onion service descriptor fetch/upload outcomes

### Summary

During the BEGIN_DIR / HSDir floods in #41339 (see also tpo/network-health/analysis#113), operators could see `tor_relay_streams_total{type="BEGIN_DIR"}` rise sharply. But nothing on the MetricsPort shows what those streams then did. We'd like to discuss adding a few observe-only, relay-wide metrics before proposing any code.

In 0.4.9.14, `tor_relay_streams_total{type="BEGIN_DIR"}` is counted once per stream in `connection_exit_connect_dir()`, before any HTTP request arrives. After that point:

1. **What the stream carried isn't visible.** Nothing separates:
   - streams that never deliver a valid request: closed while still in `DIR_CONN_STATE_SERVER_COMMAND_WAIT`, or answered with a `parse_http_url()` 400;
   - ordinary directory requests (consensus, `/tor/micro/`, `/tor/keys/`, …, including unknown URLs answered 404);
   - onion service descriptor fetches and uploads.
2. **HSDir outcomes aren't visible.** The MetricsPort has no counter for descriptor fetches or uploads. The only HSDir-related relay metrics are `tor_relay_flag{type="HSDir"}` and `tor_relay_load_oom_bytes_total{subsys="hsdir"}`. The `tor_hs_*` families only cover onion services hosted by the same tor. The extra-info line `hidserv-dir-v3-onions-seen` counts unique blinded keys, daily, binned and with added noise. So an operator can't tell:
   - fetch hits (200, the whole descriptor queued at once: typically ~14 KB, at most `HSV3MaxDescriptorSize`) from misses (404, ~60 bytes) or single-hop refusals (503);
   - accepted uploads from rejected ones, or why an upload was rejected. A 400 can mean a bad URL or version, an invalid descriptor (too large, unparsable, or failing signature or certificate checks), or a revision counter no newer than the cached copy. A stale re-upload from a legitimate service is a very different signal from junk.
   - whether a queued response was ever written out.
3. **The connections behind these streams aren't visible.** Each BEGIN_DIR creates a socketless, linked exit + directory connection pair:
   - ConnLimit and the OOS handler count only sockets;
   - `tor_relay_connections` never counts these pairs as opened (a related accounting problem is tracked in #41350);
   - an idle pair can stay open until `TestingDirConnectionMaxStall` (5 minutes);
   - bandwidth graphs barely move, since a stream may carry only a CONNECTED cell and a 404.
4. **Per-circuit and previous-hop behaviour isn't visible.**
   - Stock clients make each HSDir request on its own circuit. C tor isolates anonymized directory requests with `ISO_STREAM`, and HS fetches and uploads use `DIRIND_ANONYMOUS`. Arti uses a fresh `HsCircPool` circuit for each HSDir fetch or upload attempt. Nothing counts circuits that make several such requests. DoSStreamCreation never sees BEGIN_DIR, because `connection_exit_begin_conn()` returns before reaching it.
   - BEGIN_DIR skips the known-relay check that `RefuseUnknownExits` applies to exit streams. DoSCircuitCreation counts only client (unauthenticated) channels. So an HS request whose previous hop is relay-authenticated but in neither our consensus nor our descriptor list goes unrecorded.

### What is the expected behavior?

All values would be relay-wide, with no behaviour change. Only tunneled (linked) connections would be counted, so DirPort traffic stays out. Names are placeholders.

| Metric | Labels | Counts |
|---|---|---|
| `tor_relay_hsdir_get_total` | `action="success\|not_found\|single_hop"` | descriptor fetches answered 200, 404 (including malformed keys), or 503 because the request isn't anonymous (single-hop, or its stream or circuit is already closing) |
| `tor_relay_hsdir_post_total` | `action="success\|bad_url\|invalid\|not_newer\|single_hop"` | uploads accepted, or rejected for the reason given |
| `tor_relay_dir_requests_total` | `type="non_hs\|unparsed"` | other directory requests; streams with no valid request |
| `tor_relay_dir_responses_total` | `type="hs_descriptor\|other"` | responses fully handed to the linked exit stream |
| `tor_relay_dir_server_conns` (gauge) | `state="command_wait\|writing_hs_descriptor\|writing_other\|draining"` | open tunneled directory connections; `draining` = exit streams whose directory side has closed |
| `tor_relay_dos_total` | `type="hsdir_request_total"`, `"hsdir_req_reused"`, `"hsdir_circ_reused"`, `"hsdir_unknown_prev_hop"` | anonymous HS requests; those after the first on a circuit; circuits with two or more; HS requests whose previous hop isn't a known relay |

**Notes**

- **Reconciliation.** On a public relay, every tunneled BEGIN_DIR stream ends up in exactly one bucket. Up to scrape timing, `streams_total{BEGIN_DIR}` ≈ `hsdir_get` + `hsdir_post` + `dir_requests` + `dir_server_conns{command_wait}`. Similarly, `hsdir_get{success}` − `dir_responses{hs_descriptor}` − `dir_server_conns{writing_hs_descriptor}` counts descriptor responses abandoned before hand-off. "Written out" means handed to the exit edge, not delivered to the client; stock's own comment there calls it "only an intermediate step".
- **Cost.**
  - Increments only on paths that already run.
  - One known-relay lookup per anonymous HS request, the check RefuseUnknownExits already makes.
  - A 2-bit per-circuit request counter.
  - The gauge is computed at scrape time in one pass over the connection array.
- **Privacy.** MetricsPort is operator-local, and nothing is labelled per descriptor, key or peer. We're happy to coarsen or drop anything you'd rather not expose.

**Questions**

1. Separate families as above, or `type` labels under `tor_relay_dos_total`? It is a counter family, so the gauge can't go there. Any naming preferences?
2. Should DirPort requests be counted too, perhaps with a `transport` label?
3. Is the per-circuit and previous-hop view useful enough to keep? Is there anything you'd add or drop?

/label ~Feature ~Metrics
