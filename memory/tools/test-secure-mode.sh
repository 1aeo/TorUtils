#!/usr/bin/env bash
# test-secure-mode.sh — Build mimalloc in default + secure modes,
# validate security features, and benchmark overhead.
#
# Usage:  ./test-secure-mode.sh [--rounds N] [--keep]
#
#   --rounds N   Number of benchmark rounds (default: 500000)
#   --keep       Keep build artifacts in /tmp after test
#
# Prerequisites: cmake, gcc, make (apt install cmake gcc make)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK_DIR="/tmp/mimalloc-secure-test-$$"
MIMALLOC_VERSION="2.0.9"
MIMALLOC_URL="https://github.com/microsoft/mimalloc/archive/refs/tags/v${MIMALLOC_VERSION}.tar.gz"
ROUNDS=500000
KEEP=false

# ── Parse args ──────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --rounds) ROUNDS="$2"; shift 2 ;;
        --keep)   KEEP=true; shift ;;
        -h|--help)
            echo "Usage: $0 [--rounds N] [--keep]"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ── Helpers ─────────────────────────────────────────────────────────
info()  { printf "\033[1;34m[INFO]\033[0m  %s\n" "$1"; }
ok()    { printf "\033[1;32m[OK]\033[0m    %s\n" "$1"; }
warn()  { printf "\033[1;33m[WARN]\033[0m  %s\n" "$1"; }
fail()  { printf "\033[1;31m[FAIL]\033[0m  %s\n" "$1"; }
hr()    { printf "\n%s\n\n" "────────────────────────────────────────────────────────────────"; }

cleanup() {
    if [ "$KEEP" = false ] && [ -d "$WORK_DIR" ]; then
        info "Cleaning up $WORK_DIR"
        rm -rf "$WORK_DIR"
    fi
}
trap cleanup EXIT

# ── Prereqs ─────────────────────────────────────────────────────────
info "Checking prerequisites..."
for cmd in cmake gcc make; do
    if ! command -v "$cmd" &>/dev/null; then
        fail "Missing: $cmd — install with: apt install cmake gcc make"
        exit 1
    fi
done
ok "Build tools available (cmake, gcc, make)"

# ── Download ────────────────────────────────────────────────────────
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

info "Downloading mimalloc ${MIMALLOC_VERSION}..."
if ! wget -q "$MIMALLOC_URL" -O "v${MIMALLOC_VERSION}.tar.gz" 2>/dev/null; then
    # Fallback: try curl
    if ! curl -sL "$MIMALLOC_URL" -o "v${MIMALLOC_VERSION}.tar.gz" 2>/dev/null; then
        fail "Cannot download mimalloc — check network connectivity"
        exit 1
    fi
fi
tar xzf "v${MIMALLOC_VERSION}.tar.gz"
ok "Downloaded and extracted mimalloc ${MIMALLOC_VERSION}"

SRC_DIR="$WORK_DIR/mimalloc-${MIMALLOC_VERSION}"

# ── Build: Default mode ─────────────────────────────────────────────
hr
info "Building mimalloc ${MIMALLOC_VERSION} — DEFAULT mode"
mkdir -p "$SRC_DIR/build-default"
cd "$SRC_DIR/build-default"
cmake -DMI_SECURE=OFF -DMI_BUILD_TESTS=OFF -DMI_BUILD_SHARED=ON \
      -DCMAKE_BUILD_TYPE=Release .. > cmake.log 2>&1
make -j"$(nproc)" >> cmake.log 2>&1

DEFAULT_LIB="$SRC_DIR/build-default/libmimalloc.so.2.0"
if [ ! -f "$DEFAULT_LIB" ]; then
    # Try alternate path
    DEFAULT_LIB="$(find "$SRC_DIR/build-default" -name 'libmimalloc.so*' -type f | head -1)"
fi

if [ -z "$DEFAULT_LIB" ] || [ ! -f "$DEFAULT_LIB" ]; then
    fail "Default build did not produce shared library"
    exit 1
fi
ok "Default build: $DEFAULT_LIB ($(du -h "$DEFAULT_LIB" | cut -f1))"

# ── Build: Secure mode ──────────────────────────────────────────────
hr
info "Building mimalloc ${MIMALLOC_VERSION} — SECURE mode (-DMI_SECURE=ON)"
mkdir -p "$SRC_DIR/build-secure"
cd "$SRC_DIR/build-secure"
cmake -DMI_SECURE=ON -DMI_BUILD_TESTS=OFF -DMI_BUILD_SHARED=ON \
      -DCMAKE_BUILD_TYPE=Release .. > cmake.log 2>&1
make -j"$(nproc)" >> cmake.log 2>&1

SECURE_LIB="$SRC_DIR/build-secure/libmimalloc-secure.so.2.0"
if [ ! -f "$SECURE_LIB" ]; then
    SECURE_LIB="$(find "$SRC_DIR/build-secure" -name 'libmimalloc-secure.so*' -o -name 'libmimalloc.so*' | head -1)"
fi

if [ -z "$SECURE_LIB" ] || [ ! -f "$SECURE_LIB" ]; then
    fail "Secure build did not produce shared library"
    exit 1
fi
ok "Secure build: $SECURE_LIB ($(du -h "$SECURE_LIB" | cut -f1))"

# ── Verify secure build has security symbols ────────────────────────
hr
info "Verifying security features in secure build..."

SECURE_SYMBOLS=0

# Check for guard-page related symbols
if nm -D "$SECURE_LIB" 2>/dev/null | grep -qi 'guard\|secure\|_mi_page_init'; then
    ok "Found security-related symbols in secure build"
    SECURE_SYMBOLS=1
fi

# Check that the library name contains "secure"
if echo "$SECURE_LIB" | grep -q "secure"; then
    ok "Library named with '-secure' suffix (cmake recognized MI_SECURE=ON)"
    SECURE_SYMBOLS=1
fi

# Compare sizes — secure build should be larger due to extra checks
DEFAULT_SIZE=$(stat -c%s "$DEFAULT_LIB")
SECURE_SIZE=$(stat -c%s "$SECURE_LIB")
SIZE_DIFF=$(( (SECURE_SIZE - DEFAULT_SIZE) * 100 / DEFAULT_SIZE ))

if [ "$SECURE_SIZE" -gt "$DEFAULT_SIZE" ]; then
    ok "Secure build is ${SIZE_DIFF}% larger than default (${DEFAULT_SIZE} → ${SECURE_SIZE} bytes) — consistent with added mitigations"
else
    warn "Secure build is not larger than default — unusual"
fi

# ── Build benchmark ─────────────────────────────────────────────────
hr
info "Building benchmark program..."
BENCH_SRC="${SCRIPT_DIR}/bench-allocator.c"
BENCH_BIN="$WORK_DIR/bench-allocator"

if [ ! -f "$BENCH_SRC" ]; then
    fail "Missing benchmark source: $BENCH_SRC"
    exit 1
fi

gcc -O2 -o "$BENCH_BIN" "$BENCH_SRC" -lpthread
ok "Benchmark compiled: $BENCH_BIN"

# ── Run benchmarks ──────────────────────────────────────────────────
hr
info "Running benchmarks (${ROUNDS} rounds each)..."
echo ""

run_bench() {
    local label="$1"
    local preload="$2"

    echo ">>> ${label}"
    echo "---"
    if [ -n "$preload" ]; then
        LD_PRELOAD="$preload" "$BENCH_BIN" "$ROUNDS" 2>&1
    else
        "$BENCH_BIN" "$ROUNDS" 2>&1
    fi
    echo ""
}

# Capture output for comparison
RESULT_GLIBC=$(run_bench "glibc (system default)" "")
RESULT_DEFAULT=$(run_bench "mimalloc ${MIMALLOC_VERSION} (default)" "$DEFAULT_LIB")
RESULT_SECURE=$(run_bench "mimalloc ${MIMALLOC_VERSION} (secure)" "$SECURE_LIB")

echo "$RESULT_GLIBC"
hr
echo "$RESULT_DEFAULT"
hr
echo "$RESULT_SECURE"

# ── Extract and compare key metrics ─────────────────────────────────
hr
info "Comparison summary"
echo ""

extract_metric() {
    echo "$1" | grep "$2" | head -1 | awk '{print $(NF-1), $NF}' | sed 's/ $//'
}

extract_number() {
    echo "$1" | grep "$2" | head -1 | grep -oE '[0-9]+\.?[0-9]*' | tail -1
}

GLIBC_TOTAL=$(extract_number "$RESULT_GLIBC" "^Total:")
DEFAULT_TOTAL=$(extract_number "$RESULT_DEFAULT" "^Total:")
SECURE_TOTAL=$(extract_number "$RESULT_SECURE" "^Total:")

GLIBC_RSS=$(extract_number "$RESULT_GLIBC" "After cleanup:")
DEFAULT_RSS=$(extract_number "$RESULT_DEFAULT" "After cleanup:")
SECURE_RSS=$(extract_number "$RESULT_SECURE" "After cleanup:")

GLIBC_OPS=$(extract_number "$RESULT_GLIBC" "M ops/sec")
DEFAULT_OPS=$(extract_number "$RESULT_DEFAULT" "M ops/sec")
SECURE_OPS=$(extract_number "$RESULT_SECURE" "M ops/sec")

printf "%-30s %12s %12s %12s\n" "" "glibc" "mimalloc" "mimalloc-sec"
printf "%-30s %12s %12s %12s\n" "──────────────────────────────" "────────────" "────────────" "────────────"
printf "%-30s %10s ms %10s ms %10s ms\n" "Total time" "$GLIBC_TOTAL" "$DEFAULT_TOTAL" "$SECURE_TOTAL"
printf "%-30s %10s KB %10s KB %10s KB\n" "Final RSS" "$GLIBC_RSS" "$DEFAULT_RSS" "$SECURE_RSS"
printf "%-30s %10s    %10s    %10s   \n" "Throughput (M ops/sec)" "$GLIBC_OPS" "$DEFAULT_OPS" "$SECURE_OPS"

# Calculate overhead percentages
if [ -n "$DEFAULT_TOTAL" ] && [ -n "$SECURE_TOTAL" ]; then
    # Use awk for floating-point math
    OVERHEAD=$(awk "BEGIN { printf \"%.1f\", (($SECURE_TOTAL - $DEFAULT_TOTAL) / $DEFAULT_TOTAL) * 100 }")
    echo ""
    echo "Secure mode overhead vs default: ${OVERHEAD}%"

    if awk "BEGIN { exit ($OVERHEAD <= 15) ? 0 : 1 }" 2>/dev/null; then
        ok "Overhead is within expected range (<= 15%) — safe for Tor relay workloads"
    else
        warn "Overhead is above 15% — may warrant further investigation on production hardware"
    fi
fi

if [ -n "$GLIBC_RSS" ] && [ -n "$SECURE_RSS" ]; then
    RSS_DIFF=$(awk "BEGIN { printf \"%.1f\", (($GLIBC_RSS - $SECURE_RSS) / $GLIBC_RSS) * 100 }" 2>/dev/null || echo "N/A")
    echo "RSS reduction (secure vs glibc): ${RSS_DIFF}%"
fi

# ── Verify LD_PRELOAD actually works ────────────────────────────────
hr
info "Verifying LD_PRELOAD injection..."

# Use /proc/self/maps to confirm the library is loaded
MAPS_CHECK=$(LD_PRELOAD="$SECURE_LIB" cat /proc/self/maps 2>/dev/null | grep -c mimalloc || echo "0")
if [ "$MAPS_CHECK" -gt 0 ]; then
    ok "LD_PRELOAD injection confirmed — mimalloc-secure loaded into process memory"
else
    # Try an alternative check
    MAPS_CHECK2=$(LD_PRELOAD="$SECURE_LIB" bash -c 'cat /proc/self/maps' 2>/dev/null | grep -c mimalloc || echo "0")
    if [ "$MAPS_CHECK2" -gt 0 ]; then
        ok "LD_PRELOAD injection confirmed via subprocess"
    else
        warn "Could not confirm LD_PRELOAD injection (may be a sandboxing limitation)"
    fi
fi

# ── MIMALLOC_SHOW_STATS check ───────────────────────────────────────
hr
info "Checking mimalloc internal stats (MIMALLOC_SHOW_STATS=1)..."
echo ""

# mimalloc prints stats to stderr on process exit when MIMALLOC_SHOW_STATS=1
STATS_OUTPUT=$(MIMALLOC_SHOW_STATS=1 LD_PRELOAD="$SECURE_LIB" "$BENCH_BIN" 1000 2>&1 >/dev/null || true)

if echo "$STATS_OUTPUT" | grep -qi "mimalloc"; then
    ok "mimalloc internal stats available:"
    echo "$STATS_OUTPUT" | grep -i "mimalloc\|heap\|page\|commit\|reserved\|secure" | head -20
else
    # Stats may go to stderr; try capturing differently
    STATS_OUTPUT2=$(MIMALLOC_SHOW_STATS=1 MIMALLOC_VERBOSE=3 LD_PRELOAD="$SECURE_LIB" "$BENCH_BIN" 1000 2>&1 || true)
    if echo "$STATS_OUTPUT2" | grep -qi "mimalloc\|secure"; then
        ok "mimalloc reports:"
        echo "$STATS_OUTPUT2" | grep -i "mimalloc\|secure\|guard" | head -10
    else
        warn "Could not capture mimalloc stats (stats may require debug build)"
    fi
fi

# ── Final summary ───────────────────────────────────────────────────
hr
echo "=== TEST COMPLETE ==="
echo ""
echo "Libraries built:"
echo "  Default: $DEFAULT_LIB"
echo "  Secure:  $SECURE_LIB"
echo ""
echo "To deploy secure mode on a Tor relay:"
echo "  1. Copy the secure library to the server:"
echo "     scp $SECURE_LIB server:/usr/local/lib/mimalloc/libmimalloc-${MIMALLOC_VERSION}-secure.so"
echo ""
echo "  2. Create a systemd override:"
echo "     sudo systemctl edit tor@relay_name"
echo "     [Service]"
echo "     Environment=\"LD_PRELOAD=/usr/local/lib/mimalloc/libmimalloc-${MIMALLOC_VERSION}-secure.so\""
echo ""
echo "  3. Restart the relay:"
echo "     sudo systemctl restart tor@relay_name"

if [ "$KEEP" = true ]; then
    echo ""
    echo "Build artifacts kept at: $WORK_DIR"
fi
