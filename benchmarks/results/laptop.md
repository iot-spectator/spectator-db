# Laptop run — 2026-08-21

Full default pass with the file-size sweep, produced by:

```console
$ python benchmarks/benchmark.py --scales 1000,10000,50000 --repeats 5 \
      --file-size-sweep --json benchmarks/results/laptop.json
```

Raw measurements: [`laptop.json`](laptop.json). Methodology and caveats:
[`../README.md`](../README.md).

## Environment

- Hardware: Intel(R) Core(TM) Ultra 7 155H
- OS: Linux 6.6.87.2-microsoft-standard-WSL2 (x86_64, 22 cores)
- Python: CPython 3.13.12, SQLite 3.45.1
- Run: 2026-08-21T04:50:41+00:00

Note this is WSL2, not bare metal — fsync behaviour there is not identical to a
native Linux filesystem, and insert throughput is fsync-bound.

## Insert (`insert()`, 8.0 KiB files)

| records | median | p95 | max | inserts/sec | wall clock |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 2.66 ms | 4.98 ms | 15.95 ms | 352 | 2.8 s |
| 10,000 | 1.84 ms | 3.62 ms | 16.25 ms | 445 | 22.5 s |
| 50,000 | 1.99 ms | 3.64 ms | 25.05 ms | 424 | 117.8 s |

Flat across scales — insert cost does not grow with library size. The tail
(`max`) is the commit fsync, not the table.

## Similarity search (`search_similar()`, brute force)

| vectors | dim | median | p95 | max |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 64 | 35.8 ms | 38.4 ms | 38.4 ms |
| 10,000 | 64 | 411.3 ms | 422.9 ms | 422.9 ms |
| 50,000 | 64 | 2132.2 ms | 2170.1 ms | 2170.1 ms |

Linear in vector count, as the brute-force design implies: ~11x records costs
~11x time from 1k to 10k, and ~5x from 10k to 50k. **This is the practical
ceiling.** Interactive similarity search is comfortable at 1k, sluggish at 10k,
and unusable at 50k — and a Pi will be several times slower than this.

## Reads and updates

| records | `query()` time range | `query()` + media_type | `count()` by label | `update_enrichment()` |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 1.47 ms | 2.36 ms | 0.69 ms | 2.76 ms |
| 10,000 | 1.61 ms | 9.00 ms | 7.44 ms | 1.73 ms |
| 50,000 | 1.80 ms | 39.87 ms | 39.01 ms | 1.74 ms |

Both queries page 50 rows, and the difference is the whole point. The bare
time-range page is served by `idx_media_captured_at` and stays **flat** as the
library grows — 1.47 ms at 1k, 1.80 ms at 50k. Adding a `media_type` filter
sends SQLite to `idx_media_media_type`, which matches nearly every row in a
photo library, and it then sorts the entire match set in a temp B-tree before
`LIMIT` applies: **22x slower at 50k**, and still growing.

`count()` filtered by label scans for the same reason — labels are matched
through `json_each`, so no index applies.

## On-disk size

| records | catalog, no vectors | catalog, with vectors | bytes/record | media files |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 504.0 KiB | 2.2 MiB | 2,347 B | 7.8 MiB |
| 10,000 | 4.5 MiB | 22.0 MiB | 2,304 B | 78.1 MiB |
| 50,000 | 22.3 MiB | 109.9 MiB | 2,304 B | 390.6 MiB |

Storage is linear and predictable. Vectors dominate: ~468 B/record without
them, ~2,304 B/record with a 64-d vector, so the embedding costs about
**1.8 KiB per record**. Those same 64 floats would occupy 256 bytes packed as
binary `float32` — the ~7x overhead is the JSON text encoding. At 50k records
the catalog is 110 MiB, of which roughly 88 MiB is JSON-encoded vectors.

## Insert cost by file size (200 inserts each)

| file size | median | p95 | inserts/sec | MiB/sec |
| ---: | ---: | ---: | ---: | ---: |
| 8.0 KiB | 5.73 ms | 7.48 ms | 184 | 1.4 |
| 256.0 KiB | 6.48 ms | 8.41 ms | 164 | 41.0 |
| 2.0 MiB | 10.05 ms | 12.79 ms | 102 | 204.1 |

The bridge from the 8 KiB synthetic files above to real media. A 32x jump in
file size (8 KiB → 256 KiB) costs only 13% more per insert, because the commit
dominates. At 2 MiB — a realistic phone photo — hashing and copying finally take
over, and throughput settles near 100 inserts/sec. So **a real photo library
imports at roughly 100 files/sec on this machine**, not the 424/sec the 8 KiB
column suggests.

These sweep numbers run higher than the equivalent column in the main insert
table because each sweep entry builds a fresh library and only measures 200
inserts, so start-up cost is spread over far fewer operations.
