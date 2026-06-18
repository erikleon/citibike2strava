# Security model

This tool touches two sensitive accounts (your Gmail and your Strava). The
design goal is **least privilege, local-only secrets, and no third party in the
data path**.

## Data flow

```
        your machine only
┌────────────────────────────────────────────────┐
│  .env  ──►  Config                               │
│  browser ──OAuth──►  Google / Strava  ──tokens──►│ tokens/ (0600)
│  Gmail API ──HTML──►  parser ──►  GPX ──►  Strava │
└────────────────────────────────────────────────┘
        no other server is contacted
```

- Email content is fetched directly from Google's API to your machine, parsed in
  memory, and turned into a GPX that is sent directly to Strava's API.
- The only network endpoints are `googleapis.com` / `accounts.google.com` and
  `www.strava.com`.

## Credentials and tokens

- **You register your own OAuth apps.** No client IDs or secrets ship with the
  code, so there is no shared credential to leak or rate-limit.
- OAuth client secrets live in `.env` (git-ignored) or environment variables.
- Refresh/access tokens are written to
  `~/.config/citibike2strava/tokens/<user>/<provider>.json`:
  - the file is created with `0600` and the directory with `0700`;
  - writes are atomic (temp file + `os.replace`) so a crash can't leave a
    world-readable partial file.
- Tokens are treated as secrets: they are never logged or printed. `status`
  reports only *whether* a provider is authorized, never the token.
- `citibike2strava logout` deletes the local tokens. Revoke server-side at
  [Google permissions](https://myaccount.google.com/permissions) and
  [Strava apps](https://www.strava.com/settings/apps).

## Scopes (least privilege)

| Provider | Scope | Why | What it cannot do |
|---|---|---|---|
| Google | `gmail.modify` | Read ride receipts; add an "uploaded" label for idempotency. | Cannot send, delete, or permanently remove mail. |
| Strava | `activity:write`, `read` | Create the activity and set its type/name. | Cannot read your full activity history (`activity:read_all`). |

`gmail.modify` is the narrowest scope that still allows labelling. If you would
rather grant only `gmail.readonly`, set `CITIBIKE2STRAVA_LABEL=` (empty) to
disable labelling — but then idempotency relies solely on Strava's `external_id`
duplicate check, and re-runs will re-examine already-uploaded mail.

## Idempotency / integrity

A receipt cannot create two Strava activities:
1. uploaded emails are labelled and excluded from future searches; **and**
2. the Strava upload sets `external_id` to the receipt number, which Strava
   rejects as a duplicate on any later attempt.

## Trust boundaries & input handling

- **Email HTML is untrusted input.** It is parsed with BeautifulSoup and
  targeted regexes; we never execute it or load remote resources from it. The
  polyline is percent-decoded and run through a pure-Python integer decoder.
- **Gmail transport corruption is assumed.** Scalar lat/lng map params are known
  to be mangled and are deliberately ignored in favour of the polyline.
- The parser fails closed: a receipt missing any required field raises
  `ReceiptParseError` and is reported as an error rather than uploaded with
  guessed data.

## What this tool intentionally does not do

- No shared/hosted backend; nothing is uploaded anywhere except your own Strava.
- No analytics, telemetry, or phone-home.
- No storage of email contents beyond the in-memory parse and the GPX you
  optionally export.

## Hosted (multi-user) deployments

If you adapt this into a hosted service (see [ARCHITECTURE.md](ARCHITECTURE.md)),
the threat model changes significantly — you become a custodian of many users'
tokens. At minimum: encrypt tokens at rest (e.g. envelope encryption with a KMS),
implement the `TokenStore` against that store keyed by `user_id`, scope each
request to a single user, undergo Google OAuth verification for `gmail.modify`,
and never log tokens or email bodies. The core code is structured so none of the
parsing/GPX/upload logic needs to change for this.

## Reporting a vulnerability

Please open a private security advisory on the GitHub repository (Security →
Report a vulnerability) rather than a public issue.
