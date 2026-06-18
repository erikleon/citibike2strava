"""Geographic helpers: haversine distance and cumulative path distances."""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_000.0
METERS_PER_MILE = 1609.344


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in meters between two ``(lat, lon)`` points."""
    lat1, lon1 = a
    lat2, lon2 = b
    p = math.pi / 180.0
    dlat = (lat2 - lat1) * p
    dlon = (lon2 - lon1) * p
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def cumulative_distances_m(points: list[tuple[float, float]]) -> list[float]:
    """Cumulative distance in meters at each point (first element is 0.0)."""
    cum = [0.0]
    for i in range(1, len(points)):
        cum.append(cum[-1] + haversine_m(points[i - 1], points[i]))
    return cum


def total_distance_m(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    return cumulative_distances_m(points)[-1]
