# citibike2strava browser extension (stub)

A minimal Manifest V3 extension that adds a **↑ Strava** button to Citi Bike
ride receipts in Gmail. Clicking it uploads that ride via the local backend
(`citibike2strava serve`). This is a working starting point, not a polished
product — Gmail's DOM is unofficial and may change.

## How the pieces fit

```
Gmail (mail.google.com)                     your machine
┌───────────────────────────┐              ┌───────────────────────────┐
│ content.js                 │  POST        │ citibike2strava serve      │
│  reads data-legacy-message │ ───────────► │  /api/rides/upload         │
│  -id, shows "↑ Strava"     │  X-Auth-Token│  → Pipeline.process_message│
└───────────────────────────┘              └─────────────┬─────────────┘
                                                          ▼  Strava
```

The extension never holds your Google/Strava tokens — those stay server-side in
the local backend. It only knows the loopback endpoint and a shared auth token.

## Setup

1. Start the backend and copy the token it prints:
   ```bash
   citibike2strava serve
   # citibike2strava one-click backend on http://127.0.0.1:8722
   #   Auth token (configure this in the extension): <TOKEN>
   ```
2. Load the extension: open `chrome://extensions`, enable **Developer mode**,
   click **Load unpacked**, and select this `extension/` folder.
3. Open the extension's **Options**, paste the endpoint (default
   `http://127.0.0.1:8722`) and the `<TOKEN>`, and Save.
4. Open a Citi Bike "Ride Receipt" in Gmail. Click **↑ Strava**.

## Security notes

- The backend binds to `127.0.0.1` only and requires the `X-Auth-Token` header
  (compared with `hmac.compare_digest`). CORS is limited to
  `https://mail.google.com`.
- Chrome treats `http://127.0.0.1` as a trustworthy origin, so the loopback
  `fetch` from the HTTPS Gmail page is not blocked as mixed content.
- The backend trusts only the `message_id`; it re-fetches and re-parses the
  receipt itself, so a tampered DOM cannot inject fake ride data.

See [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) and
[../docs/SECURITY.md](../docs/SECURITY.md).

## Limitations / next steps

- Button placement is heuristic (`[data-legacy-message-id]` + sender check); a
  Gmail redesign may require selector updates.
- No build step, icons, or store packaging — add those for distribution.
