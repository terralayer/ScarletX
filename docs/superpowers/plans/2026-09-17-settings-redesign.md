# Settings Redesign Implementation Plan

**Goal:** Apply the approved nine-tab Settings preview and remove the Discover shortcut and its dedicated code.

**Design:** The user approved the inline ScarletX Settings preview on 2026-09-17: grouped navigation, section panels, readable labels and hints, toggle controls, consistent Save/Reset actions, responsive layouts, and the existing dark/scarlet identity. The existing app header and global sidebar remain the app's own chrome.

**Architecture:** Keep existing settings fields, IDs, endpoint payloads, and save handlers in app.js. Add a focused settings presentation module and scoped stylesheet that organize the existing controls without duplicating persistence. Ship both assets in the frontend web image. Add behavior-level browser coverage of every settings tab and representative real save payloads.

**Constraints:** Keep stable version 0.4.8. Do not change backend discovery or Scenes Add/Search; Discover is only a sidebar shortcut to that view. Never put credentials in screenshots. No workflow changes (current GitHub login lacks workflow-write permission).

## 1. Settings presentation
- [x] Add browser checks that first fail on the existing layout: grouped navigation, nine views, mobile overflow, provider/indexer additions, Save/Reset behavior and payloads.
- [x] Implement settings_ui.js and settings_ui.css, preserving original handlers and controls. Split Downloads into Transfers/Folders/Providers/Post-processing, and the other tabs into the sections approved in the preview.
- [x] Load and package assets for the web-container frontend; guard asynchronous rendering against navigation changes.
- [x] Run browser checks and focused tests.

## 2. Discover removal
- [x] Remove Discover sidebar markup and its dedicated click binding from dashboard_regression_hotfix.js.
- [x] Update obsolete nav assertions and verify Scenes Add/Search and Indexers shortcut still work.

## 3. Verification and delivery
- [x] Run full Python suite, browser layout/settings checks, Ruff, compilation, and JavaScript syntax checks.
- [x] Review implementation, fix findings, regenerate safe screenshots, and inspect desktop/mobile rendering.
- [ ] Create PR, wait for CI, integrate the authorized UI work and verify main image publication.

Validation: 545 Python tests; 42 dashboard browser layouts; nine settings tabs at three widths; all save flows, error retention, credential preservation, delayed navigation, and save/reset regression. Ruff, compilation, and JS syntax checks passed. Independent review finding fixed and rechecked. Desktop and phone screenshots visually inspected.
