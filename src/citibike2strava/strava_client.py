"""Strava API client: upload a GPX, wait for processing, set the sport type.

Strava's upload endpoint does not accept ``sport_type`` directly, so we upload
the GPX, poll the upload until it becomes an activity, then PUT the activity to
mark it as an E-Bike Ride and name it. We set ``external_id`` to the Citi Bike
receipt number; Strava rejects a second upload with the same ``external_id`` as
a duplicate, giving us a server-side idempotency guard in addition to the Gmail
label.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests

API_BASE = "https://www.strava.com/api/v3"


@dataclass
class UploadResult:
    activity_id: int
    activity_url: str
    duplicate: bool = False


class StravaError(RuntimeError):
    pass


class DuplicateUpload(StravaError):
    """Raised when Strava reports the receipt was already uploaded."""


class StravaClient:
    def __init__(self, access_token: str):
        self._headers = {"Authorization": f"Bearer {access_token}"}

    def upload_gpx(
        self,
        gpx: str,
        *,
        name: str,
        external_id: str,
        description: str = "",
        poll_timeout: float = 60.0,
    ) -> UploadResult:
        """Upload a GPX string and return the created activity once ready."""
        resp = requests.post(
            f"{API_BASE}/uploads",
            headers=self._headers,
            data={
                "name": name,
                "description": description,
                "data_type": "gpx",
                "external_id": external_id,
            },
            files={"file": (f"{external_id}.gpx", gpx.encode("utf-8"), "application/gpx+xml")},
            timeout=60,
        )
        if resp.status_code == 401:
            raise StravaError("Strava rejected the token (401). Re-run `login`.")
        body = resp.json()
        if body.get("error"):
            if "duplicate" in str(body["error"]).lower():
                raise DuplicateUpload(body["error"])
            raise StravaError(f"Upload error: {body['error']}")

        upload_id = body["id"]
        return self._wait_for_activity(upload_id, poll_timeout)

    def _wait_for_activity(self, upload_id: int, timeout: float) -> UploadResult:
        deadline = time.time() + timeout
        delay = 1.0
        while time.time() < deadline:
            resp = requests.get(
                f"{API_BASE}/uploads/{upload_id}", headers=self._headers, timeout=30
            )
            body = resp.json()
            if body.get("error"):
                if "duplicate" in str(body["error"]).lower():
                    raise DuplicateUpload(body["error"])
                raise StravaError(f"Processing error: {body['error']}")
            activity_id = body.get("activity_id")
            if activity_id:
                return UploadResult(
                    activity_id=activity_id,
                    activity_url=f"https://www.strava.com/activities/{activity_id}",
                )
            time.sleep(delay)
            delay = min(delay * 1.5, 5.0)
        raise StravaError("Timed out waiting for Strava to process the upload")

    def update_activity(
        self, activity_id: int, *, sport_type: str, name: str | None = None
    ) -> None:
        payload: dict = {"sport_type": sport_type}
        if name:
            payload["name"] = name
        resp = requests.put(
            f"{API_BASE}/activities/{activity_id}",
            headers=self._headers,
            data=payload,
            timeout=30,
        )
        resp.raise_for_status()
