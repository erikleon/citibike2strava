"""Google (Gmail) OAuth using the installed-app loopback flow.

Credentials are persisted via a :class:`TokenStore`, so a hosted deployment can
swap file storage for an encrypted DB without touching this module. The consent
screen runs in the user's own browser against the user's own OAuth client; we
only ever see the resulting refresh token.
"""

from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from ..config import GOOGLE_SCOPES, Config
from .token_store import DEFAULT_USER, TokenStore

PROVIDER = "google"


def _client_config(client_id: str, client_secret: str) -> dict:
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def _to_dict(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or GOOGLE_SCOPES),
    }


def authorize(
    config: Config, store: TokenStore, user_id: str = DEFAULT_USER
) -> Credentials:
    """Run the interactive consent flow and persist the resulting tokens."""
    client_id, client_secret = config.require_google()
    flow = InstalledAppFlow.from_client_config(
        _client_config(client_id, client_secret), scopes=GOOGLE_SCOPES
    )
    creds = flow.run_local_server(port=0, prompt="consent")
    store.save(PROVIDER, _to_dict(creds), user_id)
    return creds


def get_credentials(
    config: Config, store: TokenStore, user_id: str = DEFAULT_USER
) -> Credentials:
    """Return valid credentials, refreshing if needed. Raises if not authorized."""
    data = store.load(PROVIDER, user_id)
    if not data:
        raise NotAuthorizedError(
            "Gmail is not authorized yet. Run `citibike2strava login` first."
        )
    creds = Credentials.from_authorized_user_info(data, scopes=GOOGLE_SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        store.save(PROVIDER, _to_dict(creds), user_id)
    return creds


class NotAuthorizedError(RuntimeError):
    pass
