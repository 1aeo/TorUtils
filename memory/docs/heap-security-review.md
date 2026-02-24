# Heap Security Review: glibc malloc vs. Alternative Allocators

*February 2026 — prompted by reviewer feedback on our allocator comparison content*

Our allocator comparison work focused on memory efficiency (fragmentation/RSS).
This document addresses a separate axis: **heap-security hardening** — the
mitigations each allocator provides against exploitation of memory-corruption
bugs in Tor (or any C program).

## Summary

| Allocator | Inline Metadata | Pointer Obfuscation | Guard Pages | Free-List Encryption | Double-Free Detection | Allocation Randomization | Security Rating |
|-----------|:-:|:-:|:-:|:-:|:-:|:-:|:--|
| **glibc ptmalloc2** | Yes | Safe-Linking (since 2.32) | No | No | Partial (tcache key) | No | Moderate |
| **jemalloc 5.x** | No (out-of-band) | No | No | No | No | No | Low (passive benefits) |
| **mimalloc 2.x (default build)** | No (out-of-band) | No | No | No | No | No | Low (passive benefits) |
| **mimalloc 2.x (secure build)** | No (out-of-band) | Yes | Yes | Yes (per-page keys) | Yes | Yes | High |
| **hardened_malloc** | No | Yes | Yes | N/A (no free lists) | Yes | Yes | Very High |

## glibc ptmalloc2: What Security It Actually Provides

glibc's allocator has accumulated meaningful exploit mitigations over 20 years.
When switching away from it, operators should understand what they're trading:

### Active Mitigations

1. **Safe-Linking (glibc >= 2.32)** — Single-linked list pointers in fastbins and
   tcache are XOR-mangled with a value derived from ASLR page randomization
   (`PROTECT_PTR` / `REVEAL_PTR` macros). This blocks the classic
   "arbitrary-malloc" primitive that dominated heap exploitation for two decades.
   Bypass requires a heap address leak. Cost: 2–4 extra instructions per
   malloc/free — negligible.

2. **Safe-Unlinking (glibc >= 2.3.6)** — Double-linked list integrity checks on
   `unlink()` verify that `P->fd->bk == P && P->bk->fd == P` before removing a
   chunk. Blocks the original "unlink" exploit.

3. **Tcache double-free key (glibc >= 2.29)** — A per-thread random key stored
   in freed tcache chunks detects simple double-free attempts.

4. **Chunk size/alignment validation** — Multiple checks on chunk headers at
   malloc/free time catch many corruption patterns (misaligned chunks, impossible
   sizes, overlapping chunks).

5. **Top chunk size check (glibc >= 2.29)** — Prevents the "House of Force"
   technique.

### Weaknesses

- **Inline metadata**: Chunk headers sit directly adjacent to user data. A
  single byte off-the-end overflow hits metadata, opening attack surface that
  out-of-band-metadata allocators don't have.
- **No guard pages**: No OS-level page protections between allocations.
- **No allocation randomization**: Allocation order is deterministic.
- **CVE history**: Ongoing vulnerabilities including CVE-2023-4911
  (GLIBC_TUNABLES "Looney Tunables", local privilege escalation) and
  CVE-2026-0861 (memalign integer overflow causing heap corruption, affecting
  glibc 2.30–2.42).

## jemalloc: Security Profile

jemalloc was designed for performance and fragmentation avoidance, not security
hardening. However, it has one significant **passive** security advantage:

- **Out-of-band metadata**: Allocation metadata is stored separately from user
  data in "runs" and "extents." A buffer overflow from one allocation does not
  directly corrupt allocator metadata. Research has found far fewer exploitable
  primitives in jemalloc than in ptmalloc2, partly for this reason.

jemalloc provides **no** pointer obfuscation, guard pages, free-list encryption,
or allocation randomization. It does not detect double-frees.

## mimalloc: Default vs. Secure Mode

### Default Build (What We Currently Deploy)

Like jemalloc, mimalloc stores metadata out-of-band (in page headers separate
from user data), providing passive resistance to metadata corruption. But the
default build has **no active exploit mitigations**.

### Secure Build (`-DMI_SECURE=ON`)

Building with `-DMI_SECURE=ON` enables a comprehensive set of mitigations:

1. **Guard pages** around all internal mimalloc pages and heap metadata — a
   buffer overflow cannot reach metadata across a guard page boundary.

2. **Encrypted free-list pointers** using per-page random keys — prevents both
   known-pointer overwrites and detects free-list corruption.

3. **Double-free detection** — double frees are caught and ignored rather than
   corrupting allocator state.

4. **Randomized allocation order** — free lists are initialized in random order;
   allocation randomly chooses between extending and reusing within a page.

5. **Randomized OS allocation addresses** — larger heap blocks obtained from the
   OS are placed at random addresses.

**Performance overhead**: ~10% on microbenchmarks according to the mimalloc
project. For Tor relays, where the bottleneck is network I/O and cryptography
rather than allocation throughput, this overhead is likely negligible.

**How to build**:

```bash
# Build mimalloc 2.0.9 in secure mode
wget https://github.com/microsoft/mimalloc/archive/refs/tags/v2.0.9.tar.gz
tar xzf v2.0.9.tar.gz && cd mimalloc-2.0.9
mkdir build && cd build
cmake -DMI_SECURE=ON ..
make
sudo cp libmimalloc-secure.so.2.0 /usr/local/lib/mimalloc/libmimalloc-2.0.9-secure.so
```

Then update the systemd override:

```ini
[Service]
Environment="LD_PRELOAD=/usr/local/lib/mimalloc/libmimalloc-2.0.9-secure.so"
```

### Known Limitations of mimalloc Secure Mode

- Encoded free-list metadata can still be leaked from reused pages (reported in
  microsoft/mimalloc#372, mitigated in later versions).
- Very large allocations (multi-TB) could historically be used for heap spraying
  to defeat ASLR; fixed by disabling address hints for allocations over 1 GB.
- As with any mitigation, these are hardening measures, not guarantees.

## Assessment for Tor Relay Operators

### What You Lose by Leaving glibc

By switching from glibc to mimalloc (default build) or jemalloc, you **lose**:

- Safe-Linking pointer obfuscation
- Safe-Unlinking integrity checks
- Tcache double-free detection
- Chunk size/alignment validation checks

### What You Gain

- **Out-of-band metadata** (both jemalloc and mimalloc) — arguably more
  important than glibc's active checks, since it eliminates the entire class of
  "overflow into adjacent metadata" attacks.
- **80% memory reduction** — the primary reason for the switch, and itself a
  security benefit (reduced OOM risk, more headroom for other processes).

### What You Can Recover with mimalloc Secure Mode

Building mimalloc with `-DMI_SECURE=ON` recovers and **exceeds** glibc's
security posture:

- Guard pages (glibc doesn't have these)
- Encrypted free-list pointers (stronger than glibc's Safe-Linking — uses
  per-page keys rather than ASLR-derived mangling)
- Double-free detection
- Allocation randomization (glibc doesn't have this)

### Recommendation

**Build mimalloc 2.0.9 in secure mode** for production Tor relay deployments.
This provides:

- Best-in-class memory efficiency (1.28–1.41 GB vs. 4–6 GB with glibc)
- Heap-security mitigations that match or exceed glibc ptmalloc2
- ~10% allocation overhead that is negligible for Tor's workload profile

For operators who want even stronger hardening and can accept higher overhead,
GrapheneOS's **hardened_malloc** is the gold standard for security-focused
allocation, though it has not been tested for Tor relay memory efficiency.

## References

- [Safe-Linking: Eliminating a 20 year-old malloc() exploit primitive](https://research.checkpoint.com/2020/safe-linking-eliminating-a-20-year-old-malloc-exploit-primitive/) — Check Point Research
- [mimalloc Build Modes (secure, debug, guarded)](https://microsoft.github.io/mimalloc/modes.html) — Microsoft
- [Potential security issues in mimalloc-secure (Issue #372)](https://github.com/microsoft/mimalloc/issues/372) — mimalloc GitHub
- [Securing malloc in glibc: Why malloc hooks had to go](https://developers.redhat.com/articles/2021/08/25/securing-malloc-glibc-why-malloc-hooks-had-go) — Red Hat
- [hardened_malloc](https://github.com/GrapheneOS/hardened_malloc) — GrapheneOS
- [CVE-2026-0861: glibc memalign overflow](https://windowsforum.com/threads/cve-2026-0861-glibc-memalign-overflow-triggers-heap-corruption.402505/)
