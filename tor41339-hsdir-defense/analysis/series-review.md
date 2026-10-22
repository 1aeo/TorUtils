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

## Round 2

Reviewed the 15-patch series on `tor41339-hsdir-defense-clean` (`4bebda3`) after merging it into `tor41339-series-review` with a merge commit. The series applies with `git am` on tag `tor-0.4.9.14` (`8fe2745aee2c`) and on `main` at `8dbbbe6e86`. Line numbers are stock 0.4.9.14 unless the sentence says the series tree. One follow-up commit, `patches/0016`, fixes the heartbeat wording below. It is not in the `+tor41339.6` packages.

### Commit verdicts

| Commit | Verdict | Why |
|---|---|---|
| 0001 | Agree | Unchanged from round 1. The rate-limit test is still `TT_FORK`. |
| 0002 | Agree, with the same false rationale | The body cap is `min(16 MB, HSV3MaxDescriptorSize)` for non-authorities (`directory_handle_command()` in the series tree). Stock `fetch_from_buf_http()` still does not compare `Content-Length` to the limit until the body is buffered. See decision 4. 0015 is the early reject, so dropping it from 0002 is fine. |
| 0003 | Agree | Unchanged. A partial request stays in `COMMAND_WAIT`. |
| 0004 | Agree | Unchanged. Length is checked before the signing-cert parse. |
| 0005 | Agree | Credit moved to `connection_dir_finished_flushing()` after the `marked_for_close` return. Series `directory.c` around the flush handler. |
| 0006 | Agree | `-2` is only the not-newer path. See decision 3. |
| 0007 | Agree | Linked checks only. The DirPort assertion is in `test_hs_cache.c` (`directory_handle_command_get` / `post` on an unlinked connection, then the metrics stay put). |
| 0008 | Agree | The gauge requires `c->linked`, so an ordinary exit is not `draining`. A linked exit counts as `draining` only when its directory side is gone or marked. The gauge test keeps `conn_array_index` consistent with `connection_remove()`. |
| 0009 | Agree | Table lists the same stock counters. No value changes. |
| 0010 | Agree | `n_hsdir_requests` is a 2-bit field (`or_circuit_st.h`), zeroed by `tor_malloc_zero` in `or_circuit_new()` (`circuitlist.c:1140`). The series test asks four times and expects the field to stay at 2. |
| 0011 | Agree | `dos_defense_enabled()` is the stock single-hop function with the parameter name passed in. See decision 5. The reuse close is accounted once. See decision 6. |
| 0012 | Agree | BEGIN_DIR only, default 64, public relays only, counted either way. The integration test takes a linked connection off the active linked list before `connection_free_()`. The mark-down sentence matches `dirclient.c:727` and `channel.c:1936`. See decision 7. |
| 0013 | Agree | Count-only. `dos_hsdir_desc_fetch_allowed()` is not called from this commit. The bucket is copied on replace (`hs_cache.c` in the series tree, the `fetch_limiter` assignment next to `n_downloaded`). The test replaces a descriptor and expects the next fetch, in the same second, to still be over rate. Never refuses. |
| 0014 | Agree, with one cost caveat | The state machine matches the man page. See decision 8. No division by zero: shedding requires `asked > budget`, and `first <= budget/2`, so the denominator is positive. `CLAMP` is `(min, v, max)` (`src/lib/intmath/cmp.h:34`). |
| 0015 | Agree | `max_bodylen <= contentlen` in the `!force_complete` branch (`proto_http.c` in the series tree). `force_complete = 1` still returns the bytes it has. The changes text names every caller that does not set `force_complete`. |

`connection_add_impl()` still always returns 0 (`src/core/mainloop/mainloop.c:244` through the `return 0` at `:271`, same on `main`). The `< 0` branches in `connection_exit_connect_dir()` (`connection_edge.c:4722` and `:4740` in the series tree) are unreachable. The round-1 "count the stream after `connection_add()`" fix was correctly left out. `tor_event_new` is still not checked, and a NULL event would not make the function return -1.

### Decisions

#### 1. Metric families

**Agree.** Outcomes are their own families, on the pattern of `tor_relay_intro1_total{action}`. The open-connection series is a gauge. Increments are behind `linked` or behind `connection_dir_is_anonymous()`, which requires a linked edge. A DirPort connection fails that check. The issue text matches.

#### 2. Keep `hsdir_request_total`?

**Agree, keep it.** It is the anonymous subset, not the sum of the GET and POST families:

`hsdir_request_total = (every hsdir_get action except single_hop) + (every hsdir_post action except single_hop)`

`note_hs_dir_request()` runs only after the anonymity check. `single_hop` is the failure of that check, including a circuit that is already marked. The canary already graphs the dos-family name.

#### 3. `hs_cache_store_as_dir()` returns -2

**Agree. Callers are still correct.** `cache_store_v3_as_dir()` returns -1 only from the revision-counter reject. A failed decode leaves `ret` at -1. The POST handler switches on 0, -2, and default (`dircache.c` in the series tree). `test_hs_cache.c` and `test_stats.c` expect -2 for a duplicate and -1 for junk. No other production caller.

#### 4. Does stock reject `contentlen >= max_bodylen` on every path?

**Disagree for the header-only path. Agree that 0002 no longer needs its own early reject.** Stock rejects once `bodylen >= max_bodylen` (`proto_http.c:86`) before it parses `Content-Length` (`:92`). A declared length over the limit with a short body returns 0 while `force_complete` is 0. The directory server passes `force_complete = 0` (`dircache.c` in the series tree, the `connection_fetch_from_buf_http` call). 0015 rejects `contentlen >= max_bodylen` in that branch for every such caller. Callers that pass `force_complete = 1` still accept a short buffer. The equality is tested: a declared length equal to `hs_cache_get_max_descriptor_size()` is refused before any body byte.

#### 5. Is `dos_defense_enabled()` an acceptable touch of stock code?

**Agree.** Stock `dos_should_refuse_single_hop_client()` (`dos.c:1009` in 0.4.9.14) is: not a public relay, then the torrc value when it is not -1, else the consensus parameter defaulting to 0. The helper is that sequence. `public_server_mode()` is `server_mode() && !BridgeRelay` (`routermode.c:43`). The single-hop test still requires the stock parameter name.

#### 6. Reuse close, with no HTTP response

**Agree, counted once.** `directory_handle_command_get()` sets `SERVER_WRITING` before the handler. On the second request, `allow_hs_dir_request()` marks the circuit and returns false. The handler increments `refused` and returns. No response is queued. `connection_dir_about_to_close()` increments `unparsed` only in `COMMAND_WAIT`, so this close is not `unparsed` and not `success`. A later request on that circuit, still inside the same loop, fails `connection_dir_is_anonymous()` because the circuit is marked (`directory.c:249`) and is counted `single_hop`. See decision 8 for why that 503 is not delivered.

#### 7. BEGIN_DIR ceiling instead of an exit-wide rate

**Agree that dropping the rate is right, and that 64 off by default is acceptable.** `connection_exit_begin_conn()` still returns from the BEGIN_DIR branch before `dos_stream_new_begin_or_resolve_cell()`. The resource held is the linked pair, which ConnLimit does not count. A rate without a live cap does not free those pairs.

The default 64 is above what a client holds open at once. `max_dl_per_request()` returns 500 when `dirclient_must_use_begindir()` (`routerlist.c:2531`), and `router_is_already_dir_fetching()` ignores tunnel connections (`node_select.c:247`). Those constants bound how many hashes go in one URL. They do not say 36 streams are open together. Round 1, on this same client code, measured a maximum of 1 concurrent BEGIN_DIR on a one-guard client and 2 on a bridge. This round's basic-min client never had more than one origin stream open, on one circuit, across the bootstrap poll in the lab section. A refused BEGIN_DIR sends `END_STREAM_REASON_MISC` and never calls `connection_exit_connect_dir()`, so it is not in `streams_total`. The client fails that request. For a non-onion-service fetch, `connection_dir_client_request_failed()` marks the relay down (`dirclient.c:727`) unless `entry_list_is_constrained()`. `channel_do_open_actions()` clears that only when we opened the channel (`channel.c:1936`: `started_here = channel_is_outgoing(chan)`, then `router_set_status(..., 1)` at `:1938`). The manual says "until it next connects to this relay", and "it" is the client. That matches. An onion-service purpose skips the mark-down. The option is off unless the operator or the consensus turns it on. That is an acceptable footgun for an off-by-default limit.

#### 8. Count-only rate, then pressure-gated shedding

**Agree the machine does what it says. The byte cost of driving the lottery toward zero is lower than the asked-byte formula.**

No fetch is refused until some second has `asked > budget`. In that second the relay still answers until `answered` would pass `budget * 3 / 2`, and a single descriptor larger than that is served because the cap is skipped while `answered == 0` (`dos.c` in the series tree, `dos_hsdir_desc_fetch_allowed()`). The next consecutive second sheds. A gap of two seconds clears it (`now == sec + 1` fails). One quiet second of shedding after a spike is the tradeoff against cutting the over-budget second itself: the flood second still completes up to one and a half budgets, and only the following second pays the lottery. An every-other-second flood never enters a shedding second, and is held to 1.5× in each flood second. The tests cover that.

`asked += len` happens before the shed branch, including for fetches that are not served. After the 1.5× cap, further GETs increase `asked` without a response. The next second's odds are `(budget - first) / (asked - first)` with `first = min(asked_light, budget/2)`. Filling the half-budget of within-rate fetches and then adding shed GETs is the known `(budget/2) * (1 + 1/p)` in descriptor-bytes asked. The relay does not send those extra descriptor bytes. Concrete case: budget 1 MB, descriptors 10 KB. The attacker gets 150 answers in a non-shedding second (1.5 MB served) and then 10,000 more GETs that hit the cap. `asked` is about 101.5 MB. The next second's lottery is about 0.5% for a fetch that is not answered first. The relay's extra response cost for that dilution is zero. CPU and the request bytes remain. Arming the defense still costs on the order of one budget of served descriptor bytes, which is the "about as much as overloading the relay" part. I did not find a path that denies a cached descriptor with high probability without first causing a second that serves up to 1.5× the budget. Misses never enter `dos_hsdir_desc_fetch_allowed()` (the lookup fails first). Burning the victim's burst is cheap (one token per shed GET) and only moves the victim from the first-class half into that same lottery.

Shedding the second after an over-budget second, even if that second is quiet, is the right tradeoff against FCFS inside the flood second. FCFS would let the sender who filled the previous second also win the next one by arriving first. The cost is one second of lottery for everyone, including a victim whose own rate still has tokens, once other within-rate fetches have used half the budget. The code clears shedding as soon as a second stays within budget. It does not stick.

The automatic budget is sensible. `bwhist_bandwidth_assess()` is 0 until history exists (`bwhist.c:241`, maxima from `bwhist_load_state()` at `:511`). The series uses observed bandwidth only when it is greater than 0, otherwise the configured rate, then at least 512 KB. A new relay cannot be an HSDir yet: the flag needs `MinUptimeHidServDirectoryV2` of 96 hours plus Stable, Fast, and Running (`dirauth_options.inc`, `voteflags.c:160`). The 512 KB floor can sit above a tiny configured rate. The relay's bandwidth token bucket still limits the bytes. The floor makes shedding less aggressive, not more.

Closing the circuit instead of sending 503 is right. `DIR_503_TIMEOUT` is `60*60` (`routerlist.h:49`). A 503 sets `last_dir_503_at` (`dirclient.c:2127`). The shed path writes no response; it marks the circuit `END_CIRC_REASON_RESOURCELIMIT`. For a stock client the circuit is the one BEGIN_DIR from `ISO_STREAM` (`dirclient.c:1389`), and the purpose is an onion-service fetch, which does not mark the relay down.

A sibling request already queued on that circuit is counted `single_hop`, not `refused`. **Agree, leave it there.** `connection_dir_is_anonymous()` returns false when the circuit is marked, before `note_hs_dir_request()`, so the request is not in `hsdir_request_total`. Counting it as `refused` would break `hsdir_request_total = hsdir_get + hsdir_post - single_hop`. The 503 that the handler queues is not sent: `connection_edge_send_command()` returns -1 when the circuit is marked (`relay.c:799`), and `append_cell_to_circuit_queue()` returns 0 (`relay.c:3460`). `last_dir_503_at` is not set. This is the circuit-reusing case. Stock anonymous directory requests do not share a circuit.

The consensus parameter can turn shedding on for every public relay. The leak exists only while someone pays to keep that HSDir over budget, which is a different oracle from the old per-descriptor refusal on an idle relay. Default 0, and the manual states the leak. I would not flip it network-wide until that leak is an accepted cost. **Agree the parameter may exist. Disagree with treating the name as final.** `HSDirDescriptorFetchLimit` used to mean "refuse over the per-descriptor rate". It now means "shed when over the byte budget". Nothing upstream has shipped the name. The private `.5` torrcs are why this series kept it. Rename before an upstream proposal. I did not rename it here.

#### 9. Heartbeat wording

**Disagree, and fixed.** The notice is "DoS mitigation since startup" (`dos.c` in 0.4.9.14, the `dos_log_heartbeat` format string; the series keeps it). The fragments for BEGIN_DIR ("over the limit"), repeated circuits, and unknown previous hops do not say the defense refused them, and the counters increment either way. The shed line said "fetches shed". That counter increments on the shed label before `return !dos_should_shed_hsdir_fetches()`, so a fetch answered while the option is off is included. After a long disabled period, enabling the option makes the heartbeat report those serves as sheds. 0016 prints "over the shed threshold" instead. The disabled line is still `[HSDirDescriptorFetchLimit disabled]`.

### Accounting on a public relay

`streams_total{BEGIN_DIR}` counts inside `connection_exit_connect_dir()`, after the BEGIN_DIR refusal return. Every accepted stream is then either still in `command_wait` or has been classified:

- HS GET and POST take the `hsdir_*` families, including `refused` and `single_hop`.
- Anything else linked is `dir_requests` (`non_hs`, or `unparsed` for a bad URL, an unknown method that stays in `COMMAND_WAIT` until close, or a close from `COMMAND_WAIT`).
- A success still in `SERVER_WRITING` with `hs_ident` set is in `hsdir_get{success}` and in the `writing_hs_descriptor` gauge, not in `command_wait`.

That holds. These paths do not:

- A BEGIN_DIR refused by 0012 never reaches `streams_total`. It is only `begindir_over_max`. Leave it out of the identity. The issue, which does not discuss enforcement, correctly omits it.
- A non-public POST writes 503 and increments nothing (`directory_handle_command_post()`, the `public_server_mode` check). That relay is not public. The identity is for a public relay. Document, do not count it as a public-relay hole.
- `connection_add()` cannot fail, so the connect-dir error branches do not drop a counted stream.
- Identity 2's remainder is responses queued and not fully flushed. `connection_dir_finished_flushing()` runs when the outbuf is empty, so some bytes may already have been handed to the exit. The issue now says "not fully written out" rather than "abandoned before hand-off".

`hsdir_get{success} - dir_responses{hs_descriptor} - dir_server_conns{writing_hs_descriptor}` is that remainder, plus scrape timing. DirPort HS requests are not in either side.

### Lifetimes

`note_hs_dir_request()`, `allow_hs_dir_request()`, and the shed close run only after `connection_dir_is_anonymous()` has required a linked edge that is not marked, an OR circuit that is not an origin and not marked, and a non-NULL `p_chan` (`directory.c:211` through `:266`). Both the encrypted check and that walk happen first, on GET and on POST. The gauge does not follow `on_circuit` or `p_chan`. `hs_cache_get_dir_fetch_limiter()` is called only after a lookup that just returned the descriptor, on the same thread. A marked circuit takes the `single_hop` branch and does not touch `p_chan`.

### Tests and mutants

New tests mock `monotime_coarse` and, for the lottery, `hsdir_fetch_lottery_draw`. The shedding tests and the HS cache tests are `TT_FORK`, so the static `hsdir_fetch` struct starts at zero. I mutated the built tree and restored it:

| Mutant | Result |
|---|---|
| Consensus parameter spelled `HSDirDescriptorFetchLimitt` | Caught. `dos/hsdir_fetch_shedding` expected a refusal and got an answer (`test_dos.c:905`). |
| `linked` check on non-HS dir requests inverted | Caught. `hs_cache/dir_request_response_metrics` expected 2 `non_hs` and got 1. |
| `asked <= budget` changed to `asked < budget` | Caught. Three exact-budget seconds counted pressure 3 instead of 0. |
| Shed handler's `goto done` removed | Caught. `hs_cache/hsdir_desc_fetch_shedding` saw an HTTP 200 body instead of an empty reply. |
| Lottery numerator uses `hsdir_fetch_budget()` (the new second) instead of the previous second's budget | Not caught. `dos/hsdir_fetch_shedding` and `dos/hsdir_fetch_shedding_edges` passed, 2 tests ok. The tests keep the budget constant across the second boundary where they check the odds. |

The half-budget cap, the 1.5× count of 15, the 1000-ppm floor, the bridge that counts and does not refuse, and the descriptor-replace bucket are all asserted. I did not find a non-forked test that leaks the new static counters.

### Build and packaging

Commands were `./configure --enable-fatal-warnings --disable-asciidoc` and `make -j4 && make test` on each commit from 0001 through 0015, then `make check-spaces`, `make check-changes`, and `make check-docs`. Started 8:51 AM PT, finished 8:55 AM PT on 22 October 2026. Every commit passed. Counts, 23 skipped throughout: 1604, 1605, 1606, 1606, 1608, 1609, 1610, 1611, 1611, 1612, 1615, 1617, 1618, 1621, 1621. `check-docs` exited 0. It prints the stock "Not in man page" and "Orphaned in man page" lists; the new option names are not in the missing list.

`python3 scripts/maint/practracker/practracker.py` on the series tip and on stock both exited 98, with the same four kinds (`function-size` 59, `file-size` 11, `dependency-violation` 22, `include-count` 6). Stripping the trailing counts, the location sets are equal. `dos.c`'s dependency-violation exception is 8 in the series and 6 in stock, and `dos.c` is not a new problem line. `directory_handle_command_post()` is a warning at 136 lines in the series and 125 in stock, same location.

The tip with `--disable-module-relay` (`HAVE_MODULE_RELAY` unset in `orconfig.h`) passed `make test`: 1621 ok, 23 skipped, exit 0. That tree includes 0016.

`git am` of `patches/0001`–`0015` on `main` at `8dbbbe6e86` applied all 15.

Packaging, this host has no Docker, so the container scripts were not executed. Fail-closed checks of the same shell forms:

- `REV` unset, as `in-container.sh` does with `set -u`, exits 127.
- `EXPECT_PATCHES` unset, as `build-in-container-reordered.sh` does, exits 127 and prints the "set EXPECT_PATCHES" message.
- `in-container.sh` checks 8 option names and 26 metric series (`8 + 4 + 6 + 2 + 2 + 4`) and ends with `exit $fail`, so a failed `check` prints `RESULT: FAIL` and a nonzero status.

Both `+tor41339.6` binaries start on this host. `--dump-config full` with `DisableNetwork 1` shows, for noble and for resolute: `HSDirOneRequestPerCircuit auto`, `HSDirRefuseUnknownPrevHop auto`, `DoSBeginDirLimitEnabled auto`, `DoSBeginDirMaxStreams 0`, `HSDirDescriptorFetchRate 5`, `HSDirDescriptorFetchBurst 20`, `HSDirDescriptorFetchLimit auto`, `HSDirFetchBudget 0`. `auto` with no consensus parameter is off.

A private chutney `basic-min` network (four authorities, one exit, one client), `Sandbox 1`, listen address loopback, generated directory authorities checked as loopback-only before start. Noble binary and resolute binary each bootstrapped. `Caught a bad syscall` was 0 in every notice log. Each live process had `Seccomp` 2. The generated torrcs set `Sandbox 1` and do not set the eight defense options, so the defaults above are what ran. Chutney's stop needed its own SIGKILL after SIGINT; that is the stop helper, and the syscall count was taken before it.

A second basic-min run with the noble binary polled the client's control socket for origin streams through bootstrap (855 samples). The most streams open at once was 1, all on one circuit. That bounds concurrent BEGIN_DIR streams on that client by 1. It is not a bridge and not a single configured directory guard.

Client-lab: Docker is not installed, so `engineering/client-lab/run-client-lab.sh` was not re-run. The script exits nonzero if the image is missing, a client cannot bootstrap, or a baseline fetch fails (`RESULT: FAIL` if the container exits without `RESULT: PASS`). The checked-in `.6` transcripts match the README table: C1 is 20/20 and 39/40, C3 is 19/20 and 37/40, together 115 of 120, shed counts 1487, 1395, 2900, and 2768 equal `refused`, and C0 shed counts are 2920 and 2870. Those transcripts are from the packaged `.6` image, not from a run in this review.

### Issue text

`patches/gitlab-metrics-issue.md` does not mention patches, code changes, or enforcement. The stock claims checked out: the stream is counted in `connection_exit_connect_dir()` before any HTTP request; BEGIN_DIR returns before the known-relay check (`connection_edge.c:4210` is inside `if (!bcell.is_begindir)`); anonymized directory fetches use `ISO_STREAM` (`dirclient.c:1389`); HS fetches use `DIRIND_ANONYMOUS` (`hs_client.c:416`, `hs_service.c:4051`); `TestingDirConnectionMaxStall` defaults to 5 minutes (`config.c:775`). Two sentences were loose and are now tighter: a 503 queued on an already-marked circuit is not sent (`relay.c:799`), and the success-minus-response remainder is "not fully written out", not "before any byte was handed off".

### Findings, by severity

1. **Medium, design, not changed.** Once a second has served 1.5× the budget, more GETs still increase `asked` and so the next second's lottery denominator, without the relay sending those descriptors (`dos_hsdir_desc_fetch_allowed()`, the `asked += len` before the cap). Denying one descriptor to a small probability costs request processing on top of one arming second, not `(budget/2)*(1+1/p)` of served bytes. The odds match the comment, which is about demand, and the relay's served bytes stay capped. I would not change it in this series. An upstream writeup should say the formula is in descriptor-bytes asked, not bytes sent.

2. **Low, fixed in 0016.** The heartbeat said "fetches shed" for a counter that includes fetches still answered while shedding is off. Failure: run an hour with the option off under load, then enable it; the next heartbeat reports those serves as sheds.

3. **Low, issue text only.** The metrics draft said a closing circuit is "answered 503" and that the success remainder was "abandoned before hand-off". The 503 is queued and then dropped with the circuit. The remainder includes a partial flush. Both sentences are corrected. No relay code change: moving those requests to `refused` would break the `hsdir_request_total` identity, and the 503 does not reach the client.

4. **Low, test gap.** A mutant that computes lottery odds from the new second's budget instead of the previous second's survives while the tests hold the budget constant. The code uses the previous second, which is what the comment says. No production change.

### Unverified this round

- Re-running `engineering/client-lab/run-client-lab.sh`. No Docker. The README numbers were checked against the stored `.6` transcripts, not against a new run.
- A bridge, and a client limited to one directory guard, measured again. Round 1's figures for those two cases stand. This round measured the basic-min client only.
- Arti's `HsCircPool`, still with no Arti tree here.
- Rebuilding the `.6` packages with 0016. The packages stay 0000 plus 0001–0015.
- `make check-docs` on stock, to diff the orphan list. The series run exited 0 and did not list the new options as missing.
