#!/bin/bash
# Runs inside a fresh Ubuntu container matching SUITE: ubuntu:24.04 for noble
# (default), ubuntu:26.04 for resolute. /in = sources (ro), /out = results.
set -exo pipefail
SUITE="${SUITE:-noble}"
BASE="0.4.9.14-1~${SUITE}+1"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q --no-install-recommends dpkg-dev devscripts equivs quilt ca-certificates
mkdir -p /build && cd /build
cp /in/tor_0.4.9.14.orig.tar.gz "/in/tor_${BASE}.diff.gz" "/in/tor_${BASE}.dsc" .
dpkg-source -x "tor_${BASE}.dsc"
cd tor-0.4.9.14
mkdir -p debian/patches
cp /in/0000-restore-doc-nofooter.conf.patch debian/patches/
for p in /in/000[1-7]*.patch; do cp "$p" debian/patches/; done
( cd debian/patches && ls 000*.patch > series && cat series )
export QUILT_PATCHES=debian/patches
quilt push -a
quilt pop -a
DEBFULLNAME="1aeo" DEBEMAIL="github@1aeo.com" dch -v "${BASE}+tor41339.3" -D "$SUITE" \
  "Apply tor#41339 HSDir-flood defensive series (patches 0001-0007, v3 reordered, upstream-polish refactors): known-prev-hop rule, one HS dir request per circuit, count-only hsdir_* MetricsPort counters incl. hsdir_req_reused and hsdir_request_total; restore doc/nofooter.conf."
mk-build-deps -i -r -t "apt-get -y -q --no-install-recommends" debian/control
dpkg-buildpackage -us -uc -b -j"$(nproc)" 2>&1 | tee /out/dpkg-buildpackage.log
cp ../*.deb ../*.buildinfo ../*.changes /out/ || true
cp -r debian/patches /out/debian-patches
cp debian/changelog /out/changelog
