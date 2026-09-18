# Performance improvements — locked 0.4.9

User approved all five changes. Preserve existing staged release/setup work.

1. Record repeatable ASGI authentication benchmark with concurrent authenticated requests, settings loads and event-loop delay. Include normal SQLite and explicitly simulated slow reads.
2. Tests first: valid sessions avoid settings loads, DB work does not block the event loop, revoked sessions and rotated keys take effect without caching authorization.
3. Run synchronous auth checks in a worker thread, keeping each Session within that thread. Check the session first; query settings only for supplied integration keys, using fresh settings for immediate rotation visibility.
4. Add bounded Wanted pagination through backward-compatible limit/offset on existing list endpoint, deterministic ID tie-break, 50-row UI pages with next/previous and stale-response protection.
5. Pause queue fallback timers on hidden tabs, resume once visible only when fallback remains necessary, and prevent in-flight requests from restarting timers after stream recovery.
6. Expire idle rate-limit addresses periodically without allocating entries for lookups. Bound active address count and failure queues while preserving existing blocks.
7. Run focused/full tests, browser regressions, benchmark comparison and independent review; refresh saved patch/evidence. No version bump or publication.

Completed: all five improvements, 553 passing Python tests, browser suite, benchmark comparison and review. The shipped Wanted bulk override also uses pagination. See docs/PERFORMANCE-0.4.9.md for the measured no-delay overhead and slow-read improvement.
