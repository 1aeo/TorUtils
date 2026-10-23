# Lab image for run-controls.sh: a packaged tor plus chutney's Python deps.
# Build it in a directory holding this file and the tor .deb, e.g.:
#   docker build --build-arg BASE=ubuntu:26.04 \
#     --build-arg DEB=tor_0.4.9.14-1~resolute+1+tor41339.6_amd64.deb -t lab26v6 .
ARG BASE=ubuntu:26.04
FROM ${BASE}
ARG DEB
COPY ${DEB} /tmp/
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
      --no-install-recommends /tmp/${DEB} python3 python3-cryptography \
      python3-paramiko python3-typeguard python3-tomli-w \
      python3-typing-extensions libscrypt0 procps curl ca-certificates \
      iproute2 >/dev/null && apt-get clean && rm -rf /var/lib/apt/lists/*
