from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.dom import minidom

from citibike2strava.gpx import build_gpx, interpolated_times
from citibike2strava.models import Ride
from citibike2strava.receipt import parse_receipt

FIXTURE = Path(__file__).parent / "fixtures" / "sample_receipt.html"


def _ride(points=None):
    start = datetime(2026, 6, 17, 22, 59, tzinfo=timezone.utc)
    return Ride(
        receipt_id="1",
        start_station="A & B",
        end_station="C & D",
        start_time=start,
        end_time=start + timedelta(minutes=19),
        points=points or [(40.0, -73.0), (40.01, -73.01), (40.02, -73.0)],
    )


def test_gpx_is_valid_xml_with_escaped_ampersand():
    gpx = build_gpx(_ride())
    # Must parse — the unescaped "&" bug produced invalid XML here.
    dom = minidom.parseString(gpx)
    name = dom.getElementsByTagName("name")[0].firstChild.data
    assert name == "A & B → C & D"
    assert "&amp;" in gpx


def test_interpolated_times_monotonic_within_window():
    ride = _ride()
    times = interpolated_times(ride)
    assert times[0] == ride.start_time
    assert times[-1] == ride.end_time
    assert all(times[i] <= times[i + 1] for i in range(len(times) - 1))


def test_real_fixture_builds_valid_gpx():
    ride = parse_receipt(FIXTURE.read_text(encoding="utf-8"))
    gpx = build_gpx(ride)
    dom = minidom.parseString(gpx)
    pts = dom.getElementsByTagName("trkpt")
    assert len(pts) == len(ride.points)
    assert dom.getElementsByTagName("type")[0].firstChild.data == "EBikeRide"
