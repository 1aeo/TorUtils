# Rebuild the noble `.deb` from the current series (`+tor41339.3`)

The `.deb` in `../../packages/` is `+tor41339.2`, built before the patch 0002
call-order fix and the two new count-only MetricsPort counters
(`hsdir_req_reused`, `hsdir_request_total`) landed in `../../patches/0002-*.patch`.
It therefore exposes only two of the four `tor_relay_dos_total{type="hsdir…"}`
counters the operator runbook now references. This runbook rebuilds it from the
current series so the binary, the `debian-patches/` build copy, and the docs all
agree.

## Requirements

- An **amd64** host with Docker (the build runs in a fresh `ubuntu:24.04`
  amd64 container). The Mac-Studio bridge is arm64 — either use an amd64 Linux
  Docker host, or `docker run --platform linux/amd64` under emulation (slower).
- Network access for `apt-get` build-deps and to fetch the noble source package.

## Inputs

- The current series: `tor41339-hsdir-defense/patches/0001-*.patch … 0007-*.patch`
  (these already include PR #3's updated 0002) plus
  `engineering/deb/build-reordered/debian-patches/0000-restore-doc-nofooter.conf.patch`.
- The deb.torproject.org **noble** source for `tor_0.4.9.14-1~noble+1`:
  `tor_0.4.9.14.orig.tar.gz` (sha256
  `182449ac1c8ff43278da27b69b02040e11d03d0327db6d9126e4190ec6235e4a`, identical
  to dist.torproject.org), `tor_0.4.9.14-1~noble+1.diff.gz`, and
  `tor_0.4.9.14-1~noble+1.dsc`.
- The build driver `engineering/deb/build-reordered/build-in-container-reordered.sh`.

## Steps

1. Stage `/in` with the three source files above + `0000-*.patch` + the current
   `0001..0007-*.patch` from `patches/`.
2. In `build-in-container-reordered.sh`, bump the version and changelog:
   `dch -v 0.4.9.14-1~noble+1+tor41339.3 -D noble "Apply tor#41339 HSDir-flood
   defensive series (0001-0007, v3 reordered); add count-only hsdir_req_reused /
   hsdir_request_total MetricsPort counters and fix the 0002 handler call order;
   restore doc/nofooter.conf."`
3. Run it: `docker run --rm -v /in:/in:ro -v /out:/out ubuntu:24.04 bash /in/build-in-container-reordered.sh`.
   Expect `dh_auto_test` green (≈1613 tests).

## Verify (fresh container)

Install the new `.deb` + `tor-geoipdb`, then on a **private loopback** chutney
net (never the real network): `tor --verify-config`, bootstrap to 100% under
`Sandbox 1`, and confirm **all four** counters are present:
```
curl -s http://127.0.0.1:9035/metrics | grep 'tor_relay_dos_total{type="hsdir'
# must show 4 lines: hsdir_circ_reused, hsdir_req_reused, hsdir_request_total, hsdir_unknown_prev_hop
```
with both enforcement options `auto` (count-only), 0 bad syscalls, and the two
`hsdir_*` enforcement counters at 0 over 120 s.

## Deliverables (regenerate together so nothing diverges)

- `../../packages/`: the new `tor_…+tor41339.3_amd64.deb`, `tor-geoipdb_…+tor41339.3_all.deb`,
  `.buildinfo`, `.changes`, refreshed `SHA256SUMS`, and update
  `code-identity-vs-tor41339.1.txt` (or add a `.2`↔`.3` identity note — code
  should differ now, since the counters are new).
- `../build-reordered/debian-patches/`: replace the `0002` copy (and any other
  changed patch) so it matches `patches/`.
- `../build-reordered/changelog` and `../build-reordered/install-run-reordered/`:
  refresh to the `.3` version + the 4-counter check.
- `README.md` (this directory) and `../../operator/DEPLOY-AND-MEASURE.md` §1/§3:
  drop the "pre-telemetry / refreshed build pending" caveats once `.3` is attached.
- Open a PR against `tor41339-hsdir-defense-clean` with the regenerated artifacts.

---

Pasteable prompt for a build agent with an amd64 Docker host:

````
You have an amd64 host with Docker. DEFENSIVE task: rebuild the Ubuntu 24.04 (noble) .deb
for our patched Tor from the CURRENT patch series, so the binary exposes all four count-only
MetricsPort counters. Everything runs on your build host / in throwaway containers — never
touch the real Tor network.

1. Check out branch `tor41339-hsdir-defense-clean` of `1aeo/torutils`. Read
   `tor41339-hsdir-defense/engineering/deb/REBUILD-FROM-CURRENT-SERIES.md` and follow it.
2. Fetch the deb.torproject.org noble source for tor_0.4.9.14-1~noble+1 (orig tarball sha256
   182449ac1c8ff43278da27b69b02040e11d03d0327db6d9126e4190ec6235e4a), stage it with the 0000
   patch + the current patches/0001..0007, bump the version to +tor41339.3 with the changelog
   line in the runbook, and run build-in-container-reordered.sh in a fresh ubuntu:24.04 container.
3. Verify in a fresh container on a PRIVATE loopback chutney net only: tor --verify-config,
   bootstrap 100%, and `curl -s http://127.0.0.1:9035/metrics | grep tor_relay_dos_total{type="hsdir'`
   shows ALL FOUR counters (circ_reused, req_reused, request_total, unknown_prev_hop), both
   options `auto`, 0 bad syscalls.
4. Regenerate packages/ (.deb + geoipdb + SHA256SUMS + buildinfo/changes), the
   build-reordered/debian-patches copy, the changelog, and the install transcript to match .3;
   drop the "pre-telemetry" caveats in engineering/deb/README.md and operator/DEPLOY-AND-MEASURE.md
   §1/§3. Open a PR against tor41339-hsdir-defense-clean.
CONFIDENTIALITY: no real relay fingerprints/IPs/hostnames/onion addresses in anything you commit.
Report the new sha256sums and the 4-counter grep output back.
````
