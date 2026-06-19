from unittest import mock

import pytest

from citibike2strava.strava_client import (
    RateLimitError,
    StravaClient,
    _SlidingWindowLimiter,
)


class FakeResp:
    def __init__(self, status_code=200, json_data=None, headers=None):
        self.status_code = status_code
        self._json = json_data or {}
        self.headers = headers or {}

    def json(self):
        return self._json


# -- sliding-window limiter -------------------------------------------------

def _stepping_clock(seq):
    """Clock that advances through ``seq`` then holds at the last value."""
    it = iter(seq)
    last = [0.0]

    def clock():
        try:
            last[0] = next(it)
        except StopIteration:
            pass
        return last[0]

    return clock


def test_limiter_does_not_sleep_under_limit():
    sleeps = []
    lim = _SlidingWindowLimiter(
        3, 100.0, clock=_stepping_clock([0.0, 1.0, 2.0, 3.0]), sleeper=sleeps.append
    )
    lim.acquire()
    lim.acquire()
    assert sleeps == []


def test_limiter_sleeps_when_window_full():
    sleeps = []
    # First two stamps land at t=0; the third request happens at t=1, so it must
    # wait out the remaining ~99s of the 100s window from the oldest stamp.
    lim = _SlidingWindowLimiter(
        2, 100.0, clock=_stepping_clock([0.0, 0.0, 0.0, 0.0, 1.0]),
        sleeper=sleeps.append,
    )
    lim.acquire()  # stamp at 0.0
    lim.acquire()  # stamp at 0.0
    lim.acquire()  # window full at t=1.0 -> sleep ~99s
    assert sleeps and sleeps[0] == pytest.approx(99.0)


# -- 429 retry --------------------------------------------------------------

def _client(sleeps):
    return StravaClient(
        "tok", sleeper=sleeps.append, clock=lambda: 0.0, max_retries=2
    )


def test_upload_retries_then_succeeds_honouring_retry_after():
    sleeps = []
    client = _client(sleeps)
    responses = [
        FakeResp(429, headers={"Retry-After": "7"}),          # POST upload -> 429
        FakeResp(200, {"id": 99}),                            # POST upload retry
        FakeResp(200, {"activity_id": 555}),                  # GET poll
    ]
    with mock.patch(
        "citibike2strava.strava_client.requests.request",
        side_effect=responses,
    ):
        result = client.upload_gpx("<gpx/>", name="n", external_id="e")
    assert result.activity_id == 555
    assert sleeps == [7.0]  # honoured Retry-After, not exponential backoff


def test_upload_raises_rate_limit_after_exhausting_retries():
    sleeps = []
    client = _client(sleeps)
    with mock.patch(
        "citibike2strava.strava_client.requests.request",
        return_value=FakeResp(429, headers={"Retry-After": "1"}),
    ):
        with pytest.raises(RateLimitError):
            client.upload_gpx("<gpx/>", name="n", external_id="e")
    # max_retries=2 -> two backoff sleeps before giving up on the third attempt.
    assert len(sleeps) == 2
