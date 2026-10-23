**Numbering note.** The `Patched, 0001 enforcing` and `Patched, 0002 enforcing`
labels below are the raw run labels from `results-x86-full.csv` and use the
**pre-reorder** numbering, the **inverse** of the shipped `patches/` numbering:
`0001` here is the **one-request-per-circuit / circuit-close** defense (shipped
**`patches/0002`**, `HSDirOneRequestPerCircuit`, counter `hsdir_circ_reused`) and
`0002` here is the **unknown-previous-hop / 503-refusal** defense (shipped
**`patches/0001`**, `HSDirRefuseUnknownPrevHop`, counter
`hsdir_unknown_prev_hop`). Defense **names** are authoritative; the labels are
left as recorded so this table stays in sync with the un-edited
`results-x86-full.csv`.

| Configuration | Load | Valid / total reps | Served fraction | Stock-client success | Target bytes written (MB) |
|---|---|---|---|---|---|
| Unpatched 0.4.9.14 | none | 1 / 1 | - | 1.000 | 1.26 |
| Unpatched 0.4.9.14 | fetch | 3 / 3 | 1.00 | 1.000 | 2.41 |
| Unpatched 0.4.9.14 | reuse-5 | 3 / 3 | 1.00 | 1.000 | 3.82 |
| Unpatched 0.4.9.14 | reuse-22 | 3 / 3 | 1.00 | 1.000 | 6.36 |
| Unpatched 0.4.9.14 | onehop | 3 / 3 | 1.00 | 1.000 | 1.73 |
| Unpatched 0.4.9.14 | adapted | 3 / 3 | 1.00 | 1.000 | 2.42 |
| Patched, count-only (default) | none | 1 / 1 | - | 1.000 | 1.15 |
| Patched, count-only (default) | fetch | 3 / 3 | 1.00 | 1.000 | 1.69 |
| Patched, count-only (default) | reuse-5 | 2 / 3 | 1.00 | 1.000 | 3.68 |
| Patched, count-only (default) | reuse-22 | 3 / 3 | 1.00 | 1.000 | 6.28 |
| Patched, count-only (default) | onehop | 3 / 3 | 1.00 | 1.000 | 1.64 |
| Patched, count-only (default) | adapted | 3 / 3 | 1.00 | 1.000 | 1.69 |
| Patched, 0001 enforcing | none | 1 / 1 | - | 1.000 | 1.02 |
| Patched, 0001 enforcing | fetch | 3 / 3 | 1.00 | 1.000 | 1.62 |
| Patched, 0001 enforcing | reuse-5 | 3 / 3 | 0.00 | 1.000 | 1.25 |
| Patched, 0001 enforcing | reuse-22 | 3 / 3 | 0.00 | 1.000 | 1.19 |
| Patched, 0001 enforcing | onehop | 3 / 3 | 0.50 | 1.000 | 1.40 |
| Patched, 0001 enforcing | adapted | 3 / 3 | 1.00 | 1.000 | 1.65 |
| Patched, 0002 enforcing | none | 1 / 1 | - | 0.979 | 0.87 |
| Patched, 0002 enforcing | fetch | 1 / 3 | 1.00 | 1.000 | 1.69 |
| Patched, 0002 enforcing | reuse-5 | 2 / 3 | 1.00 | 1.000 | 3.63 |
| Patched, 0002 enforcing | reuse-22 | 3 / 3 | 1.00 | 1.000 | 6.28 |
| Patched, 0002 enforcing | onehop | 3 / 3 | 0.03 | 1.000 | 1.20 |
| Patched, 0002 enforcing | adapted | 3 / 3 | 1.00 | 1.000 | 1.66 |
| Patched, 0001 + 0002 enforcing | none | 1 / 1 | - | 1.000 | 1.11 |
| Patched, 0001 + 0002 enforcing | fetch | 3 / 3 | 1.00 | 1.000 | 1.65 |
| Patched, 0001 + 0002 enforcing | reuse-5 | 3 / 3 | 0.00 | 1.000 | 1.23 |
| Patched, 0001 + 0002 enforcing | reuse-22 | 3 / 3 | 0.00 | 1.000 | 1.21 |
| Patched, 0001 + 0002 enforcing | onehop | 3 / 3 | 0.03 | 1.000 | 1.19 |
| Patched, 0001 + 0002 enforcing | adapted | 3 / 3 | 1.00 | 1.000 | 1.65 |
