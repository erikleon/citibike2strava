# Architecture

The project is deliberately layered so the **core** (parse → GPX → upload) knows
nothing about *how* it is invoked or *where* tokens live. That is what makes the
same code reusable across a local CLI today, a hosted multi-user service, and a
"one-click from inside the email" browser extension later.

## Module map

```
src/citibike2strava/
├── models.py         Ride / TrackPoint dataclasses (pure data, no I/O)
├── polyline.py       Google encoded-polyline decoder (no deps)
├── geo.py            haversine + cumulative/total distance
├── receipt.py        receipt HTML → Ride  (parse_receipt)
├── gpx.py            Ride → GPX 1.1 string (XML-escaped, UTC, interpolated time)
├── gmail_client.py   Gmail API: search / read HTML / label
├── strava_client.py  Strava API: upload GPX, poll, set sport type
├── config.py         env/.env/toml config + on-disk locations
├── pipeline.py       orchestration: process_message / process_inbox  ← reusable core
├── cli.py            argparse front-end (one of potentially many front-ends)
└── auth/
    ├── token_store.py   TokenStore ABC + FileTokenStore  ← the storage seam
    ├── google_auth.py   Gmail OAuth (installed-app loopback)
    └── strava_auth.py   Strava OAuth (authorization-code, localhost callback)
```

### Dependency direction

```
cli  ─►  pipeline  ─►  { receipt, gpx, gmail_client, strava_client, auth }
                         │
              models / polyline / geo  (pure, dependency-free)
```

Front-ends depend on the pipeline; the pipeline depends on the core; the core
(`models`, `polyline`, `geo`, `receipt`, `gpx`) has no auth/network/storage
dependencies and is trivially unit-testable offline.

## The two seams that enable reuse

1. **`TokenStore`** (`auth/token_store.py`) — an abstract interface for
   per-user, per-provider token persistence. The CLI injects `FileTokenStore`;
   everything else only sees the interface. Swap in a DB-backed implementation
   and the rest of the system is unchanged.

2. **`Pipeline.process_message(message_id, *, dry_run)`** — a single entrypoint
   that takes a Gmail message id (and is constructed with a `Config`, a
   `TokenStore`, and a `user_id`). Any front-end — CLI, HTTP handler, queue
   worker — calls this same method.

```python
from citibike2strava import Pipeline
from citibike2strava.config import load_config
from citibike2strava.auth import FileTokenStore

config = load_config()
pipeline = Pipeline(config, FileTokenStore(config.tokens_dir), user_id="default")
result = pipeline.process_message("<gmail-message-id>")
```

## Path 1 — hosted multi-user service

What changes (and, importantly, what doesn't):

- **Unchanged:** `receipt.py`, `gpx.py`, `polyline.py`, `geo.py`,
  `gmail_client.py`, `strava_client.py`, `pipeline.py`.
- **New `TokenStore`:** implement against an encrypted datastore keyed by
  `user_id` (envelope-encrypt with a KMS key; never store plaintext tokens).
- **Web OAuth flows:** replace the localhost loopback in `auth/*_auth.py` with a
  hosted redirect URI and server-side code exchange. The token *shape* stored is
  identical, so `get_credentials` / `get_access_token` are reused as-is.
- **Per-user invocation:** a web handler resolves the signed-in `user_id`,
  constructs a `Pipeline`, and calls `process_message`.
- **Compliance:** Google OAuth app verification is required for `gmail.modify`
  beyond test users; see [SECURITY.md](SECURITY.md) for the custodial threat
  model.

A natural automation for the hosted version is **Gmail push notifications**
(`users.watch` → Pub/Sub): on a new matching message, enqueue
`process_message(message_id, user_id)`.

## Path 2 — one-click upload from inside the email

Goal: a button in the Gmail message ("Send this ride to Strava") that uploads
the open receipt in one click.

Recommended shape:

- A **browser extension** (content script) that detects an open Citi Bike
  receipt in Gmail and injects a button. It reads the message id from the Gmail
  DOM/URL (or via `gmail.js`).
- The button calls a small **backend endpoint** — either the hosted service
  above or a tiny local helper bound to `127.0.0.1` — e.g.:
  ```
  POST /api/rides/upload   { "message_id": "...", "user_id": "..." }
  → { "status": "uploaded", "activity_url": "https://www.strava.com/activities/…" }
  ```
- That endpoint is a one-line wrapper over `Pipeline.process_message`, returning
  the existing `RideResult`. No core changes.

Security notes for this path: authenticate the extension→backend call (per-user
token / same-origin + CSRF protection), keep the backend's OAuth tokens server-
side (never expose them to the extension), and treat the `message_id` as
untrusted (the backend re-fetches and re-parses the receipt itself rather than
trusting any client-supplied ride data).

## Testing strategy

- Pure core is covered offline by `tests/` against a sanitized fixture that
  preserves the real template's quirks (corrupted scalar map params, ampersands,
  a real polyline). Network layers (`gmail_client`, `strava_client`, `auth`) are
  thin wrappers kept free of business logic so they can be exercised against the
  live APIs or mocked at the boundary.
