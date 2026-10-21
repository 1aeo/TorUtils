/* Audited scaling benchmark for Tor main-thread connection cleanup:
 * Varies active_linked_connection_lst size (A), global connection_array size
 * (N), and batch closures (C) independently across multiple scales, victim
 * states (inactive in array, active on link, already absent from array, and
 * mixed with held-open backlog), and records:
 *   1. Exact full-list smartlist_remove comparisons (matching actual
 *      smartlist_remove in src/lib/smartlist_core/smartlist_core.c, which does
 *      NOT break on first match) alongside the legacy first-match counter to
 *      quantify the prior undercount.
 *   2. Separate mark-for-close (add_connection_to_closeable_list) vs teardown
 *      (close_closeable_connections) comparison counts.
 *   3. Repeated trial distributions (9 trials: min, p25, median/p50, mean,
 *      p95, max, stdev) for both process CPU time and monotonic wall time,
 *      plus RSS and sizeof(connection_t).
 *
 * NOTE: Live perf captures did not record runtime smartlist lengths (N, A, C).
 * All (A, N, C) points below are explicit synthetic parameter sweeps, not
 * replayed field counts.
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
#include <sys/resource.h>
#include <unistd.h>

#include "core/or/or.h"
#include "core/or/connection_st.h"
#include "core/or/connection_edge.h"
#include "core/or/edge_connection_st.h"
#include "core/mainloop/connection.h"
#include "core/mainloop/mainloop.h"
#include "feature/dircommon/directory.h"
#include "lib/evloop/compat_libevent.h"
#include "lib/buf/buffers.h"
#include "lib/container/smartlist.h"
#include "lib/log/log.h"
#include "app/main/subsysmgr.h"

extern void __real_smartlist_remove(smartlist_t *sl, const void *element);
extern int __real_smartlist_contains(const smartlist_t *sl,
                                     const void *element);
extern void __real_smartlist_del(smartlist_t *sl, int idx);

static int g_count_phase = 0; /* 0=off, 1=mark_for_close, 2=teardown */
static uint64_t g_mark_contains_calls = 0;
static uint64_t g_mark_contains_cmps = 0;
static uint64_t g_remove_calls = 0;
static uint64_t g_remove_full_cmps = 0;
static uint64_t g_remove_first_match_cmps = 0;
static uint64_t g_contains_calls = 0;
static uint64_t g_contains_cmps = 0;
static uint64_t g_del_calls = 0;

void
__wrap_smartlist_remove(smartlist_t *sl, const void *element)
{
  if (g_count_phase == 2 && element != NULL) {
    g_remove_calls++;
    if (sl) {
      /* Actual smartlist_remove in smartlist_core.c scans all sl->num_used
       * entries even after swapping a match from the tail (via i--). */
      g_remove_full_cmps += (uint64_t)sl->num_used;
      for (int i = 0; i < sl->num_used; i++) {
        g_remove_first_match_cmps++;
        if (sl->list[i] == element)
          break;
      }
    }
  }
  __real_smartlist_remove(sl, element);
}

int
__wrap_smartlist_contains(const smartlist_t *sl, const void *element)
{
  if (g_count_phase != 0) {
    uint64_t cmps = 0;
    if (sl) {
      for (int i = 0; i < sl->num_used; i++) {
        cmps++;
        if (sl->list[i] == element)
          break;
      }
    }
    if (g_count_phase == 1) {
      g_mark_contains_calls++;
      g_mark_contains_cmps += cmps;
    } else if (g_count_phase == 2) {
      g_contains_calls++;
      g_contains_cmps += cmps;
    }
  }
  return __real_smartlist_contains(sl, element);
}

void
__wrap_smartlist_del(smartlist_t *sl, int idx)
{
  if (g_count_phase == 2) {
    g_del_calls++;
  }
  __real_smartlist_del(sl, idx);
}

static uint64_t
now_ns(clockid_t cid)
{
  struct timespec ts;
  clock_gettime(cid, &ts);
  return (uint64_t)ts.tv_sec * UINT64_C(1000000000) + (uint64_t)ts.tv_nsec;
}

static long
current_rss_kb(void)
{
  FILE *f = fopen("/proc/self/status", "r");
  if (f) {
    char line[256];
    long rss = 0;
    while (fgets(line, sizeof(line), f)) {
      if (sscanf(line, "VmRSS: %ld kB", &rss) == 1) {
        fclose(f);
        return rss;
      }
    }
    fclose(f);
  }
  struct rusage ru;
  if (getrusage(RUSAGE_SELF, &ru) == 0) {
    return ru.ru_maxrss;
  }
  return 0;
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

static void
activate_on_linked_list(connection_t *c)
{
  connection_start_reading(c);
  c->reading_from_linked_conn = 0;
}

typedef enum victim_mode_t {
  VICTIM_INACTIVE_IN_ARRAY = 0,
  VICTIM_ACTIVE_IN_ARRAY = 1,
  VICTIM_ABSENT_FROM_ARRAY = 2,
  VICTIM_MIXED_WITH_HELD_OPEN = 3
} victim_mode_t;

typedef struct bench_point_t {
  const char *sweep_name;
  int A;
  int N;
  int C;
  victim_mode_t mode;
  int held_open_H;
} bench_point_t;

static const char *
victim_mode_str(victim_mode_t m)
{
  switch (m) {
    case VICTIM_INACTIVE_IN_ARRAY: return "inactive_in_array";
    case VICTIM_ACTIVE_IN_ARRAY: return "active_in_array";
    case VICTIM_ABSENT_FROM_ARRAY: return "absent_from_array";
    case VICTIM_MIXED_WITH_HELD_OPEN: return "mixed_with_held_open";
    default: return "unknown";
  }
}

static void
run_single_pass(const bench_point_t *pt,
                int count_mode,
                double *cpu_ms_out,
                double *wall_ms_out,
                long *rss_kb_out)
{
  tor_init_connection_lists();

  int total_N = pt->N;
  int active_A = pt->A;
  int close_C = pt->C;
  int held_H = pt->held_open_H;
  if (total_N < active_A + close_C + held_H) {
    total_N = active_A + close_C + held_H;
  }

  smartlist_t *bg_conns = smartlist_new();
  smartlist_t *held_conns = smartlist_new();
  smartlist_t *victims = smartlist_new();

  /* 1. Populate A background active-linked connections. */
  for (int i = 0; i < active_A; ++i) {
    connection_t *c = make_dir_conn();
    connection_add(c);
    activate_on_linked_list(c);
    smartlist_add(bg_conns, c);
  }

  /* 2. Populate inactive background connections so connection_array has N
   * entries (or N - C when C victims are in connection_array). */
  int victims_in_array = (pt->mode == VICTIM_ABSENT_FROM_ARRAY) ? 0 : close_C;
  int inactive_bg = total_N - active_A - victims_in_array - held_H;
  for (int i = 0; i < inactive_bg; ++i) {
    connection_t *c = make_dir_conn();
    connection_add(c);
    smartlist_add(bg_conns, c);
  }

  /* 3. Optionally populate H held-open connections at the head of
   * closeable_connection_lst (simulating connections deferred in
   * close_closeable_connections). */
  for (int i = 0; i < held_H; ++i) {
    connection_t *c = make_dir_conn();
    connection_add(c);
    connection_mark_for_close(c);
    c->marked_for_close = 0; /* Causes conn_close_if_marked to return 0 (++i) */
    smartlist_add(held_conns, c);
  }

  /* 4. Populate C victim connections to be closed in this pass. */
  for (int i = 0; i < close_C; ++i) {
    connection_t *c = make_dir_conn();
    if (pt->mode != VICTIM_ABSENT_FROM_ARRAY) {
      connection_add(c);
    }
    if (pt->mode == VICTIM_ACTIVE_IN_ARRAY ||
        (pt->mode == VICTIM_MIXED_WITH_HELD_OPEN && (i & 1) == 0)) {
      activate_on_linked_list(c);
    }
    smartlist_add(victims, c);
  }

  if (count_mode) {
    g_mark_contains_calls = 0;
    g_mark_contains_cmps = 0;
    g_remove_calls = 0;
    g_remove_full_cmps = 0;
    g_remove_first_match_cmps = 0;
    g_contains_calls = 0;
    g_contains_cmps = 0;
    g_del_calls = 0;
    g_count_phase = 1;
  }

  SMARTLIST_FOREACH_BEGIN(victims, connection_t *, v) {
    connection_mark_for_close(v);
  } SMARTLIST_FOREACH_END(v);

  if (count_mode) {
    g_count_phase = 2;
  }

  uint64_t cpu0 = now_ns(CLOCK_PROCESS_CPUTIME_ID);
  uint64_t wall0 = now_ns(CLOCK_MONOTONIC);

  close_closeable_connections();

  uint64_t cpu1 = now_ns(CLOCK_PROCESS_CPUTIME_ID);
  uint64_t wall1 = now_ns(CLOCK_MONOTONIC);
  g_count_phase = 0;

  if (cpu_ms_out)
    *cpu_ms_out = (double)(cpu1 - cpu0) / 1e6;
  if (wall_ms_out)
    *wall_ms_out = (double)(wall1 - wall0) / 1e6;
  if (rss_kb_out)
    *rss_kb_out = current_rss_kb();

  /* Clean up any held-open connections and background connections outside
   * the timed region. */
  SMARTLIST_FOREACH_BEGIN(held_conns, connection_t *, c) {
    c->marked_for_close = 1;
  } SMARTLIST_FOREACH_END(c);
  if (smartlist_len(held_conns) > 0) {
    close_closeable_connections();
  }

  SMARTLIST_FOREACH_BEGIN(bg_conns, connection_t *, c) {
    if (c->active_on_link) {
      connection_stop_reading_from_linked_conn(c);
    }
    if (c->conn_array_index >= 0) {
      connection_remove(c);
    }
    connection_free_(c);
  } SMARTLIST_FOREACH_END(c);

  smartlist_free(bg_conns);
  smartlist_free(held_conns);
  smartlist_free(victims);
}

typedef struct stats_t {
  double min;
  double p25;
  double median;
  double mean;
  double p95;
  double max;
  double stdev;
} stats_t;

static void
compute_stats(double *vals, int n, stats_t *out)
{
  for (int a = 0; a < n - 1; ++a) {
    for (int b = a + 1; b < n; ++b) {
      if (vals[b] < vals[a]) {
        double t = vals[a];
        vals[a] = vals[b];
        vals[b] = t;
      }
    }
  }
  out->min = vals[0];
  out->p25 = vals[n / 4];
  out->median = vals[n / 2];
  out->p95 = vals[(n * 95) / 100];
  out->max = vals[n - 1];
  double sum = 0.0;
  for (int i = 0; i < n; ++i)
    sum += vals[i];
  out->mean = sum / (double)n;
  double var = 0.0;
  for (int i = 0; i < n; ++i) {
    double d = vals[i] - out->mean;
    var += d * d;
  }
  out->stdev = (n > 1) ? sqrt(var / (double)(n - 1)) : 0.0;
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

#define N_TRIALS 9

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

  const bench_point_t points[] = {
    /* Sweep 1: Vary A (active_linked_connection_lst) at N=32000, C=1000 */
    {"vary_A_inactive_victims",     0, 32000, 1000, VICTIM_INACTIVE_IN_ARRAY, 0},
    {"vary_A_inactive_victims",   500, 32000, 1000, VICTIM_INACTIVE_IN_ARRAY, 0},
    {"vary_A_inactive_victims",  1000, 32000, 1000, VICTIM_INACTIVE_IN_ARRAY, 0},
    {"vary_A_inactive_victims",  2000, 32000, 1000, VICTIM_INACTIVE_IN_ARRAY, 0},
    {"vary_A_inactive_victims",  4000, 32000, 1000, VICTIM_INACTIVE_IN_ARRAY, 0},
    {"vary_A_inactive_victims",  8000, 32000, 1000, VICTIM_INACTIVE_IN_ARRAY, 0},
    {"vary_A_inactive_victims", 12000, 32000, 1000, VICTIM_INACTIVE_IN_ARRAY, 0},

    {"vary_A_active_victims",       0, 32000, 1000, VICTIM_ACTIVE_IN_ARRAY, 0},
    {"vary_A_active_victims",     500, 32000, 1000, VICTIM_ACTIVE_IN_ARRAY, 0},
    {"vary_A_active_victims",    1000, 32000, 1000, VICTIM_ACTIVE_IN_ARRAY, 0},
    {"vary_A_active_victims",    2000, 32000, 1000, VICTIM_ACTIVE_IN_ARRAY, 0},
    {"vary_A_active_victims",    4000, 32000, 1000, VICTIM_ACTIVE_IN_ARRAY, 0},
    {"vary_A_active_victims",    8000, 32000, 1000, VICTIM_ACTIVE_IN_ARRAY, 0},
    {"vary_A_active_victims",   12000, 32000, 1000, VICTIM_ACTIVE_IN_ARRAY, 0},

    /* Sweep 2: Vary N (global connection_array) at A=2000, C=1000 */
    {"vary_N",  2000,  4000, 1000, VICTIM_ACTIVE_IN_ARRAY, 0},
    {"vary_N",  2000,  8000, 1000, VICTIM_ACTIVE_IN_ARRAY, 0},
    {"vary_N",  2000, 16000, 1000, VICTIM_ACTIVE_IN_ARRAY, 0},
    {"vary_N",  2000, 32000, 1000, VICTIM_ACTIVE_IN_ARRAY, 0},
    {"vary_N",  2000, 64000, 1000, VICTIM_ACTIVE_IN_ARRAY, 0},

    /* Sweep 3: Vary C (closures per pass) at A=4000, N=32000 */
    {"vary_C",  4000, 32000,  100, VICTIM_ACTIVE_IN_ARRAY, 0},
    {"vary_C",  4000, 32000,  250, VICTIM_ACTIVE_IN_ARRAY, 0},
    {"vary_C",  4000, 32000,  500, VICTIM_ACTIVE_IN_ARRAY, 0},
    {"vary_C",  4000, 32000, 1000, VICTIM_ACTIVE_IN_ARRAY, 0},
    {"vary_C",  4000, 32000, 2000, VICTIM_ACTIVE_IN_ARRAY, 0},
    {"vary_C",  4000, 32000, 4000, VICTIM_ACTIVE_IN_ARRAY, 0},

    /* Sweep 4: Already-absent victims (!connection_in_array branch) */
    {"absent_victims", 4000, 32000, 1000, VICTIM_ABSENT_FROM_ARRAY, 0},

    /* Sweep 5: Mixed victims with held-open backlog in closeable list */
    {"mixed_with_held_open_backlog", 4000, 32000, 1000, VICTIM_MIXED_WITH_HELD_OPEN, 200},

    /* Sweep 6: Ordinary relay load baselines */
    {"ordinary_load_small",  20,  200,  10, VICTIM_ACTIVE_IN_ARRAY, 0},
    {"ordinary_load_medium", 50, 1500,  25, VICTIM_MIXED_WITH_HELD_OPEN, 5},
  };

  printf("[\n");
  size_t n_pts = sizeof(points) / sizeof(points[0]);
  for (size_t i = 0; i < n_pts; ++i) {
    /* Pass 1: exact operation/comparison counts */
    run_single_pass(&points[i], 1, NULL, NULL, NULL);
    uint64_t mark_con_calls = g_mark_contains_calls;
    uint64_t mark_con_cmps = g_mark_contains_cmps;
    uint64_t rem_calls = g_remove_calls;
    uint64_t rem_full_cmps = g_remove_full_cmps;
    uint64_t rem_first_cmps = g_remove_first_match_cmps;
    uint64_t con_calls = g_contains_calls;
    uint64_t con_cmps = g_contains_cmps;
    uint64_t del_calls = g_del_calls;

    /* Pass 2: unperturbed CPU and wall time across N_TRIALS runs */
    double cpu_samples[N_TRIALS], wall_samples[N_TRIALS];
    long rss_kb = 0;
    for (int r = 0; r < N_TRIALS; ++r) {
      run_single_pass(&points[i], 0, &cpu_samples[r], &wall_samples[r], &rss_kb);
    }
    stats_t cpu_st, wall_st;
    compute_stats(cpu_samples, N_TRIALS, &cpu_st);
    compute_stats(wall_samples, N_TRIALS, &wall_st);

    printf("  {\"build\": \"%s\", \"sweep\": \"%s\", \"A\": %d, \"N\": %d, "
           "\"C\": %d, \"held_open_H\": %d, \"victim_mode\": \"%s\", "
           "\"trials\": %d, \"sizeof_connection_t\": %zu, "
           "\"mark_contains_calls\": %" PRIu64 ", "
           "\"mark_contains_comparisons\": %" PRIu64 ", "
           "\"smartlist_remove_calls\": %" PRIu64 ", "
           "\"smartlist_remove_full_comparisons\": %" PRIu64 ", "
           "\"smartlist_remove_legacy_first_match_comparisons\": %" PRIu64 ", "
           "\"smartlist_remove_undercount\": %" PRIu64 ", "
           "\"teardown_contains_calls\": %" PRIu64 ", "
           "\"teardown_contains_comparisons\": %" PRIu64 ", "
           "\"total_teardown_linear_comparisons\": %" PRIu64 ", "
           "\"total_lifecycle_linear_comparisons\": %" PRIu64 ", "
           "\"smartlist_del_calls\": %" PRIu64 ", "
           "\"cpu_ms_min\": %.4f, \"cpu_ms_p25\": %.4f, "
           "\"cpu_ms_median\": %.4f, \"cpu_ms_mean\": %.4f, "
           "\"cpu_ms_p95\": %.4f, \"cpu_ms_max\": %.4f, \"cpu_ms_stdev\": %.4f, "
           "\"wall_ms_min\": %.4f, \"wall_ms_p25\": %.4f, "
           "\"wall_ms_median\": %.4f, \"wall_ms_mean\": %.4f, "
           "\"wall_ms_p95\": %.4f, \"wall_ms_max\": %.4f, \"wall_ms_stdev\": %.4f, "
           "\"rss_kb\": %ld}%s\n",
           label, points[i].sweep_name, points[i].A, points[i].N,
           points[i].C, points[i].held_open_H, victim_mode_str(points[i].mode),
           N_TRIALS, sizeof(connection_t),
           mark_con_calls, mark_con_cmps,
           rem_calls, rem_full_cmps, rem_first_cmps,
           rem_full_cmps - rem_first_cmps,
           con_calls, con_cmps,
           rem_full_cmps + con_cmps,
           mark_con_cmps + rem_full_cmps + con_cmps,
           del_calls,
           cpu_st.min, cpu_st.p25, cpu_st.median, cpu_st.mean,
           cpu_st.p95, cpu_st.max, cpu_st.stdev,
           wall_st.min, wall_st.p25, wall_st.median, wall_st.mean,
           wall_st.p95, wall_st.max, wall_st.stdev,
           rss_kb,
           (i + 1 < n_pts) ? "," : "");
    fflush(stdout);
  }
  printf("]\n");
  return 0;
}
