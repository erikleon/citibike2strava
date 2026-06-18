"""Local one-click backend for the browser extension.

A tiny stdlib HTTP server, bound to loopback only, that exposes a single
endpoint wrapping :meth:`Pipeline.process_message`. A Gmail content script can
``POST /api/rides/upload {"message_id": "..."}`` to upload the currently open
receipt with one click.

Security posture (see docs/SECURITY.md):

* Binds to ``127.0.0.1`` exclusively — never reachable off the machine.
* Requires a bearer token (``X-Auth-Token``) that is generated locally and
  shared only with the extension; compared with ``hmac.compare_digest``.
* CORS is restricted to ``https://mail.google.com``.
* The ``message_id`` from the client is untrusted: the backend re-fetches and
  re-parses the receipt itself and never trusts client-supplied ride data.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from .auth import DEFAULT_USER, FileTokenStore
from .config import Config
from .pipeline import Pipeline, RideResult

ALLOWED_ORIGIN = "https://mail.google.com"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8722

# Type of the injected worker: a Gmail message id -> RideResult.
Processor = Callable[[str], RideResult]


def load_or_create_token(config: Config) -> str:
    """Return the local API token, generating and persisting it on first use."""
    path = config.home / "server_token"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    # Create the file with 0600 from the start, never world-readable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token)
    return token


def make_handler(token: str, process: Processor):
    """Build a request handler bound to ``token`` and a ``process`` callable."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "citibike2strava/0.1"

        # -- helpers ----------------------------------------------------
        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers", "Content-Type, X-Auth-Token"
            )

        def _json(self, status: int, body: dict) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self._cors()
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _authorized(self) -> bool:
            supplied = self.headers.get("X-Auth-Token", "")
            return hmac.compare_digest(supplied, token)

        # -- routes -----------------------------------------------------
        def do_OPTIONS(self):  # noqa: N802 (CORS preflight)
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):  # noqa: N802
            if self.path == "/health":
                self._json(200, {"status": "ok"})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path != "/api/rides/upload":
                self._json(404, {"error": "not found"})
                return
            if not self._authorized():
                self._json(401, {"error": "invalid or missing X-Auth-Token"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(length) or b"{}")
                message_id = data.get("message_id")
            except (ValueError, json.JSONDecodeError):
                self._json(400, {"error": "invalid JSON body"})
                return
            if not message_id or not isinstance(message_id, str):
                self._json(400, {"error": "message_id is required"})
                return

            try:
                result = process(message_id)
            except Exception as exc:  # surface as JSON, don't leak a stack trace
                self._json(500, {"status": "error", "detail": str(exc)})
                return

            status = 200 if result.status in ("uploaded", "duplicate") else 422
            self._json(status, _result_to_dict(result))

        def log_message(self, *args):  # quiet by default
            pass

    return Handler


def _result_to_dict(r: RideResult) -> dict:
    return {
        "status": r.status,
        "receipt_id": r.receipt_id,
        "activity_url": r.activity_url,
        "distance_mi": r.distance_mi,
        "detail": r.detail,
    }


def build_server(
    token: str,
    process: Processor,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> ThreadingHTTPServer:
    """Construct (but do not start) the loopback server. Useful for tests."""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Refusing to bind the one-click server to a non-loopback host")
    return ThreadingHTTPServer((host, port), make_handler(token, process))


def serve(
    config: Config,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    user_id: str = DEFAULT_USER,
) -> None:
    """Run the local one-click backend until interrupted."""
    store = FileTokenStore(config.tokens_dir)
    pipeline = Pipeline(config, store, user_id=user_id)
    token = load_or_create_token(config)

    httpd = build_server(token, pipeline.process_message, host=host, port=port)
    print(f"citibike2strava one-click backend on http://{host}:{port}")
    print(f"  Auth token (configure this in the extension): {token}")
    print(f"  Token file: {config.home / 'server_token'}")
    print("  Press Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        httpd.server_close()


__all__ = ["serve", "build_server", "make_handler", "load_or_create_token"]
