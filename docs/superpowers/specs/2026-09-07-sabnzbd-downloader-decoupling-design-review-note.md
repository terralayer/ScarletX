# SABnzbd Decoupling Spec Self-Review

Reviewed: 2026-09-07

The design was checked for placeholders, internal contradictions, unnecessary scope expansion, and ambiguous ownership boundaries.

Findings:

- No TODO/TBD placeholders remain.
- SABnzbd owns download, repair, unpack, and retry behavior; ScarletX owns submission tracking and all post-download media import behavior.
- The native downloader is intentionally retained but disconnected from normal runtime behavior.
- Existing native downloader database rows and settings should be preserved as legacy data even when removed from active UI/runtime paths.
- SAB queue disappearance is not treated as completion; history reconciliation is required.
- Import is idempotent and must occur only after a positive SAB completion state.
- Shared completed-download path semantics are explicit for container/TrueNAS deployments.
- Full SAB queue administration is deliberately out of scope for the first refactor.

One wording ambiguity in Acceptance Criterion 11 should be resolved during implementation planning: retired native settings are hidden from active UI/runtime but should remain preserved in storage unless a later migration explicitly removes them. This is consistent with the compatibility goals and avoids destructive upgrade behavior.
