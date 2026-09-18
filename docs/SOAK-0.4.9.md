# Local mixed-workload and cache-growth checks

The new `tools/soak_local.py` runner uses a disposable temporary directory and database. It combines paginated reads/Wanted queries, repeated library scans, artwork requests, and 1 MiB local file copies through the downloader's I/O helper. It samples process RSS, request latency, event-loop delay and artwork-cache size.

All artwork network responses are fixtures. There is no real Usenet transfer, archive unpacking, provider access or interaction with user media. The runner creates 5,000 scene records and 20 small unmatched files. A fixed set of 32 image/thumbnail pairs is warmed before measurements. Repeated requests must keep cache file count/bytes unchanged and must not redownload originals.

Run from the project root:

```sh
python tools/soak_local.py --seconds 120 --output local-soak.json
python tools/soak_local.py --seconds 28800 --output overnight-local-soak.json
```

The second command is available for an eight-hour local run; it has not been run as part of the short validation session. Failures produce a nonzero exit status. Successful reports contain measurements only, with no credentials.

A stable fixed-corpus cache proves reuse, not a disk-size cap. New images and new thumbnail variants will still consume additional space. This check does not justify a cleanup policy or deleting cached artwork; measure growth under the real library workload before choosing a storage budget and retention policy.

The short test cannot rule out slow leaks or prove overnight stability. Real TrueNAS lifecycle and real download/processing throughput remain pending. The 0.5.0 transition requirements are in RELEASE-GATE-0.5.0.md.

The runner bounds its own measurement history to 10,000 read durations and 2,048 memory samples. Full-run RSS and event-loop-delay maxima are kept separately. This prevents the test harness from growing without limit during an overnight run. Read p95 describes the retained recent sample when the run exceeds that capacity.

## Local result

Final run: 120.55 seconds, 2,069 read cycles, 60 scans, 7,584 artwork requests and 1,176 local 1 MiB copies; no errors. Read p95 was 9.7 ms; maximum observed event-loop delay was 44.74 ms. Sampled RSS increased from 128.13 to 130.72 MiB (peak 130.72 MiB). The short run does not establish a memory plateau or exclude long-term leaks.

The warmed cache stayed at 96 files / 271,552 bytes, with exactly 32 mocked original downloads and none repeated. Growing a real library will increase cache use.

The repeatable runner passed lint/compilation and independent review. All 16 release-contract checks passed, preserving the active 0.4.9 lock. Production application code did not change in this validation batch; the existing 590-test suite evidence remains applicable. No overnight run, actual TrueNAS run or real Usenet throughput measurement has been completed.
