# Records of the `+tor41339.7` reviews

The reviews themselves, their findings and what changed are in
`../../analysis/v7-review.md`. Every build here was in-tree with
`--disable-asciidoc --enable-fatal-warnings --disable-zstd`.

## Round 1 (`round1/`): the nine commits the first `.7` added

These records use that round's numbering and names:
- round 1's 0016 (the heartbeat wording) is now part of 0014;
- its 0017–0024 are now 0016–0023;
- for metric names, see the rename table in the review.

**`per-commit.txt`:** each of the nine commits. Each line gives:
- the compiler warnings (0);
- the whole unit suite (`./src/test/test`);
- `make check-spaces`.

**`mutants.tsv`:** the mutation pass over every new or changed production
line of those commits. Each row gives:
- `file:line`, the commit the line belongs to (from `git blame`), the
  mutant and its result;
- the test that kills it, or why the mutant is equivalent.

How to read the results:
- "survived; killed by new test" means the mutant passed the tests as first
  written and fails on the test now in the series;
- "build-fail" counts as killed under `-Werror`;
- the ids ending in `v` are those build-fails rerun with the unused variable
  cast to `void`.

## Round 2 (`round2/`): all 23 commits, after round 2's changes

**`per-commit.txt`:** the final series, one line per commit, as in round 1.
The hashes are those in the `From` lines of `../../patches/`.

**`mutants.tsv`:** 343 mutants over every production line round 2 added or
changed. They ran against the reviewed tree, so line numbers and some names
are from before the final renames (`hsdir_request`, `lookup="missing"`,
`RELAY_METRICS_DIR_SERVER_CONNS`, ...). Each row gives:
- the id, `file:line` and patch;
- the mutant;
- its result: `killed`, `survived; killed by new test`, `equivalent` or
  `build-fail`;
- the killing test or the equivalence reason.

**`gap-mutants-final.tsv`:** 29 mutants, each with its result at the final
tip:
- 23 of the 25 that only round 2's new tests kill, re-targeted to the final
  code. The other two were on the dropped `hsdir_request` label and no
  longer apply.
- Three of round 2's killed mutants on the same lines.
- Two on the `not_found` label.
- R2-FA-10, equivalent until 0014's dead store of the lottery odds was
  removed.

**`stock-bugs/`:** fixes for two stock tor bugs found by the bugs review.
They are not part of the series.
