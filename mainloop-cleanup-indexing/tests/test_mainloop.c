/* Copyright (c) 2018-2021, The Tor Project, Inc. */
/* See LICENSE for licensing information */

/**
 * \file test_mainloop.c
 * \brief Tests for functions closely related to the Tor main loop
 */

#define CONFIG_PRIVATE
#define DIRCACHE_PRIVATE
#define MAINLOOP_PRIVATE
#define STATEFILE_PRIVATE

#include "test/test.h"
#include "test/log_test_helpers.h"

#include "lib/confmgt/confmgt.h"

#include "core/or/or.h"
#include "core/or/connection_edge.h"
#include "core/or/connection_st.h"
#include "core/or/edge_connection_st.h"
#include "core/mainloop/connection.h"
#include "core/mainloop/mainloop.h"
#include "core/mainloop/mainloop_state_st.h"
#include "core/mainloop/mainloop_sys.h"
#include "core/mainloop/netstatus.h"

#include "feature/dircache/dircache.h"
#include "feature/dircommon/dir_connection_st.h"
#include "feature/dircommon/directory.h"
#include "feature/hs/hs_service.h"
#include "feature/relay/relay_metrics.h"
#include "lib/metrics/metrics_store.h"

#include "app/config/config.h"
#include "app/config/statefile.h"
#include "app/config/or_state_st.h"

#include "app/main/subsysmgr.h"

#ifndef _WIN32
#include <sys/wait.h>
#endif

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

static void
new_test_linked_pair(connection_t **a_out, connection_t **b_out,
                     smartlist_t *live)
{
  connection_t *a = connection_new(CONN_TYPE_EXIT, AF_INET);
  connection_t *b = connection_new(CONN_TYPE_DIR, AF_INET);
  a->state = EXIT_CONN_STATE_OPEN;
  a->purpose = EXIT_PURPOSE_CONNECT;
  a->address = tor_strdup("127.0.0.1");
  TO_EDGE_CONN(a)->edge_has_sent_end = 1;
  TO_EDGE_CONN(a)->end_reason = END_STREAM_REASON_DONE;
  b->state = DIR_CONN_STATE_SERVER_WRITING;
  b->purpose = DIR_PURPOSE_SERVER;
  b->address = tor_strdup("127.0.0.1");
  connection_link_connections(a, b);
  if (live) {
    connection_add(a);
    connection_add(b);
    smartlist_add(live, a);
    smartlist_add(live, b);
  }
  *a_out = a;
  *b_out = b;
}

static void
free_test_conn(connection_t *c)
{
  if (connection_in_active_linked_list(c))
    connection_stop_reading_from_linked_conn(c);
  if (connection_in_array(c))
    connection_remove(c);
  connection_free_(c);
}

static void
mock_start_reading_marks_conn_for_close(connection_t *conn)
{
  if (!conn->marked_for_close)
    connection_mark_for_close(conn);
}

static void
assert_cleanup_containers_coherent(smartlist_t *live_conns)
{
  SMARTLIST_FOREACH_BEGIN(connection_array, connection_t *, c) {
    tt_int_op(c->conn_array_index, OP_EQ, c_sl_idx);
    tt_int_op(connection_in_array(c), OP_EQ, 1);
    tt_assert(smartlist_contains(live_conns, c));
  } SMARTLIST_FOREACH_END(c);
  SMARTLIST_FOREACH_BEGIN(closeable_connection_lst, connection_t *, c) {
    tt_int_op(c->closeable_conn_idx, OP_EQ, c_sl_idx);
    tt_int_op(connection_is_on_closeable_list(c), OP_EQ, 1);
    tt_assert(smartlist_contains(live_conns, c));
  } SMARTLIST_FOREACH_END(c);
  SMARTLIST_FOREACH_BEGIN(active_linked_connection_lst, connection_t *, c) {
    tt_int_op(c->active_on_link, OP_EQ, 1);
    tt_int_op(c->active_linked_conn_idx, OP_EQ, c_sl_idx);
    tt_int_op(connection_in_active_linked_list(c), OP_EQ, 1);
    tt_assert(smartlist_contains(live_conns, c));
  } SMARTLIST_FOREACH_END(c);
  SMARTLIST_FOREACH_BEGIN(live_conns, connection_t *, c) {
    tt_int_op(connection_in_array(c), OP_EQ,
              smartlist_contains(connection_array, c));
    tt_int_op(connection_is_on_closeable_list(c), OP_EQ,
              smartlist_contains(closeable_connection_lst, c));
    tt_int_op(connection_in_active_linked_list(c), OP_EQ,
              smartlist_contains(active_linked_connection_lst, c));
  } SMARTLIST_FOREACH_END(c);
 done:
  ;
}

static void
test_mainloop_active_linked_list_indexing(void *arg)
{
  (void)arg;
  smartlist_t *live = smartlist_new();
  connection_t *conns[6] = {NULL};

  tor_init_connection_lists();
  initialize_mainloop_events();

  /* 1. Direct free of unadded connection_new object + empty list checks. */
  connection_t *unadded = connection_new(CONN_TYPE_DIR, AF_INET);
  tt_int_op(connection_in_array(unadded), OP_EQ, 0);
  tt_int_op(connection_is_on_closeable_list(unadded), OP_EQ, 0);
  tt_int_op(connection_in_active_linked_list(unadded), OP_EQ, 0);
  connection_free_(unadded);

  /* 2. Singleton add/remove and idempotent start/stop. */
  new_test_linked_pair(&conns[0], &conns[1], NULL);
  tt_int_op(connection_add(conns[0]), OP_EQ, 0);
  tt_int_op(connection_in_array(conns[0]), OP_EQ, 1);
  connection_start_reading_from_linked_conn(conns[0]);
  connection_start_reading_from_linked_conn(conns[0]);
  tt_int_op(smartlist_len(active_linked_connection_lst), OP_EQ, 1);
  connection_stop_reading_from_linked_conn(conns[0]);
  connection_stop_reading_from_linked_conn(conns[0]);
  tt_int_op(smartlist_len(active_linked_connection_lst), OP_EQ, 0);
  tt_int_op(connection_remove(conns[0]), OP_EQ, 0);
  tt_int_op(connection_in_array(conns[0]), OP_EQ, 0);
  connection_free_(conns[0]);
  connection_free_(conns[1]);

  /* 3. First, middle, and tail removal + swapped index repair. */
  for (int i = 0; i < 6; i += 2) {
    new_test_linked_pair(&conns[i], &conns[i + 1], live);
    connection_start_reading_from_linked_conn(conns[i]);
    connection_start_reading_from_linked_conn(conns[i + 1]);
  }
  assert_cleanup_containers_coherent(live);

  connection_stop_reading_from_linked_conn(conns[0]);
  tt_int_op(conns[5]->active_linked_conn_idx, OP_EQ, 0);
  connection_stop_reading_from_linked_conn(conns[2]);
  tt_int_op(conns[4]->active_linked_conn_idx, OP_EQ, 2);
  connection_stop_reading_from_linked_conn(conns[3]);
  tt_int_op(conns[3]->active_linked_conn_idx, OP_EQ, -1);
  assert_cleanup_containers_coherent(live);

  tt_int_op(connection_remove(conns[0]), OP_EQ, 0);
  tt_int_op(conns[5]->conn_array_index, OP_EQ, 0);
  tt_int_op(connection_remove(conns[2]), OP_EQ, 0);
  tt_int_op(conns[4]->conn_array_index, OP_EQ, 2);
  assert_cleanup_containers_coherent(live);

 done:
  SMARTLIST_FOREACH(live, connection_t *, c, free_test_conn(c));
  smartlist_free(live);
}

static void
test_mainloop_linked_peer_teardown_and_oom_reorder(void *arg)
{
  (void)arg;
  smartlist_t *live = smartlist_new();
  connection_t *a[3] = {NULL}, *b[3] = {NULL};

  tor_init_connection_lists();
  initialize_mainloop_events();

  for (int i = 0; i < 3; ++i)
    new_test_linked_pair(&a[i], &b[i], live);
  b[1]->reading_from_linked_conn = 1;
  buf_add(a[2]->outbuf, "hi", 2);
  connection_start_reading_from_linked_conn(a[1]);
  connection_start_reading_from_linked_conn(a[2]);
  assert_cleanup_containers_coherent(live);

  /* Mark a[0], a[1], a[2]; defer a[0] at idx 0 so idx 1..2 swap/close. */
  for (int i = 0; i < 3; ++i)
    connection_mark_for_close(a[i]);
  assert_cleanup_containers_coherent(live);
  a[0]->marked_for_close = 0;
  smartlist_remove(live, a[1]);
  smartlist_remove(live, a[2]);
  close_closeable_connections();
  tt_int_op(smartlist_len(closeable_connection_lst), OP_EQ, 1);
  tt_int_op(a[0]->closeable_conn_idx, OP_EQ, 0);
  tt_ptr_op(b[1]->linked_conn, OP_EQ, NULL);
  tt_ptr_op(b[2]->linked_conn, OP_EQ, NULL);
  tt_int_op(connection_in_active_linked_list(b[1]), OP_EQ, 1);
  tt_int_op(connection_in_active_linked_list(b[2]), OP_EQ, 1);
  assert_cleanup_containers_coherent(live);

  a[0]->marked_for_close = 1;
  smartlist_remove(live, a[0]);
  close_closeable_connections();
  tt_int_op(smartlist_len(closeable_connection_lst), OP_EQ, 0);
  tt_ptr_op(b[0]->linked_conn, OP_EQ, NULL);
  assert_cleanup_containers_coherent(live);

  /* Simulate circuits_handle_oom() sorting/re-indexing connection_array. */
  smartlist_reverse(connection_array);
  SMARTLIST_FOREACH_BEGIN(connection_array, connection_t *, c) {
    c->conn_array_index = c_sl_idx;
  } SMARTLIST_FOREACH_END(c);
  assert_cleanup_containers_coherent(live);

  for (int i = 0; i < 3; ++i)
    connection_mark_for_close(b[i]);
  smartlist_clear(live);
  close_closeable_connections();
  tt_int_op(smartlist_len(connection_array), OP_EQ, 0);
  tt_int_op(smartlist_len(active_linked_connection_lst), OP_EQ, 0);

  /* Exercise re-entrant connection_mark_for_close() triggered from inside
   * connection_unlink() before the current connection is swap-deleted from
   * closeable_connection_lst. */
  connection_t *ra = NULL, *rb = NULL;
  new_test_linked_pair(&ra, &rb, live);
  rb->reading_from_linked_conn = 1;
  connection_mark_for_close(ra);
  MOCK(connection_start_reading, mock_start_reading_marks_conn_for_close);
  smartlist_clear(live);
  close_closeable_connections();
  UNMOCK(connection_start_reading);
  tt_int_op(smartlist_len(closeable_connection_lst), OP_EQ, 0);
  tt_int_op(smartlist_len(connection_array), OP_EQ, 0);
  tt_int_op(smartlist_len(active_linked_connection_lst), OP_EQ, 0);

 done:
  UNMOCK(connection_start_reading);
  SMARTLIST_FOREACH(live, connection_t *, c, free_test_conn(c));
  smartlist_free(live);
}

#ifndef _WIN32
#define ASSERT_CHILD_ABORTS(stmt) STMT_BEGIN {                    \
  pid_t pid = fork();                                             \
  tt_int_op(pid, OP_GE, 0);                                       \
  if (pid == 0) {                                                 \
    close(STDERR_FILENO);                                         \
    close(STDOUT_FILENO);                                         \
    stmt;                                                         \
    _exit(0);                                                     \
  }                                                               \
  int status = 0;                                                 \
  pid_t w;                                                        \
  do {                                                            \
    w = waitpid(pid, &status, 0);                                 \
  } while (w < 0 && errno == EINTR);                              \
  tt_int_op(w, OP_EQ, pid);                                       \
  tt_assert(WIFSIGNALED(status) ||                                \
            (WIFEXITED(status) && WEXITSTATUS(status) != 0));     \
} STMT_END

static void
test_mainloop_index_corruption_assertions(void *arg)
{
  (void)arg;
  connection_t *c1 = NULL, *c2 = NULL;
  tor_init_connection_lists();
  initialize_mainloop_events();

  new_test_linked_pair(&c1, &c2, NULL);
  tt_int_op(connection_add(c1), OP_EQ, 0);
  tt_int_op(connection_add(c2), OP_EQ, 0);
  connection_start_reading_from_linked_conn(c1);
  connection_start_reading_from_linked_conn(c2);

  ASSERT_CHILD_ABORTS({ c1->conn_array_index = -2;
                        (void)connection_in_array(c1); });
  ASSERT_CHILD_ABORTS({ c1->conn_array_index = 99;
                        (void)connection_in_array(c1); });
  ASSERT_CHILD_ABORTS({ c1->conn_array_index = c2->conn_array_index;
                        (void)connection_in_array(c1); });
  ASSERT_CHILD_ABORTS({ connection_array = NULL;
                        (void)connection_in_array(c1); });
  ASSERT_CHILD_ABORTS({ c2->conn_array_index = -1;
                        connection_remove(c1); });
  ASSERT_CHILD_ABORTS(connection_free_(c1));
  ASSERT_CHILD_ABORTS({ c1->active_on_link = 0;
                        (void)connection_in_active_linked_list(c1); });
  ASSERT_CHILD_ABORTS({ c1->linked = 0;
                        (void)connection_in_active_linked_list(c1); });
  ASSERT_CHILD_ABORTS({ c1->active_linked_conn_idx = -1;
                        (void)connection_in_active_linked_list(c1); });
  ASSERT_CHILD_ABORTS({ c1->active_linked_conn_idx = 50;
                        (void)connection_in_active_linked_list(c1); });
  ASSERT_CHILD_ABORTS({ c1->active_linked_conn_idx =
                          c2->active_linked_conn_idx;
                        (void)connection_in_active_linked_list(c1); });
  ASSERT_CHILD_ABORTS({ connection_remove(c1); connection_free_(c1); });
  ASSERT_CHILD_ABORTS({ c1->closeable_conn_idx = 50;
                        (void)connection_is_on_closeable_list(c1); });
  ASSERT_CHILD_ABORTS({ c1->marked_for_close = 1;
                        add_connection_to_closeable_list(c1);
                        add_connection_to_closeable_list(c1); });
  ASSERT_CHILD_ABORTS({ c1->marked_for_close = 1;
                        add_connection_to_closeable_list(c1);
                        c2->closeable_conn_idx = c1->closeable_conn_idx;
                        (void)connection_is_on_closeable_list(c2); });
  ASSERT_CHILD_ABORTS({ c1->marked_for_close = 1;
                        add_connection_to_closeable_list(c1);
                        connection_stop_reading_from_linked_conn(c1);
                        connection_remove(c1);
                        connection_free_(c1); });

 done:
  if (c1)
    free_test_conn(c1);
  if (c2)
    free_test_conn(c2);
}
#endif /* !defined(_WIN32) */

static void
test_mainloop_randomized_cleanup_lifecycle(void *arg)
{
  (void)arg;
  smartlist_t *live = smartlist_new();
  uint64_t rng = UINT64_C(0x1ae020261018beef);

  tor_init_connection_lists();
  initialize_mainloop_events();

  for (int step = 0; step < 2500; ++step) {
    rng ^= rng >> 12;
    rng ^= rng << 25;
    rng ^= rng >> 27;
    uint64_t r = rng * UINT64_C(2685821657736338717);
    int op = (int)(r % 7);
    int n_live = smartlist_len(live);

    if (op == 0 || n_live == 0) {
      if (n_live < 96) {
        connection_t *a = NULL, *b = NULL;
        new_test_linked_pair(&a, &b, live);
        if (r & 0x100) {
          a->reading_from_linked_conn = 1;
          connection_start_reading_from_linked_conn(a);
        }
        if (r & 0x200) {
          b->reading_from_linked_conn = 1;
          connection_start_reading_from_linked_conn(b);
        }
      }
    } else if (op == 1) {
      connection_free_(connection_new(CONN_TYPE_DIR, AF_INET));
    } else if (op == 2) {
      connection_t *c = smartlist_get(live, (int)((r >> 8) % n_live));
      c->reading_from_linked_conn = (r >> 17) & 1;
      if ((r >> 16) & 1) {
        connection_start_reading_from_linked_conn(c);
      } else {
        connection_stop_reading_from_linked_conn(c);
      }
    } else if (op == 3) {
      int count = 1 + (int)((r >> 8) % 3);
      for (int k = 0; k < count && smartlist_len(live) > 0; ++k) {
        int idx = (int)((r >> (16 + k * 8)) % smartlist_len(live));
        connection_t *victim = smartlist_get(live, idx);
        if (!victim->marked_for_close)
          connection_mark_for_close(victim);
      }
      assert_cleanup_containers_coherent(live);
      SMARTLIST_FOREACH(closeable_connection_lst, connection_t *, c,
                        smartlist_remove(live, c));
      close_closeable_connections();
    } else if (op == 4) {
      connection_t *victim = smartlist_get(live, (int)((r >> 8) % n_live));
      if (connection_in_array(victim))
        connection_remove(victim);
      connection_mark_for_close(victim);
      assert_cleanup_containers_coherent(live);
      smartlist_remove(live, victim);
      close_closeable_connections();
    } else if (op == 5) {
      int len = smartlist_len(connection_array);
      for (int i = len - 1; i > 0; --i) {
        int j = (int)(((r >> 8) + (uint64_t)i * 2654435761U) %
                      (uint64_t)(i + 1));
        smartlist_swap(connection_array, i, j);
      }
      SMARTLIST_FOREACH_BEGIN(connection_array, connection_t *, c) {
        c->conn_array_index = c_sl_idx;
      } SMARTLIST_FOREACH_END(c);
    } else {
      int idx = (int)((r >> 8) % n_live);
      connection_t *victim = smartlist_get(live, idx);
      smartlist_del(live, idx);
      free_test_conn(victim);
    }
    assert_cleanup_containers_coherent(live);
  }

  SMARTLIST_FOREACH(live, connection_t *, c, connection_mark_for_close(c));
  assert_cleanup_containers_coherent(live);
  smartlist_clear(live);
  close_closeable_connections();
  assert_cleanup_containers_coherent(live);
  tt_int_op(smartlist_len(connection_array), OP_EQ, 0);
  tt_int_op(smartlist_len(active_linked_connection_lst), OP_EQ, 0);

 done:
  SMARTLIST_FOREACH(live, connection_t *, c, free_test_conn(c));
  smartlist_free(live);
}

static dir_connection_t *
new_test_server_dir_pair(connection_t **edge_out, uint16_t stream_idx,
                         smartlist_t *live)
{
  connection_t *edge_c = NULL, *dir_c = NULL;
  new_test_linked_pair(&edge_c, &dir_c, live);
  tor_addr_from_ipv4h(&edge_c->addr, 0x7f000001);
  tor_addr_from_ipv4h(&dir_c->addr, 0x7f000001);
  dir_c->state = DIR_CONN_STATE_SERVER_COMMAND_WAIT;
  dir_connection_t *d = TO_DIR_CONN(dir_c);
  relay_metrics_note_dir_stream_phase(d, DIR_STREAM_PHASE_OPENED, stream_idx);
  if (edge_out)
    *edge_out = edge_c;
  return d;
}

static void
test_mainloop_normal_directory_and_metrics(void *arg)
{
  (void)arg;
  smartlist_t *live = smartlist_new();
  buf_t *prom_buf = buf_new();
  char *prom_str = NULL;

  tor_init_connection_lists();
  initialize_mainloop_events();
  reset_main_loop_counters();
  relay_metrics_free();
  relay_metrics_init();

  /* 1. Multi-stream circuit reuse: consensus, microdesc, server_desc,
   * extra_info, authority_certs, and hs_v3_fetch on the same circuit. */
  static const char *const reqs[] = {
    "GET /tor/status-vote/current/consensus HTTP/1.0\r\n\r\n",
    "GET /tor/micro/d/abcd HTTP/1.0\r\n\r\n",
    "GET /tor/server/fp/abcd HTTP/1.0\r\n\r\n",
    "GET /tor/extra/fp/abcd HTTP/1.0\r\n\r\n",
    "GET /tor/keys/all HTTP/1.0\r\n\r\n",
    "GET /tor/hs/3/z32blindedkey HTTP/1.0\r\n\r\n",
  };
  for (size_t i = 0; i < ARRAY_LENGTH(reqs); ++i) {
    connection_t *edge_c = NULL;
    dir_connection_t *d =
      new_test_server_dir_pair(&edge_c, (uint16_t)(i + 1), live);
    buf_add_string(TO_CONN(d)->inbuf, reqs[i]);
    tt_int_op(directory_handle_command(d), OP_EQ, 0);
    tt_int_op(d->dir_stream_phase, OP_EQ, DIR_STREAM_PHASE_WRITING);
    size_t moved = buf_move_all(edge_c->inbuf, TO_CONN(d)->outbuf);
    relay_metrics_note_dir_bytes(d, true, moved);
    tt_int_op(connection_dir_finished_flushing(d), OP_EQ, 0);
    tt_int_op(d->dir_stream_phase, OP_EQ, DIR_STREAM_PHASE_COMPLETED);
    connection_mark_for_close(edge_c);
  }
  assert_cleanup_containers_coherent(live);
  smartlist_clear(live);
  close_closeable_connections();

  /* 2. Pre-HTTP abort, mid-HTTP client abort, mid-response write abort,
   * and server early rejection (unknown verb). */
  connection_t *e_pre = NULL, *e_mid = NULL, *e_wr = NULL, *e_rej = NULL;
  (void)new_test_server_dir_pair(&e_pre, 1, live);
  dir_connection_t *d_mid = new_test_server_dir_pair(&e_mid, 1, live);
  dir_connection_t *d_wr = new_test_server_dir_pair(&e_wr, 1, live);
  dir_connection_t *d_rej = new_test_server_dir_pair(&e_rej, 1, live);

  TO_CONN(d_mid)->inbuf_reached_eof = 1;
  buf_add_string(TO_CONN(d_mid)->inbuf, "GET /tor/partial");

  buf_add_string(TO_CONN(d_wr)->inbuf, "GET /tor/robots.txt HTTP/1.0\r\n\r\n");
  tt_int_op(directory_handle_command(d_wr), OP_EQ, 0);
  TO_CONN(d_wr)->linked_conn_is_closed = 1;
  buf_clear(TO_CONN(d_wr)->outbuf);

  buf_add_string(TO_CONN(d_rej)->inbuf, "PUT /tor/ HTTP/1.0\r\n\r\n");
  tt_int_op(directory_handle_command(d_rej), OP_EQ, -1);

  SMARTLIST_FOREACH(live, connection_t *, c, connection_mark_for_close(c));
  smartlist_clear(live);
  close_closeable_connections();

  /* 3. Slow client holding response open across a close pass before flushing. */
  connection_t *e_slow = NULL;
  dir_connection_t *d_slow = new_test_server_dir_pair(&e_slow, 1, live);
  buf_add_string(TO_CONN(d_slow)->inbuf, "GET /tor/ HTTP/1.0\r\n\r\n");
  tt_int_op(directory_handle_command(d_slow), OP_EQ, 0);
  connection_mark_for_close(TO_CONN(d_slow));
  TO_CONN(d_slow)->hold_open_until_flushed = 1;
  /* First pass: linked flush moves outbuf to e_slow and completes d_slow. */
  smartlist_remove(live, TO_CONN(d_slow));
  close_closeable_connections();
  connection_mark_for_close(e_slow);
  smartlist_clear(live);
  close_closeable_connections();

  const mainloop_metrics_t *m = mainloop_get_metrics();
  tt_int_op(m->conn_array_len, OP_EQ, 0);
  tt_int_op(m->closeable_len, OP_EQ, 0);
  tt_int_op(m->active_linked_len, OP_EQ, 0);
  tt_u64_op(m->closeable_added, OP_EQ, 22);
  tt_u64_op(m->close_pass_runs, OP_GE, 4);
  tt_u64_op(m->close_pass_closed, OP_EQ, 22);

  const smartlist_t *stores = relay_metrics_get_stores();
  tt_assert(stores);
  metrics_store_get_output(METRICS_FORMAT_PROMETHEUS,
                           smartlist_get(stores, 0), prom_buf);
  prom_str = buf_extract(prom_buf, NULL);
  tt_assert(strstr(prom_str,
    "tor_relay_dir_streams_total{phase=\"opened\"} 11\n"));
  tt_assert(strstr(prom_str,
    "tor_relay_dir_streams_total{phase=\"writing\"} 8\n"));
  tt_assert(strstr(prom_str,
    "tor_relay_dir_streams_total{phase=\"completed\"} 7\n"));
  tt_assert(strstr(prom_str,
    "tor_relay_dir_streams_total{phase=\"aborted_pre_http\"} 1\n"));
  tt_assert(strstr(prom_str,
    "tor_relay_dir_streams_total{phase=\"aborted_mid_http\"} 2\n"));
  tt_assert(strstr(prom_str,
    "tor_relay_dir_streams_total{phase=\"aborted_writing\"} 1\n"));
  tt_assert(strstr(prom_str,
    "tor_relay_dir_streams_total{phase=\"reused_circuit\"} 5\n"));
  tt_assert(strstr(prom_str,
    "tor_relay_dir_streams_active{state=\"opened_wait\"} 0\n"));
  tt_assert(strstr(prom_str,
    "tor_relay_dir_streams_active{state=\"writing\"} 0\n"));
  tt_assert(strstr(prom_str,
    "tor_relay_dir_http_requests_total{class=\"invalid\","
    "status=\"rejected_early\"} 1\n"));
  tt_assert(strstr(prom_str,
    "tor_relay_dir_http_requests_total{class=\"hs_v3_fetch\","
    "status=\"503\"} 1\n"));

 done:
  tor_free(prom_str);
  buf_free(prom_buf);
  relay_metrics_free();
  SMARTLIST_FOREACH(live, connection_t *, c, free_test_conn(c));
  smartlist_free(live);
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
  MAINLOOP_TEST(active_linked_list_indexing),
  MAINLOOP_TEST(linked_peer_teardown_and_oom_reorder),
#ifndef _WIN32
  MAINLOOP_TEST(index_corruption_assertions),
#endif
  MAINLOOP_TEST(randomized_cleanup_lifecycle),
  MAINLOOP_TEST(normal_directory_and_metrics),
  END_OF_TESTCASES
};
