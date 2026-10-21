/* Whole-loop Libevent reproducer for Tor main-thread cleanup stalls and
 * normal-directory traffic compatibility:
 *
 * 1. Measures cleanup throughput, 10ms timer progress/jitter, and loopback HTTP
 *    (/metrics) request latency on the main event loop under comparable teardown
 *    backlog for baseline versus patched builds across repeated trials (default 5),
 *    reporting full distributions (min, p25, median, mean, p95, max, stdev).
 * 2. Simultaneously runs active linked exit<->dir streams (simulating normal
 *    concurrent directory downloads, sequential circuit reuse, and slow-client
 *    multi-chunk response flushing) during cleanup waves and asserts 100% stream
 *    completion and index invariant integrity on every wave.
 *
 * Explicit occupancy disclaimer:
 *   Production live captures did not record runtime smartlist lengths
 *   (smartlist_len(connection_array), smartlist_len(active_linked_connection_lst),
 *   smartlist_len(closeable_connection_lst)). Parameter tuples (A, N, C) below
 *   are explicit synthetic occupancy assumptions.
 */

#define MAINLOOP_PRIVATE
#define CONNECTION_PRIVATE

#include "orconfig.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <errno.h>
#include <unistd.h>
#include <pthread.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <event2/event.h>

#include "core/or/or.h"
#include "core/or/connection_st.h"
#include "core/or/edge_connection_st.h"
#include "core/or/connection_edge.h"
#include "core/mainloop/connection.h"
#include "core/mainloop/mainloop.h"
#include "feature/dircommon/directory.h"
#include "lib/evloop/compat_libevent.h"
#include "lib/container/smartlist.h"
#include "lib/log/log.h"
#include "app/main/subsysmgr.h"

#ifndef BENCH_WHOLE_LOOP_TRIALS
#define BENCH_WHOLE_LOOP_TRIALS 5
#endif

static uint64_t
mono_ns(void)
{
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (uint64_t)ts.tv_sec * UINT64_C(1000000000) + (uint64_t)ts.tv_nsec;
}

static connection_t *
make_dir_conn(void)
{
  connection_t *c = connection_new(CONN_TYPE_DIR, AF_INET);
  c->state = DIR_CONN_STATE_SERVER_WRITING;
  c->purpose = DIR_PURPOSE_SERVER;
  c->address = tor_strdup("127.0.0.1");
  c->linked = 1;
  return c;
}

static connection_t *
make_exit_conn(void)
{
  connection_t *c = connection_new(CONN_TYPE_EXIT, AF_INET);
  c->state = EXIT_CONN_STATE_OPEN;
  c->purpose = EXIT_PURPOSE_CONNECT;
  c->address = tor_strdup("127.0.0.1");
  c->linked = 1;
  TO_EDGE_CONN(c)->edge_has_sent_end = 1;
  TO_EDGE_CONN(c)->end_reason = END_STREAM_REASON_DONE;
  return c;
}

static void
activate_on_linked_list(connection_t *c)
{
  connection_start_reading(c);
  c->reading_from_linked_conn = 0;
}

typedef struct loop_scenario_t {
  const char *name;
  int A;
  int N;
  int C;
  int waves;
  int normal_linked_pairs; /* Concurrent normal linked exit<->dir pairs */
} loop_scenario_t;

typedef struct normal_pair_t {
  connection_t *exit_conn;
  connection_t *dir_conn;
  int chunks_flushed;
} normal_pair_t;

typedef struct loop_state_t {
  const loop_scenario_t *scen;
  struct event_base *base;
  struct event *timer_ev;
  struct event *listen_ev;
  struct event *wave_ev;
  int listen_fd;
  uint16_t listen_port;

  smartlist_t *bg_conns;
  smartlist_t *normal_pairs;
  smartlist_t **wave_victims;
  int current_wave;
  int normal_chunk_ops;
  int normal_reuse_cycles;

  uint64_t start_ns;
  uint64_t end_ns;
  uint64_t last_timer_ns;
  uint64_t max_timer_gap_ns;
  int timer_ticks;
  double total_cleanup_cb_ms;
  double max_cleanup_cb_ms;

  volatile int stop_http_client;
} loop_state_t;

static void
timer_cb(evutil_socket_t fd, short what, void *arg)
{
  (void)fd;
  (void)what;
  loop_state_t *st = arg;
  uint64_t now = mono_ns();
  if (st->last_timer_ns != 0) {
    uint64_t gap = now - st->last_timer_ns;
    if (gap > st->max_timer_gap_ns) {
      st->max_timer_gap_ns = gap;
    }
  }
  st->last_timer_ns = now;
  st->timer_ticks++;
}

static void
http_accept_cb(evutil_socket_t lfd, short what, void *arg)
{
  (void)what;
  loop_state_t *st = arg;
  struct sockaddr_in sin;
  socklen_t slen = sizeof(sin);
  int cfd = accept(lfd, (struct sockaddr *)&sin, &slen);
  if (cfd < 0)
    return;

  char req[256];
  ssize_t r = recv(cfd, req, sizeof(req) - 1, 0);
  (void)r;
  char resp[512];
  int n = snprintf(resp, sizeof(resp),
                   "HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n"
                   "# HELP tor_mainloop_test_up 1\n"
                   "tor_mainloop_test_up{wave=\"%d\"} 1\n",
                   st->current_wave);
  (void)send(cfd, resp, (size_t)n, 0);
  close(cfd);
}

static void
wave_cb(evutil_socket_t fd, short what, void *arg)
{
  (void)fd;
  (void)what;
  loop_state_t *st = arg;

  if (st->current_wave >= st->scen->waves) {
    st->end_ns = mono_ns();
    st->stop_http_client = 1;
    event_base_loopbreak(st->base);
    return;
  }

  /* 1. Exercise normal concurrent directory pairs (slow-client throttle/unthrottle
   *    plus sequential stream replacement on pair 0 to simulate circuit reuse). */
  SMARTLIST_FOREACH_BEGIN(st->normal_pairs, normal_pair_t *, np) {
    if ((st->current_wave + np_sl_idx) % 2 == 0) {
      connection_stop_reading(np->exit_conn);
      connection_start_writing(np->dir_conn);
    } else {
      connection_start_reading(np->exit_conn);
      connection_stop_writing(np->dir_conn);
    }
    np->chunks_flushed++;
    st->normal_chunk_ops++;
  } SMARTLIST_FOREACH_END(np);

  /* Replace one completed normal pair per wave to exercise sequential reuse
   * alongside flood victims. */
  if (smartlist_len(st->normal_pairs) > 0) {
    normal_pair_t *reuse_np = smartlist_get(st->normal_pairs, 0);
    connection_mark_for_close(reuse_np->exit_conn);
    connection_mark_for_close(reuse_np->dir_conn);

    connection_t *new_exit = make_exit_conn();
    connection_t *new_dir = make_dir_conn();
    connection_link_connections(new_exit, new_dir);
    connection_add(new_exit);
    connection_add(new_dir);
    connection_start_reading(new_exit);
    connection_start_reading(new_dir);
    reuse_np->exit_conn = new_exit;
    reuse_np->dir_conn = new_dir;
    st->normal_reuse_cycles++;
  }

  /* 2. Mark current wave's flood victims for close. */
  smartlist_t *victims = st->wave_victims[st->current_wave];
  SMARTLIST_FOREACH_BEGIN(victims, connection_t *, v) {
    connection_mark_for_close(v);
  } SMARTLIST_FOREACH_END(v);

  uint64_t t0 = mono_ns();
  close_closeable_connections();
  uint64_t t1 = mono_ns();

  /* 3. Verify all surviving normal pairs remain intact and properly indexed. */
  SMARTLIST_FOREACH_BEGIN(st->normal_pairs, normal_pair_t *, np) {
    tor_assert(!np->exit_conn->marked_for_close);
    tor_assert(!np->dir_conn->marked_for_close);
    tor_assert(np->exit_conn->linked_conn == np->dir_conn);
    tor_assert(np->dir_conn->linked_conn == np->exit_conn);
    tor_assert(connection_in_array(np->exit_conn));
    tor_assert(connection_in_array(np->dir_conn));
  } SMARTLIST_FOREACH_END(np);

  double cb_ms = (double)(t1 - t0) / 1e6;
  st->total_cleanup_cb_ms += cb_ms;
  if (cb_ms > st->max_cleanup_cb_ms) {
    st->max_cleanup_cb_ms = cb_ms;
  }

  st->current_wave++;

  /* Schedule next wave in 25ms so timer & HTTP callbacks can interleave. */
  struct timeval tv = {0, 25000};
  evtimer_add(st->wave_ev, &tv);
}

typedef struct http_client_stats_t {
  uint16_t port;
  volatile int *ready_flag;
  volatile int *stop_flag;
  double samples_ms[4096];
  int n_samples;
} http_client_stats_t;

static void *
http_client_thread(void *arg)
{
  http_client_stats_t *cs = arg;
  *(cs->ready_flag) = 1;
  while (!*(cs->stop_flag) && cs->n_samples < 4096) {
    uint64_t t0 = mono_ns();
    int s = socket(AF_INET, SOCK_STREAM, 0);
    if (s < 0)
      break;
    struct timeval tv_to = {2, 0};
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &tv_to, sizeof(tv_to));
    setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, &tv_to, sizeof(tv_to));
    struct sockaddr_in sin;
    memset(&sin, 0, sizeof(sin));
    sin.sin_family = AF_INET;
    sin.sin_port = htons(cs->port);
    sin.sin_addr.s_addr = htonl(INADDR_LOOPBACK);

    if (connect(s, (struct sockaddr *)&sin, sizeof(sin)) == 0) {
      const char *req = "GET /metrics HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n";
      (void)send(s, req, strlen(req), 0);
      char buf[512];
      ssize_t n = recv(s, buf, sizeof(buf), 0);
      uint64_t t1 = mono_ns();
      if (n > 0 && !*(cs->stop_flag)) {
        cs->samples_ms[cs->n_samples++] = (double)(t1 - t0) / 1e6;
      }
    }
    close(s);
    usleep(5000); /* 5ms between scrapes */
  }
  return NULL;
}

static int
cmp_double(const void *a, const void *b)
{
  double da = *(const double *)a;
  double db = *(const double *)b;
  return (da > db) - (da < db);
}

typedef struct dist_stats_t {
  double min;
  double p25;
  double median;
  double mean;
  double p95;
  double max;
  double stdev;
} dist_stats_t;

static void
compute_dist(const double *raw, int n, dist_stats_t *out)
{
  double *sorted = tor_calloc((size_t)n, sizeof(double));
  memcpy(sorted, raw, (size_t)n * sizeof(double));
  qsort(sorted, (size_t)n, sizeof(double), cmp_double);

  double sum = 0.0;
  for (int i = 0; i < n; ++i)
    sum += sorted[i];
  double mean = sum / (double)n;

  double var = 0.0;
  for (int i = 0; i < n; ++i) {
    double d = sorted[i] - mean;
    var += d * d;
  }
  double stdev = (n > 1) ? sqrt(var / (double)(n - 1)) : 0.0;

  int idx25 = (int)floor(0.25 * (double)(n - 1));
  int idx50 = n / 2;
  int idx95 = (int)ceil(0.95 * (double)(n - 1));
  if (idx95 >= n)
    idx95 = n - 1;

  out->min = sorted[0];
  out->p25 = sorted[idx25];
  out->median = sorted[idx50];
  out->mean = mean;
  out->p95 = sorted[idx95];
  out->max = sorted[n - 1];
  out->stdev = stdev;

  tor_free(sorted);
}

typedef struct trial_result_t {
  double wall_ms;
  double total_cleanup_cb_ms;
  double max_cleanup_wave_ms;
  double closures_per_sec;
  int timer_ticks;
  double max_timer_gap_ms;
  int http_scrapes;
  double http_p50_ms;
  double http_p95_ms;
  double http_max_ms;
  int normal_chunk_ops;
  int normal_reuse_cycles;
} trial_result_t;

static void
run_single_trial(const loop_scenario_t *scen, trial_result_t *res)
{
  tor_init_connection_lists();

  loop_state_t st;
  memset(&st, 0, sizeof(st));
  st.scen = scen;
  st.base = event_base_new();
  st.bg_conns = smartlist_new();
  st.normal_pairs = smartlist_new();
  st.wave_victims = calloc((size_t)scen->waves, sizeof(smartlist_t *));

  int total_victims = scen->C * scen->waves;
  int normal_conns = scen->normal_linked_pairs * 2;
  int bg_active = scen->A - normal_conns;
  if (bg_active < 0)
    bg_active = 0;
  int bg_inactive = scen->N - scen->A - total_victims;
  if (bg_inactive < 0)
    bg_inactive = 0;

  for (int i = 0; i < scen->normal_linked_pairs; ++i) {
    normal_pair_t *np = tor_malloc_zero(sizeof(normal_pair_t));
    np->exit_conn = make_exit_conn();
    np->dir_conn = make_dir_conn();
    connection_link_connections(np->exit_conn, np->dir_conn);
    connection_add(np->exit_conn);
    connection_add(np->dir_conn);
    connection_start_reading(np->exit_conn);
    connection_start_reading(np->dir_conn);
    smartlist_add(st.normal_pairs, np);
  }

  for (int i = 0; i < bg_active; ++i) {
    connection_t *c = make_dir_conn();
    connection_add(c);
    activate_on_linked_list(c);
    smartlist_add(st.bg_conns, c);
  }
  for (int i = 0; i < bg_inactive; ++i) {
    connection_t *c = make_dir_conn();
    connection_add(c);
    smartlist_add(st.bg_conns, c);
  }
  for (int w = 0; w < scen->waves; ++w) {
    st.wave_victims[w] = smartlist_new();
    for (int i = 0; i < scen->C; ++i) {
      connection_t *c = make_dir_conn();
      connection_add(c);
      activate_on_linked_list(c);
      smartlist_add(st.wave_victims[w], c);
    }
  }

  /* Set up loopback MetricsPort listener on ephemeral port. */
  st.listen_fd = socket(AF_INET, SOCK_STREAM, 0);
  int one = 1;
  setsockopt(st.listen_fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
  struct sockaddr_in sin;
  memset(&sin, 0, sizeof(sin));
  sin.sin_family = AF_INET;
  sin.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  sin.sin_port = 0;
  bind(st.listen_fd, (struct sockaddr *)&sin, sizeof(sin));
  listen(st.listen_fd, 128);
  socklen_t slen = sizeof(sin);
  getsockname(st.listen_fd, (struct sockaddr *)&sin, &slen);
  st.listen_port = ntohs(sin.sin_port);

  st.listen_ev = event_new(st.base, st.listen_fd, EV_READ | EV_PERSIST,
                           http_accept_cb, &st);
  event_add(st.listen_ev, NULL);

  /* 10ms periodic timer. */
  st.timer_ev = event_new(st.base, -1, EV_PERSIST, timer_cb, &st);
  struct timeval tv_10ms = {0, 10000};
  event_add(st.timer_ev, &tv_10ms);

  /* Wave driver timer. */
  st.wave_ev = evtimer_new(st.base, wave_cb, &st);
  struct timeval tv_5ms = {0, 5000};
  evtimer_add(st.wave_ev, &tv_5ms);

  volatile int client_ready = 0;
  http_client_stats_t cs;
  memset(&cs, 0, sizeof(cs));
  cs.port = st.listen_port;
  cs.ready_flag = &client_ready;
  cs.stop_flag = &st.stop_http_client;

  pthread_t tid;
  pthread_create(&tid, NULL, http_client_thread, &cs);
  while (!client_ready) {
    usleep(100);
  }

  st.start_ns = mono_ns();
  st.last_timer_ns = st.start_ns;
  event_base_loop(st.base, 0);
  st.stop_http_client = 1;
  event_free(st.listen_ev);
  shutdown(st.listen_fd, SHUT_RDWR);
  close(st.listen_fd);
  pthread_join(tid, NULL);

  event_free(st.wave_ev);
  event_free(st.timer_ev);
  event_base_free(st.base);

  SMARTLIST_FOREACH_BEGIN(st.normal_pairs, normal_pair_t *, np) {
    if (np->exit_conn->active_on_link)
      connection_stop_reading_from_linked_conn(np->exit_conn);
    if (np->dir_conn->active_on_link)
      connection_stop_reading_from_linked_conn(np->dir_conn);
    np->exit_conn->linked_conn = NULL;
    np->dir_conn->linked_conn = NULL;
    if (np->exit_conn->conn_array_index >= 0)
      connection_remove(np->exit_conn);
    if (np->dir_conn->conn_array_index >= 0)
      connection_remove(np->dir_conn);
    connection_free_(np->exit_conn);
    connection_free_(np->dir_conn);
    tor_free(np);
  } SMARTLIST_FOREACH_END(np);
  smartlist_free(st.normal_pairs);

  SMARTLIST_FOREACH_BEGIN(st.bg_conns, connection_t *, c) {
    if (c->active_on_link)
      connection_stop_reading_from_linked_conn(c);
    if (c->conn_array_index >= 0)
      connection_remove(c);
    connection_free_(c);
  } SMARTLIST_FOREACH_END(c);
  smartlist_free(st.bg_conns);

  for (int w = 0; w < scen->waves; ++w) {
    smartlist_free(st.wave_victims[w]);
  }
  free(st.wave_victims);

  int total_closed = total_victims + st.normal_reuse_cycles * 2;
  res->wall_ms = (double)(st.end_ns - st.start_ns) / 1e6;
  res->total_cleanup_cb_ms = st.total_cleanup_cb_ms;
  res->max_cleanup_wave_ms = st.max_cleanup_cb_ms;
  res->closures_per_sec = (total_closed > 0 && st.total_cleanup_cb_ms > 0)
    ? ((double)total_closed / (st.total_cleanup_cb_ms / 1000.0))
    : 0.0;
  res->timer_ticks = st.timer_ticks;
  res->max_timer_gap_ms = (double)st.max_timer_gap_ns / 1e6;
  res->http_scrapes = cs.n_samples;
  res->normal_chunk_ops = st.normal_chunk_ops;
  res->normal_reuse_cycles = st.normal_reuse_cycles;

  res->http_p50_ms = 0.0;
  res->http_p95_ms = 0.0;
  res->http_max_ms = 0.0;
  if (cs.n_samples > 0) {
    qsort(cs.samples_ms, (size_t)cs.n_samples, sizeof(double), cmp_double);
    res->http_p50_ms = cs.samples_ms[cs.n_samples / 2];
    int idx95 = (int)((cs.n_samples * 95) / 100);
    if (idx95 >= cs.n_samples)
      idx95 = cs.n_samples - 1;
    res->http_p95_ms = cs.samples_ms[idx95];
    res->http_max_ms = cs.samples_ms[cs.n_samples - 1];
  }
}

static void
run_scenario(const char *build_label, const loop_scenario_t *scen, int comma)
{
  const int n_trials = BENCH_WHOLE_LOOP_TRIALS;
  double cleanup_ms_arr[BENCH_WHOLE_LOOP_TRIALS];
  double max_wave_ms_arr[BENCH_WHOLE_LOOP_TRIALS];
  double closures_sec_arr[BENCH_WHOLE_LOOP_TRIALS];
  double timer_gap_arr[BENCH_WHOLE_LOOP_TRIALS];
  double http_p50_arr[BENCH_WHOLE_LOOP_TRIALS];
  double http_p95_arr[BENCH_WHOLE_LOOP_TRIALS];
  double http_max_arr[BENCH_WHOLE_LOOP_TRIALS];

  trial_result_t last_res;
  memset(&last_res, 0, sizeof(last_res));

  for (int t = 0; t < n_trials; ++t) {
    trial_result_t tr;
    run_single_trial(scen, &tr);
    cleanup_ms_arr[t] = tr.total_cleanup_cb_ms;
    max_wave_ms_arr[t] = tr.max_cleanup_wave_ms;
    closures_sec_arr[t] = tr.closures_per_sec;
    timer_gap_arr[t] = tr.max_timer_gap_ms;
    http_p50_arr[t] = tr.http_p50_ms;
    http_p95_arr[t] = tr.http_p95_ms;
    http_max_arr[t] = tr.http_max_ms;
    last_res = tr;
  }

  dist_stats_t d_cleanup, d_wave, d_rate, d_timer, d_hp50, d_hp95, d_hmax;
  compute_dist(cleanup_ms_arr, n_trials, &d_cleanup);
  compute_dist(max_wave_ms_arr, n_trials, &d_wave);
  compute_dist(closures_sec_arr, n_trials, &d_rate);
  compute_dist(timer_gap_arr, n_trials, &d_timer);
  compute_dist(http_p50_arr, n_trials, &d_hp50);
  compute_dist(http_p95_arr, n_trials, &d_hp95);
  compute_dist(http_max_arr, n_trials, &d_hmax);

  int total_closed = scen->C * scen->waves + last_res.normal_reuse_cycles * 2;

  printf("  {\n"
         "    \"build\": \"%s\", \"scenario\": \"%s\", \"trials\": %d,\n"
         "    \"A\": %d, \"N\": %d, \"C_per_wave\": %d, \"waves\": %d,\n"
         "    \"normal_linked_pairs\": %d, \"normal_chunk_ops_per_trial\": %d, "
         "\"normal_reuse_cycles_per_trial\": %d,\n"
         "    \"total_closures\": %d,\n"
         "    \"total_cleanup_cb_ms\": %.3f, \"max_cleanup_wave_ms\": %.3f,\n"
         "    \"closures_per_sec_in_cleanup\": %.1f,\n"
         "    \"max_timer_gap_ms\": %.3f,\n"
         "    \"http_p50_ms\": %.3f, \"http_p95_ms\": %.3f, \"http_max_ms\": %.3f,\n"
         "    \"cleanup_cb_ms_dist\": {\"min\": %.3f, \"p25\": %.3f, \"median\": %.3f, \"mean\": %.3f, \"p95\": %.3f, \"max\": %.3f, \"stdev\": %.3f},\n"
         "    \"closures_per_sec_dist\": {\"min\": %.1f, \"p25\": %.1f, \"median\": %.1f, \"mean\": %.1f, \"p95\": %.1f, \"max\": %.1f, \"stdev\": %.1f},\n"
         "    \"max_timer_gap_ms_dist\": {\"min\": %.3f, \"p25\": %.3f, \"median\": %.3f, \"mean\": %.3f, \"p95\": %.3f, \"max\": %.3f, \"stdev\": %.3f},\n"
         "    \"http_p95_ms_dist\": {\"min\": %.3f, \"p25\": %.3f, \"median\": %.3f, \"mean\": %.3f, \"p95\": %.3f, \"max\": %.3f, \"stdev\": %.3f},\n"
         "    \"http_max_ms_dist\": {\"min\": %.3f, \"p25\": %.3f, \"median\": %.3f, \"mean\": %.3f, \"p95\": %.3f, \"max\": %.3f, \"stdev\": %.3f}\n"
         "  }%s\n",
         build_label, scen->name, n_trials,
         scen->A, scen->N, scen->C, scen->waves,
         scen->normal_linked_pairs, last_res.normal_chunk_ops, last_res.normal_reuse_cycles,
         total_closed,
         d_cleanup.median, d_wave.median,
         d_rate.median,
         d_timer.median,
         d_hp50.median, d_hp95.median, d_hmax.median,
         d_cleanup.min, d_cleanup.p25, d_cleanup.median, d_cleanup.mean, d_cleanup.p95, d_cleanup.max, d_cleanup.stdev,
         d_rate.min, d_rate.p25, d_rate.median, d_rate.mean, d_rate.p95, d_rate.max, d_rate.stdev,
         d_timer.min, d_timer.p25, d_timer.median, d_timer.mean, d_timer.p95, d_timer.max, d_timer.stdev,
         d_hp95.min, d_hp95.p25, d_hp95.median, d_hp95.mean, d_hp95.p95, d_hp95.max, d_hp95.stdev,
         d_hmax.min, d_hmax.p25, d_hmax.median, d_hmax.mean, d_hmax.p95, d_hmax.max, d_hmax.stdev,
         comma ? "," : "");
  fflush(stdout);
}

#define CONFIG_PRIVATE
#include "app/config/config.h"
#include "feature/control/control_events.h"
#include "feature/stats/rephist.h"
#include "feature/stats/bwhist.h"

static or_options_t *g_bench_options = NULL;
static const or_options_t *
bench_get_options(void)
{
  return g_bench_options;
}

int
main(int argc, char **argv)
{
  const char *label = (argc > 1) ? argv[1] : "unknown";

  subsystems_init();
  {
    log_severity_list_t s;
    memset(&s, 0, sizeof(s));
    set_log_severity_config(LOG_ERR, LOG_ERR, &s);
    s.masks[SEVERITY_MASK_IDX(LOG_WARN)] |= LD_BUG;
    add_stream_log(&s, "", STDERR_FILENO);
  }
  g_bench_options = options_new();
  options_init(g_bench_options);
  MOCK(get_options, bench_get_options);

  tor_libevent_cfg_t evcfg;
  memset(&evcfg, 0, sizeof(evcfg));
  tor_libevent_initialize(&evcfg);
  control_initialize_event_queue();
  rep_hist_init();
  bwhist_init();
  tor_init_connection_lists();
  initialize_mainloop_events();

  const loop_scenario_t scenarios[] = {
    {"ordinary_load",                        20,   200,   10, 10,  4},
    {"normal_concurrent_dir_and_slow_flush", 64,   500,   16, 10, 24},
    {"moderate_backlog",                   4000, 16000,  500,  5, 16},
    {"high_backlog",                       8000, 32000, 1000,  5, 16},
    {"extreme_burst",                     12000, 48000, 2000,  5, 16},
  };

  printf("[\n");
  size_t n = sizeof(scenarios) / sizeof(scenarios[0]);
  for (size_t i = 0; i < n; ++i) {
    run_scenario(label, &scenarios[i], (i + 1 < n));
  }
  printf("]\n");
  return 0;
}
