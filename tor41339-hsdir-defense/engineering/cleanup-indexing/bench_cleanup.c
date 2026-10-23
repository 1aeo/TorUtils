/* Microbenchmark for the connection-cleanup scans that tor#41339's flood
 * drives (BEGIN_DIR teardown and linked-connection toggling).
 *
 * Links against a real libtor.a and drives the real connection lifecycle
 * functions (connection_add, connection_mark_for_close,
 * close_closeable_connections, connection_start/stop_reading_from_linked_conn,
 * connection_free_). It does NOT reimplement them.
 *
 * It --wraps smartlist_remove / smartlist_contains / smartlist_del so it can
 * count, per phase (marking vs teardown), the exact number of element
 * comparisons each one performs. smartlist_remove scans the WHOLE list even
 * after a match (it is an all-matches remove), so we count sl->num_used
 * comparisons per call, not up-to-first-match. This is what the stock code
 * pays; the indexed build calls smartlist_del instead and does no scan.
 *
 * All list lengths here are synthetic parameters (N,A,C,H). Production list
 * lengths were never captured; see the report.
 *
 * Two kinds of run per point:
 *   - a counting run (count_mode=1): wraps active, exact comparison counts;
 *   - timing runs (count_mode=0): wrappers inert, CPU and wall time only,
 *     repeated for a distribution.
 */
#define MAINLOOP_PRIVATE
#include "orconfig.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include <time.h>

#include "core/or/or.h"
#include "core/or/connection_st.h"
#include "core/or/edge_connection_st.h"
#include "core/or/connection_edge.h"
#include "core/mainloop/connection.h"
#include "core/mainloop/mainloop.h"
#include "feature/dircommon/directory.h"
#include "lib/testsupport/testsupport.h"
#include "lib/buf/buffers.h"
#include "lib/container/smartlist.h"
#include "lib/log/log.h"
#include "app/main/subsysmgr.h"
#include "app/config/config.h"
#include "feature/control/control_events.h"
#include "feature/stats/rephist.h"
#include "feature/stats/bwhist.h"
#include "lib/evloop/compat_libevent.h"

extern void __real_smartlist_remove(smartlist_t *sl, const void *element);
extern int __real_smartlist_contains(const smartlist_t *sl, const void *e);
extern void __real_smartlist_del(smartlist_t *sl, int idx);

/* 0 = off, 1 = marking phase, 2 = teardown phase */
static int g_phase = 0;
static uint64_t mark_contains_cmp, mark_remove_cmp, mark_remove_calls;
static uint64_t tear_contains_cmp, tear_remove_cmp, tear_remove_calls;
static uint64_t tear_del_calls, mark_del_calls;

void
__wrap_smartlist_remove(smartlist_t *sl, const void *element)
{
  if (g_phase && sl && element) {
    uint64_t c = sl->num_used; /* all-matches scan: whole list */
    if (g_phase == 1) { mark_remove_cmp += c; mark_remove_calls++; }
    else { tear_remove_cmp += c; tear_remove_calls++; }
  }
  __real_smartlist_remove(sl, element);
}

int
__wrap_smartlist_contains(const smartlist_t *sl, const void *element)
{
  if (g_phase && sl) {
    uint64_t c = 0;
    for (int i = 0; i < sl->num_used; i++) { c++; if (sl->list[i]==element) break; }
    if (g_phase == 1) mark_contains_cmp += c; else tear_contains_cmp += c;
  }
  return __real_smartlist_contains(sl, element);
}

void
__wrap_smartlist_del(smartlist_t *sl, int idx)
{
  if (g_phase == 1) mark_del_calls++;
  else if (g_phase == 2) tear_del_calls++;
  __real_smartlist_del(sl, idx);
}

static uint64_t
now_ns(clockid_t cid)
{
  struct timespec ts; clock_gettime(cid, &ts);
  return (uint64_t)ts.tv_sec*UINT64_C(1000000000) + (uint64_t)ts.tv_nsec;
}

/* A linked exit<->dir pair as connection_exit_connect_dir() makes. */
static void
make_pair(connection_t **ex, connection_t **dir)
{
  connection_t *e = connection_new(CONN_TYPE_EXIT, AF_INET);
  connection_t *d = connection_new(CONN_TYPE_DIR, AF_INET);
  e->state = EXIT_CONN_STATE_OPEN; e->purpose = EXIT_PURPOSE_CONNECT;
  e->address = tor_strdup("127.0.0.1");
  TO_EDGE_CONN(e)->edge_has_sent_end = 1;
  TO_EDGE_CONN(e)->end_reason = END_STREAM_REASON_DONE;
  d->state = DIR_CONN_STATE_SERVER_WRITING; d->purpose = DIR_PURPOSE_SERVER;
  d->address = tor_strdup("127.0.0.1");
  connection_link_connections(d, e);
  *ex = e; *dir = d;
}

typedef struct { int N, A, C, H; const char *sweep; } point_t;

/* Build a population of N connections: A of them active-on-link, H held-open
 * (marked, kept unflushable), C victims to close this pass. Then (timed)
 * mark the C victims and close them. */
static void
run_point(const point_t *p, int count_mode,
          double *cpu_ms, double *wall_ms)
{
  tor_init_connection_lists();
  initialize_mainloop_events();

  smartlist_t *bg = smartlist_new();      /* background, freed at end */
  smartlist_t *held = smartlist_new();    /* held-open backlog */
  smartlist_t *victims = smartlist_new(); /* closed in the timed region */

  int A = p->A, C = p->C, H = p->H;
  int N = p->N; if (N < A + C + H) N = A + C + H;
  int bg_n = N - A - C - H;

  /* A active-linked background pairs (dir side active). */
  for (int i = 0; i < A; i++) {
    connection_t *e,*d; make_pair(&e,&d);
    connection_add(e); connection_add(d);
    d->reading_from_linked_conn = 1; e->writing_to_linked_conn = 1;
    buf_add(e->outbuf, "x", 1);
    connection_start_reading(d);
    smartlist_add(bg,e); smartlist_add(bg,d);
  }
  /* inactive background singletons to pad connection_array to N. */
  for (int i = 0; i < bg_n; i++) {
    connection_t *c = connection_new(CONN_TYPE_DIR, AF_INET);
    c->state = DIR_CONN_STATE_SERVER_WRITING; c->purpose = DIR_PURPOSE_SERVER;
    c->address = tor_strdup("127.0.0.1"); c->linked = 1;
    connection_add(c); smartlist_add(bg,c);
  }
  /* H held-open connections at the head of the closeable list: marked, but
   * conn_close_if_marked returns 0 for them (array index kept, not flushed),
   * so they stay on the list across the pass. */
  for (int i = 0; i < H; i++) {
    connection_t *c = connection_new(CONN_TYPE_DIR, AF_INET);
    c->state = DIR_CONN_STATE_SERVER_WRITING; c->purpose = DIR_PURPOSE_SERVER;
    c->address = tor_strdup("127.0.0.1"); c->linked = 1;
    connection_add(c);
    connection_mark_for_close(c);
    c->marked_for_close = 0; /* conn_close_if_marked -> 0 -> stays, ++i */
    smartlist_add(held,c);
  }
  /* C victim linked pairs; close the dir side (also unlinks the exit side). */
  for (int i = 0; i < C; i++) {
    connection_t *e,*d; make_pair(&e,&d);
    connection_add(e); connection_add(d);
    d->reading_from_linked_conn = 1; e->writing_to_linked_conn = 1;
    buf_add(e->outbuf, "x", 1);
    connection_start_reading(d);
    smartlist_add(victims,d);  /* close dir side; exit side follows via unlink */
    smartlist_add(victims,e);
  }

  if (count_mode) {
    mark_contains_cmp=mark_remove_cmp=mark_remove_calls=0;
    tear_contains_cmp=tear_remove_cmp=tear_remove_calls=0;
    tear_del_calls=mark_del_calls=0;
    g_phase = 1;
  }
  /* Mark phase: mark the C dir victims (their exit peers unlink on close). */
  SMARTLIST_FOREACH_BEGIN(victims, connection_t *, c) {
    if (c->type == CONN_TYPE_DIR && !c->marked_for_close)
      connection_mark_for_close(c);
  } SMARTLIST_FOREACH_END(c);
  if (count_mode) g_phase = 2;

  uint64_t c0=now_ns(CLOCK_PROCESS_CPUTIME_ID), w0=now_ns(CLOCK_MONOTONIC);
  close_closeable_connections();
  uint64_t c1=now_ns(CLOCK_PROCESS_CPUTIME_ID), w1=now_ns(CLOCK_MONOTONIC);
  g_phase = 0;
  if (cpu_ms) *cpu_ms = (double)(c1-c0)/1e6;
  if (wall_ms) *wall_ms = (double)(w1-w0)/1e6;

  /* teardown outside timed region */
  SMARTLIST_FOREACH(held, connection_t *, c, c->marked_for_close = 1);
  if (smartlist_len(held)) close_closeable_connections();
  SMARTLIST_FOREACH_BEGIN(bg, connection_t *, c) {
    if (c->active_on_link) connection_stop_reading_from_linked_conn(c);
    if (c->linked_conn) { c->linked_conn->linked_conn = NULL; c->linked_conn=NULL; }
    if (c->conn_array_index >= 0) connection_remove(c);
    connection_free_(c);
  } SMARTLIST_FOREACH_END(c);
  smartlist_free(bg); smartlist_free(held); smartlist_free(victims);
}

typedef struct { double min,p50,mean,p95,max,stdev; } stat_t;
static int cmp_d(const void*a,const void*b){double x=*(const double*)a,y=*(const double*)b;return (x>y)-(x<y);}
static void stats(double *v,int n,stat_t *s){
  qsort(v,n,sizeof(double),cmp_d);
  s->min=v[0]; s->p50=v[n/2]; s->p95=v[(n*95)/100>=n?n-1:(n*95)/100]; s->max=v[n-1];
  double sum=0; for(int i=0;i<n;i++) sum+=v[i]; s->mean=sum/n;
  double var=0; for(int i=0;i<n;i++){double d=v[i]-s->mean; var+=d*d;}
  s->stdev=n>1?sqrt(var/(n-1)):0;
}

static or_options_t *g_opt=NULL;
static const or_options_t *mock_opts(void){return g_opt;}

#define NTRIAL 11
int
main(int argc, char **argv)
{
  const char *label = argc>1?argv[1]:"build";
  subsystems_init();
  { log_severity_list_t s; memset(&s,0,sizeof(s));
    set_log_severity_config(LOG_ERR,LOG_ERR,&s);
    add_stream_log(&s,"",2); }
  g_opt=options_new(); options_init(g_opt); MOCK(get_options,mock_opts);
  tor_libevent_cfg_t ev; memset(&ev,0,sizeof(ev)); tor_libevent_initialize(&ev);
  control_initialize_event_queue();
  rep_hist_init(); bwhist_init();
  tor_init_connection_lists(); initialize_mainloop_events();

  const point_t points[] = {
    /* vary N, fixed C=500, A=0: does fixed-C cleanup grow with unrelated N? */
    {2000,0,500,0,"vary_N"},{8000,0,500,0,"vary_N"},{16000,0,500,0,"vary_N"},
    {32000,0,500,0,"vary_N"},{64000,0,500,0,"vary_N"},
    /* vary A, fixed C=500, N=32000: does it grow with unrelated active list? */
    {32000,0,500,0,"vary_A"},{32000,1000,500,0,"vary_A"},{32000,4000,500,0,"vary_A"},
    {32000,16000,500,0,"vary_A"},{32000,30000,500,0,"vary_A"},
    /* vary C, N=32000, A=4000: cost should be ~linear in C for indexed. */
    {32000,4000,100,0,"vary_C"},{32000,4000,250,0,"vary_C"},{32000,4000,500,0,"vary_C"},
    {32000,4000,1000,0,"vary_C"},{32000,4000,2000,0,"vary_C"},{32000,4000,4000,0,"vary_C"},
    /* held-open backlog H present during the pass. */
    {32000,4000,500,200,"held_open"},{32000,4000,500,2000,"held_open"},
    /* small normal workloads. */
    {200,20,10,0,"normal_small"},{1500,50,25,5,"normal_small"},
  };
  int np = sizeof(points)/sizeof(points[0]);
  printf("[\n");
  for (int i=0;i<np;i++){
    run_point(&points[i],1,NULL,NULL);
    uint64_t mc=mark_contains_cmp, mr=mark_remove_cmp;
    uint64_t tc=tear_contains_cmp, tr=tear_remove_cmp;
    uint64_t trc=tear_remove_calls, mrc=mark_remove_calls;
    uint64_t td=tear_del_calls, md=mark_del_calls;
    double cpu[NTRIAL], wall[NTRIAL];
    for (int t=0;t<NTRIAL;t++) run_point(&points[i],0,&cpu[t],&wall[t]);
    stat_t cs,ws; stats(cpu,NTRIAL,&cs); stats(wall,NTRIAL,&ws);
    printf("  {\"build\":\"%s\",\"sweep\":\"%s\",\"N\":%d,\"A\":%d,\"C\":%d,\"H\":%d,"
      "\"sizeof_conn\":%zu,\"trials\":%d,"
      "\"mark_contains_cmp\":%llu,\"mark_remove_cmp\":%llu,\"mark_remove_calls\":%llu,\"mark_del_calls\":%llu,"
      "\"tear_contains_cmp\":%llu,\"tear_remove_cmp\":%llu,\"tear_remove_calls\":%llu,\"tear_del_calls\":%llu,"
      "\"total_scan_cmp\":%llu,"
      "\"cpu_ms_min\":%.5f,\"cpu_ms_p50\":%.5f,\"cpu_ms_mean\":%.5f,\"cpu_ms_p95\":%.5f,\"cpu_ms_max\":%.5f,\"cpu_ms_stdev\":%.5f,"
      "\"wall_ms_p50\":%.5f,\"wall_ms_mean\":%.5f}%s\n",
      label, points[i].sweep, points[i].N, points[i].A, points[i].C, points[i].H,
      sizeof(connection_t), NTRIAL,
      (unsigned long long)mc,(unsigned long long)mr,(unsigned long long)mrc,(unsigned long long)md,
      (unsigned long long)tc,(unsigned long long)tr,(unsigned long long)trc,(unsigned long long)td,
      (unsigned long long)(mc+mr+tc+tr),
      cs.min,cs.p50,cs.mean,cs.p95,cs.max,cs.stdev, ws.p50,ws.mean,
      i+1<np?",":"");
    fflush(stdout);
  }
  printf("]\n");
  return 0;
}
