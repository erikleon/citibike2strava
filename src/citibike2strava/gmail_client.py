"""Thin Gmail API wrapper: find receipts, read their HTML, and label them.

Scope is gmail.modify (read + label). We never delete or send mail. The HTML
body is base64url-decoded locally; note that the Gmail transport can mangle some
high-bit bytes (see :mod:`polyline`), which is exactly why the parser relies on
the ASCII-safe ``polyline=`` param rather than the static-map scalar lat/lng.
"""

from __future__ import annotations

import base64
from datetime import date

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import Config


class GmailClient:
    def __init__(self, credentials):
        self._service = build("gmail", "v1", credentials=credentials)

    # -- searching -------------------------------------------------------
    def search_message_ids(self, query: str) -> list[str]:
        ids: list[str] = []
        page_token = None
        while True:
            resp = (
                self._service.users()
                .messages()
                .list(userId="me", q=query, pageToken=page_token)
                .execute()
            )
            ids.extend(m["id"] for m in resp.get("messages", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return ids

    # -- reading ---------------------------------------------------------
    def get_html_body(self, message_id: str) -> str:
        msg = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        html = self._extract_html(msg["payload"])
        if html is None:
            raise ValueError(f"No HTML body found in message {message_id}")
        return html

    @staticmethod
    def _extract_html(payload: dict) -> str | None:
        """Depth-first search of the MIME tree for the text/html part."""
        if payload.get("mimeType") == "text/html":
            data = payload.get("body", {}).get("data")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", "replace")
        for part in payload.get("parts", []) or []:
            html = GmailClient._extract_html(part)
            if html is not None:
                return html
        return None

    # -- labelling (idempotency) ----------------------------------------
    def ensure_label(self, name: str) -> str:
        for label in self._service.users().labels().list(userId="me").execute().get(
            "labels", []
        ):
            if label["name"] == name:
                return label["id"]
        created = (
            self._service.users()
            .labels()
            .create(
                userId="me",
                body={
                    "name": name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
            .execute()
        )
        return created["id"]

    def add_label(self, message_id: str, label_id: str) -> None:
        self._service.users().messages().modify(
            userId="me", id=message_id, body={"addLabelIds": [label_id]}
        ).execute()

    def get_label_ids(self, message_id: str) -> list[str]:
        msg = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="minimal")
            .execute()
        )
        return msg.get("labelIds", [])


def build_unprocessed_query(
    config: Config, *, since: date | None = None, until: date | None = None
) -> str:
    """Gmail query for receipts that have not been uploaded yet.

    ``since`` / ``until`` restrict the search to a date window (used by backfill
    to target a slice of history). Gmail's ``after:``/``before:`` take
    ``YYYY/MM/DD`` and are inclusive of ``after`` and exclusive of ``before``.
    """
    # Exclude already-labelled mail at the query level; the pipeline also
    # double-checks per-message to stay correct if the label was just created.
    parts = [config.gmail_query]
    if config.processed_label:
        parts.append(f'-label:"{config.processed_label}"')
    if since is not None:
        parts.append(f"after:{since:%Y/%m/%d}")
    if until is not None:
        parts.append(f"before:{until:%Y/%m/%d}")
    return " ".join(parts)


__all__ = ["GmailClient", "build_unprocessed_query", "HttpError"]
