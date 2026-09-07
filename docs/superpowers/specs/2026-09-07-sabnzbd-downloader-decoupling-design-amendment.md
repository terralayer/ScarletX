# SABnzbd Decoupling Design Amendment

Date: 2026-09-07

This amendment resolves the compatibility wording in the main design spec.

For the initial SABnzbd decoupling release, native-downloader settings are **preserved in storage** even when they are hidden from the active Settings UI and ignored by normal runtime behavior. No migration in this effort should delete native provider credentials, native tuning settings, native job rows, or native history. Destructive removal of those legacy values is explicitly out of scope and would require a separate future migration/design.

Accordingly, Acceptance Criterion 11 should be interpreted as: existing 0.3.10 databases upgrade without destructive loss of native downloader jobs, history, or settings; those values may become dormant and hidden from active product surfaces.
