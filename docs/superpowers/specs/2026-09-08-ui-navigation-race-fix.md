# ScarletX UI navigation race fix

## Problem

Rapid navigation between asynchronous views can leave older requests in flight. Several renderers write into shared DOM containers after awaiting API responses without confirming that their originating view is still active. This allows stale responses to repaint a newer page, especially across Scenes, Performers, and Studios which share `#entityGrid`.

## Fix boundary

Add stale-view guards immediately after awaited read requests and before DOM mutation in the final runtime renderers for entity library/search, Library, Wanted, Activity, Calendar, and Settings. Preserve current request behavior, caching, SSE, pagination, and download actions; this change only prevents an obsolete response from painting after navigation.

## Verification

Regression tests must fail on the current implementation, then pass after the minimal guards are added. Full CI, container builds, performance baseline, and TrueNAS validation remain required before merge.
