"""Build a GPX 1.1 track from a :class:`Ride`.

Two correctness details that were real bugs during prototyping:

* **XML escaping.** Station names contain ``&`` (e.g. "Bedford Ave & Maple St").
  We build the document with :mod:`xml.etree.ElementTree`, which escapes text and
  attributes automatically, so the ``&`` becomes ``&amp;`` and the file parses.
* **Per-point time.** Receipts only give an overall start/end time, so we
  interpolate each point's timestamp proportional to its cumulative distance
  along the route (constant-speed assumption). Total distance and elapsed time
  are therefore exact; only the intermediate speed profile is smoothed.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import timedelta

from .geo import cumulative_distances_m
from .models import Ride

GPX_NS = "http://www.topografix.com/GPX/1/1"
_ISO_UTC = "%Y-%m-%dT%H:%M:%SZ"


def interpolated_times(ride: Ride) -> list:
    """UTC timestamp for each point, spaced by cumulative distance fraction."""
    cum = cumulative_distances_m(ride.points)
    total = cum[-1]
    duration = ride.duration_seconds
    if total <= 0:
        # Degenerate route (all points identical): spread evenly over time.
        n = len(ride.points)
        return [
            ride.start_time + timedelta(seconds=duration * i / max(n - 1, 1))
            for i in range(n)
        ]
    return [ride.start_time + timedelta(seconds=duration * (d / total)) for d in cum]


def build_gpx(ride: Ride, *, creator: str = "citibike2strava") -> str:
    """Return a GPX 1.1 document (as a string) for ``ride``."""
    times = interpolated_times(ride)

    gpx = ET.Element(
        "gpx",
        {
            "version": "1.1",
            "creator": creator,
            "xmlns": GPX_NS,
        },
    )

    metadata = ET.SubElement(gpx, "metadata")
    ET.SubElement(metadata, "time").text = ride.start_time.strftime(_ISO_UTC)

    trk = ET.SubElement(gpx, "trk")
    # ET escapes this automatically -> "&" becomes "&amp;".
    ET.SubElement(trk, "name").text = ride.activity_name
    ET.SubElement(trk, "type").text = ride.sport_type

    trkseg = ET.SubElement(trk, "trkseg")
    for (lat, lon), t in zip(ride.points, times):
        trkpt = ET.SubElement(
            trkseg, "trkpt", {"lat": f"{lat:.6f}", "lon": f"{lon:.6f}"}
        )
        ET.SubElement(trkpt, "time").text = t.strftime(_ISO_UTC)

    ET.indent(gpx, space="  ")
    body = ET.tostring(gpx, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"
