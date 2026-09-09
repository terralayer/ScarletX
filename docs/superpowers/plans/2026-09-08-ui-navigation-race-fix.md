# UI Navigation Race Fix Plan

1. Add regression tests for stale async page responses.
2. Verify the tests fail on the current runtime implementation.
3. Add minimal active-view guards before stale responses can mutate DOM.
4. Verify regression tests and full CI, including TrueNAS validation.
5. Merge only with fresh green evidence.

Implementation note: guards are applied only after read requests complete and before DOM mutation, so existing download actions, SSE updates, pagination, and caches remain unchanged.
