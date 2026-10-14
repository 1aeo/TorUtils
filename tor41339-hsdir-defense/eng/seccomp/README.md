# Seccomp sandbox check (amd64)

All runs use a private, loopback-only chutney network (its own authorities and
consensus). Patched tor runs on the authorities and relays with `Sandbox 1`.
The onion service and the client are stock (unpatched) tor.

- `hs-v3-sandbox`: chutney network script. Set env `STOCK_TOR` to the stock
  tor binary and `RELAY_EXTRA` to optional extra relay torrc lines.
- `run-seccomp.sh <label> <relay-tor> [extra-torrc]`: brings the net up, runs
  chutney verify plus 10 ordinary single HSFETCHes from the stock client, and
  sends single DirPort probes. Then it records `/proc/<pid>/status` Seccomp
  mode and scans every node log for `Caught a bad syscall`.
- `dirport-probes.py <port>`: sends single malformed or oversized HTTP requests
  to one lab node's DirPort on 127.0.0.1. These drive the 0003, 0004 and 0005
  parser paths.
- `sandbox-check.sh <datadir>...`: read-only evidence collector for any lab
  node. It reports the torrc Sandbox value, the live Seccomp mode
  (2 = filter), the bad-syscall count and the `hsdir_*` DoS metrics.
