# Library reliability improvements

The user approved all five improvements from the read-only review and previously asked not to repeat approval prompts. Work continues in the existing local checkout, preserving its uncommitted changes and current library/settings. No commits, resets, fresh databases, credential changes, or live download-control actions are part of this work.

## Outcomes

1. Performer and studio searches immediately show saved matches, including pagination. An explicit **Find more online** button switches to provider results without hiding the already displayed results while loading. Provider pages retain their original total/order and are saved locally, so previously fetched pages do not require the provider again. Empty local results offer the same button. Errors keep the previous results and allow retry. Normal navigation returns to the library, not search.
2. Every existing pager stays centered below its list. Successful page changes scroll to the beginning of that list below the sticky header. Failed or stale responses must not scroll, overwrite another page, or silently advance the page number. Cover entities, active downloads, completed/failed downloads, history, media library, and Wanted.
3. **Pause Downloads** persists a global pause flag in the existing settings store and pauses current queued/downloading jobs. New work is held while paused, across browser reloads and service restarts. **Resume Downloads** clears the flag and releases paused work in one server operation. Post-processing continues; completed, failed, and cancelled work is not resurrected by Resume All. Individual Resume cannot bypass a global pause. Deployment must not toggle the user's current queue.
4. Performer/studio discovery status distinguishes never checked, queued/running, completed, and failed. Show pages checked/scenes saved and last successful check time, preserving that time if a later refresh fails. Saved scenes remain usable on failures. Do not claim a failed or unfinished scan is up to date.
5. Consolidate the touched UI behaviors into clear owners: one entity-search implementation, shared pagination transition handling, and one download-toolbar controller. Remove superseded definitions/override layers where safe while preserving the established display, authentication boot, monitoring behavior, and event-driven queue updates. This is targeted consolidation, not a framework rewrite.

## Interfaces

- Existing performer/studio search endpoints gain `source=auto|local|online`. `auto` preserves existing API compatibility; the UI explicitly starts with `local`. `online` uses a persisted query/page cache before contacting the provider. Response shape remains `items,total,page,per_page`.
- `GET /api/downloads/native/control` returns `{paused: boolean}`; pause-all and new resume-all responses include persistent state plus affected count. Global pause defaults to false for existing installations.
- Catalog status adds queued/finished timestamps and `last_success_at`, serialized as timezone-aware ISO strings or null.
- New frontend files must be included in both index script order and the packaged web image; do not bypass `authGateBoot`.

## Verification and rollout

Use isolated test databases and fake external providers for regression tests. Run Node behavioral tests for browser handlers, the full Python suite, lint/syntax checks, and build both app images. Review the integrated changes independently. Deploy to the existing local preview and check browser navigation, status text, and pager geometry. Never click Pause/Resume or start an external discovery merely for a live test. Preserve mounted database, cache, media, and secrets. No external publication or version-control integration is requested.
