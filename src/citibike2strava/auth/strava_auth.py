"""Strava OAuth (authorization-code flow with a localhost redirect).

Strava has no official Python SDK for auth, so we implement the small flow by
hand: open the consent URL in the user's browser, catch the redirect on a
loopback HTTP server, exchange the code for tokens, and persist them via the
:class:`TokenStore`. Access tokens are short-lived (~6h); we refresh
automatically using the stored refresh token.
"""

from __future__ import annotations

import http.server
import secrets
import threading
import time
import urllib.parse
import webbrowser

import requests

from ..config import STRAVA_SCOPES, Config
from .token_store import DEFAULT_USER, TokenStore

PROVIDER = "strava"
AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
# Strava only allows a single registered callback domain; localhost is standard
# for desktop apps. The port is fixed so it can match the app's "Authorization
# Callback Domain" = localhost.
REDIRECT_HOST = "localhost"
REDIRECT_PORT = 8721
REDIRECT_URI = f"http://{REDIRECT_HOST}:{REDIRECT_PORT}/callback"


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    code: str | None = None
    state: str | None = None
    error: str | None = None

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.code = (params.get("code") or [None])[0]
        _CallbackHandler.state = (params.get("state") or [None])[0]
        _CallbackHandler.error = (params.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h2>citibike2strava</h2>"
            b"<p>Authorization received. You can close this tab.</p></body></html>"
        )

    def log_message(self, *args):  # silence the default stderr logging
        pass


def _exchange(client_id: str, client_secret: str, payload: dict) -> dict:
    resp = requests.post(TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        **payload,
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()


def authorize(
    config: Config, store: TokenStore, user_id: str = DEFAULT_USER
) -> dict:
    """Run the interactive Strava consent flow and persist the tokens."""
    client_id, client_secret = config.require_strava()
    state = secrets.token_urlsafe(16)
    query = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": ",".join(STRAVA_SCOPES),
        "state": state,
    })
    auth_url = f"{AUTHORIZE_URL}?{query}"

    server = http.server.HTTPServer((REDIRECT_HOST, REDIRECT_PORT), _CallbackHandler)
    _CallbackHandler.code = None
    _CallbackHandler.state = None
    _CallbackHandler.error = None
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    print(f"Opening browser to authorize Strava:\n  {auth_url}")
    webbrowser.open(auth_url)
    thread.join(timeout=300)
    server.server_close()

    if _CallbackHandler.error:
        raise StravaAuthError(f"Strava authorization failed: {_CallbackHandler.error}")
    if not _CallbackHandler.code:
        raise StravaAuthError("Timed out waiting for Strava authorization")
    # CSRF protection: the redirect must echo back the exact state we sent.
    if _CallbackHandler.state != state:
        raise StravaAuthError("State mismatch on Strava callback (possible CSRF)")

    token = _exchange(client_id, client_secret, {
        "code": _CallbackHandler.code,
        "grant_type": "authorization_code",
    })
    store.save(PROVIDER, token, user_id)
    return token


def get_access_token(
    config: Config, store: TokenStore, user_id: str = DEFAULT_USER
) -> str:
    """Return a valid access token, refreshing it if it has expired."""
    data = store.load(PROVIDER, user_id)
    if not data:
        raise NotAuthorizedError(
            "Strava is not authorized yet. Run `citibike2strava login` first."
        )
    # Refresh a minute early to avoid edge-of-expiry failures.
    if data.get("expires_at", 0) <= time.time() + 60:
        client_id, client_secret = config.require_strava()
        data = _exchange(client_id, client_secret, {
            "grant_type": "refresh_token",
            "refresh_token": data["refresh_token"],
        })
        store.save(PROVIDER, data, user_id)
    return data["access_token"]


class StravaAuthError(RuntimeError):
    pass


class NotAuthorizedError(RuntimeError):
    pass
