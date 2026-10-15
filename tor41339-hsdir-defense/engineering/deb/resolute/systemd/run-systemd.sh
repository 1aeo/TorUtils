#!/bin/bash
# Host driver: boot Ubuntu 26.04 systemd (systemd 259 needs cgroup v2, so the
# container mounts a private cgroup2) with NO network interface, then run
# in-systemd.sh. Image: ubuntu:26.04 + systemd, Ubuntu's tor, needrestart,
# binutils, curl, and mimalloc v2.0.9 built from the upstream tag with
# cmake, installed as /usr/local/lib/mimalloc/libmimalloc-2.0.9.so (the
# fleet's allocator preload). Usage: DEBDIR=<dir with the resolute .deb> OUT=<file> ./run-systemd.sh
set -u
: "${DEBDIR:?}" "${OUT:?}" "${IMAGE:=sdtest26m}"
HERE=$(cd "$(dirname "$0")" && pwd)
docker rm -f tor41339-sd26 >/dev/null 2>&1
docker run -d --name tor41339-sd26 --network none --privileged --cgroupns=private \
  --tmpfs /run --tmpfs /run/lock -v "$DEBDIR":/debs:ro -v "$HERE/in-systemd.sh":/in-systemd.sh:ro \
  --entrypoint /bin/bash "$IMAGE" -c 'umount /sys/fs/cgroup 2>/dev/null; mount -t cgroup2 none /sys/fs/cgroup && exec /lib/systemd/systemd' >/dev/null
for i in $(seq 1 60); do s=$(docker exec tor41339-sd26 systemctl is-system-running 2>/dev/null); case "$s" in running|degraded) break;; esac; sleep 1; done
docker exec tor41339-sd26 bash /in-systemd.sh 2>&1 | tee "$OUT"
docker rm -f tor41339-sd26 >/dev/null
