"""Local record of receipt numbers already uploaded to Strava.

This is a **performance fast-path**, not the source of truth. The Gmail path
already labels processed mail, and every upload carries the receipt number as
Strava's ``external_id`` — which Strava rejects as a duplicate. That server-side
guard remains authoritative.

The cache exists so the ``.eml`` / paste path (which has no Gmail label to set)
can skip re-parsing and re-uploading a receipt it has already handled, *without*
a network round-trip. On any conflict, Strava wins: a real upload attempt always
reconciles (a duplicate response is recorded back into the cache), and
``--force`` bypasses the cache entirely so a receipt re-deleted on Strava can be
re-uploaded.

Stored as a JSON object ``{receipt_id: iso8601_timestamp}`` written atomically.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class ProcessedStore:
    """Set of receipt ids already uploaded, persisted to a JSON file."""

    def __init__(self, path: Path):
        self._path = Path(path)
        self._seen: dict[str, str] | None = None

    def _load(self) -> dict[str, str]:
        if self._seen is None:
            try:
                with self._path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                self._seen = data if isinstance(data, dict) else {}
            except (FileNotFoundError, json.JSONDecodeError):
                # Missing or corrupt cache is non-fatal: treat as empty. Strava's
                # external_id guard still prevents any duplicate upload.
                self._seen = {}
        return self._seen

    def contains(self, receipt_id: str) -> bool:
        return receipt_id in self._load()

    def add(self, receipt_id: str) -> None:
        seen = self._load()
        if receipt_id in seen:
            return
        seen[receipt_id] = datetime.now(timezone.utc).isoformat()
        self._write(seen)

    def _write(self, seen: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(seen, fh, indent=0)
        os.replace(tmp, self._path)
