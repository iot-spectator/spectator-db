# Benchmarks

Honest numbers for the three things that decide whether spectator-db fits a
given job: how fast it ingests, how fast similarity search answers, and how
much disk it uses — measured at 1k, 10k, and 50k records.

The harness is stdlib-only, exactly like the library's core, so the same
script runs unmodified on a laptop and on a Raspberry Pi.

## Running it

```console
$ python benchmarks/benchmark.py                      # 1k, 10k, 50k
$ python benchmarks/benchmark.py --scales 1000,10000  # shorter pass
$ python benchmarks/benchmark.py --file-size-sweep --json results/mine.json
```

Run it from the repository root. The report is Markdown on stdout; `--json`
additionally writes every raw measurement.

Each scale is built from scratch, measured, and deleted before the next one
starts. Peak disk is roughly `scale × --file-size` plus the catalog, so the
default 50k run at 8 KiB files needs about **500 MiB** free. The full default
pass takes a few minutes on a laptop and considerably longer on a Pi — start
there with `--scales 1000,10000`.

## What is measured, and what that means

| Phase | Call | Notes |
| --- | --- | --- |
| Insert | `insert()` | SHA-256 + copy into storage + one committed SQLite row |
| Enrich | `update_enrichment()` | attaches a 64-d vector, the store-first/enrich-later path |
| Search | `search_similar()` | pure-Python brute-force cosine over every vector |
| Reads | `query()`, `count()` | the ordinary gallery operations |
| Size | on disk | catalog measured with and without vectors, media counted separately |

## Methodology

The details that make the numbers reproducible rather than decorative:

- **Warm-up first.** A throwaway library is built and exercised before any
  measurement, so the first scale is not charged for interpreter start-up and a
  cold SQLite page cache. Without it the smallest scale looks *slower* than the
  largest, inverting the trend being measured.
- **Per-operation timing.** Every insert, update, and search is timed
  individually with `time.perf_counter`. Results are reported as median and
  p95, not a mean — commit-per-insert has a long tail, and a mean hides it.
- **File generation is never timed.** The source file is rewritten with fresh
  random bytes before each insert, outside the timed region. Fresh bytes also
  guarantee a distinct content hash, so nothing is skipped as a duplicate.
- **Capture times are passed explicitly**, which deliberately excludes the EXIF
  path. Synthetic files carry no EXIF, so timing the fallback would flatter the
  result rather than describe it.
- **The WAL is checkpointed before sizing.** Otherwise recent writes still live
  in the `-wal` sidecar and the catalog looks smaller than it is. Reported size
  is the sum of the `.db`, `-wal`, and `-shm` files.
- **Everything is warm.** Process, page cache, and connection are all hot. A
  first query after boot will be slower than anything reported here.
- **Corpora are seeded** (`--seed`), so a rerun on the same machine builds the
  same library.

## Reading the results

Three things are worth knowing before quoting any of these numbers.

**Similarity search is O(N) and pure Python.** Every vector for the model is
loaded, JSON-decoded, and scored on each call. `limit` is applied *after*
scoring, so it bounds the result list, not the work. Search cost therefore
tracks the vector count almost exactly — expect roughly linear growth, and
expect a Pi to be several times slower than a laptop. This is the number that
decides the practical ceiling for interactive similarity search.

**Insert is dominated by the commit, until files get large.** Each insert
fsyncs, which puts a floor on throughput no amount of tuning in the caller can
move. Below a few hundred KiB the file size barely matters; past that, hashing
and copying bytes take over. `--file-size-sweep` measures exactly where that
crossover sits on your hardware, which is what lets an 8 KiB synthetic result
be translated to real multi-megabyte photos.

**Vectors dominate catalog size.** Embeddings are stored as JSON text, so a
64-d vector costs far more than the 256 bytes its floats would occupy packed
binary. The size table reports the catalog before and after enrichment so the
two costs can be told apart.

## Known scaling limits found here

These are findings, not tuning knobs — recorded so nobody has to rediscover
them.

- **`query()` with a low-selectivity filter is not index-served.** A bare
  time-range page walks `idx_media_captured_at` and stops at the limit, staying
  flat as the library grows. Adding `media_type` sends SQLite to
  `idx_media_media_type` instead, which matches nearly every row in a
  photo library; it then builds a temp B-tree over the entire match set before
  `LIMIT` applies. The result is a paged query whose cost grows with the
  library rather than with the page. `EXPLAIN QUERY PLAN` shows both steps. A
  composite `(media_type, captured_at)` index would fix it, at the cost of a
  schema migration. The benchmark reports both query shapes side by side so the
  gap stays visible.
- **`count()` with a label filter always scans.** Labels live in a JSON column
  matched through `json_each`, so no index applies and cost grows linearly.
  Expected, but worth stating before an article implies otherwise.

## Results

Recorded runs live in `results/`. Each is a full default pass with the
file-size sweep, kept alongside the raw JSON.

| Machine | Report | Raw |
| --- | --- | --- |
| Laptop (x86_64) | [`results/laptop.md`](results/laptop.md) | `results/laptop.json` |

A Raspberry Pi run is still outstanding — it needs the hardware, and it is the
number that matters most for the on-device story.
