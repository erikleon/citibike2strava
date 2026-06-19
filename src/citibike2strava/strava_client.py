"""Strava API client: upload a GPX, wait for processing, set the sport type.

Strava's upload endpoint does not accept ``sport_type`` directly, so we upload
the GPX, poll the upload until it becomes an activity, then PUT the activity to
mark it as an E-Bike Ride and name it. We set ``external_id`` to the Citi Bike
receipt number; Strava rejects a second upload with the same ``external_id`` as
a duplicate, giving us a server-side idempotency guard in addition to the Gmail
label.

**Rate-limit resilience.** Bulk backfill of a long ride history can exceed
Strava's per-application limits (200 requests / 15 min by default). Every request
goes through :meth:`StravaClient._request`, which (a) paces requests with a
client-side sliding-window limiter to stay under the cap, and (b) on a ``429``
honours ``Retry-After`` (falling back to exponential backoff) and retries. The
clock and sleeper are injectable so this is testable without real waiting.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

import requests

API_BASE = "https://www.strava.com/api/v3"

# Strava's default per-app limit is 200 requests / 15 min. We pace a little under
# it so concurrent manual use does not tip us over during a long backfill.
DEFAULT_RATE_LIMIT = 190
DEFAULT_RATE_WINDOW_S = 15 * 60


@dataclass
class UploadResult:
    activity_id: int
    activity_url: str
    duplicate: bool = False


class StravaError(RuntimeError):
    pass


class DuplicateUpload(StravaError):
    """Raised when Strava reports the receipt was already uploaded."""


class RateLimitError(StravaError):
    """Raised when Strava keeps returning 429 after exhausting retries."""


class _SlidingWindowLimiter:
    """Paces calls to at most ``max_requests`` within ``window_s`` seconds.

    A sliding window of recent request timestamps; when full, :meth:`acquire`
    sleeps until the oldest timestamp ages out. ``clock`` and ``sleeper`` are
    injected so tests can drive it deterministically.
    """

    def __init__(
        self,
        max_requests: int,
        window_s: float,
        *,
        clock: Callable[[], float],
        sleeper: Callable[[float], None],
    ):
        self._max = max_requests
        self._window = window_s
        self._clock = clock
        self._sleep = sleeper
        self._stamps: deque[float] = deque()

    def _evict(self, now: float) -> None:
        while self._stamps and now - self._stamps[0] >= self._window:
            self._stamps.popleft()

    def acquire(self) -> None:
        now = self._clock()
        self._evict(now)
        if len(self._stamps) >= self._max:
            wait = self._window - (now - self._stamps[0])
            if wait > 0:
                self._sleep(wait)
            self._evict(self._clock())
        self._stamps.append(self._clock())


class StravaClient:
    def __init__(
        self,
        access_token: str,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        max_retries: int = 5,
        base_backoff_s: float = 30.0,
        max_backoff_s: float = DEFAULT_RATE_WINDOW_S,
        rate_limit: int = DEFAULT_RATE_LIMIT,
        rate_window_s: float = DEFAULT_RATE_WINDOW_S,
    ):
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._sleep = sleeper
        self._max_retries = max_retries
        self._base_backoff = base_backoff_s
        self._max_backoff = max_backoff_s
        self._limiter = _SlidingWindowLimiter(
            rate_limit, rate_window_s, clock=clock, sleeper=sleeper
        )

    # -- request plumbing (throttle + 429 retry) ------------------------
    def _retry_after(self, resp: requests.Response, attempt: int) -> float:
        header = resp.headers.get("Retry-After")
        if header and header.strip().isdigit():
            return min(float(header), self._max_backoff)
        return min(self._base_backoff * (2 ** attempt), self._max_backoff)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", 60)
        for attempt in range(self._max_retries + 1):
            self._limiter.acquire()
            resp = requests.request(method, url, headers=self._headers, **kwargs)
            if resp.status_code != 429:
                return resp
            if attempt >= self._max_retries:
                raise RateLimitError(
                    "Strava rate limit (429) persisted after "
                    f"{self._max_retries} retries"
                )
            self._sleep(self._retry_after(resp, attempt))
        raise RateLimitError("Strava rate limit retry loop exhausted")

    # -- API methods ----------------------------------------------------
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
        resp = self._request(
            "POST",
            f"{API_BASE}/uploads",
            data={
                "name": name,
                "description": description,
                "data_type": "gpx",
                "external_id": external_id,
            },
            files={
                "file": (f"{external_id}.gpx", gpx.encode("utf-8"), "application/gpx+xml")
            },
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
            resp = self._request("GET", f"{API_BASE}/uploads/{upload_id}")
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
        resp = self._request(
            "PUT", f"{API_BASE}/activities/{activity_id}", data=payload
        )
        resp.raise_for_status()
