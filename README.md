# ScarletX 0.3.6 Local

[![Tests](https://github.com/troyshank/ScarletX/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/troyshank/ScarletX/actions/workflows/tests.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)

ScarletX is a private local development build for managing TPDB-verified adult production-studio scenes.

## Start on macOS

Double-click `Start-ScarletX.command`, or run:

```bash
chmod +x Start-ScarletX.command
./Start-ScarletX.command
```

The launcher uses the first available local port starting at `8690` and opens ScarletX automatically.

On macOS, if Homebrew is available, the launcher installs missing PAR2, 7-Zip, RAR extraction, and FFmpeg/FFprobe tools automatically. Set `SCARLETX_SKIP_TOOL_INSTALL=1` to skip that convenience step.

## Docker / Linux

ScarletX is also packaged to run inside a Linux container. The same Python application code is used on macOS and Linux; the image installs the system post-processing tools during the image build.

Build and start:

```bash
docker compose up -d --build
```

Open `http://localhost:8690`.

Persistent mounts:

- `/config` — ScarletX SQLite database/configuration
- `/downloads` — incomplete, complete, and failed Usenet jobs
- `/media` — media library mount
- `/backups` — backups

The container binds ScarletX to `0.0.0.0:8690`; local/macOS launch remains bound to localhost unless changed.


## Built-in media library and player

ScarletX now includes the focused local-library functions that previously required a separate Stash-style application:

- background library scanning of configured scene roots
- FFprobe codec, resolution, bitrate, duration, and container indexing
- persistent file fingerprints for duplicate detection
- missing-file and unmatched-file tracking
- local-title matching for newly discovered scene files
- FFmpeg screengrab and thumbnail generation
- on-demand short preview generation
- direct browser playback with HTTP byte-range seeking
- resume position, play count, and favorites
- automatic indexing after ScarletX completes and imports a download
- persistent TPDB response and artwork caching under the ScarletX cache directory

The media scanner runs as a background job so large libraries do not block the web UI. In Docker, `/media` is the default scene root and generated assets/cache remain under `/config`.

## Studio-only policy

ScarletX only displays/imports/monitors scenes attached to a valid TPDB site/studio entity. Creator platforms, tube sites, amateur/homemade releases, and explicitly blocked networks such as Anal Vids / AnalVids are excluded. Release matching also requires the TPDB studio name to match the Usenet release.

## Performer profiles

Performer cards/images open the performer profile. TPDB performer data is shown with US measurements first and metric equivalents in parentheses, including feet/inches with centimeters, pounds with kilograms, and inches with centimeters for body measurements.

## Downloads

ScarletX Built-In Usenet is the only download client. NNTP is TLS-only (TLS 1.2+). This private dev build seeds the supplied Astraweb and Newshosting provider profiles. Provider passwords and API/indexer keys are masked by the Settings API.

- Astraweb: `us.astraweb.com:563`, 50 connections
- Newshosting: `news.newshosting.com:563`, 100 connections
- Global native worker cap: 120 by default (up to provider limits)
- Adjustable speed limit: Unlimited–250 MB/s

ScarletX load-balances articles across both providers, preserves provider failover, uses a rolling segment scheduler, and uses a bulk yEnc decoder to reduce downloader CPU overhead.

The download/queue name is the TPDB scene title rather than the Usenet release string. Indexer names are not shown in download-client information.

Failed jobs move into `downloads/failed`. The Activity page has a dedicated Failed area with Retry, Archive Password, and Clear Failed. Retry resumes preserved partial segments; Clear Failed removes the failed jobs and their partial files.

Post-processing is stage-aware and bounded. Direct playable video posts skip unnecessary PAR2 verification; PAR2 verification is capped at 3 minutes and repair/archive extraction at 10 minutes each. Activity shows the current post-processing stage, and Cancel remains available while repair or extraction is running.

The Activity queue is live: progress, downloaded/total size, speed, ETA, state, and the active-download counter update automatically without refreshing the page.

PAR2, UnRAR/RAR extraction, and 7-Zip are part of the normal install path. The Docker image installs them at build time; the macOS launcher installs missing tools through Homebrew when available.

## Development credentials

This package intentionally embeds private TPDB, indexer, and NNTP development credentials supplied for local testing. Do not publish or distribute this ZIP or a container image built from it.

See `RELEASE-NOTES-0.3.6.md` for the feature summary.

### Performance-tuned native downloader

ScarletX uses provider connection counts as hard limits but defaults to a 120-connection active working set and dynamically favors the fastest healthy provider while spilling to the other provider when the preferred pool is saturated. Provider maxima remain 50 Astraweb / 100 Newshosting. Live queue progress is held in memory and persisted roughly once per second, and SQLite runs in WAL mode to keep the UI from blocking the downloader.

The default local scene root folder is `/tmp`. Set `SCARLETX_DEFAULT_MEDIA_ROOT` before launch to use a permanent library path. Docker deployments can override the same variable (normally to a mounted media dataset).


### Native downloader performance
ScarletX uses fair weighted provider scheduling and bounded shared TLS connection pools. With the bundled dev provider limits (Astraweb 50, Newshosting 100), the default 120-worker active window learns observed throughput/reliability and spills work to whichever healthy provider has free capacity.

### High-throughput Usenet acceleration

ScarletX 0.3.6 uses SABCTools when available for SIMD yEnc decoding and direct positional file writes. The Mac/Windows launchers try to install this accelerator automatically, but failure is non-fatal and the built-in decoder remains available. Set `SCARLETX_SKIP_ACCEL_INSTALL=1` to skip the optional install attempt.
