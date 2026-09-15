# TPDB date diagnostic

Run from the ScarletX checkout using its Python environment, with access to the
live SQLite database and a TPDB API key in `SCARLETX_TPDB_API_KEY`. No app server
startup, settings seeding, scene persistence, or discovery marker updates occur.
The source database opens read-only and is backed up into an in-memory snapshot.
Allow memory for that snapshot. TPDB requests bypass ScarletX's caches, including
stale fallback, so an unavailable page is recorded as an error.

```sh
python -m scarletx.tpdb_date_diagnostic \
  --database /path/to/scarletx.db \
  --output /path/to/new-diagnostic-directory \
  --count 100 --seed 20260915 \
  --start 2026-09-01 --end 2026-09-30 --limit 500
```

Use the date range and limit of the affected Calendar request. The default window
is today through 30 days ahead. The endpoint supports limits through 2000; use the
actual client value. An existing output file is never overwritten. A population
smaller than the requested sample fails explicitly; no replacement sampling.

The sampler requests every page for each selected monitored performer,
sequentially, with a default safety bound of 1000 pages per performer. HTTP errors,
repeated pages and exhausted bounds make the report incomplete (exit status 2).
No retry or cached response conceals those failures. Rerun to a new output directory
after addressing an outage or rate limit. Keep the seed and performer list when
comparing runs; the same seed requires the same monitored population to reproduce
selection.

Outputs:

- `summary.json`: seed, sample identities, completion/error counts, Calendar row
  counts, unique scene counts and evidence flags.
- `pages.jsonl`: performer/page provenance, fetch times and TPDB pagination metadata.
- `scenes.jsonl`: one record per performer/scene occurrence, raw top-level date,
  release and timestamp fields (including nulls), TPDB ID/title, selected field,
  normalized date, stored ID/title/date, studio policy and Calendar status.

Counts in the summary deduplicate scene IDs; the row file preserves overlapping
performer observations. The database reflects snapshot time; TPDB is fetched
later. A mismatch can therefore also reflect newer upstream metadata.

## Interpreting evidence

- Missing or unparseable `date` is evidence to inspect upstream format/content.
  It is not proof that TPDB has no release information elsewhere.
- Alternate release fields are preserved for mapping/precedence review. Do not
  assume `created_at`/`updated_at` represent a release date.
- `stored_normalized_mismatch` warrants tracing persistence and refresh history;
  it alone does not establish a normalization defect.
- `limit_excluded` means the real Calendar query includes the scene without its
  limit but drops it with the supplied limit. `outside_window`, missing date,
  content-type and monitoring exclusions are recorded separately.
- `unexpected_query_exclusion` requires query investigation. If a scene is
  included by the backend but absent in the UI, inspect the actual frontend
  request and rendering before attributing a cause.
- `not_stored` and studio-policy exclusions identify discovery/filtering questions.

An incomplete run cannot establish the outcome for 100 performers. Review actual
rows before making any bounded application fix. Production evidence stays outside
the repository; it includes performer names and scene metadata.
