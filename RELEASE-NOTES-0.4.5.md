# ScarletX 0.4.5

ScarletX 0.4.5 synchronizes all changes merged since 0.4.4 into one stable release.

## UI and branding

- Preserves the approved ScarletX horizontal wordmark, ribbon favicon/app icon, dashboard banner, and consistent vector navigation icons.
- Removes the CSS-generated `Built with ♥ for the scene.` pseudo-footer so the sidebar terminates at the real application footer.
- Keeps the approved real footer with the ScarletX version and motto.
- Adds the processing queue, activity-history, library-health, and Wanted UI improvements, including bounded selected-row Search and Unmonitor actions.

## Acquisition, processing, and library safety

- Adds persistent processing-state visibility and processing-capacity/backpressure protections.
- Improves scene matching, media validation, atomic import publishing, safe rename/move behavior, and cleanup policy handling.
- Adds incremental scanning, duplicate detection, and library-health reporting.
- Adds safer quality-profile evaluation and rollback-safe automatic upgrades.

## Wanted, monitoring, and scale

- Expands Wanted state tracking and missing-scene handling.
- Adds bounded bulk operations for selected Wanted scenes while preserving global search actions.
- Bounds performer and studio list query work, including replacing correlated studio count subqueries with a page-scoped aggregate.

## Packaging and release consistency

- Aligns the Python package, API-reported version, startup scripts, outbound User-Agent strings, Docker/Compose definitions, GHCR image tags, and TrueNAS application metadata at `0.4.5`.
- Advances the TrueNAS catalog package to `1.0.11` with backend and web images pinned to `0.4.5`.
