# The v8 metrics prototype

This is a prototype of the additions proposed in
`../../analysis/v8-metrics-proposal.md`, built on `+tor41339.7` to measure
what they really cost. It is not part of the series or the packages.

## Files

- **`prototype.diff`:** the change, with its tests. It applies to the `.7`
  tree: tor 0.4.9.14 with `../../patches/0001`–`0023`.
- **`mutants.tsv`:** 47 mutants over every production line the change adds
  or alters, and the reruns of the two that failed to build. Each row gives
  the mutant and its result.
- **`lab/`:** the private-lab run (`run-v8-lab.sh`, `in-lab-v8.sh` and
  `drive-v8.py`) and its results (`lab/results/`).

## What it changes

| file | change |
|---|---|
| `relay_metrics.c`, `.h` | the seven families: counters, entries and fill functions |
| `connection_edge.c` | when a BEGIN_DIR stream closes, writes how it ended into its directory connection, and counts the bytes it took but never sent. `connection_exit_connect_dir()` copies the stream's band and marks to its directory connection |
| `dir_connection_st.h`, `edge_connection_st.h` | 11 bits in existing bitfield words |
| `dircache.c` | marks each onion service request with the rules that would refuse it, and a circuit's directory streams at its first onion service request |
| `dos.c`, `.h` | the BEGIN_DIR stream-rate shadow marks its stream; `dos_hsdir_desc_fetch_allowed()` says whether it would shed |
| `rephist.c`, `.h` | counts circuits when their BEGIN_DIR cells reach each threshold |
| `mainloop.c` | counts the response bytes `conn_close_if_marked()` moves to the stream |
| `directory.c` | counts what a closing directory connection still holds |
| `relay_stub.c` | the stub of the new function, for builds without the relay module |

## Checks

All in-tree, with `--disable-asciidoc --enable-fatal-warnings
--disable-zstd`:
- **Build:** no warnings.
- **Unit suite** (`./src/test/test`): 1640 tests pass, 31 skipped. The
  new tests:
  - `hs_cache/request_position_metrics`;
  - `hs_cache/empty_stream_metrics`;
  - `hs_cache/dos_response_bytes_metrics`;
  - `hs_cache/dir_close_path_bytes`, which drives the real close path
    (`close_closeable_connections()`) with linked connections;
  - more checks in `dos/begindir_refused` and
    `dos/begindir_over_stream_rate`;
  - the series counts in `hs_cache/prev_hop_metric_series`.
- **`make check-spaces`:** clean.
- **practracker, compared with the `.7` tree:** practracker already reports
  98 problems in that tree's stock files. The prototype adds:
  - one include, and a dependency-violation warning, in `mainloop.c`
    (core now includes `relay_metrics.h`);
  - one include in `connection_edge.c`;
  - 23 lines in each of `connection_edge.c` and `rephist.c`, both already
    over their file-size limits.
- **Mutants:** 47, all killed by a test. Two first failed to build under
  `-Werror` (an unused value). Rerun with the value kept, both were killed
  by a test.
- **Struct sizes** (from the binary's debug information):
  - `dir_connection_t` is still 240 bytes;
  - the new bits of `edge_connection_t` fill a hole in an existing word;
  - `or_circuit_t` doesn't change.

## Lab

`lab/run-v8-lab.sh` runs a private chutney network in a container with no
network interface (`--network none`), with every node running the prototype
(`TOR_BIN`). It drives one target HSDir with five load clients, using the
test-only load client of `../../simulator/loadclient-testonly.diff`:

| client | what it does |
|---|---|
| reuse | descriptor fetches multiplexed on shared circuits, through relays |
| onehop-unlisted | one-hop fetches from an unpublished relay identity |
| onehop-client | one-hop fetches from a plain client, answered 503 |
| empty-mixed | on one shared circuit, every second fetch opens its BEGIN_DIR stream and never sends its request; the circuit is closed 35 s in |
| empty-only | on one shared circuit, every fetch's stream stays empty, until a stall timeout (`TestingDirConnectionMaxStall`: 30 s in a test network) |

Without `TOR_BIN`, the nodes run the image's `.7` package: the same load,
as a control.

### Results

The totals below are from `lab/results/v8-prototype-lab24v7.txt`.

- **Requests by place.** The 291 descriptor fetches were at:
  - position 1: 5;
  - 2–10: 31;
  - 11–100: 180;
  - 101–1000: 75.

  The 31 empty streams were at 1 (1), 2–10 (14) and 11–100 (16). That is
  the same 31 as `begindir_request_total{type="no_request"}`.
- **Empty streams.** All 31 were 10–59 s old when they closed:
  - 26 ended with the client's END: for the load clients' streams, when
    their own 30 s stall timeout fired;
  - 5 died with the circuit closed at 35 s;
  - 10 were on circuits that made onion service requests: the empty-mixed
    client's.

  Which end's 30 s timer fires first is a race. In two other runs of the
  same load, ours won instead, and the empty-only client's 20 streams were
  `ended="relay"`.
- **Bytes by rule:**
  - `hsdir_req_reused`: 3,094,420 bytes, the 217 reused requests' 14,260
    bytes each;
  - `hsdir_unknown_prev_hop`: 499,100 bytes, the unpublished identity's 35
    fetches;
  - `hsdir_descriptor_bytes_total`: 3,151,460 bytes, for the 221 fetches
    answered with a descriptor (291 less the one-hop client's 70, answered
    503).
- **Circuits.** In every class, `reached="1"` equals the circuits that sent
  a BEGIN_DIR (5, 7 and 2). The relay class's multiplexed circuit reached
  101.
- **Discarded and pending bytes: 0.** No response was cut off in this run.
  The unit test `hs_cache/dir_close_path_bytes` drives both through the
  real close path.
- **The control.** `lab/results/v7-control-lab24v7.txt` is the same load on
  `.7`. It gives the same answers for what `.7` counts:
  - 217 requests on reused circuits;
  - 35 from the unpublished identity;
  - 186 fetches through relays;
  - nothing unaccounted.

  The breakdown tool's conclusions there end with what `.7` can't say. The
  load differed slightly: the one-hop client sent one request per fetch,
  not two, and there were 30 empty streams, not 31.
- **Warnings.** No bad syscalls, in either run. This load ran six times,
  four with the prototype and two with `.7`. In two prototype runs and one
  `.7` run, the target logged "connection_edge_process_relay_cell (away from
  origin) failed", 1 to 5 times. Each came right after "Client asked me to
  extend back to the previous hop": tor's own refusal of such an EXTEND
  (`circuitbuild_relay.c`), which a small test network's path selection hits
  by chance. It doesn't involve BEGIN_DIR.
