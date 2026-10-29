/* Copyright (c) 2018-2021, The Tor Project, Inc. */
/* See LICENSE for licensing information */

/**
 * \file test_mainloop.c
 * \brief Tests for functions closely related to the Tor main loop
 */

#define CHANNEL_OBJECT_PRIVATE
#define CONFIG_PRIVATE
#define DIRCACHE_PRIVATE
#define MAINLOOP_PRIVATE
#define STATEFILE_PRIVATE

#include "test/test.h"
#include "test/log_test_helpers.h"

#include "lib/confmgt/confmgt.h"
#include "lib/metrics/metrics_store.h"

#include "core/or/or.h"
#include "core/or/channel.h"
#include "core/or/circuitlist.h"
#include "core/or/connection_edge.h"
#include "core/or/edge_connection_st.h"
#include "core/or/or_circuit_st.h"
#include "core/mainloop/connection.h"
#include "core/mainloop/mainloop.h"
#include "core/mainloop/mainloop_state_st.h"
#include "core/mainloop/mainloop_sys.h"
#include "core/mainloop/netstatus.h"

#include "feature/dircache/dircache.h"
#include "feature/dircommon/dir_connection_st.h"
#include "feature/dircommon/directory.h"
#include "feature/hs/hs_cache.h"
#include "feature/hs/hs_service.h"
#include "feature/relay/relay_metrics.h"

#include "app/config/config.h"
#include "app/config/statefile.h"
#include "app/config/or_state_st.h"

#include "app/main/subsysmgr.h"

static const uint64_t BILLION = 1000000000;

static void
test_mainloop_update_time_normal(void *arg)
{
  (void)arg;

  monotime_enable_test_mocking();
  /* This is arbitrary */
  uint64_t mt_now = UINT64_C(7493289274986);
  /* This time is in the past as of when this test was written. */
  time_t now = 1525272090;
  monotime_coarse_set_mock_time_nsec(mt_now);
  reset_uptime();
  update_current_time(now);
  tt_int_op(approx_time(), OP_EQ, now);
  tt_int_op(get_uptime(), OP_EQ, 0);

  update_current_time(now); // Same time as before is a no-op.
  tt_int_op(get_uptime(), OP_EQ, 0);

  now += 1;
  mt_now += BILLION;
  monotime_coarse_set_mock_time_nsec(mt_now);
  update_current_time(now);
  tt_int_op(approx_time(), OP_EQ, now);
  tt_int_op(get_uptime(), OP_EQ, 1);

  now += 2; // two-second jump is unremarkable.
  mt_now += 2*BILLION;
  update_current_time(now);
  monotime_coarse_set_mock_time_nsec(mt_now);
  tt_int_op(approx_time(), OP_EQ, now);
  tt_int_op(get_uptime(), OP_EQ, 3);

  now -= 1; // a one-second hop backwards is also unremarkable.
  update_current_time(now);
  tt_int_op(approx_time(), OP_EQ, now); // it changes the approx time...
  tt_int_op(get_uptime(), OP_EQ, 3); // but it doesn't roll back our uptime

 done:
  monotime_disable_test_mocking();
}

static void
test_mainloop_update_time_jumps(void *arg)
{
  (void)arg;

  monotime_enable_test_mocking();
  /* This is arbitrary */
  uint64_t mt_now = UINT64_C(7493289274986);
  /* This time is in the past as of when this test was written. */
  time_t now = 220897152;
  monotime_coarse_set_mock_time_nsec(mt_now);
  reset_uptime();
  update_current_time(now);
  tt_int_op(approx_time(), OP_EQ, now);
  tt_int_op(get_uptime(), OP_EQ, 0);

  /* Put some uptime on the clock.. */
  now += 3;
  mt_now += 3*BILLION;
  monotime_coarse_set_mock_time_nsec(mt_now);
  update_current_time(now);
  tt_int_op(approx_time(), OP_EQ, now);
  tt_int_op(get_uptime(), OP_EQ, 3);

  /* Now try jumping forward and backward, without updating the monotonic
   * clock.  */
  setup_capture_of_logs(LOG_NOTICE);
  now += 1800;
  update_current_time(now);
  expect_single_log_msg_containing(
               "Your system clock just jumped 1800 seconds forward");
  tt_int_op(approx_time(), OP_EQ, now);
  tt_int_op(get_uptime(), OP_EQ, 3); // no uptime change.
  mock_clean_saved_logs();

  now -= 600;
  update_current_time(now);
  expect_single_log_msg_containing(
               "Your system clock just jumped 600 seconds backward");
  tt_int_op(approx_time(), OP_EQ, now);
  tt_int_op(get_uptime(), OP_EQ, 3); // no uptime change.
  mock_clean_saved_logs();

  /* uptime tracking should go normally now if the clock moves sensibly. */
  now += 2;
  mt_now += 2*BILLION;
  update_current_time(now);
  tt_int_op(approx_time(), OP_EQ, now);
  tt_int_op(get_uptime(), OP_EQ, 5);

  /* If we skip forward by a few minutes but the monotonic clock agrees,
   * we've just been idle: that counts as not worth warning about. */
  now += 1800;
  mt_now += 1800*BILLION;
  monotime_coarse_set_mock_time_nsec(mt_now);
  update_current_time(now);
  expect_no_log_entry();
  tt_int_op(approx_time(), OP_EQ, now);
  tt_int_op(get_uptime(), OP_EQ, 5); // this doesn't count to uptime, though.

  /* If we skip forward by a long time, even if the clock agrees, it's
   * idnless that counts. */
  now += 4000;
  mt_now += 4000*BILLION;
  monotime_coarse_set_mock_time_nsec(mt_now);
  update_current_time(now);
  expect_single_log_msg_containing("Tor has been idle for 4000 seconds");
  tt_int_op(approx_time(), OP_EQ, now);
  tt_int_op(get_uptime(), OP_EQ, 5);

 done:
  teardown_capture_of_logs();
  monotime_disable_test_mocking();
}

static int schedule_rescan_called = 0;
static void
mock_schedule_rescan_periodic_events(void)
{
  ++schedule_rescan_called;
}

static void
test_mainloop_user_activity(void *arg)
{
  (void)arg;
  const time_t start = 1542658829;
  update_approx_time(start);

  MOCK(schedule_rescan_periodic_events, mock_schedule_rescan_periodic_events);

  reset_user_activity(start);
  tt_i64_op(get_last_user_activity_time(), OP_EQ, start);

  set_network_participation(false);

  // reset can move backwards and forwards, but does not change network
  // participation.
  reset_user_activity(start-10);
  tt_i64_op(get_last_user_activity_time(), OP_EQ, start-10);
  reset_user_activity(start+10);
  tt_i64_op(get_last_user_activity_time(), OP_EQ, start+10);

  tt_int_op(schedule_rescan_called, OP_EQ, 0);
  tt_int_op(false, OP_EQ, is_participating_on_network());

  // "note" can only move forward.  Calling it from a non-participating
  // state makes us rescan the periodic callbacks and set participation.
  note_user_activity(start+20);
  tt_i64_op(get_last_user_activity_time(), OP_EQ, start+20);
  tt_int_op(true, OP_EQ, is_participating_on_network());
  tt_int_op(schedule_rescan_called, OP_EQ, 1);

  // Calling it again will move us forward, but not call rescan again.
  note_user_activity(start+25);
  tt_i64_op(get_last_user_activity_time(), OP_EQ, start+25);
  tt_int_op(true, OP_EQ, is_participating_on_network());
  tt_int_op(schedule_rescan_called, OP_EQ, 1);

  // We won't move backwards.
  note_user_activity(start+20);
  tt_i64_op(get_last_user_activity_time(), OP_EQ, start+25);
  tt_int_op(true, OP_EQ, is_participating_on_network());
  tt_int_op(schedule_rescan_called, OP_EQ, 1);

  // We _will_ adjust if the clock jumps though.
  netstatus_note_clock_jumped(500);
  tt_i64_op(get_last_user_activity_time(), OP_EQ, start+525);

  netstatus_note_clock_jumped(-400);
  tt_i64_op(get_last_user_activity_time(), OP_EQ, start+125);

 done:
  UNMOCK(schedule_rescan_periodic_events);
}

static unsigned int
mock_get_num_services(void)
{
  return 1;
}

static connection_t *
mock_connection_gbtu(int type)
{
  (void) type;
  return (void *)"hello fellow connections";
}

static void
test_mainloop_check_participation(void *arg)
{
  (void)arg;
  or_options_t *options = options_new();
  const time_t start = 1542658829;
  const time_t ONE_DAY = 24*60*60;

  options->DormantTimeoutEnabled = 1;

  // Suppose we've been idle for a day or two
  reset_user_activity(start - 2*ONE_DAY);
  set_network_participation(true);
  check_network_participation_callback(start, options);
  tt_int_op(is_participating_on_network(), OP_EQ, false);
  tt_i64_op(get_last_user_activity_time(), OP_EQ, start-2*ONE_DAY);

  // suppose we've been idle for 2 days... but we are a server.
  reset_user_activity(start - 2*ONE_DAY);
  options->ORPort_set = 1;
  set_network_participation(true);
  check_network_participation_callback(start+2, options);
  tt_int_op(is_participating_on_network(), OP_EQ, true);
  tt_i64_op(get_last_user_activity_time(), OP_EQ, start+2);
  options->ORPort_set = 0;

  // idle for 2 days, but we have a hidden service.
  reset_user_activity(start - 2*ONE_DAY);
  set_network_participation(true);
  MOCK(hs_service_get_num_services, mock_get_num_services);
  check_network_participation_callback(start+3, options);
  tt_int_op(is_participating_on_network(), OP_EQ, true);
  tt_i64_op(get_last_user_activity_time(), OP_EQ, start+3);
  UNMOCK(hs_service_get_num_services);

  // idle for 2 days but we have at least one user connection
  MOCK(connection_get_by_type_nonlinked, mock_connection_gbtu);
  reset_user_activity(start - 2*ONE_DAY);
  set_network_participation(true);
  options->DormantTimeoutDisabledByIdleStreams = 1;
  check_network_participation_callback(start+10, options);
  tt_int_op(is_participating_on_network(), OP_EQ, true);
  tt_i64_op(get_last_user_activity_time(), OP_EQ, start+10);

  // as above, but DormantTimeoutDisabledByIdleStreams is not set
  reset_user_activity(start - 2*ONE_DAY);
  set_network_participation(true);
  options->DormantTimeoutDisabledByIdleStreams = 0;
  check_network_participation_callback(start+13, options);
  tt_int_op(is_participating_on_network(), OP_EQ, false);
  tt_i64_op(get_last_user_activity_time(), OP_EQ, start-2*ONE_DAY);
  UNMOCK(connection_get_by_type_nonlinked);
  options->DormantTimeoutDisabledByIdleStreams = 1;

  // idle for 2 days but DormantClientTimeout is 3 days
  reset_user_activity(start - 2*ONE_DAY);
  set_network_participation(true);
  options->DormantClientTimeout = ONE_DAY * 3;
  check_network_participation_callback(start+30, options);
  tt_int_op(is_participating_on_network(), OP_EQ, true);
  tt_i64_op(get_last_user_activity_time(), OP_EQ, start-2*ONE_DAY);

 done:
  or_options_free(options);
  UNMOCK(hs_service_get_num_services);
  UNMOCK(connection_get_by_type_nonlinked);
}

static void
test_mainloop_dormant_load_state(void *arg)
{
  (void)arg;
  or_state_t *or_state = or_state_new();
  mainloop_state_t *state;
  {
    int idx = subsystems_get_state_idx(&sys_mainloop);
    tor_assert(idx >= 0);
    state = config_mgr_get_obj_mutable(get_state_mgr(), or_state, idx);
  }
  const time_t start = 1543956575;

  reset_user_activity(0);
  set_network_participation(false);

  // When we construct a new state, it starts out in "auto" mode.
  tt_int_op(state->Dormant, OP_EQ, -1);

  // Initializing from "auto" makes us start out (by default) non-Dormant,
  // with activity right now.
  netstatus_load_from_state(state, start);
  tt_assert(is_participating_on_network());
  tt_i64_op(get_last_user_activity_time(), OP_EQ, start);

  // Initializing from dormant clears the last user activity time, and
  // makes us dormant.
  state->Dormant = 1;
  netstatus_load_from_state(state, start);
  tt_assert(! is_participating_on_network());
  tt_i64_op(get_last_user_activity_time(), OP_EQ, 0);

  // Initializing from non-dormant sets the last user activity time, and
  // makes us non-dormant.
  state->Dormant = 0;
  state->MinutesSinceUserActivity = 123;
  netstatus_load_from_state(state, start);
  tt_assert(is_participating_on_network());
  tt_i64_op(get_last_user_activity_time(), OP_EQ, start - 123*60);

  // If we would start dormant, but DormantCanceledByStartup is set, then
  // we start up non-dormant.
  state->Dormant = 1;
  get_options_mutable()->DormantCanceledByStartup = 1;
  netstatus_load_from_state(state, start);
  tt_assert(is_participating_on_network());
  tt_i64_op(get_last_user_activity_time(), OP_EQ, start);

 done:
  or_state_free(or_state);
}

static void
test_mainloop_dormant_save_state(void *arg)
{
  (void)arg;
  mainloop_state_t *state = tor_malloc_zero(sizeof(mainloop_state_t));
  const time_t start = 1543956575;

  // Can we save a non-dormant state correctly?
  reset_user_activity(start - 1000);
  set_network_participation(true);
  netstatus_flush_to_state(state, start);

  tt_int_op(state->Dormant, OP_EQ, 0);
  tt_int_op(state->MinutesSinceUserActivity, OP_EQ, 1000 / 60);

  // Can we save a dormant state correctly?
  set_network_participation(false);
  netstatus_flush_to_state(state, start);

  tt_int_op(state->Dormant, OP_EQ, 1);
  tt_int_op(state->MinutesSinceUserActivity, OP_EQ, 0);

 done:
  tor_free(state);
}

static int
mock_channel_get_addr_if_possible(const channel_t *chan, tor_addr_t *addr_out)
{
  (void)chan;
  (void)addr_out;
  return 0;
}

static dir_connection_t *
new_test_server_dir_pair(or_circuit_t *circ, connection_t **edge_out)
{
  edge_connection_t *edge = edge_connection_new(CONN_TYPE_EXIT, AF_INET);
  dir_connection_t *dir = dir_connection_new(AF_INET);
  edge->base_.purpose = EXIT_PURPOSE_CONNECT;
  edge->base_.state = EXIT_CONN_STATE_OPEN;
  edge->edge_has_sent_end = 1;
  dir->base_.purpose = DIR_PURPOSE_SERVER;
  dir->base_.state = DIR_CONN_STATE_SERVER_COMMAND_WAIT;
  tor_addr_from_ipv4h(&edge->base_.addr, 0x7f000001);
  tor_addr_from_ipv4h(&dir->base_.addr, 0x7f000001);
  edge->base_.address = tor_strdup("127.0.0.1");
  dir->base_.address = tor_strdup("127.0.0.1");
  connection_link_connections(TO_CONN(dir), TO_CONN(edge));
  if (circ) {
    edge->on_circuit = TO_CIRCUIT(circ);
    edge->next_stream = circ->n_streams;
    circ->n_streams = edge;
    if (circ->begindir_stream_count < UINT16_MAX)
      ++circ->begindir_stream_count;
  }
  int r1 = connection_add(TO_CONN(edge));
  int r2 = connection_add(TO_CONN(dir));
  tor_assert(r1 == 0 && r2 == 0);
  connection_start_reading(TO_CONN(dir));
  relay_metrics_note_dir_stream_phase(dir, DIR_STREAM_PHASE_OPENED,
                                      circ ? circ->begindir_stream_count : 1);
  if (edge_out)
    *edge_out = TO_CONN(edge);
  return dir;
}

static void
close_all_test_conns(void)
{
  SMARTLIST_FOREACH_BEGIN(get_connection_array(), connection_t *, c) {
    if (!c->marked_for_close)
      connection_mark_for_close(c);
  } SMARTLIST_FOREACH_END(c);
  close_closeable_connections();
}

static void
test_mainloop_normal_directory_and_metrics(void *arg)
{
  (void)arg;
  channel_t chan = {0};
  or_circuit_t *circ1 = NULL, *circ2 = NULL;
  buf_t *prom_buf = buf_new();
  char *prom_str = NULL;
  or_options_t *options = get_options_mutable();

  hs_cache_init();
  options->ORPort_set = 1;
  options->BridgeRelay = 0;
  MOCK(channel_get_addr_if_possible, mock_channel_get_addr_if_possible);
  tor_init_connection_lists();
  initialize_mainloop_events();
  reset_main_loop_counters();
  relay_metrics_free();
  relay_metrics_init();

  circ1 = or_circuit_new(0, NULL);
  circ2 = or_circuit_new(0, NULL);
  circ1->p_chan = circ2->p_chan = &chan;
  circ1->base_.purpose = circ2->base_.purpose = CIRCUIT_PURPOSE_OR;

  /* 1. Multi-stream circuit reuse across ordinary endpoints + 1st HSDir fetch,
   * followed by 2nd HSDir rejection and a queued stream on closing circ1. */
  static const char *const hs_get =
    "GET /tor/hs/3/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    " HTTP/1.0\r\n\r\n";
  static const char *const reqs[] = {
    "GET /tor/status-vote/current/consensus HTTP/1.0\r\n\r\n",
    "GET /tor/micro/d/abcd HTTP/1.0\r\n\r\n",
    "GET /tor/server/fp/abcd HTTP/1.0\r\n\r\n",
    "GET /tor/extra/fp/abcd HTTP/1.0\r\n\r\n",
    "GET /tor/keys/all HTTP/1.0\r\n\r\n",
  };
  for (size_t i = 0; i <= ARRAY_LENGTH(reqs); ++i) {
    connection_t *edge_c = NULL;
    dir_connection_t *d = new_test_server_dir_pair(circ1, &edge_c);
    buf_add_string(TO_CONN(d)->inbuf,
                   i < ARRAY_LENGTH(reqs) ? reqs[i] : hs_get);
    tt_int_op(directory_handle_command(d), OP_EQ, 0);
    tt_int_op(d->dir_stream_phase, OP_EQ, DIR_STREAM_PHASE_WRITING);
    size_t moved = buf_move_all(edge_c->inbuf, TO_CONN(d)->outbuf);
    relay_metrics_note_dir_bytes(d, true, moved);
    tt_int_op(connection_dir_finished_flushing(d), OP_EQ, 0);
    tt_int_op(d->dir_stream_phase, OP_EQ, DIR_STREAM_PHASE_COMPLETED);
    connection_mark_for_close(edge_c);
  }
  dir_connection_t *d_hs2 = new_test_server_dir_pair(circ1, NULL);
  buf_add_string(TO_CONN(d_hs2)->inbuf, hs_get);
  tt_int_op(directory_handle_command(d_hs2), OP_EQ, 0);
  tt_assert(TO_CIRCUIT(circ1)->marked_for_close);

  dir_connection_t *d_closing = new_test_server_dir_pair(circ1, NULL);
  buf_add_string(TO_CONN(d_closing)->inbuf, hs_get);
  tt_int_op(directory_handle_command(d_closing), OP_EQ, -1);
  close_all_test_conns();

  /* 2. HSDir POST, pre-HTTP abort, mid-HTTP abort, dying-peer write abort,
   * and unknown HTTP verb early rejection on circ2. */
  connection_t *e_post = NULL, *e_wr = NULL;
  dir_connection_t *d_post = new_test_server_dir_pair(circ2, &e_post);
  buf_add_string(TO_CONN(d_post)->inbuf,
                 "POST /tor/hs/3/publish HTTP/1.0\r\n"
                 "Content-Length: 4\r\n\r\njunk");
  tt_int_op(directory_handle_command(d_post), OP_EQ, 0);
  size_t moved = buf_move_all(e_post->inbuf, TO_CONN(d_post)->outbuf);
  relay_metrics_note_dir_bytes(d_post, true, moved);
  tt_int_op(connection_dir_finished_flushing(d_post), OP_EQ, 0);

  (void)new_test_server_dir_pair(circ2, NULL);
  dir_connection_t *d_mid = new_test_server_dir_pair(circ2, NULL);
  TO_CONN(d_mid)->inbuf_reached_eof = 1;
  buf_add_string(TO_CONN(d_mid)->inbuf, "GET /tor/partial");

  dir_connection_t *d_wr = new_test_server_dir_pair(circ2, &e_wr);
  buf_add_string(TO_CONN(d_wr)->inbuf,
                 "GET /tor/nonexistent HTTP/1.0\r\n\r\n");
  tt_int_op(directory_handle_command(d_wr), OP_EQ, 0);
  /* Mark d_wr first and e_wr second so conn_close_if_marked() sees a dying
   * linked peer and must neither count written bytes nor mark completed. */
  connection_mark_for_close(TO_CONN(d_wr));
  connection_mark_for_close(e_wr);

  dir_connection_t *d_rej = new_test_server_dir_pair(circ2, NULL);
  buf_add_string(TO_CONN(d_rej)->inbuf, "PUT /tor/ HTTP/1.0\r\n\r\n");
  tt_int_op(directory_handle_command(d_rej), OP_EQ, -1);
  close_all_test_conns();

  /* 3. Slow client holding response open until conn_close_if_marked(). */
  connection_t *e_slow = NULL;
  dir_connection_t *d_slow = new_test_server_dir_pair(circ2, &e_slow);
  buf_add_string(TO_CONN(d_slow)->inbuf,
                 "GET /tor/robots.txt HTTP/1.0\r\n\r\n");
  tt_int_op(directory_handle_command(d_slow), OP_EQ, 0);
  connection_mark_for_close(TO_CONN(d_slow));
  TO_CONN(d_slow)->hold_open_until_flushed = 1;
  close_closeable_connections();
  connection_mark_for_close(e_slow);
  close_closeable_connections();

  const mainloop_metrics_t *m = mainloop_get_metrics();
  tt_int_op(m->conn_array_len, OP_EQ, 0);
  tt_int_op(m->closeable_len, OP_EQ, 0);
  tt_int_op(m->active_linked_len, OP_EQ, 0);
  tt_u64_op(m->closeable_added, OP_EQ, 28);
  tt_u64_op(m->active_linked_added, OP_EQ, 1);
  tt_u64_op(m->close_pass_runs, OP_GE, 4);
  tt_u64_op(m->close_pass_closed, OP_EQ, 28);

  const smartlist_t *stores = relay_metrics_get_stores();
  tt_assert(stores);
  metrics_store_get_output(METRICS_FORMAT_PROMETHEUS,
                           smartlist_get(stores, 0), prom_buf);
  prom_str = buf_extract(prom_buf, NULL);
  static const char *const expected[] = {
    "tor_relay_mainloop_connection_list_size{list=\"connection_array\"} 0\n",
    "tor_relay_mainloop_connection_list_ops_total{"
      "list=\"closeable\",op=\"add\"} 28\n",
    "tor_relay_mainloop_close_pass_total{field=\"closed\"} 28\n",
    "tor_relay_mainloop_ticks_total{threshold=\"over_10ms\"} ",
    "tor_relay_mainloop_tick_max_duration_usec ",
    "tor_relay_dir_streams_total{phase=\"opened\"} 14\n",
    "tor_relay_dir_streams_total{phase=\"writing\"} 9\n",
    "tor_relay_dir_streams_total{phase=\"completed\"} 8\n",
    "tor_relay_dir_streams_total{phase=\"aborted_pre_http\"} 1\n",
    "tor_relay_dir_streams_total{phase=\"aborted_mid_http\"} 4\n",
    "tor_relay_dir_streams_total{phase=\"aborted_writing\"} 1\n",
    "tor_relay_dir_streams_total{phase=\"reused_circuit\"} 12\n",
    "tor_relay_dir_streams_active{state=\"opened_wait\"} 0\n",
    "tor_relay_dir_streams_active{state=\"writing\"} 0\n",
    "tor_relay_dir_http_requests_total{"
      "class=\"hs_v3_fetch\",status=\"404\"} 1\n",
    "tor_relay_dir_http_requests_total{"
      "class=\"hs_v3_fetch\",status=\"rejected_early\"} 1\n",
    "tor_relay_dir_http_requests_total{"
      "class=\"hs_v3_publish\",status=\"400\"} 1\n",
    "tor_relay_dir_http_requests_total{"
      "class=\"other_valid\",status=\"200\"} 1\n",
    "tor_relay_dir_http_requests_total{"
      "class=\"invalid\",status=\"rejected_early\"} 1\n",
    "tor_relay_dir_bytes_total{class=\"invalid\",dir=\"read\"} 55\n",
    "tor_relay_dir_bytes_total{class=\"invalid\",dir=\"written\"} 0\n",
    "tor_relay_dir_bytes_total{class=\"other_valid\",dir=\"read\"} 32\n",
  };
  for (size_t i = 0; i < ARRAY_LENGTH(expected); ++i)
    tt_assert(strstr(prom_str, expected[i]));

 done:
  tor_free(prom_str);
  buf_free(prom_buf);
  if (smartlist_len(get_connection_array()) > 0) {
    SMARTLIST_FOREACH_BEGIN(get_connection_array(), connection_t *, c) {
      c->hold_open_until_flushed = 0;
      buf_clear(c->outbuf);
    } SMARTLIST_FOREACH_END(c);
    close_all_test_conns();
  }
  if (circ1)
    circ1->p_chan = NULL;
  if (circ2)
    circ2->p_chan = NULL;
  circuit_free_all();
  hs_cache_free_all();
  UNMOCK(channel_get_addr_if_possible);
}

#define MAINLOOP_TEST(name) \
  { #name, test_mainloop_## name , TT_FORK, NULL, NULL }

struct testcase_t mainloop_tests[] = {
  MAINLOOP_TEST(update_time_normal),
  MAINLOOP_TEST(update_time_jumps),
  MAINLOOP_TEST(user_activity),
  MAINLOOP_TEST(check_participation),
  MAINLOOP_TEST(dormant_load_state),
  MAINLOOP_TEST(dormant_save_state),
  MAINLOOP_TEST(normal_directory_and_metrics),
  END_OF_TESTCASES
};
