<p align="center">
  <img src="assets/logo.svg" alt="citibike2strava logo" width="120" height="120" />
</p>

# citibike2strava

[![CI](https://github.com/erikleon/citibike2strava/actions/workflows/ci.yml/badge.svg)](https://github.com/erikleon/citibike2strava/actions/workflows/ci.yml)

Turn the **Ride Receipt** emails Citi Bike sends to your Gmail into **Strava
activities** — with the real route map (decoded from the receipt's polyline),
correct distance, and proper timestamps. E-bike rides are tagged as
**E-Bike Ride** on Strava.

It is a small, auditable Python CLI that you run yourself. **You register your
own Google and Strava apps, and your tokens never leave your machine** — there
is no shared server and no third party in the loop. See
[docs/SECURITY.md](docs/SECURITY.md).

Beyond a single run it can [**backfill your whole ride history**](#backfill-your-whole-history)
(rate-limit aware and resumable), [**sync new rides automatically**](#unattended-auto-sync)
on a schedule, work [**without Gmail at all**](#without-connecting-gmail-eml--paste) from a
saved `.eml`, and import from [**other Lyft bikeshares**](#other-lyft-bikeshare-cities)
(Divvy, Bay Wheels, Bluebikes, Capital Bikeshare).

```
$ citibike2strava run
✓ [uploaded] receipt #2230948359918490468 3.39 mi — Bedford Ave & Maple St → Myrtle Ave & Lewis Ave
    https://www.strava.com/activities/123456789

1 uploaded, 0 errors, 1 total.
```

## How it works

```
Gmail ("Ride Receipt")  ──►  parse receipt  ──►  build GPX  ──►  Strava upload  ──►  tag E-Bike Ride
   (gmail.modify)            stations/times       polyline →        (activity:write)      + label email
                             + polyline           track + times                            as uploaded
```

1. Search Gmail for `from:updates.citibikenyc.com subject:"Ride Receipt"`.
2. Parse each receipt: start/end stations, start/end times, e-bike flag,
   receipt number, and the Google-encoded **polyline** of the route.
3. Compute distance from the polyline and build a GPX track, interpolating each
   point's timestamp across the ride window (the email only gives start/end
   times). Distance and elapsed time are exact; the speed profile is smoothed.
4. Upload the GPX to Strava, set the sport type to **E-Bike Ride**, and label
   the email so it is never uploaded twice.

### Parsing details that matter (hard-won)

- **The polyline is the source of truth for coordinates.** The Gmail API mangles
  some high-bit bytes in the static-map URL, corrupting its scalar
  `origin_lat`/`dest_lng` params (e.g. `origin_lat@.66035`). The `polyline=`
  value is pure ASCII percent-escapes and survives intact, so we take the
  start/end from its first/last decoded points. (`src/citibike2strava/polyline.py`)
- **Station names contain `&`** ("Bedford Ave & Maple St"). The GPX is built with
  `xml.etree.ElementTree`, which escapes `&`→`&amp;` automatically, so the file
  is valid XML and Strava accepts it.
- **Times are local (NYC).** They are converted to UTC for GPX using
  `zoneinfo`, which handles EDT/EST and DST correctly. Timezone is configurable
  for other Lyft bikeshares.
- **No distance field exists** in the email; it is computed from the polyline
  (haversine).

## Quick start

Requires Python 3.11+.

> **Strava API prerequisite.** As of 2026, Strava's API is available at the
> Standard tier with a **Strava subscription** (per Strava's
> [API FAQ](https://communityhub.strava.com/developers-knowledge-base-14/strava-api-faq-12906),
> a subscriber pays no additional fee for API access). Free-tier Strava accounts
> may need to subscribe to register the API app this tool uses. You still register
> your **own** app — there is no shared backend.

```bash
git clone https://github.com/erikleon/citibike2strava
cd citibike2strava
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 1. Register your own Google + Strava apps and add credentials.
#    Full walkthrough: docs/OAUTH_SETUP.md
cp .env.example .env
$EDITOR .env

# 2. Authorize (opens your browser for each service).
citibike2strava login

# 3. Preview what would be uploaded — parses only, no writes.
citibike2strava run --dry-run

# 4. Do it for real.
citibike2strava run
```

## Commands

| Command | Description |
|---|---|
| `citibike2strava login [--gmail] [--strava]` | Authorize one or both services (browser OAuth). |
| `citibike2strava status` | Show what is authorized, the selected system, and current config. |
| `citibike2strava run [--dry-run] [--limit N] [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--force]` | Process not-yet-uploaded receipts; use `--since/--until` to backfill a date window. |
| `citibike2strava process <message_id> [--dry-run] [--force]` | Process a single receipt by Gmail message id. |
| `citibike2strava process-file <path\|-> [--dry-run] [--force]` | Process a saved/forwarded `.eml` (or pasted HTML on stdin) — no Gmail API needed. |
| `citibike2strava export <message_id> [-o ride.gpx]` | Write a receipt's GPX without uploading (debugging). |
| `citibike2strava serve [--port N]` | Run the local one-click backend for the browser extension. |
| `citibike2strava schedule [--interval-minutes N]` | Print cron/launchd/Task Scheduler recipes for unattended auto-sync. |
| `citibike2strava watch [--interval-minutes N]` | Poll for new receipts on an interval in the foreground (single-command auto-sync). |
| `citibike2strava logout` | Delete stored tokens. |

### Backfill your whole history

`run` processes every receipt not yet uploaded, so the first run imports your
entire history. It paces itself under Strava's rate limit (200 requests / 15
min), backs off on `429`, and a failure on one ride doesn't abort the batch, so a
large import resumes cleanly on re-run. Target a slice with `--since`/`--until`:

```bash
citibike2strava run --since 2024-01-01 --until 2025-01-01
```

### Other Lyft bikeshare cities

Citi Bike (NYC) is verified. The same Lyft receipt template powers other
systems; select one with `CITIBIKE2STRAVA_SYSTEM` (the Gmail sender and timezone
are derived automatically):

| `CITIBIKE2STRAVA_SYSTEM` | System | Status |
|---|---|---|
| `citibike` | Citi Bike (NYC) | supported |
| `divvy` | Divvy (Chicago) | experimental |
| `baywheels` | Bay Wheels (SF) | experimental |
| `bluebikes` | Bluebikes (Boston) | experimental |
| `capitalbikeshare` | Capital Bikeshare (DC) | experimental |

"Experimental" means the sender/timezone are best-known but not yet verified
against a real receipt fixture. The parser **fails closed** — if a system's
template differs it raises an error rather than uploading a wrong route. If you
use an experimental system and it works (or doesn't), please open an issue with a
sanitized receipt so it can be promoted to "supported".

### Without connecting Gmail (`.eml` / paste)

You don't have to grant Gmail access at all. Save a receipt as `.eml` (or forward
it to yourself) and feed it in — the receipt is parsed locally and uploaded to
Strava exactly as the Gmail path does:

```bash
citibike2strava process-file ride-receipt.eml
# or pipe raw receipt HTML:
pbpaste | citibike2strava process-file -
```

This path needs only Strava authorization. Duplicate uploads are prevented by a
local processed-receipts cache (bypass with `--force`) backed by Strava's
`external_id` duplicate check.

### Unattended auto-sync

Two ways to keep Strava in sync without thinking about it:

- **OS scheduler (recommended for true background):** `citibike2strava schedule`
  prints a ready-to-use cron / launchd / Windows Task Scheduler recipe that runs
  the idempotent `run` on a timer — it survives reboots and there's no process to
  babysit.
- **Foreground loop:** `citibike2strava watch --interval-minutes 30` polls in a
  single long-running command. It syncs immediately, then every interval; a
  transient error (network blip, rate limit) is logged and it keeps going, while
  a fatal auth error (a revoked token needing `login` again) stops it with a
  non-zero exit so you notice. Ctrl-C (or SIGTERM) shuts it down cleanly.

Either way, set `CITIBIKE2STRAVA_LOG=<path>` so each run appends a one-line
summary — that way a silent failure (e.g. an expired token) is visible after the
fact.

## One-click from inside the email (browser extension)

For uploading the receipt you're currently reading in Gmail with a single click:

```bash
citibike2strava serve        # loopback backend; prints an auth token
```

Then load the [`extension/`](extension/) folder as an unpacked Chrome extension,
paste the printed token into its Options, and a **↑ Strava** button appears on
Citi Bike receipts. The extension never holds your OAuth tokens — it only calls
the local backend, which re-fetches and re-parses the receipt server-side. See
[extension/README.md](extension/README.md).

## Configuration

Settings come from environment variables, a local `.env`, or
`~/.config/citibike2strava/config.toml` (in that precedence). See
[`.env.example`](.env.example). Key options:

- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — your Google OAuth app.
- `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` — your Strava API app.
- `CITIBIKE2STRAVA_TZ` — receipt timezone (default `America/New_York`).
- `CITIBIKE2STRAVA_GMAIL_QUERY`, `CITIBIKE2STRAVA_LABEL` — override search/label.

### Behind a corporate proxy

The Google API client uses `httplib2`, which only routes through an
`HTTP_PROXY`/`HTTPS_PROXY` proxy when the `PySocks` package is installed.
Without it, httplib2 **silently ignores the proxy** and connects directly,
which on a locked-down network fails with a connection timeout
(`WinError 10060` on Windows). If you are behind a proxy, install it:

```bash
pip install pysocks
```

Set the proxy via the standard env vars (URL-encode any special characters in
the credentials, e.g. `@` → `%40`):

```bash
export HTTPS_PROXY="http://user%40domain:pass@proxy.host:8080"
export HTTP_PROXY="$HTTPS_PROXY"
```

## Idempotency

A ride is never double-counted: after a successful upload the source email is
labelled `citibike2strava/uploaded` (excluded from future searches), **and** the
Strava upload uses the receipt number as `external_id`, which Strava rejects as a
duplicate on a second attempt.

## Security

You bring your own OAuth apps; tokens are stored locally with `0600`
permissions and never transmitted to anyone but Google/Strava. Requested scopes
are minimal (`gmail.modify`, Strava `activity:write,read`). Full threat model
and data-flow in [docs/SECURITY.md](docs/SECURITY.md). To report a vulnerability,
see that document.

## Reuse & future direction

The parsing/GPX/upload core is decoupled from auth and storage behind a
`TokenStore` interface and two entrypoints: `Pipeline.process_message(message_id)`
(Gmail) and `Pipeline.process_html(html)` (a saved `.eml`, a paste, or a future
inbound-email webhook — no Gmail needed). The same code could power a hosted
multi-user service or the "one-click from inside the email" browser extension.
Design and migration notes: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Development

```bash
pip install -e ".[dev]"
pytest
```

Tests run fully offline against a sanitized fixture
(`tests/fixtures/sample_receipt.html`) that preserves the real template quirks
(corrupted scalar map params, ampersands in station names, a real polyline).

## License

MIT — see [LICENSE](LICENSE). Not affiliated with Citi Bike, Lyft, or Strava.
