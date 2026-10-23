# For the cleanup-indexing work: what `.7` changed in 0012's check

The cleanup-indexing work's item 4 has 0012 refuse a BEGIN_DIR before
`edge_connection_new()`. The `+tor41339.7` series changed the function it
moves: rebase that fix-up onto all of `patches/0001`–`0023`.

In `.7`, `dos_should_refuse_begindir(or_circuit_t *circ, edge_connection_t *stream)`
does two more things than in `.6`:

1. **0019 marks the stream.** When the circuit already holds
   `DoSBeginDirMaxStreams` open directory streams, whether or not the limit
   is enforced, it sets `stream->begindir_over_max`.
   `connection_exit_connect_dir()` copies that mark to the directory
   connection, so the request is counted by type in
   `tor_relay_begindir_request_over_max_total`.
   - Called before the allocation, there is no stream to mark. The
     `if (stream)` guard makes that loss silent; the test
     `dos/begindir_refused` catches it.
2. **0023 counts the stream-rate shadow.** It first calls
   `dos_note_begindir_stream_rate(circ)`, a second per-circuit token bucket
   at `DoSStreamCreationRate`/`Burst` that only counts
   `tor_relay_dos_total{type="begindir_over_stream_rate"}`, and only while
   a MetricsPort is configured.
   - Called before `we_are_hibernating()`, that bucket would also count
     cells refused for hibernation. 0023's commit message says it runs
     "after the directory and hibernation checks".

A shape that keeps both counters exactly as they are:
- return the over-max result through an out-parameter;
- set it on `n_stream` in the caller once the stream exists;
- call `dos_note_begindir_stream_rate()` from `connection_exit_begin_conn()`
  where the check is today, after the hibernation check.

Keep `END_STREAM_REASON_MISC` and the `begindir_over_max` / `refused`
counting unchanged, as the original brief says.
