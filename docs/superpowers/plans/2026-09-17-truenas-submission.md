# TrueNAS submission preparation

**Goal:** Prepare ScarletX 0.4.9 and a reviewable community catalog addition addressing the feedback on TrueNAS PR #5698.

**Architecture:** Retain the backend/web deployment and official TrueNAS library 2.3.12. Use stable service names, private backend networking with outbound access, normal permission checks, and standard additional storage/network schemas. Keep credentials user-supplied. Prepare a new upstream release without overwriting 0.4.8.

**Authorization:** User requested submission readiness and selected preparation of 0.4.9. No TrueNAS test machine is available. Do not submit a public TrueNAS PR or assert a NAS install test has passed.

- [x] Update release lock/metadata and workflow for 0.4.9; preserve manual publication and existing stable tags.
- [x] Address prior review: stable names, standard README, custom networks, additional storage, documented envs, representative test values.
- [x] Use the official tooling to vendor the library, render scenarios and validate component schemas (full CLI pending); record catalog commit and local candidate image IDs (published digests pending).
- [x] Test isolated containers via rootless Podman: non-root startup, health, storage, persistence and configurable UID. Distinguish these from TrueNAS installation tests.
- [x] Run Python/browser checks and independent review; fix findings.
- [x] Produce catalog bundle, PR draft, feedback resolution matrix and remaining release/install checklist.

Files: packaging/truenas/scarletx/{app.yaml,ix_values.yaml,questions.yaml,README.md,templates/*}; release metadata files listed in tools/release_version.py; .github/workflows/release.yml; tests covering packaging/release contracts; docs/TRUENAS-SUBMISSION.md. Generated delivery artifacts belong in outputs/.
