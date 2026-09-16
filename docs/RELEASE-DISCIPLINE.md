# ScarletX release discipline

ScarletX roadmap work is intentionally separated from release-version work.

## Roadmap pull requests

- Each numbered roadmap section is delivered in its own pull request.
- Roadmap pull requests must not change the shipped ScarletX version, release notes, TrueNAS app version, container release tags, or other release metadata unless the pull request is itself the dedicated release-discipline/release change.
- The current shipped release lock remains `0.4.7` until an explicit release decision changes it.
- Feature, reliability, performance, and refactor pull requests must preserve backward compatibility unless their roadmap section explicitly changes behavior.
- A section is mergeable only after its section-specific regression tests pass and applicable repository gates have been checked. Known failures already present on the base branch must be documented rather than hidden.

## Release train

Roadmap work progresses in small mergeable slices: foundation, reliability, concurrency, imports, library/features, hardening, and validation. Beta or stable releases are cut only from an explicit release change after the intended slice is complete; feature PRs do not silently advance versions.

The stable release workflow is intentionally manual-only, so ordinary merges to `main` cannot start a release implicitly. Normal `main` builds publish only moving development tags (`main` and SHA tags) and never overwrite a stable release tag. A stable release is published only through an explicit manual dispatch of the release workflow, which is locked to the selected version and tags the exact release commit it verifies and builds.

## Version-helper contract

The release helper may exercise beta-to-stable transitions only inside the currently supported and locked release range. Synthetic test fixtures must not request a version newer than the active release lock, because such a request is correctly rejected by the production helper.

This policy keeps version changes auditable, prevents accidental auto-bumps during roadmap work, and makes CI failures attributable to the section that introduced them.
