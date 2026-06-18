"""Configuration loading and on-disk locations.

Secrets (OAuth client id/secret) are read from environment variables, an
optional ``.env`` file, or an optional ``config.toml`` in the app home dir — in
that order of precedence. We never commit secrets; see ``.env.example`` and
docs/OAUTH_SETUP.md. Each user registers their own Google and Strava OAuth apps,
so no shared credentials ship with the code.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "citibike2strava"

# Gmail query that isolates Citi Bike ride receipts (verified against real mail).
DEFAULT_GMAIL_QUERY = 'from:updates.citibikenyc.com subject:"Ride Receipt"'
# Gmail label applied after a successful upload, for idempotency.
DEFAULT_PROCESSED_LABEL = "citibike2strava/uploaded"
DEFAULT_TIMEZONE = "America/New_York"

# Minimal scopes. gmail.modify is required to add the "uploaded" label;
# without labelling we could not reliably avoid re-uploading. Strava needs
# activity:write to create the activity and read to confirm/update it.
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
STRAVA_SCOPES = ["activity:write", "read"]


def default_home() -> Path:
    """App home dir: $CITIBIKE2STRAVA_HOME or ~/.config/citibike2strava."""
    env = os.environ.get("CITIBIKE2STRAVA_HOME")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / APP_NAME


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader (no dependency). Existing env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass
class Config:
    home: Path
    google_client_id: str | None
    google_client_secret: str | None
    strava_client_id: str | None
    strava_client_secret: str | None
    gmail_query: str = DEFAULT_GMAIL_QUERY
    processed_label: str = DEFAULT_PROCESSED_LABEL
    timezone: str = DEFAULT_TIMEZONE

    @property
    def tokens_dir(self) -> Path:
        return self.home / "tokens"

    def require_google(self) -> tuple[str, str]:
        if not self.google_client_id or not self.google_client_secret:
            raise ConfigError(
                "Missing Google OAuth credentials. Set GOOGLE_CLIENT_ID and "
                "GOOGLE_CLIENT_SECRET (see docs/OAUTH_SETUP.md)."
            )
        return self.google_client_id, self.google_client_secret

    def require_strava(self) -> tuple[str, str]:
        if not self.strava_client_id or not self.strava_client_secret:
            raise ConfigError(
                "Missing Strava OAuth credentials. Set STRAVA_CLIENT_ID and "
                "STRAVA_CLIENT_SECRET (see docs/OAUTH_SETUP.md)."
            )
        return self.strava_client_id, self.strava_client_secret


class ConfigError(RuntimeError):
    pass


def load_config(home: Path | None = None) -> Config:
    home = home or default_home()
    _load_dotenv(Path.cwd() / ".env")
    _load_dotenv(home / ".env")

    file_cfg: dict = {}
    cfg_path = home / "config.toml"
    if cfg_path.exists():
        with cfg_path.open("rb") as fh:
            file_cfg = tomllib.load(fh)

    def pick(env_key: str, toml_section: str, toml_key: str, default=None):
        if env_key in os.environ:
            return os.environ[env_key]
        return file_cfg.get(toml_section, {}).get(toml_key, default)

    return Config(
        home=home,
        google_client_id=pick("GOOGLE_CLIENT_ID", "google", "client_id"),
        google_client_secret=pick("GOOGLE_CLIENT_SECRET", "google", "client_secret"),
        strava_client_id=pick("STRAVA_CLIENT_ID", "strava", "client_id"),
        strava_client_secret=pick("STRAVA_CLIENT_SECRET", "strava", "client_secret"),
        gmail_query=pick("CITIBIKE2STRAVA_GMAIL_QUERY", "gmail", "query", DEFAULT_GMAIL_QUERY),
        processed_label=pick("CITIBIKE2STRAVA_LABEL", "gmail", "processed_label", DEFAULT_PROCESSED_LABEL),
        timezone=pick("CITIBIKE2STRAVA_TZ", "general", "timezone", DEFAULT_TIMEZONE),
    )
