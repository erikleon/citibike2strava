"""Core data models for a parsed Citi Bike ride.

These types are deliberately free of any I/O, auth, or network concern so that
the same objects can be produced by the CLI today and by a hosted multi-user
service later (see docs/ARCHITECTURE.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class TrackPoint:
    """A single GPS sample along the route.

    ``time`` is timezone-aware UTC. It is interpolated (see ``gpx.py``) because
    Citi Bike receipts only give an overall start and end time, not per-point
    timing.
    """

    lat: float
    lon: float
    time: datetime  # timezone-aware, UTC


@dataclass(frozen=True)
class Ride:
    """A fully parsed ride, ready to be turned into a GPX file.

    All times are timezone-aware. ``start_time`` / ``end_time`` are converted to
    UTC by the parser. ``points`` are ordered start -> end.
    """

    receipt_id: str
    start_station: str
    end_station: str
    start_time: datetime  # timezone-aware, UTC
    end_time: datetime  # timezone-aware, UTC
    points: list[tuple[float, float]]  # (lat, lon) from the decoded polyline
    is_ebike: bool = True
    source_message_id: str | None = None
    raw_line_item: str | None = None

    @property
    def duration_seconds(self) -> float:
        return (self.end_time - self.start_time).total_seconds()

    @property
    def sport_type(self) -> str:
        """Strava ``sport_type`` value."""
        return "EBikeRide" if self.is_ebike else "Ride"

    @property
    def activity_name(self) -> str:
        return f"{self.start_station} → {self.end_station}"
