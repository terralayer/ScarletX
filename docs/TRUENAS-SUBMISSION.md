# TrueNAS community app submission

This is the preparation record for the proposed ScarletX 0.4.9 app. It is not a claim that the release is published or that a TrueNAS installation has passed.

## Scope and prior review

- Existing app request: https://github.com/truenas/apps/issues/5711
- Closed initial submission: https://github.com/truenas/apps/pull/5698
- Target: `ix-dev/community/scarletx` in https://github.com/truenas/apps
- Application version: 0.4.9; initial catalog revision: 1.0.0.
- Two containers: backend and web, using stable service names. The web endpoint is the only published application port.
- Rendering library: 2.3.12, generated using the official catalog tool, not edited by hand.

## Installation requirements

Create dedicated datasets for configuration, downloads, media, and backups. Grant the configured user/group (defaults 568:568) write and traversal access to those datasets. Existing host paths retain their ownership by default; configure their ACLs before installing. The optional Automatic Permissions setting adjusts only top-level ownership for the configured user/group. Automatic ixVolume permission setup checks the mount root and does not recursively rewrite an existing media library. The database belongs on local writable storage, not an SMB or NFS mount.

The mount paths inside the backend are `/config`, `/downloads`, `/media`, and `/backups`. Additional storage mounts support the standard catalog host-path, ixVolume, SMB and NFS options. Use a read-only additional mount for archives that ScarletX must not modify. Hardlinks require source and destination on the same filesystem; use copy/move for separate datasets.

The backend needs outbound HTTPS for metadata/indexers and TLS NNTP to the user's provider. No TrueNAS management API, host networking, host devices, or Docker socket is required. Custom networks are optional and must already exist. Containers use the selected non-root UID/GID. The one-shot storage permissions helper uses root with CHOWN, FOWNER and DAC_OVERRIDE; those privileges do not apply to the long-running backend/web containers.

Choose a web port at or above 1024. Keep the web interface on a trusted LAN or behind a separately authenticated reverse proxy. First launch requires an administrator account and a generated ScarletX API key. Existing installations without an administrator also require setup. Complete setup promptly on a trusted network: the first visitor claims the administrator account. UI sessions and header/bearer API keys are enforced; API keys in URLs are rejected.

After starting, open Settings → TPDB and add the user's own API token. Configure indexers and Usenet providers using user-owned credentials. No test credentials are included. The configured media root is `/media`; download paths are `/downloads/incomplete` and `/downloads/complete`; database backups go to `/backups`.

## Validation scenarios

- `basic-values.yaml`: ixVolumes, UID/GID 568, published web port 8080.
- `host-path-values.yaml`: dedicated host paths, UID/GID 1000, loopback binding, documented connection-cap environment setting and read-only `/archive` mount.
- `exposed-values.yaml`: internal exposed port and web-only custom label; no host port published.

Run the official catalog tools from a fresh `truenas/apps` checkout after copying `packaging/truenas/scarletx` to `ix-dev/community/scarletx`. Vendor the library with `apps_catalog_hash_generate`, render each test with `apps_render_app render`, and validate with `apps_dev_charts_validate validate`. The upstream `ci.py` helper wraps these operations and can deploy with Docker.

Rootless Podman testing is useful container evidence, but does not verify TrueNAS middleware schema normalization, ixVolume creation, ACL handling, or the install/upgrade UI. Those checks require a TrueNAS system before submission.

## Prior reviewer feedback resolution

| Feedback on #5698 | Resolution |
| --- | --- |
| Missing standard question sections | Standard custom networks and additional storage copied from current catalog patterns; no host-network option for the two-container deployment. |
| Triplicate/versioned container names | Stable `backend`, `web`, `permissions`; nginx target supplied through supported environment variables. |
| Non-root claim unproven | Validate both UID 568 and UID 1000 with writable dedicated storage; record results separately from TrueNAS tests. |
| Nonstandard README | Short linked application description matching other catalog apps; installation guidance is upstream here. |
| Fixed-version changelog link | Releases index retained; release 0.4.9 must exist before submission. |
| Undocumented environment/test values | Host-path scenario uses `SCARLETX_USENET_MAX_CONNECTIONS`, implemented in `scarletx/config.py`; this sets the downloader connection ceiling (16 in the fixture). |
| Test port/order and duplicate scenarios | Common 8080 test port, conventional block order, distinct storage/UID/binding/label scenarios. |
| Expensive Python healthcheck | Catalog backend uses the library HTTP check; web uses wget. |
| Hard-coded paths and missing internal network | Mounts and backend target use constants; both containers join the catalog-managed network. |
| Incomplete PR description | App Addition template supplied as a draft with truthful incomplete items. |

## Release and submission gates

1. Review and merge the prepared 0.4.9 changes, including the manual release workflow update. The current GitHub login lacks the `workflow` scope needed to push workflow edits.
2. Run the release workflow for the reviewed commit. Do not overwrite existing 0.4.8 tags. Confirm anonymous pulls for both 0.4.9 images and record their digests.
3. Validate the final catalog package against those exact published images, including all three scenarios.
4. On TrueNAS, verify a clean install, writable datasets, saved settings after restart, backup creation/restore on disposable data, and an upgrade preserving the database and library.
5. Open the new catalog PR against the existing app request only after reviewing the generated package and accurate test evidence. Provide non-explicit icon/screenshots for CDN upload and disclose LLM assistance.

No public TrueNAS PR is opened by this preparation step.

## Preparation evidence (2026-09-17)

Catalog baseline: `111323261a21a642a0b46d92a0eba4f486e694e1`. Official library 2.3.12 hash: `1a258793b511e2d91cb0f0381b142e793236892f6619d6e76cec158c95e5ee1d`.

All three fixtures rendered with the current upstream Python renderer and passed Docker Compose configuration parsing. Upstream metadata generation, metadata JSON schema, question validation and library hash verification passed. Hash generation used upstream apps_validation revision `fedb34c8aa7d39154daf8e706ea13a43c5bb5b1a` (before its native atomic-write dependency). Metadata generation used the official generator with its Docker transport replaced by the same upstream renderer. The complete validator CLI/container was not run successfully: local middleware dependencies were unavailable and the large validator-image download was stopped. These component checks do not substitute for the full release CI checks.

Local candidate images passed rootless Podman checks at UID/GID 568 and 1000 with all capabilities dropped: HTTP health/version, four writable volumes, consecutive distinct backups, saved settings after backend restart, current web assets, and verified outbound TLS. This is local candidate evidence, not published-image or TrueNAS evidence. Browser checks covered 42 dashboard layouts and all nine Settings pages at three widths. Screenshots contain fictional data.

The generated catalog metadata uses prospective TrueNAS CDN URLs. The icon and screenshots still require maintainer upload; those URLs are not evidence that assets are already available. Initial setup and authentication are now required as described above.

Final preparation checks: 601 Python tests passed (724 dependency deprecation warnings); Ruff, Python compilation, browser checks and independent code review passed.

Performance validation and benchmark limitations are recorded in `PERFORMANCE-0.4.9.md`. All five performance improvements retain the 0.4.9 version lock.

The second performance batch also passed local candidate-to-candidate container replacement at UID 568 and 1000 with persistent settings, session/API-key access, and all three new indexes. This uses disposable rootless Podman volumes; it does not replace TrueNAS upgrade testing.

Reliability changes and the pending hardware lifecycle checklist are documented in `RELIABILITY-0.4.9.md`. The 50,000-scene synthetic pagination/search test passed. Local backup/key restore tests cover administrator and API access. No diagnostics-export feature was added.

Third performance batch: bounded probe submissions, reduced list columns, concurrent artwork warming, worker-thread downloader storage operations, and rebuildable canonical-path lookup. The current full suite has 601 passing tests. See PERFORMANCE-0.4.9.md for measured gains, initial cache-build cost and unchanged/slower list latency in the synthetic fixture.

Release direction: remain locked at 0.4.9 while actual TrueNAS lifecycle and real-throughput checks are pending. Troy has conditionally authorized moving to 0.5.0 after those checks pass, then locking at 0.5.0. See RELEASE-GATE-0.5.0.md and SOAK-0.4.9.md; synthetic local checks do not satisfy the actual hardware/provider gates.

Management features: storage overview, daily quiet hours, read-only cleanup, saved-connection wizard and backup reminders are included. Management browser flows and authenticated container endpoints/schedule persistence passed. See MANAGEMENT-0.4.9.md.
