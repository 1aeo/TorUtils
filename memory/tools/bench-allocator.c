/*
 * bench-allocator.c — Simulates Tor directory-cache allocation patterns.
 *
 * Tor's DirCache generates millions of small, short-lived allocations
 * (consensus diffs, microdescriptors, cell buffers). This program
 * reproduces that pattern to benchmark allocator overhead and measure
 * fragmentation behavior.
 *
 * Build:  gcc -O2 -o bench-allocator bench-allocator.c -lpthread
 * Usage:  ./bench-allocator [rounds]   (default: 500000)
 *
 * With LD_PRELOAD you can swap in any allocator:
 *   LD_PRELOAD=/path/to/libmimalloc-secure.so ./bench-allocator
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/resource.h>

/* Simple xorshift64 — fast, deterministic, no glibc rand() lock contention */
static unsigned long long rng_state = 0xdeadbeefcafe1234ULL;

static unsigned long long xorshift64(void) {
    unsigned long long x = rng_state;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    rng_state = x;
    return x;
}

/* Return a random size in [lo, hi) */
static size_t rand_range(size_t lo, size_t hi) {
    return lo + (xorshift64() % (hi - lo));
}

/*
 * Read VmRSS from /proc/self/status (Linux-specific).
 * Returns RSS in kilobytes, or 0 on failure.
 */
static long read_rss_kb(void) {
    FILE *f = fopen("/proc/self/status", "r");
    if (!f) return 0;
    char line[256];
    long rss = 0;
    while (fgets(line, sizeof(line), f)) {
        if (strncmp(line, "VmRSS:", 6) == 0) {
            sscanf(line + 6, " %ld", &rss);
            break;
        }
    }
    fclose(f);
    return rss;
}

/*
 * Phase 1 — Rapid churn: allocate small buffers (64–4096 bytes),
 * write to them, free in random order.  Mimics consensus-diff handling.
 */
static void phase_churn(int rounds) {
    /* Keep a pool of live allocations to free randomly */
    const int POOL = 2048;
    void *pool[2048];
    memset(pool, 0, sizeof(pool));

    for (int i = 0; i < rounds; i++) {
        int idx = xorshift64() % POOL;

        if (pool[idx]) {
            free(pool[idx]);
            pool[idx] = NULL;
        }

        size_t sz = rand_range(64, 4096);
        pool[idx] = malloc(sz);
        if (pool[idx])
            memset(pool[idx], (int)(i & 0xff), sz);  /* touch pages */
    }

    /* Cleanup */
    for (int i = 0; i < POOL; i++)
        free(pool[i]);
}

/*
 * Phase 2 — Long-lived accumulation: allocate medium buffers
 * (4 KB–64 KB) and keep them alive.  Mimics cached directory objects
 * that fragment glibc's arena.
 */
static void phase_accumulate(int count, void ***out_ptrs, int *out_count) {
    *out_ptrs = malloc(sizeof(void *) * (size_t)count);
    *out_count = count;

    for (int i = 0; i < count; i++) {
        size_t sz = rand_range(4096, 65536);
        (*out_ptrs)[i] = malloc(sz);
        if ((*out_ptrs)[i])
            memset((*out_ptrs)[i], 0xAB, sz);
    }
}

/*
 * Phase 3 — Interleaved free/alloc: free every other long-lived
 * allocation, then allocate different sizes into the holes.
 * This is the pattern that causes glibc fragmentation.
 */
static void phase_fragment(void **ptrs, int count) {
    /* Free odd-indexed allocations */
    for (int i = 1; i < count; i += 2) {
        free(ptrs[i]);
        ptrs[i] = NULL;
    }

    /* Re-allocate with different sizes into the holes */
    for (int i = 1; i < count; i += 2) {
        size_t sz = rand_range(128, 8192);  /* smaller than originals */
        ptrs[i] = malloc(sz);
        if (ptrs[i])
            memset(ptrs[i], 0xCD, sz);
    }
}

static double timespec_diff_ms(struct timespec *start, struct timespec *end) {
    double s = (double)(end->tv_sec - start->tv_sec) * 1000.0;
    double ns = (double)(end->tv_nsec - start->tv_nsec) / 1e6;
    return s + ns;
}

int main(int argc, char *argv[]) {
    int rounds = 500000;
    if (argc > 1)
        rounds = atoi(argv[1]);
    if (rounds < 1000)
        rounds = 1000;

    int accum_count = rounds / 50;  /* ~2% kept long-lived */
    if (accum_count < 100)
        accum_count = 100;

    printf("=== Allocator Benchmark (Tor-like pattern) ===\n");
    printf("Churn rounds:       %d\n", rounds);
    printf("Accumulation count: %d\n", accum_count);
    printf("\n");

    long rss_start = read_rss_kb();
    struct timespec t0, t1, t2, t3, t4;

    /* ---- Phase 1: Rapid churn ---- */
    clock_gettime(CLOCK_MONOTONIC, &t0);
    phase_churn(rounds);
    clock_gettime(CLOCK_MONOTONIC, &t1);

    long rss_after_churn = read_rss_kb();

    /* ---- Phase 2: Accumulation ---- */
    void **accum_ptrs = NULL;
    int accum_actual = 0;
    clock_gettime(CLOCK_MONOTONIC, &t2);
    phase_accumulate(accum_count, &accum_ptrs, &accum_actual);
    long rss_after_accum = read_rss_kb();

    /* ---- Phase 3: Fragmentation ---- */
    phase_fragment(accum_ptrs, accum_actual);
    clock_gettime(CLOCK_MONOTONIC, &t3);

    long rss_after_frag = read_rss_kb();

    /* ---- Cleanup ---- */
    for (int i = 0; i < accum_actual; i++)
        free(accum_ptrs[i]);
    free(accum_ptrs);
    clock_gettime(CLOCK_MONOTONIC, &t4);

    long rss_final = read_rss_kb();

    /* ---- Report ---- */
    double churn_ms = timespec_diff_ms(&t0, &t1);
    double accum_frag_ms = timespec_diff_ms(&t2, &t3);
    double total_ms = timespec_diff_ms(&t0, &t4);

    printf("--- Timing ---\n");
    printf("Phase 1 (churn):              %8.1f ms\n", churn_ms);
    printf("Phase 2+3 (accum+fragment):   %8.1f ms\n", accum_frag_ms);
    printf("Total:                        %8.1f ms\n", total_ms);
    printf("\n");
    printf("--- RSS (KB) ---\n");
    printf("Start:            %8ld KB\n", rss_start);
    printf("After churn:      %8ld KB\n", rss_after_churn);
    printf("After accumulate: %8ld KB\n", rss_after_accum);
    printf("After fragment:   %8ld KB\n", rss_after_frag);
    printf("After cleanup:    %8ld KB\n", rss_final);
    printf("\n");

    /* Ops/sec */
    double ops = (double)rounds + (double)accum_count * 3.0;
    printf("--- Throughput ---\n");
    printf("Total alloc ops:  %.0f\n", ops);
    printf("Throughput:       %.0f ops/ms  (%.2f M ops/sec)\n",
           ops / total_ms, ops / total_ms / 1000.0);
    printf("\n");

    /* Fragmentation ratio */
    if (rss_after_accum > 0 && rss_after_frag > 0) {
        double frag = (double)rss_after_frag / (double)rss_after_accum;
        printf("--- Fragmentation ---\n");
        printf("RSS ratio (post-fragment / post-accumulate): %.3f\n", frag);
        printf("  < 1.0 = allocator reclaimed memory well\n");
        printf("  > 1.0 = fragmentation caused growth\n");
    }

    return 0;
}
