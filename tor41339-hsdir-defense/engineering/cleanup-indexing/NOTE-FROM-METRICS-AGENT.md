# Note from the Directory-flood metrics agent (verbatim), relayed 2026-10-23

Received via the operator; the source file lives on the metrics agent's host
(`note-for-cleanup-indexing-agent.md`) and the `.7` push carries a copy. Treat
as a peer note; the behaviour below was independently verified here against the
`+tor41339.7` patches 0020 and 0024 on `tor41339-hsdir-defense-clean`.

---

For the agent working on the cleanup-scan fix (moving `dos_should_refuse_begindir()`
ahead of `edge_connection_new()`):

Two commits in the `+tor41339.7` series added to
`dos_should_refuse_begindir(or_circuit_t *circ, edge_connection_t *stream)`.
When you move it, keep both:

1. "dos: Count what BEGIN_DIR streams over DoSBeginDirMaxStreams ask for". When
   the circuit is over `DoSBeginDirMaxStreams`, enforced or not, the function
   sets `stream->begindir_over_max`. `connection_exit_connect_dir()` then copies
   that onto the directory connection, so the request is counted by type in the
   over-max requests family.
   * Called before the stream is allocated, there is no stream to mark.
   * The `if (stream)` guard hides that loss; `dos/begindir_refused` will catch it.
2. "dos: Count BEGIN_DIR cells over the stream creation rate". The function
   first calls `dos_note_begindir_stream_rate(circ)`, a second per-circuit token
   bucket at `DoSStreamCreationRate`/`Burst`. It only counts
   `tor_relay_dos_total{type="begindir_over_stream_rate"}`.
   * Called before `we_are_hibernating()`, it would also count cells refused for
     hibernation.
   * That breaks the commit message's promise that it runs "after the directory
     and hibernation checks".

Suggested shape:

* Return the over-max result through an out-parameter, and set it on `n_stream`
  in the caller once the stream exists.
* Call `dos_note_begindir_stream_rate()` from `connection_exit_begin_conn()`
  where the check sits today, after the hibernation check.
* Keep `END_STREAM_REASON_MISC`, and keep the `begindir_over_max` and `refused`
  counting unchanged.

Rebase your fix-up of the BEGIN_DIR limit patch ("dos: Add an off-by-default
limit on open BEGIN_DIR streams") onto the full series on
`tor41339-hsdir-defense-clean`. That's `patches/` after this round's push.
