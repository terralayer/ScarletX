# ScarletX Release Discipline

ScarletX roadmap work and ScarletX releases are separate concerns.

- Roadmap pull requests must not bump the application version.
- Version changes must be isolated in a dedicated release pull request.
- Feature, reliability, performance, refactor, migration, and test-only roadmap pull requests preserve the version already present on their base branch.
- The release helper computes the next patch version generically within the supported `0.4.x` release series; it must not contain a hardcoded lock to whichever patch happens to be current.
- The default branch publishes `main` and commit-SHA container tags. Numeric stable container tags are published only from version tags/releases.
- A dedicated release pull request is responsible for versioned metadata, release notes, TrueNAS catalog metadata, image/tag references, and any other shipped version markers.
- Release pull requests must pass the normal Python matrix, source checks, dependency audit, performance baseline, container builds, and TrueNAS validation before merge.
- Roadmap sections remain reviewable as individual pull requests rather than being bundled into a giant release change.

This policy keeps version changes deliberate while allowing non-release development and CI to validate future patch calculations without altering the shipped version.
