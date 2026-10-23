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
# Every numbered patch in /in (0000 first, then the series in order). Fail
# unless exactly EXPECT_PATCHES were staged, so a stale or partial staging
# directory can never silently drop or add patches.
for p in /in/[0-9][0-9][0-9][0-9]-*.patch; do cp "$p" debian/patches/; done
( cd debian/patches && ls [0-9][0-9][0-9][0-9]-*.patch > series && cat series )
N=$(grep -c . debian/patches/series)
[ "$N" -eq "${EXPECT_PATCHES:?set EXPECT_PATCHES to 1 + the series length}" ] || { echo "staged $N patches, expected $EXPECT_PATCHES" >&2; exit 1; }
export QUILT_PATCHES=debian/patches
quilt push -a
quilt pop -a
DEBFULLNAME="1aeo" DEBEMAIL="github@1aeo.com" dch -v "${BASE}+tor41339.${REV:?set REV, e.g. 4}" -D "$SUITE" \
  "${CHANGELOG_MSG:?set CHANGELOG_MSG}"
mk-build-deps -i -r -t "apt-get -y -q --no-install-recommends" debian/control
dpkg-buildpackage -us -uc -b -j"$(nproc)" 2>&1 | tee /out/dpkg-buildpackage.log
cp ../tor_*_amd64.deb ../tor-geoipdb_*_all.deb ../*.buildinfo ../*.changes /out/
cp -r debian/patches /out/debian-patches
cp debian/changelog /out/changelog
