from datetime import timedelta
from pathlib import Path

import pytest

from citibike2strava.receipt import ReceiptParseError, parse_receipt

FIXTURE = Path(__file__).parent / "fixtures" / "sample_receipt.html"


@pytest.fixture
def html():
    return FIXTURE.read_text(encoding="utf-8")


def test_parses_stations_with_ampersand(html):
    ride = parse_receipt(html)
    assert ride.start_station == "Bedford Ave & Maple St"
    assert ride.end_station == "Myrtle Ave & Lewis Ave"


def test_times_converted_to_utc(html):
    ride = parse_receipt(html)
    # 6:59pm EDT (UTC-4) on 2026-06-17 -> 22:59 UTC.
    assert ride.start_time.utcoffset() == timedelta(0)
    assert (ride.start_time.hour, ride.start_time.minute) == (22, 59)
    assert (ride.end_time.hour, ride.end_time.minute) == (23, 18)
    assert ride.duration_seconds == 19 * 60


def test_receipt_id_and_ebike(html):
    ride = parse_receipt(html)
    assert ride.receipt_id == "1234567890123456789"
    assert ride.is_ebike is True
    assert ride.sport_type == "EBikeRide"


def test_polyline_endpoints_trusted_over_corrupted_scalars(html):
    ride = parse_receipt(html)
    # Decoded polyline start, not the mangled origin_lat@.66035 scalar.
    assert abs(ride.points[0][0] - 40.66035) < 1e-5
    assert abs(ride.points[0][1] - -73.95679) < 1e-5
    assert len(ride.points) > 100


def test_missing_polyline_raises():
    with pytest.raises(ReceiptParseError):
        parse_receipt("<html><body>Receipt # 1 Start End</body></html>")
