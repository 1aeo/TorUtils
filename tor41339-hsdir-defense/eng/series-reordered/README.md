# Reordered series (0002 before 0001)

These are the 7 v3 patches, reordered so that the known-previous-hop rule
comes **before** the one-request-per-circuit rule. Apply them with `git am`.
They apply cleanly onto tor `main` (8dbbbe6e86), `maint-0.4.9` (ccd9eb8611)
and the `tor-0.4.9.14` tag.

| # here | Was | Subject |
|---|---|---|
| 0001 | 0002 | hsdir: Refuse HS dir requests whose previous hop is not a known relay |
| 0002 | 0001 | hsdir: Serve one onion service directory request per circuit |
| 0003–0007 | 0003–0007 | unchanged order |

**Backport note:** do not backport "Serve one onion service directory
request per circuit" without "Refuse HS dir requests whose previous hop is
not a known relay". The commit message of the one-request-per-circuit commit
says so.

## What changed versus `patches/` (v3), mechanically

- **Identity.** All 7 commits are `From: 1aeo <github@1aeo.com>` and carry one
  identical `Co-Authored-By` trailer. That was already true of v3, so nothing
  was re-authored.
- **Hunks split by hand.** The 0002 hunks that overlap 0001 in dos.c/h,
  dos_options.inc, dircache.c, directory.c/h, relay_metrics.c, tor.1.txt,
  test_status.c and test_hs_cache.c were split. The known-previous-hop commit
  now carries only its own code.
- **Test support moved into the known-previous-hop commit.** Its unit test
  needs the `get_dos_options()` test helper (opts_test_helpers.c/.h) and six
  includes in test_hs_cache.c. In v3 those came with 0001, so they now move
  into this commit, at the positions they have in the final file.
- **Wording, mechanical only.** "the previous commit" and "the next commit"
  were swapped in the two commit messages. The known-previous-hop commit's
  dos.c comment no longer refers to an option that does not exist yet at that
  point in the series.
- **practracker.** Each commit now carries the exceptions.txt bump it needs:
  - known-previous-hop commit: `directory_handle_command_post()` 124 → 130;
  - one-request-per-circuit commit: the same function 130 → 132;
  - hs_desc signature-length commit: adds `hs_descriptor.c` file-size 3153,
    next to v3's existing `desc_decode_plaintext_v3()` 102 entry.

  Measured against an empty exceptions file, the series introduces no
  practracker problem beyond these. The rest of upstream's exceptions.txt is
  already stale on `main`: 99 problems exist at the base, before any patch.
  `practracker-full-regen.txt` is a full `--regen` of the final tree, for
  reference only. It is not part of the series.
- **Final tree.** It is byte-identical to v3 plus those three
  exceptions.txt lines (`git diff v3 v3-reordered` touches only
  `scripts/maint/practracker/exceptions.txt`).

## Per-commit validation

The log is `per-commit-SUMMARY.txt`. Each commit was built with
`--enable-fatal-warnings` (gcc 13.3, amd64) and run through `make check`,
`make check-spaces` and `make check-changes`. The `PYTHONUNBUFFERED`
variable is unset so practracker's self-test is not perturbed. See
`../README.md` for why that matters.

### Result

All 7 commits pass, in order. Each one builds with 0 warnings under
`--enable-fatal-warnings`, `make check` returns 0 with no failures, and
`make check-spaces` and `make check-changes` both return 0. Unit tests ok per
commit: 1603, 1604, 1605, 1606, 1611, 1611, 1613. Details are in
`per-commit-SUMMARY.txt` and `per-commit-logs/`.

The first attempt at the reorder had a broken first commit: its test used the
`get_dos_options()` helper and dos/config includes that only arrived with the
next commit. It failed with `-Werror` implicit-declaration; the log is
`per-commit-logs/attempt1-commit1-BUILD-FAILURE.log.gz`. The fix moved that
helper and those includes into the first commit. The final tree was
unchanged.
