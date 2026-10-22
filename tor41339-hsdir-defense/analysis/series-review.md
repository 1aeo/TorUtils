# Independent review of the tor#41339 HSDir series

Reviewed the 13 commits on `tor41339-hsdir-defense-clean` against Tor
0.4.9.14 (`8fe2745aee2c`, tag `tor-0.4.9.14`) and `main` at `8dbbbe6e86`.
The previous 11-patch tree is `c167724`. Line numbers below are stock
0.4.9.14 unless the sentence says the series tree.

Four follow-up commits fix defects this review could prove. They are
`patches/0014`–`0017` and the same files under
`engineering/deb/build-reordered/debian-patches/`. `git am` of 0001–0017
applies on 0.4.9.14 and on `main` at `8dbbbe6e86`.

The `+tor41339.5` packages were built from 0000 plus 0001–0013. They do
not contain 0014–0017.

## Commit verdicts

| Commit | Verdict | Why |
|---|---|---|
| 0001 | Agree | One 37-byte request hits two warnings. `fetch_from_buf_http()` logs the bogus `Content-Length` at warn (`src/core/proto/proto_http.c:93`), then `directory_handle_command()` logs again (`src/feature/dircache/dircache.c:1748`). `connection_describe_peer()` scrubs OR and exit peers, not directory connections (`src/core/mainloop/connection.c:409`, `:435`, `:470`). `safe_str()` returns `"[scrubbed]"` unless `SafeLogging` is 0 (`src/app/config/config.c:1139`). Directory clients and the HTTPS proxy keep their own warn on parser failure (`src/feature/dirclient/dirclient.c:2043`, `src/core/mainloop/connection.c:2867`). The rate-limit test is `TT_FORK`. |
| 0002 | Agree, with a false rationale for dropping the early reject | Non-authorities only store HS descriptors, and decode already rejects `strlen >= hs_cache_get_max_descriptor_size()` (`src/feature/hs/hs_descriptor.c:1148` and `:2681`). Capping the buffered body at `min(16MB, HSV3MaxDescriptorSize)` matches that. The claim that stock already rejects `contentlen >= max_bodylen` is false. See decision 4 and 0014. |
| 0003 | Agree | In `COMMAND_WAIT` the function returned 0 and never applied the 10 MB cap (`src/feature/dircommon/directory.c:489`). In `SERVER_WRITING` it fell through and closed at 10 MB (`:501`). The new server block clears `inbuf` only in `SERVER_WRITING` and returns before that cap. A partial request stays in `COMMAND_WAIT` with its bytes. Clients are not `DIR_PURPOSE_SERVER`. Linked connections notice EOF only while reading (`src/core/mainloop/connection.c:4256`). |
| 0004 | Agree | Stock parses the signing cert at `src/feature/hs/hs_descriptor.c:2229` and only then reads `R3_SIGNATURE` at `:2278`. `ED25519_SIG_BASE64_LEN` is 86 (`src/lib/defs/x25519_sizes.h:45`), which is what `ed25519_signature_from_base64()` requires (`src/lib/crypt_ops/crypto_format.c:258`). Checking length first skips the cert parse for a wrong-length signature. |
| 0005 | Agree | Stock credits in `connection_dir_about_to_close()` whenever `hs_ident` is set (`src/feature/dircommon/directory.c:535`), including a close before the bytes leave the outbuf. Moving the credit to `connection_dir_finished_flushing()`, after the `marked_for_close` early return, credits one full flush. A second flush sees the mark and returns. HS responses use `connection_buf_add`, not the spool, so they do not hit the spool bug path. |
| 0006 | Agree | `hs_cache_store_as_dir()`'s only negative return from a parsed descriptor is the not-newer path. See decision 3. Outcome labels match the HTTP codes the handlers already return. |
| 0007 | Agree | Counts are behind `linked` checks, and a close from `COMMAND_WAIT` is the unparsed bucket. DirPort traffic is not linked. |
| 0008 | Agree | The gauge walks the connection array at scrape time. It does not follow `on_circuit` or `p_chan`. A linked exit is `DRAINING` only when its directory side is gone or marked. Healthy pairs are counted on the directory side. |
| 0009 | Agree | The table lists the same stock counters the old straight-line function reported. No value changes. |
| 0010 | Agree | `n_hsdir_requests` is a 2-bit field. The counter is updated only after `connection_dir_is_anonymous()` succeeds, and it saturates at 2. `hsdir_request_total` counts that anonymous subset once. |
| 0011 | Agree | The helper matches stock `dos_should_refuse_single_hop_client()` byte for byte in behavior. The reuse close does not double-count. See decisions 5 and 6. |
| 0012 | Agree, with a measurement caveat | BEGIN_DIR-only, off by default, public relays only, counted either way. The default 64 is above what this lab observed and above the client launch burst computed from source. It was not measured as "36 concurrent" on a 9,000-relay network. See decision 7. |
| 0013 | Agree the counter and the torrc-only switch. The enforcement is an operator opt-in with a real popularity oracle. | 404s never touch the bucket. The bucket is copied by value when a descriptor is replaced. See decision 8. |

## Decisions

### 1. Metric families

**Agree.** Outcome counters follow `tor_relay_intro1_total{action}`: one family per event, `action` or `type` as the label. `tor_relay_dos_total` is a counter family, so the open-connection series has to be its own gauge. Only linked connections are incremented: the single-hop, unparsed, non-HS, and response increments are inside `if (linked)` or happen only after `connection_dir_is_anonymous()` has required a live edge and OR circuit. A DirPort connection fails that check and is not counted. That matches the issue text.

### 2. Keep `hsdir_request_total`?

**Agree, keep it.** It is not the sum of the GET and POST families. It is the anonymous subset:

`hsdir_request_total = (every hsdir_get action except single_hop) + (every hsdir_post action except single_hop)`

`note_hs_dir_request()` runs only after the anonymity check, and every such path then records exactly one outcome, including `refused`. `single_hop` is the anonymous-check failure and is not in this counter. The deployed canary already graphs the dos-family name. One extra counter is cheap. Dropping it would split dashboards for a number operators can already derive once the new families exist. Keep it until those dashboards move, and document the formula.

### 3. `hs_cache_store_as_dir()` returns -2 for "not newer"

**Agree. Callers are still correct.** `cache_store_v3_as_dir()` returns -1 only from the revision-counter reject (`src/feature/hs/hs_cache.c`, the `goto err` under the revision compare). A failed decode still returns -1 from `hs_cache_store_as_dir()` because `ret` stays -1. The directory POST switches on 0, -2, and default. `src/test/test_stats.c` and `src/test/test_hs_cache.c` expect -2 for a duplicate and -1 for junk. No other production caller exists.

### 4. Does stock `fetch_from_buf_http()` reject `contentlen >= max_bodylen`?

**Disagree.** The buffered-body check runs first and does not look at `Content-Length`:

```c
if (max_bodylen <= bodylen) {
  log_warn(...);
  return -1;
}
```

`src/core/proto/proto_http.c:86`. The content-length parse is at `:92`. If the body has not arrived and `force_complete` is 0, the function returns 0 at `:100` with no comparison of `contentlen` to `max_bodylen`. A declared length of `INT_MAX` keeps the directory connection in `COMMAND_WAIT` until `bodylen` reaches the cap or the 5-minute stall fires (`src/app/config/config.c:775`, `TestingDirConnectionMaxStall`).

`directory_handle_command()` passes `force_complete = 0`. Callers that pass `force_complete = 1` (partial descriptor downloads) can still accept a short buffered body whose declared length is over the limit. That path must stay.

0014 rejects `contentlen >= max_bodylen` only in the `!force_complete` branch. Tests cover a headers-only HS POST at the limit, a headers-only POST one byte under it, a proto_http case with a short body and `Content-Length: 99999`, and `force_complete = 1` still returning the bytes it has.

### 5. Is the `dos_defense_enabled()` refactor acceptable?

**Agree.** Stock `dos_should_refuse_single_hop_client()` is: not a public relay, then the torrc value when it is not -1, else consensus parameter `DoSRefuseSingleHopClientRendezvous` defaulting to 0. `public_server_mode()` is `server_mode() && !BridgeRelay` (`src/feature/relay/routermode.c:43`). The new helper is that sequence with the parameter name as an argument. `test_dos_refuse_single_hop` still requires the stock parameter name, torrc override, and `ORPort_set = 0`. Touching that function is the right place to share the AUTOBOOL rule. It is not a drive-by behavior change.

### 6. Reuse close: state and double counting

**Agree, the close is accounted once.** `directory_handle_command_get()` sets `SERVER_WRITING` before the anonymity check. On the second request, `allow_hs_dir_request()` marks the circuit and returns false. The handler increments `refused` and returns. No response bytes are queued. `connection_dir_about_to_close()` increments `unparsed` only in `COMMAND_WAIT`, so this close is not `unparsed` and not `success`. `circuit_mark_for_close()` records the reason and returns; it does not free the connection under the handler. A later request on a circuit that is already marked fails `connection_dir_is_anonymous()` (`src/feature/dircommon/directory.c:249`) and is counted as `single_hop`, which the issue text already describes as including a stream or circuit that is already closing.

### 7. BEGIN_DIR limit instead of the old exit-wide limiter

**Agree that dropping the old exit-wide rate limit is right.** That older patch applied a ceiling to every exit BEGIN and RESOLVE and counted `stream_rejected` while the defense was off. `DoSStreamCreation` still does not see BEGIN_DIR, because `connection_exit_begin_conn()` returns from the BEGIN_DIR branch at `src/core/or/connection_edge.c:4326` before `dos_stream_new_begin_or_resolve_cell()` at `:4340`. A live cap on open BEGIN_DIR streams is the resource that is actually held: each one is a linked pair that ConnLimit does not count. A rate without a live cap does not free those pairs. Leaving BEGIN_DIR without its own rate is consistent with that. A rate can be a later patch if the open-stream counter shows a trickle that never reaches 64.

**The default 64 is defensible. It is not a measured 36-wide concurrent peak.**

Client launch math, stock `src/feature/nodelist/routerlist.c`:

- `max_dl_per_request()` returns 500 when `dirclient_must_use_begindir()` (`:2531`).
- `MIN_REQUESTS` is 3 (`:2543`). For 9,000 digests, the batch size is 500, so one purpose launches `ceil(9000/500) = 18` requests.
- `update_all_descriptor_downloads()` launches router descriptors and microdescriptors in one callback. That is 36 requests.
- Extrainfo is a third loop (`:2919`) of another up to 18 requests.
- `router_is_already_dir_fetching()` returns 0 when the port is 0 (`src/feature/nodelist/node_select.c:243`) and its comment says tunnel connections are not checked (`:247`). BEGIN_DIR connections are stored with the OR port (`src/feature/dirclient/dirclient.c:1287`). The busy flag does not serialize them.

Those requests are initiated back to back. They are concurrent only while earlier responses are still open. This lab did not build a 9,000-relay consensus, so it did not observe 36 or 54 in flight.

Private loopback chutney, defenses at their defaults, Sandbox on. Info-log pairing of `Sending relay cell 1 on circ` with the matching end cell:

| Run | When (PT) | Node | BEGIN_DIR cells | Circuits | Max open on one circuit |
|---|---|---|---|---|---|
| 3 authorities, 1 exit, client `NumEntryGuards 1` and `NumDirectoryGuards 1` | 21 Oct 2026, 11:58 PM | client | 20 | 3 | 1 |
| Same shape plus a bridge authority, one bridge, one bridge client | 22 Oct 2026, 12:09 AM | bridge relay, as a client | 6 | 4 | 2 |
| same | same | bridge client | 4 | 1 | 1 |

64 is above both the lab peaks and the 36-request (or 54, with extrainfo) launch burst. It is a reasonable off-by-default ceiling. It is not evidence from a large network.

**A refused BEGIN_DIR fails that client request, and an ordinary client marks the relay down. That is acceptable for an off-by-default limit.**

The relay sends `END_STREAM_REASON_MISC` before `CONNECTED` (`connection_exit_begin_conn`). The client marks the AP stream (`src/core/or/relay.c:1851`) and the linked directory connection reaches EOF. If it is not in `CLIENT_READING`, `connection_dir_reached_eof()` closes it (`src/feature/dirclient/dirclient.c:2837`). `connection_dir_about_to_close()` calls `connection_dir_client_request_failed()` when `state < DIR_CONN_STATE_CLIENT_FINISHED`. Client states are 1–3 and `CLIENT_FINISHED` is 4 (`src/feature/dircommon/directory.h:18`). That function calls `router_set_status(digest, 0)` only when the client is not using bridges or `EntryNodes` (`src/feature/client/entrynodes.c:3511`) and the purpose is not an onion-service purpose (`src/feature/dirclient/dirclient.c:713`). An HTTP 503 takes the same mark-down path: `connection_dir_client_reached_eof()` returns -1 for status 503 (`:2127`) and does not set `CLIENT_FINISHED`. The END does not invent a harsher directory failure than a 503. Onion-service fetches, bridge clients, and `EntryNodes` clients still fail the request and do not mark the relay down. 0016 corrects the manual, which used to say every non-onion-service client marks the relay down.

### 8. Per-descriptor fetch limit

**Agree with the counter, the torrc-only switch, skipping `success`, keeping the bucket, and the second lookup. The enforcement should stay opt-in.**

- A global bucket was the wrong scope: one client could spend it and deny every descriptor. Dropping it is right.
- A consensus parameter would let the network turn on a per-descriptor popularity oracle. Torrc-only is right. The manual states the oracle in `doc/man/tor.1.txt` under `HSDirDescriptorFetchLimit`.
- Refused fetches increment `HSDIR_GET_REFUSED` and return before `HSDIR_GET_SUCCESS`. They are not counted as success.
- `token_bucket_ctr_t` has no pointers (`src/lib/evloop/token_bucket.h:110`). Assigning it onto the replacement descriptor keeps the token count.
- The second lookup is one digest-map get. It cannot miss on this path: the first lookup just found the descriptor, nothing in between removes it, and tor is single-threaded here. Changing `hs_cache_lookup_as_dir()` would thread the bucket through every caller for no gain.
- 5/s and burst 20 are the counting thresholds even while enforcement is off. Five fetches a second of one descriptor on one HSDir is a busy onion, not a casual one, so the counter will not chatter on ordinary services. A wide scan that fetches many blinded keys once each, and every 404, never touches a bucket: the limit runs only after `hs_cache_lookup_as_dir()` succeeds. The counter is a hot-descriptor signal. It is not a detector for the spread-out flood. That is a reason to ship the counter and leave enforcement off, which is what the default does. I would not add a consensus switch later without a separate proposal.

### 9. Heartbeat wording

**Agree.** The line is `Heartbeat: DoS mitigation since startup`. Each defense prints its counter when the defense is enabled and `[Option disabled]` otherwise. The counters increment whether or not the defense is enabled, so a number shown after a later `SETCONF` includes events from before the option was turned on. "Since startup" is the accurate window. The phrases describe the events that are counted (over the limit, repeated requests, unknown previous hop, over the rate), not "refusals since I turned this on."

One loose word: while `DoSBeginDirLimitEnabled` is on, the cells that are refused never become streams, and the heartbeat still says "BEGIN_DIR streams over the limit." The test locks that string. I left it. It is not a wrong total.

## Lifetimes

`note_hs_dir_request()`, `allow_hs_dir_request()`, and the fetch-limit close run only after `connection_dir_is_anonymous()` returns true. That function, in order, requires a linked directory connection, an edge `linked_conn` that is not closed and not marked, an OR circuit that is not an origin circuit and not marked, and a non-NULL `p_chan` (`src/feature/dircommon/directory.c:203`). A NULL `p_chan` on an unmarked circuit hits `BUG()` and returns false. Both anonymity checks (linked/encrypted, and not a client channel at `:266`) happen before any of the new dereferences. A circuit that is already marked is counted as `single_hop` and does not enter `note_hs_dir_request()`.

The gauge does not read `on_circuit` or `p_chan`. It skips marked connections and unlinked connections, and it reads `linked_conn->marked_for_close` only after a NULL check. The only linked exits in the tree are BEGIN_DIR exits (`connection_link_connections()` is the client `connection_ap_make_link` path and `connection_exit_connect_dir`).

## Accounting

The issue's public-relay identities, with defenses off:

1. `streams_total{BEGIN_DIR}` ≈ `hsdir_get` + `hsdir_post` + `dir_requests` + `dir_server_conns{command_wait}`
2. `hsdir_get{success}` − `dir_responses{hs_descriptor}` − `dir_server_conns{writing_hs_descriptor}` = descriptor responses abandoned before hand-off

`streams_total{BEGIN_DIR}` is `rep_hist_note_exit_stream(RELAY_COMMAND_BEGIN_DIR)` inside `connection_exit_connect_dir()` (stock `:4697`).

| Path | Breaks identity 1 as shipped? | What to do |
|---|---|---|
| `connection_add()` of the exit or the directory connection fails after the stream was counted. Both connections are freed, not closed, so nothing reaches `about_to_close`. | Yes | **Fixed in 0015.** The count now happens only after both adds succeed. A failed add is in neither counter. |
| `CONNECTED` cannot be sent. Both connections are marked. The directory side is still `COMMAND_WAIT` and linked, so close counts `unparsed`. | No, once 0015 has counted the stream | Leave it. |
| BEGIN_DIR refused by 0012 before `connection_exit_connect_dir()`. | No. The stream counter has not run. `begindir_over_max` is a separate dos counter. | Document. Do not add it to the directory families. |
| HS request refused by 0011 or 0013. State is already `SERVER_WRITING`. Counted as `refused`. | The sum of the families holds. The issue's label list omits `refused` because that label is enforcement. With the defenses off, `refused` stays 0. | Document. Do not put enforcement in the issue. |
| Non-public POST returns 503 before any counter, with state `SERVER_WRITING`. | Not on a public relay. `public_server_mode()` is false for bridges. | Document. The issue already says "on a public relay." |
| DirPort HS fetch. | No. It fails anonymity and the `linked` checks, and it is not a BEGIN_DIR stream. | Leave it. |
| Parser overflow or an unknown method. State stays `COMMAND_WAIT`. Close counts `unparsed` once. | No | Leave it. |
| `parse_http_url()` fails. State is already `SERVER_WRITING`, `unparsed` is incremented immediately, and close does not increment again. | No | Leave it. |
| Connection marked but not yet freed. | The gauge skips it and `unparsed` waits for close. | The issue's "up to scrape timing" covers this. |
| Exit still draining after the directory side closed. | The request was already classified when it left `command_wait`. Draining is not a term in identity 1. | Leave it. |

Identity 2 holds. `success` and `hs_ident` are set together, before the handler returns. The response counter and the download credit run in `finished_flushing` only when the connection is not already marked, and the response counter also requires `linked`. The gauge counts an unmarked linked server connection in `SERVER_WRITING` with `hs_ident` as `writing_hs_descriptor`. A close before flush drops the gauge entry and does not increment the response counter, so the difference counts the abandoned body. The spool early-close path does not apply to descriptor bodies.

## Findings, by severity

1. **High, fixed (0014).** A non-authority does not reject an oversized `Content-Length` until the bytes arrive. One BEGIN_DIR per circuit can sit in `COMMAND_WAIT` for the stall timeout holding up to `HSV3MaxDescriptorSize` and, until then, only the bytes received. The series dropped the early reject on a false reading of `fetch_from_buf_http()`. Failure: headers `Content-Length: 2000000000` and a slow drip. The connection stays open and is counted only as `command_wait` until it dies.

2. **Medium, fixed (0015).** `connection_exit_connect_dir()` counted the BEGIN_DIR stream and then freed both connections if `connection_add()` failed. That stream was in `tor_relay_streams_total{type="BEGIN_DIR"}` and in no directory bucket. Failure: the connection table is full, which is a plausible moment during a flood. Identity 1 breaks by those streams.

3. **Medium, fixed (0016).** The manual said every non-onion-service client marks the relay not running after a refused BEGIN_DIR. Bridge clients and `EntryNodes` clients do not. Operators enabling the limit would overstate the client damage.

4. **Low, fixed (0017).** Removing `if (prev_reqs < 2)` survived `hs_cache/hsdir_reuse_and_prev_hop_counters`, the defenses test, and the fetch-limit test. A fourth request wraps the 2-bit field to 0. The new assertion `n_hsdir_requests == 2` after four requests fails that mutant (observed `0` vs `2`).

5. **Low, not a code change.** `DoSBeginDir` heartbeat says "streams" for cells that were refused. The total is right and the line says "since startup."

6. **Design limit, not a defect.** The fetch limit does not apply to 404s or to a scan across many descriptors. Enforcement, while on, is a popularity oracle. Defaults keep it off.

## Mutation

Each mutant was built and run against the tests named. Sources were restored afterward.

| Mutant | Result |
|---|---|
| Consensus name `HSDirOneRequestPerCircut` | Caught. `hs_cache/hsdir_reuse_and_prev_hop_defenses` served a 404 and `refused` was 4 instead of 5. |
| `about_to_close` unparsed check inverted to `!linked` | Caught. `hs_cache/dir_request_response_metrics` expected `unparsed + 2` and saw `+ 3`. |
| BEGIN_DIR ceiling `n <= max` instead of `n < max` | Caught. `dos/begindir_max_streams` did not refuse at 64. `dos/begindir_refused` connected 3 streams instead of 2. |
| `goto done` removed after a GET `refused` | Caught. The defenses test saw a second HTTP status in the reply. |
| Saturation cap removed, before 0017 | **Survived** the three HSDir tests above. |
| Same mutant after 0017 | Caught. `n_hsdir_requests` was 0 vs 2. |

`test_dos_refuse_single_hop` still names `DoSRefuseSingleHopClientRendezvous`, so a misspelling of the stock parameter fails that test. I did not re-run that mutant after reading the test.

## Build, tests, packaging, lab

Compiler: gcc 13.3.0. Configure: `--enable-fatal-warnings --disable-asciidoc` unless noted. `LD_LIBRARY_PATH` for the test binary must be the system libevent. A tmux session sets `LD_LIBRARY_PATH=/exec-daemon/tmux-root/lib`, whose libevent has no `evutil_secure_rng_add_bytes`, and `./src/test/test` then will not start.

| Command | Result |
|---|---|
| `make -j4` of the series tip before the review fixes, `--enable-fatal-warnings` | exit 0 |
| `make test` of that tip | `1618 tests ok. (23 skipped)`, exit 0 |
| `make test` of the tip including 0014–0017 | `1618 tests ok. (23 skipped)`, exit 0. 0017 adds assertions inside an existing test, so the count does not grow. |
| Per commit, `git checkout` of each of 0001–0016 in a fresh tree, `./configure --enable-fatal-warnings --disable-asciidoc`, `make -j4 test` | 16 times `OK`. The last log ends `1618 tests ok. (23 skipped)`. `make test` exits 0 only when the suite passes. |
| `./configure --enable-fatal-warnings --disable-asciidoc --disable-module-relay && make -j4 test` | configure reports `relay: no` and `dircache: no`. `1618 tests ok. (23 skipped)`. Dircache is not a separate switch (`configure.ac` ties `BUILD_MODULE_DIRCACHE` to the relay module). `relay_increment_hsdir_*` is called only from `dircache.c`, which is not linked in this build. The dir-request stubs in `relay_stub.c` are the ones this build needs, and they are present. |
| `make check-spaces` | exit 0, before and after 0017 |
| `make check-changes` | exit 0, before and after 0017 |
| `make check-docs` | exit 0. Pre-existing orphan lines (`SOCKSPort`, signals, hidden options). None of the new option names are in the "Not in man page" list. |
| `practracker.py` on stock 0.4.9.14 and on the series tip | Both report 98 problems of the same four kinds (30 dependency-violation, 16 file-size, 108 function-size, 11 include-count). Diff of problem locations with the trailing count removed is empty. No new problem kind and no new location. |
| `git am` of `patches/0001`–`0017` onto `main` at `8dbbbe6e86` | exit 0 |

Targeted tests after 0014, before the later commits: `proto/http/..`, `dir_handle_get/hs_post_size_limit`, `dir_handle_get/malformed_warn_ratelim`, `dir_handle_get/server_discards_extra_input`. 7 tests ok.

Packaging scripts, run as snippets rather than inside a container (this host has no Docker):

| Check | Exit |
|---|---|
| `${REV:?}` unset, as `in-container.sh` does | 127 |
| `${EXPECT_PATCHES:?}` unset, as `build-in-container-reordered.sh` does | 1 |
| `N=17` against `EXPECT_PATCHES=13` | 1, message `staged 17 patches, expected 13` |
| `check` helper with two failing commands | exit 1, `RESULT: FAIL` |

Both extracted `.deb` binaries run on this host (Ubuntu 24.04, glibc 2.39). The resolute binary was built with GCC 15.2.0 and still starts. Each was started with `Sandbox 1`, `SocksPort 0`, and a private `DataDirectory`:

| Package | Seccomp field | `Caught a bad syscall` | Defense defaults |
|---|---|---|---|
| `tor_0.4.9.14-1~noble+1+tor41339.5_amd64.deb` | 2 (filter mode) | 0 | `HSDirOneRequestPerCircuit auto`, `HSDirRefuseUnknownPrevHop auto`, `DoSBeginDirLimitEnabled auto`, `DoSBeginDirMaxStreams 0`, `HSDirDescriptorFetchLimit 0`, rate 5, burst 20 |
| resolute `+tor41339.5` deb | 2 | 0 | same |

`auto` with no consensus parameter is off. `DoSBeginDirMaxStreams 0` means "use the consensus," whose code default is 64, and the limit stays off because `DoSBeginDirLimitEnabled` is auto/0.

The source-built tip (0014–0016, not yet 0017) bootstrapped the one-guard chutney net in 79 seconds and the bridge net's later phases in 4 and 3 seconds. Every live process had `Seccomp: 2`. `Caught a bad syscall` was 0 in every `notice.log`. A second bridge start while the first net still held TCP ports failed with `Address already in use` and was rerun after `chutney stop`. That failure is lab bookkeeping, not a Tor bug.

## Unverified

- Arti's `HsCircPool` behavior, which the issue and the `HSDirOneRequestPerCircuit` manual state as fact. No Arti tree was in this workspace.
- The issue's "~14 KB" descriptor and "~60 byte" 404 sizes. The code splits those responses. I did not measure the bytes.
- A 9,000-relay consensus. The 36-request figure is from `max_dl_per_request()` and `MIN_REQUESTS`, not from a lab of that size.
- Rebuilding `+tor41339.5` with 0014–0017. The host has no Docker, and the build script expects the Ubuntu source package inside a container. The existing debs were checked as shipped.
- `make check-docs` was run once, on the tree that already had the manual edit. I did not rebuild the asciidoc man page (`--disable-asciidoc`). `checkOptionDocs.pl` exited 0.
- Per-commit `make test` was not repeated for 0017 inside the 16-commit loop. 0017's full `make test` on the tip exited 0 separately, and the saturation assertion was run on its own before that.
