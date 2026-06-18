from citibike2strava import polyline


def test_decode_known_value():
    # Canonical example from Google's polyline algorithm documentation.
    encoded = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    points = polyline.decode(encoded)
    assert points == [
        (38.5, -120.2),
        (40.7, -120.95),
        (43.252, -126.453),
    ]


def test_decode_roundtrip_endpoints():
    # The real receipt polyline; endpoints must match the (clean) coordinates
    # that the corrupted scalar map params only hinted at.
    import urllib.parse

    # The leading vertex of the real receipt's polyline ("endwF|tkbM" once
    # unescaped) decodes to the clean start coordinate that the corrupted
    # origin_lat@.66035 scalar param only hinted at.
    enc = "endwF%7CtkbM"
    pts = polyline.decode(urllib.parse.unquote(enc))
    assert abs(pts[0][0] - 40.66035) < 1e-5
    assert abs(pts[0][1] - -73.95679) < 1e-5
