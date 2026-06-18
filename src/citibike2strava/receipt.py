"""Parse a Citi Bike "Ride Receipt" email (Lyft make_email template) into a Ride.

The parser is intentionally defensive: it locates fields by their stable
structural markers ("Start" / "End" labels, the ``polyline=`` map param, the
``Receipt #`` line) rather than by absolute position, so minor template tweaks
don't silently break it. Every failure raises :class:`ReceiptParseError` with a
human-readable reason instead of returning half-populated data.
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from . import polyline as polyline_codec
from .models import Ride

# Citi Bike is an NYC system; receipts print wall-clock local time with no zone.
# Configurable for the other Lyft-operated bikeshares (Divvy, Bay Wheels, ...).
DEFAULT_TIMEZONE = "America/New_York"

_DATE_RE = re.compile(r"([A-Za-z]+ \d{1,2}, \d{4})")
_TIME_RE = re.compile(r"(\d{1,2}:\d{2}\s*[apAP][mM])")
_RECEIPT_RE = re.compile(r"Receipt\s*#\s*([0-9]+)")
# e.g. "Ebike ride ($0.27 per min for 20 min)" / "Classic ride (...)"
_LINE_ITEM_RE = re.compile(
    r"((?:Ebike|Electric|Classic|Bike)\s+ride[^)]*\))", re.IGNORECASE
)
_EBIKE_RE = re.compile(r"\b(e-?bike|electric)\b", re.IGNORECASE)


class ReceiptParseError(ValueError):
    """Raised when a receipt cannot be parsed into a complete :class:`Ride`."""


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parse_time(time_str: str) -> datetime:
    """Parse '6:59 pm' into a naive datetime carrying only hour/minute."""
    return datetime.strptime(time_str.strip().upper().replace(" ", ""), "%I:%M%p")


def _extract_station_and_time(soup: BeautifulSoup, label: str) -> tuple[str, str]:
    """Find the station name and time for the 'Start' or 'End' marker.

    Template layout (per row): ``<td>station</td><td><span>Start</span><br>time</td>``.
    We anchor on the label span and read the station from the preceding cell.
    """
    span = soup.find("span", string=lambda s: s and s.strip() == label)
    if span is None:
        raise ReceiptParseError(f"Could not find '{label}' marker in receipt")

    time_cell = span.find_parent("td")
    station_cell = time_cell.find_previous_sibling("td") if time_cell else None
    if time_cell is None or station_cell is None:
        raise ReceiptParseError(f"Malformed '{label}' row in receipt")

    station = _clean(station_cell.get_text(" ", strip=True))
    # The cell holds "Start" + <br> + the time; pull the time token out.
    time_match = _TIME_RE.search(time_cell.get_text(" ", strip=True))
    if not station or not time_match:
        raise ReceiptParseError(f"Missing station or time for '{label}'")
    return station, time_match.group(1)


def _extract_polyline_points(html: str) -> list[tuple[float, float]]:
    # Require it to be a real query parameter (preceded by ? or & / &amp;) so we
    # don't accidentally match the word "polyline" elsewhere in the document.
    match = re.search(r"[?&](?:amp;)?polyline=([^\"'&\s<>]+)", html)
    if not match:
        raise ReceiptParseError("No polyline found in static-map URL")
    decoded = urllib.parse.unquote(match.group(1))
    points = polyline_codec.decode(decoded, precision=5)
    if len(points) < 2:
        raise ReceiptParseError("Polyline decoded to fewer than 2 points")
    return points


def parse_receipt(
    html: str,
    *,
    message_id: str | None = None,
    timezone: str = DEFAULT_TIMEZONE,
) -> Ride:
    """Parse receipt ``html`` into a :class:`Ride` with UTC timestamps."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    tz = ZoneInfo(timezone)

    # Date of the ride (first "Month DD, YYYY" in the body).
    date_match = _DATE_RE.search(text)
    if not date_match:
        raise ReceiptParseError("Could not find ride date in receipt")
    ride_date = datetime.strptime(date_match.group(1).title(), "%B %d, %Y").date()

    start_station, start_time_str = _extract_station_and_time(soup, "Start")
    end_station, end_time_str = _extract_station_and_time(soup, "End")

    start_local = _parse_time(start_time_str).time()
    end_local = _parse_time(end_time_str).time()

    start_dt = datetime.combine(ride_date, start_local, tzinfo=tz)
    end_dt = datetime.combine(ride_date, end_local, tzinfo=tz)
    # Ride crossing midnight: end is on the next calendar day.
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    receipt_match = _RECEIPT_RE.search(text)
    if not receipt_match:
        raise ReceiptParseError("Could not find 'Receipt #' in receipt")
    receipt_id = receipt_match.group(1)

    line_item_match = _LINE_ITEM_RE.search(text)
    line_item = _clean(line_item_match.group(1)) if line_item_match else None
    is_ebike = bool(line_item and _EBIKE_RE.search(line_item))

    points = _extract_polyline_points(html)

    return Ride(
        receipt_id=receipt_id,
        start_station=start_station,
        end_station=end_station,
        start_time=start_dt.astimezone(ZoneInfo("UTC")),
        end_time=end_dt.astimezone(ZoneInfo("UTC")),
        points=points,
        is_ebike=is_ebike,
        source_message_id=message_id,
        raw_line_item=line_item,
    )
