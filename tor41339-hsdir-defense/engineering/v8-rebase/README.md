# The rebase onto tor 0.4.9.15 (`+tor41339.8`)

`.7` was 23 patches on tor 0.4.9.14, plus a Debian-only option alias. Tor
0.4.9.15 (tor#41411) added BEGIN_DIR defenses of its own, so the series is
now 20 patches on tor 0.4.9.15 (`../../patches/`). This directory has the
checks of the result.

## What changed from `.7`

| `.7` | `.8` | Why |
|---|---|---|
| 0010 counted `hsdir_req_reused`, `hsdir_circ_reused` and `hsdir_unknown_prev_hop`, before any rule | 0010 counts `hsdir_unknown_prev_hop` only, after tor's limit of one HSDir request per circuit | Tor now refuses a circuit's second HSDir request, as `begindir_hsdir_rejected`. Counted after that limit, `hsdir_unknown_prev_hop` is exactly what `HSDirRefuseUnknownPrevHop` refuses or would refuse |
| 0011 `HSDirOneRequestPerCircuit` and `HSDirRefuseUnknownPrevHop` | 0011 `HSDirRefuseUnknownPrevHop` only | Tor's own rule is always on |
| 0012 `DoSBeginDirLimitEnabled` and `DoSBeginDirMaxStreams`: at most 64 open directory streams per circuit; 0019 counted the requests over it by type | dropped | `begindir_over_max` stayed at 0 in every flood saved from `.7` relays: no circuit held 64 open directory streams. Tor 0.4.9.15 also uses the name `DoSBeginDirLimitEnabled` for a consensus parameter of its own |
| 0023 `begindir_over_stream_rate` | dropped | Tor's BEGIN_DIR rate limit refuses and counts those cells |
| 0006 the HSDir action `circuit_dead` | dropped | Tor drops a request on a closing stream or circuit before parsing it, so the action could never count. 0015 counts those requests as the request type `circuit_dead` |
| Debian-only 0024, the `HSDirDescriptorFetchLimit` alias | dropped | `.7`'s option names need not keep working |

`.7`'s 0013–0018 are `.8`'s 0012–0017, and `.7`'s 0020–0022 are `.8`'s
0018–0020.

## The review

A reviewer read the rebased series through git objects only, with no build. It found no functional bug, and seven documentation or test problems, all fixed:

1. **0006:** `circuit_dead` could not be counted, yet the test counted it, by calling the handlers directly. The action, its code and that test path are gone.
2. **0013:** the doc of the action `refused` left out shedding. It now names it.
3. **0015:** the message said 45 more series; the net is 43 (its 27 request series replace 0007's 2).
4. **0017:** the response-bytes test left out the request type `circuit_dead`. It is in.
5. **0010, 0011 and 0015:** their messages said `hsdir_unknown_prev_hop` shows what `HSDirRefuseUnknownPrevHop` would refuse. The count included second requests on a circuit, which tor refuses first.
   - It now runs after tor's limit, so the claim holds.
   - The counter test checks both handlers' order: a second GET and a second POST on a circuit aren't counted.
   - The defense test checks that the count is the 503s, plus what the defense would have refused while off.
6. **`.7`'s 0019 (dropped):** its message pointed at the wrong count of refusals.
7. **0002:** its message said BEGIN_DIR streams aren't subject to DoSStreamCreation. It now names the 0.4.9.15 rate limit, which bounds how fast each circuit opens streams, not how many circuits open them.

## Checks

- **`per-commit.txt`:** every commit, built with `--enable-fatal-warnings`:
  - no compiler warning;
  - `check-spaces` and `lintChanges.py` clean;
  - the full unit suite passes: 1605 to 1641 tests, 31 skipped.
- **`practracker.txt`:** after every commit, practracker reports the same 98 problems as stock 0.4.9.15. Two exceptions change:
  - 0007 raises `directory_handle_command_post()`'s from 124 to 138 lines;
  - 0013 raises `dos.c`'s dependency-violation count from 6 to 8.
- **Applying the patches:**
  - `git am` onto `tor-0.4.9.15` gives the branch's tree exactly;
  - `git am -3` onto tor `main` at a0062a3e3e (2026-10-28) applies all 20.
- **At the tip:**
  - `check-includes`, `check-docs`, `check-logs` and `check-changes` pass;
  - `check-best-practices` exits with practracker's 98 problems, as on stock;
  - with `--disable-module-relay`, the tip builds with no warning and passes the unit suite (1641 tests, 31 skipped).
- **`mutants.tsv`:** 19 mutants over every line the rebase added or changed, each killed by the test meant to catch it. They cover:
  - the action counts;
  - the place of `hsdir_unknown_prev_hop` relative to tor's limit and to `HSDirRefuseUnknownPrevHop`, for GET and POST;
  - the defense itself;
  - the `circuit_dead` request type;
  - where BEGIN_DIR cells are counted, relative to tor's directory-cache check and rate limit;
  - the response bytes of untyped requests;
  - the descriptor-only split.
