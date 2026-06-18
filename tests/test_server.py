import json
import threading
import urllib.error
import urllib.request

import pytest

from citibike2strava.pipeline import RideResult
from citibike2strava.server import build_server

TOKEN = "test-token-123"


def _processor(message_id: str) -> RideResult:
    return RideResult(
        message_id,
        "uploaded",
        receipt_id="42",
        activity_url="https://www.strava.com/activities/42",
        distance_mi=3.39,
        detail="A & B → C & D",
    )


@pytest.fixture
def server():
    httpd = build_server(TOKEN, _processor, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


def _post(base, body, headers=None):
    req = urllib.request.Request(
        f"{base}/api/rides/upload",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_refuses_non_loopback_bind():
    with pytest.raises(ValueError):
        build_server(TOKEN, _processor, host="0.0.0.0")


def test_health(server):
    with urllib.request.urlopen(f"{server}/health") as resp:
        assert json.loads(resp.read())["status"] == "ok"


def test_upload_requires_token(server):
    status, body = _post(server, {"message_id": "abc"})
    assert status == 401
    assert "error" in body


def test_upload_with_token(server):
    status, body = _post(server, {"message_id": "abc"}, {"X-Auth-Token": TOKEN})
    assert status == 200
    assert body["status"] == "uploaded"
    assert body["activity_url"].endswith("/42")


def test_missing_message_id(server):
    status, body = _post(server, {}, {"X-Auth-Token": TOKEN})
    assert status == 400


def test_cors_preflight(server):
    req = urllib.request.Request(
        f"{server}/api/rides/upload", method="OPTIONS"
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 204
        assert resp.headers["Access-Control-Allow-Origin"] == "https://mail.google.com"
