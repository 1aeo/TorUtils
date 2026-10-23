#!/bin/bash
# Incremental dev build inside the container.
# usage: dev-make.sh TREE CMD...   (TREE = tor-stock | tor | tor-main ...)
# Syncs tracked+untracked (non-ignored) files of /work/TREE into
# /build/dev-TREE/src keeping mtimes, configures once, then runs CMD in the
# build dir (e.g. "make -j16 src/test/test").
set -uo pipefail
tree=$1; shift
src=${HOSTWORK:-/work}/$tree; dst=/build/dev-$tree
mkdir -p "$dst/src" "$dst/b"
cd "$src" && git -c safe.directory='*' ls-files -co --exclude-standard -z \
  | tar --null -T - -cf - | (cd "$dst/src" && tar -xpf -)
if [ ! -f "$dst/b/Makefile" ]; then
  (cd "$dst/src" && ./autogen.sh >/dev/null 2>&1) || { echo autogen failed; exit 1; }
  (cd "$dst/b" && ../src/configure ${DEV_CONFIGURE:---enable-fatal-warnings --disable-asciidoc} >/dev/null 2>&1) || { echo configure failed; exit 1; }
fi
cd "$dst/b" && eval "$@"
