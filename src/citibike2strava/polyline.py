"""Google Encoded Polyline Algorithm decoder (precision 5).

Self-contained, no third-party dependency, so it is easy to audit and to reuse
in other environments. Reference:
https://developers.google.com/maps/documentation/utilities/polylinealgorithm

Why we rely on the polyline and not the static-map's scalar lat/lng params:
the Gmail API mangles some high-bit bytes in the static-map URL, corrupting the
``origin_lat`` / ``dest_lng`` query params (e.g. ``origin_lat@.66035``). The
``polyline=`` value is pure ASCII percent-escapes and survives intact, so the
first and last decoded points are the trustworthy ride endpoints.
"""

from __future__ import annotations


def decode(encoded: str, precision: int = 5) -> list[tuple[float, float]]:
    """Decode an encoded polyline string into a list of ``(lat, lon)`` tuples.

    ``encoded`` must already be percent-unescaped (use ``urllib.parse.unquote``
    on the value taken straight from the email's ``polyline=`` query param).
    """
    coordinates: list[tuple[float, float]] = []
    index = 0
    lat = 0
    lng = 0
    factor = 10**precision
    length = len(encoded)

    while index < length:
        for is_longitude in (False, True):
            shift = 0
            result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if (result & 1) else (result >> 1)
            if is_longitude:
                lng += delta
            else:
                lat += delta
        coordinates.append((lat / factor, lng / factor))

    return coordinates
