# Conditional release gate: 0.4.9 → 0.5.0

Troy authorized this transition on September 17, 2026, conditional on successful actual TrueNAS and throughput testing. The active source, images, workflow and helper remain locked to 0.4.9. Passing local synthetic checks does not satisfy the hardware/network gates.

| Gate | Current status | Evidence required |
| --- | --- | --- |
| Local regressions | Passed: 590 tests | Full-suite results for the final candidate |
| Local upgrade/restore | Passed: UID 568 and 1000 | Existing disposable-container evidence |
| Mixed workload/cache check | Local synthetic check only | SOAK-0.4.9.md and raw results |
| Actual TrueNAS lifecycle | Pending system availability | Version, hardware, mount layout, image IDs and install/upgrade/restart/restore results |
| Actual download throughput | Pending system/provider access | Reproducible real transfer, processing/import results and bottleneck assessment |
| Overnight real workload (recommended extended validation) | Pending | Hours-long mixed operation without unexplained stalls, unbounded memory growth or lost job state |

## TrueNAS lifecycle

Follow the disposable-install checklist in RELIABILITY-0.4.9.md. Verify fresh setup, existing-admin preservation, legacy setup requirements, storage permissions, interrupted scans/downloads, upgrade and matching database/key restore. Preserve evidence and resolve any data-loss, authentication, migration or restart-recovery failures before transition.

## Throughput protocol

Use the user's own provider credentials and authorized test content. Keep credentials out of saved evidence.

1. Record CPU/RAM, TrueNAS version, network link, provider connection limits, enabled TLS, storage layout and whether incomplete/complete/media paths share a filesystem.
2. Establish a storage/network baseline on disposable data. Record the intended throughput target before judging the app; do not infer it from synthetic local file-copy tests.
3. Run a representative direct-video download and an archived download at the same configured connection count and speed limit. Repeat to distinguish a cold-cache run from steady state. Record file size, elapsed transfer time, average/peak transfer rate, processing time and import time.
4. During transfer and unpack/import, browse lists, open Settings and run a scan. Record noticeable UI delay, CPU, memory, disk throughput and job errors. Verify pause/resume and restart retain partial work.
5. Exercise a controlled repair case if PAR2 is part of the intended use. Check that healthy payloads avoid unnecessary repair downloads and that repair errors preserve retryable state.
6. Test a cross-dataset completion/import path if users will use separate datasets. Separate copy time from network time.
7. Identify the limiting resource. Investigate unexplained throughput drops or stalls rather than requiring an arbitrary MB/s number. Record whether the agreed target is met; resolve application-caused bottlenecks and rerun affected cases.
8. Recommended extended validation: run an overnight workload on the target system, checking memory/cache growth and job recovery. A short synthetic run does not establish overnight stability.

## Transition after evidence passes

Once the actual lifecycle and throughput evidence is accepted and outstanding blocking failures are resolved, apply the already-authorized dedicated release change. The recommended overnight run is additional confidence work, not a new condition added to Troy’s authorization:

- Move source/package metadata, user agents, container/catalog references and workflow expectations to 0.5.0.
- Change the release helper's expected series to 0.5 and its locked version to exactly 0.5.0. Preserve tests that reject subsequent automatic bumps.
- Add final release notes, rerun release-contract/full regression and container checks, and record the tested commit and image digests.
- Keep 0.5.0 locked until Troy authorizes another change.

This conditional version authorization does not publish images or submit a public catalog PR by itself. Publishing remains a separate explicitly authorized action.
