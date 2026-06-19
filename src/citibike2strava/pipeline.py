"""Orchestration: Gmail receipt -> parsed Ride -> GPX -> Strava activity.

This module is the reusable core. The CLI calls it today; a hosted service or a
"one-click from inside the email" browser-extension backend would call the very
same entrypoints. There are two:

* :meth:`Pipeline.process_message` — given a Gmail message id, fetch the HTML and
  process it (and label the mail afterwards for idempotency).
* :meth:`Pipeline.process_html` — given raw receipt HTML (a saved/forwarded
  ``.eml`` body, a pasted receipt, or a future inbound-email webhook), process it
  with no Gmail dependency at all.

Both share :meth:`_process_html`, which parses, builds the GPX, and uploads.
Nothing here assumes a single user or local files beyond what the injected
:class:`TokenStore` and :class:`ProcessedStore` provide.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

import requests

from .auth import DEFAULT_USER, TokenStore
from .auth import google_auth, strava_auth
from .config import Config
from .geo import METERS_PER_MILE, total_distance_m
from .gmail_client import GmailClient, HttpError, build_unprocessed_query
from .gpx import build_gpx
from .processed import ProcessedStore
from .receipt import ReceiptParseError, parse_receipt
from .strava_client import DuplicateUpload, StravaClient, StravaError


@dataclass
class RideResult:
    message_id: str
    status: str  # "uploaded" | "duplicate" | "dry-run" | "skipped" | "error"
    receipt_id: str | None = None
    activity_url: str | None = None
    distance_mi: float | None = None
    detail: str | None = None


# Per-ride failures we isolate during a bulk run so one bad receipt does not
# abort the whole batch. Programming errors are intentionally NOT caught here.
_ISOLATED_ERRORS = (StravaError, HttpError, requests.RequestException)


class Pipeline:
    def __init__(
        self,
        config: Config,
        store: TokenStore,
        user_id: str = DEFAULT_USER,
        *,
        processed: ProcessedStore | None = None,
    ):
        self.config = config
        self.store = store
        self.user_id = user_id
        self.processed = processed or ProcessedStore(config.home / "processed.json")
        self._gmail: GmailClient | None = None
        self._strava: StravaClient | None = None

    # -- lazily-built, auth'd clients -----------------------------------
    def gmail(self) -> GmailClient:
        if self._gmail is None:
            creds = google_auth.get_credentials(self.config, self.store, self.user_id)
            self._gmail = GmailClient(creds)
        return self._gmail

    def strava(self) -> StravaClient:
        if self._strava is None:
            token = strava_auth.get_access_token(self.config, self.store, self.user_id)
            self._strava = StravaClient(token)
        return self._strava

    # -- core ------------------------------------------------------------
    def _process_html(
        self, html: str, *, source_id: str | None, dry_run: bool, force: bool
    ) -> RideResult:
        """Parse receipt HTML and upload it. Shared by both entrypoints."""
        ident = source_id or "?"
        try:
            ride = parse_receipt(
                html, message_id=source_id, timezone=self.config.timezone
            )
        except (ReceiptParseError, ValueError) as exc:
            return RideResult(ident, "error", detail=str(exc))

        distance_mi = round(total_distance_m(ride.points) / METERS_PER_MILE, 2)

        # Fast-path: skip a receipt we already uploaded, without any network call.
        # `force` bypasses this; Strava's external_id stays authoritative if the
        # cache and server ever disagree.
        if not dry_run and not force and self.processed.contains(ride.receipt_id):
            return RideResult(
                ident,
                "skipped",
                receipt_id=ride.receipt_id,
                distance_mi=distance_mi,
                detail="already uploaded (cached)",
            )

        gpx = build_gpx(ride)

        if dry_run:
            return RideResult(
                ident,
                "dry-run",
                receipt_id=ride.receipt_id,
                distance_mi=distance_mi,
                detail=f"{ride.activity_name} ({ride.sport_type})",
            )

        # Keep the description free of billing details (the receipt line item
        # carries the per-minute rate and dollar charge); link the project.
        description = (
            f"Imported from Citi Bike receipt #{ride.receipt_id}. "
            f"{distance_mi} mi via citibike2strava — "
            f"https://github.com/erikleon/citibike2strava"
        )
        try:
            result = self.strava().upload_gpx(
                gpx,
                name=ride.activity_name,
                external_id=ride.receipt_id,
                description=description,
            )
        except DuplicateUpload as exc:
            self.processed.add(ride.receipt_id)
            return RideResult(
                ident,
                "duplicate",
                receipt_id=ride.receipt_id,
                distance_mi=distance_mi,
                detail=str(exc),
            )

        # Strava ignores sport type on GPX upload; set it on the activity.
        self.strava().update_activity(
            result.activity_id, sport_type=ride.sport_type, name=ride.activity_name
        )
        self.processed.add(ride.receipt_id)
        return RideResult(
            ident,
            "uploaded",
            receipt_id=ride.receipt_id,
            activity_url=result.activity_url,
            distance_mi=distance_mi,
            detail=ride.activity_name,
        )

    def process_html(
        self,
        html: str,
        *,
        source_id: str | None = None,
        dry_run: bool = False,
        force: bool = False,
    ) -> RideResult:
        """Process raw receipt HTML (``.eml`` body, paste, webhook). No Gmail."""
        return self._process_html(
            html, source_id=source_id, dry_run=dry_run, force=force
        )

    def process_message(
        self, message_id: str, *, dry_run: bool = False, force: bool = False
    ) -> RideResult:
        """Process a single receipt by Gmail message id."""
        gmail = self.gmail()
        html = gmail.get_html_body(message_id)
        result = self._process_html(
            html, source_id=message_id, dry_run=dry_run, force=force
        )
        # Label the source mail so future searches skip it (idempotency).
        if result.status in ("uploaded", "duplicate"):
            self._mark_processed(message_id)
        return result

    def process_inbox(
        self,
        *,
        dry_run: bool = False,
        limit: int | None = None,
        since: date | None = None,
        until: date | None = None,
        force: bool = False,
        on_result: Callable[[RideResult], None] | None = None,
    ) -> list[RideResult]:
        """Process every not-yet-uploaded receipt, optionally within a date window.

        Resilient by design for backfills: a failure on one receipt (rate limit
        exhausted, a transient network/Gmail error) is captured as an ``error``
        result and the batch continues. Results stream through ``on_result`` as
        they complete so long runs show progress.
        """
        gmail = self.gmail()
        query = build_unprocessed_query(self.config, since=since, until=until)
        message_ids = gmail.search_message_ids(query)
        if limit is not None:
            message_ids = message_ids[:limit]

        results: list[RideResult] = []
        for mid in message_ids:
            try:
                result = self.process_message(mid, dry_run=dry_run, force=force)
            except _ISOLATED_ERRORS as exc:
                result = RideResult(
                    mid, "error", detail=f"{type(exc).__name__}: {exc}"
                )
            results.append(result)
            if on_result is not None:
                on_result(result)
        return results

    # -- idempotency -----------------------------------------------------
    def _mark_processed(self, message_id: str) -> None:
        if self.config.processed_label:
            gmail = self.gmail()
            label_id = gmail.ensure_label(self.config.processed_label)
            gmail.add_label(message_id, label_id)
