# TODOS

Deferred work, with enough context to pick it up cold. Recorded during the
2026-06-18 plan review (see `~/.claude/plans/2026-06-18-citibike2strava-sharpen-local-tool-ceo.md`).

## 1. Hosted multi-user service (BLOCKED — platform risk)

- **What:** A hosted version so non-developers can use the tool without running
  a CLI or registering their own OAuth apps. Two designs were analyzed:
  Approach A (inbound email relay — user forwards receipts, no server-side Gmail
  scope) and Approach B (server-side Gmail OAuth + Pub/Sub push).
- **Why deferred:** Strava gate-keeps every app past **10 connected athletes**
  with discretionary review ("increased access is not a guarantee"), and is
  actively locking down third-party API use ahead of its IPO (Nov 2024 agreement
  restrictions; $11.99/mo developer paywall as of 2026-06-01). A paid,
  Strava-API-dependent SaaS concentrates existential platform risk in one hostile
  gatekeeper.
- **Context:** The current bring-your-own-OAuth local design is a *moat* — each
  user is their own "Single Player Mode" app, so Strava's multi-user approval
  gate never applies. Going hosted is what *creates* that risk. If pursued,
  prefer Approach A (no Google `gmail.modify` custody → no Google restricted-scope
  verification / annual CASA assessment).
- **Depends on:** Strava granting >10-athlete partner/commercial approval. Do not
  build until that gate is cleared.

## 2. Richer activity data + variable-speed timing

- **What:** (a) Gear assignment, calorie estimate, per-point elevation
  enrichment; (b) variable-speed timing instead of today's constant-speed
  interpolation.
- **Why deferred:** Lower leverage than backfill/multi-city/.eml. Constant-speed
  timing makes total distance/elapsed time exact but renders Strava segment/KOM
  times meaningless — only matters to users who race segments, not commuters.
- **Context:** See `gpx.py:interpolated_times`. Receipts give only overall
  start/end times, so any speed profile is inferred regardless.
- **Depends on:** evidence that users care about segment accuracy.

## 3. Gmail read-side quota handling for large backfills

- **What:** Apply throttle/backoff to the Gmail message-fetch side of backfill
  (Gmail API quota units + pagination), matching the Strava-write resilience.
- **Why deferred:** Considered during the 2026-06-18 review and not taken this
  round. The backfill resilience work targets Strava writes; a hundreds-of-message
  import could still choke on the Gmail read side.
- **Context:** `gmail_client.search_message_ids` (pagination already correct) and
  `get_html_body` (one `get` per message). Risk scales with history size.
- **Depends on:** real-world reports of large backfills hitting Gmail limits.
