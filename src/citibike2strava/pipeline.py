"""Orchestration: Gmail receipt -> parsed Ride -> GPX -> Strava activity.

This module is the reusable core. The CLI calls it today; a hosted service or a
"one-click from inside the email" browser-extension backend would call the very
same :meth:`Pipeline.process_message` with a Gmail message id and a ``user_id``.
Nothing here assumes a single user or local files beyond what the injected
:class:`TokenStore` provides.
"""

from __future__ import annotations

from dataclasses import dataclass

from .auth import DEFAULT_USER, TokenStore
from .auth import google_auth, strava_auth
from .config import Config
from .geo import METERS_PER_MILE, total_distance_m
from .gmail_client import GmailClient, build_unprocessed_query
from .gpx import build_gpx
from .receipt import ReceiptParseError, parse_receipt
from .strava_client import DuplicateUpload, StravaClient


@dataclass
class RideResult:
    message_id: str
    status: str  # "uploaded" | "duplicate" | "dry-run" | "error"
    receipt_id: str | None = None
    activity_url: str | None = None
    distance_mi: float | None = None
    detail: str | None = None


class Pipeline:
    def __init__(self, config: Config, store: TokenStore, user_id: str = DEFAULT_USER):
        self.config = config
        self.store = store
        self.user_id = user_id
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
    def process_message(self, message_id: str, *, dry_run: bool = False) -> RideResult:
        """Process a single receipt by Gmail message id."""
        gmail = self.gmail()
        try:
            html = gmail.get_html_body(message_id)
            ride = parse_receipt(
                html, message_id=message_id, timezone=self.config.timezone
            )
        except (ReceiptParseError, ValueError) as exc:
            return RideResult(message_id, "error", detail=str(exc))

        distance_mi = round(total_distance_m(ride.points) / METERS_PER_MILE, 2)
        gpx = build_gpx(ride)

        if dry_run:
            return RideResult(
                message_id,
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
            self._mark_processed(message_id)
            return RideResult(
                message_id,
                "duplicate",
                receipt_id=ride.receipt_id,
                distance_mi=distance_mi,
                detail=str(exc),
            )

        # Strava ignores sport type on GPX upload; set it on the activity.
        self.strava().update_activity(
            result.activity_id, sport_type=ride.sport_type, name=ride.activity_name
        )
        self._mark_processed(message_id)
        return RideResult(
            message_id,
            "uploaded",
            receipt_id=ride.receipt_id,
            activity_url=result.activity_url,
            distance_mi=distance_mi,
            detail=ride.activity_name,
        )

    def process_inbox(
        self, *, dry_run: bool = False, limit: int | None = None
    ) -> list[RideResult]:
        """Process every receipt that has not been uploaded yet."""
        gmail = self.gmail()
        message_ids = gmail.search_message_ids(build_unprocessed_query(self.config))
        if limit is not None:
            message_ids = message_ids[:limit]
        return [self.process_message(mid, dry_run=dry_run) for mid in message_ids]

    # -- idempotency -----------------------------------------------------
    def _mark_processed(self, message_id: str) -> None:
        if self.config.processed_label:
            gmail = self.gmail()
            label_id = gmail.ensure_label(self.config.processed_label)
            gmail.add_label(message_id, label_id)
