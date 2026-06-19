from datetime import date

from citibike2strava.config import Config
from citibike2strava.gmail_client import build_unprocessed_query


def _config(**kw):
    base = dict(
        home=None,
        google_client_id=None,
        google_client_secret=None,
        strava_client_id=None,
        strava_client_secret=None,
    )
    base.update(kw)
    return Config(**base)


def test_excludes_processed_label():
    q = build_unprocessed_query(_config())
    assert '-label:"citibike2strava/uploaded"' in q


def test_empty_label_omits_exclusion():
    q = build_unprocessed_query(_config(processed_label=""))
    assert "-label:" not in q


def test_date_window_uses_gmail_format():
    q = build_unprocessed_query(
        _config(), since=date(2025, 1, 5), until=date(2025, 2, 1)
    )
    assert "after:2025/01/05" in q
    assert "before:2025/02/01" in q
