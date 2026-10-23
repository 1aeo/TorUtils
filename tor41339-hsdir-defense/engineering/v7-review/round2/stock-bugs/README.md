# Two stock tor bugs found while reviewing `.7`

Neither is changed by the series. Both diffs apply to tor 0.4.9.14 and
`main`, and were tested only on 0.4.9.14. They are for upstream tickets of
their own (`../../../../analysis/v7-review.md`, "Stock tor bugs").

## A failed options change leaves the listener list stale

- **The diff:** `config-restore-ports-on-failed-set-options.diff`, in
  `set_options()`.
- **The bug:**
  - `options_start_listener_transaction()` calls `parse_ports()` with the
    new options, which replaces `configured_ports`.
  - When `options_act_reversible()` then fails, for example on a bind, the
    rollback restores the old options but not that list.
  - `retry_listeners_callback()` reopens listeners from the stale list every
    60 seconds.
- **Trigger:** SETCONF, RESETCONF or LOADCONF that validates and then fails.
  A failed SIGHUP makes tor exit instead. The state heals at the next
  successful options change.
- **Reproduced** with a loopback-only tor that has
  `MetricsPortPolicy accept 127.0.0.1` but no MetricsPort, while another
  socket holds a port:

  ```
  SETCONF MetricsPort=127.0.0.1:<free> SocksPort=127.0.0.1:<held>
  553 Unable to set option: Failed to bind one of the listener ports.
  right after: the metrics port is closed
  65 s later:  the metrics port answers 200 OK
  GETCONF MetricsPort -> 250 MetricsPort   (unset)
  ```

  The log shows "Closing partially-constructed Metrics listener", then
  "Opened Metrics listener connection (ready)" a minute later.
- **The fix:** after `global_options = old_options;`, re-run `parse_ports()`
  on the old options. With it, the same scenario leaves the port closed, and
  config/, options/ and control/ pass (177 tests).
- **Effect on the series:** 0020, 0021 and 0023 count only while
  `MetricsPort_set` is set. In this state a MetricsPort serves those three
  families, frozen, while the flag is 0.

## GETCONF of an abbreviated option reads as unset

- **The diff:** `confmgt-getconf-expand-abbrev.diff`, one line in
  `config_get_assigned_option()`.
- **The bug:** `handle_control_getconf()` accepts a key through
  `option_is_recognized()`, which expands abbreviations. It then reads the
  value through `config_get_assigned_option()`, which doesn't.
- **What the controller sees:**
  - The answer carries no value, which reads as the default, whatever the
    setting.
  - Each query logs `Unknown option '<name>'.  Failing.`
  - For example, `GETCONF SocksSocketsGroupWritable` answers
    `250 UnixSocksGroupWritable` while it is 1.
  - With the Debian packages' alias, `GETCONF HSDirDescriptorFetchLimit`
    answers `250 HSDirFetchShedding`.
- **The fix:** `key = config_expand_abbrev(mgr, key, 0, 0);` before the
  lookup. It fixes every abbreviation. With it, a unit test of GETCONF
  through the alias passes, as do config/, control/ and options/ (178 tests).
