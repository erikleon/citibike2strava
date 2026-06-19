# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-06-18

Sharpen the local tool: bulk backfill, more cities, no-Gmail ingestion, and
unattended sync. (Strategic decision: stay a local OSS tool rather than a hosted
SaaS — see `TODOS.md` for the Strava platform-risk rationale.)

### Added

- **Bulk backfill with rate-limit resilience**: `run --since/--until` targets a
  date window; `strava_client` now paces requests under Strava's 200/15min limit
  (client-side sliding window) and honours `Retry-After` with backoff on `429`.
  A failure on one receipt no longer aborts the batch, and results stream as they
  complete. Resumable via idempotency.
- **`.eml` / paste ingestion**: `process-file <path|->` parses a saved or
  forwarded receipt (including forwarded-as-attachment `message/rfc822`) or a
  raw HTML paste on stdin — no Gmail API needed. New `Pipeline.process_html`
  seam; `gmail.modify` is not required for this path.
- **Multi-city Lyft systems**: `CITIBIKE2STRAVA_SYSTEM` selects Citi Bike (NYC,
  verified) or experimental Divvy / Bay Wheels / Bluebikes / Capital Bikeshare,
  deriving the Gmail sender and timezone. The parser fails closed on any
  template mismatch.
- **Scheduled auto-sync recipes**: `schedule [--interval-minutes N]` prints
  cron / launchd / Task Scheduler snippets that invoke the idempotent `run`.
- **Local processed-receipts cache**: a fast-path skip for the `.eml` path
  (`--force` bypasses); Strava's `external_id` remains authoritative on conflict.

### Changed

- OAuth refresh failures (revoked/expired tokens) now raise a clear "re-run
  login" error instead of a traceback — important for unattended runs.
- Set `CITIBIKE2STRAVA_LOG=<path>` to append a one-line summary per run so a
  silent scheduled failure is discoverable.

## [0.1.0] - 2026-06-18

Initial release.

### Added

- **Core pipeline**: find Citi Bike "Ride Receipt" emails in Gmail, parse them,
  build a GPX from the route, and upload each as a Strava **E-Bike Ride**.
  - `receipt.py` — parses start/end stations, times, e-bike flag, receipt
    number, and the Google-encoded route polyline.
  - `polyline.py` — dependency-free encoded-polyline decoder. The polyline is
    the trusted source of coordinates because the Gmail API mangles the
    static-map URL's scalar `origin_lat`/`dest_lng` params.
  - `gpx.py` — GPX 1.1 builder via `ElementTree` (escapes `&` in station names);
    converts NYC-local times to UTC with `zoneinfo` (DST-correct) and
    interpolates per-point timestamps across the ride window.
  - `geo.py` — haversine distance (the email has no distance field).
- **CLI** (`citibike2strava`): `login`, `logout`, `status`, `run` (with
  `--dry-run`/`--limit`), `process`, `export`, and `serve`.
- **Auth & security**: each user registers their own Google + Strava OAuth apps;
  minimal scopes (`gmail.modify`, Strava `activity:write,read`); tokens stored
  locally with `0600` permissions behind a pluggable `TokenStore`.
- **Idempotency**: processed emails are labelled `citibike2strava/uploaded`, and
  the Strava upload sets `external_id` to the receipt number to reject
  duplicates server-side.
- **One-click backend** (`server.py` + `extension/`): a loopback-only HTTP
  endpoint wrapping `Pipeline.process_message`, plus a Manifest V3 browser
  extension stub that adds a "↑ Strava" button to receipts in Gmail. OAuth
  tokens never leave the backend.
- **Docs**: README, `docs/OAUTH_SETUP.md`, `docs/SECURITY.md` (threat model),
  `docs/ARCHITECTURE.md` (reuse seams + path to a hosted multi-user service).
- **Tests & CI**: offline test suite against a sanitized fixture; GitHub Actions
  workflow running pytest on Python 3.11–3.13.

[Unreleased]: https://github.com/erikleon/citibike2strava/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/erikleon/citibike2strava/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/erikleon/citibike2strava/releases/tag/v0.1.0
