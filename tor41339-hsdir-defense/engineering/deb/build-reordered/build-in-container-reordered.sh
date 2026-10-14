#!/bin/bash
# Runs inside a fresh ubuntu:24.04 container. /in = sources (ro), /out = results.
set -exo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q --no-install-recommends dpkg-dev devscripts equivs quilt ca-certificates
mkdir -p /build && cd /build
cp /in/tor_0.4.9.14.orig.tar.gz /in/tor_0.4.9.14-1~noble+1.diff.gz /in/tor_0.4.9.14-1~noble+1.dsc .
dpkg-source -x tor_0.4.9.14-1~noble+1.dsc
cd tor-0.4.9.14
mkdir -p debian/patches
cp /in/0000-restore-doc-nofooter.conf.patch debian/patches/
for p in /in/000[1-7]*.patch; do cp "$p" debian/patches/; done
( cd debian/patches && ls 000*.patch > series && cat series )
export QUILT_PATCHES=debian/patches
quilt push -a
quilt pop -a
DEBFULLNAME="1aeo" DEBEMAIL="github@1aeo.com" dch -v 0.4.9.14-1~noble+1+tor41339.3 -D noble \
  "Apply tor#41339 HSDir-flood defensive series (patches 0001-0007, v3 reordered, upstream-polish refactors): known-prev-hop rule, one HS dir request per circuit, count-only hsdir_* MetricsPort counters incl. hsdir_req_reused and hsdir_request_total; restore doc/nofooter.conf."
mk-build-deps -i -r -t "apt-get -y -q --no-install-recommends" debian/control
dpkg-buildpackage -us -uc -b -j"$(nproc)" 2>&1 | tee /out/dpkg-buildpackage.log
cp ../*.deb ../*.buildinfo ../*.changes /out/ || true
cp -r debian/patches /out/debian-patches
cp debian/changelog /out/changelog
