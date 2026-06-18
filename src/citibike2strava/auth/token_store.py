"""Pluggable token storage.

This is the single seam that lets the same core run both as a local CLI and as
a hosted multi-user service:

* The CLI uses :class:`FileTokenStore`, which writes one JSON file per provider
  under a per-user directory with ``0600`` permissions. Tokens never leave the
  machine.
* A hosted deployment would implement :class:`TokenStore` against an encrypted
  database keyed by ``user_id`` (e.g. envelope-encrypted with a KMS key). No
  other module needs to change — :mod:`pipeline`, :mod:`gmail_client`, and
  :mod:`strava_client` only ever see the abstract interface.

Tokens are secrets. Treat anything returned here as sensitive: never log it.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path

DEFAULT_USER = "default"


class TokenStore(ABC):
    """Persists and retrieves per-user, per-provider OAuth token bundles."""

    @abstractmethod
    def load(self, provider: str, user_id: str = DEFAULT_USER) -> dict | None:
        """Return the stored token bundle, or ``None`` if not authorized yet."""

    @abstractmethod
    def save(self, provider: str, data: dict, user_id: str = DEFAULT_USER) -> None:
        """Persist a token bundle for ``provider``/``user_id``."""

    @abstractmethod
    def delete(self, provider: str, user_id: str = DEFAULT_USER) -> None:
        """Remove stored tokens (used by ``logout``)."""


class FileTokenStore(TokenStore):
    """Stores tokens as ``<base>/<user_id>/<provider>.json`` with 0600 perms."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    def _path(self, provider: str, user_id: str) -> Path:
        return self.base_dir / user_id / f"{provider}.json"

    def load(self, provider: str, user_id: str = DEFAULT_USER) -> dict | None:
        path = self._path(provider, user_id)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def save(self, provider: str, data: dict, user_id: str = DEFAULT_USER) -> None:
        path = self._path(provider, user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Restrict the directory too, in case it was just created.
        os.chmod(path.parent, 0o700)
        # Write atomically, then lock down permissions before it holds secrets.
        tmp = path.with_suffix(".json.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
        os.chmod(path, 0o600)

    def delete(self, provider: str, user_id: str = DEFAULT_USER) -> None:
        path = self._path(provider, user_id)
        if path.exists():
            path.unlink()
