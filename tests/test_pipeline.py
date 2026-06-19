from pathlib import Path

import pytest

from citibike2strava.config import Config
from citibike2strava.pipeline import Pipeline
from citibike2strava.processed import ProcessedStore
from citibike2strava.strava_client import DuplicateUpload, StravaError, UploadResult

FIXTURE = Path(__file__).parent / "fixtures" / "sample_receipt.html"


@pytest.fixture
def receipt_html():
    return FIXTURE.read_text(encoding="utf-8")


def _config(tmp_path):
    return Config(
        home=tmp_path,
        google_client_id=None,
        google_client_secret=None,
        strava_client_id=None,
        strava_client_secret=None,
    )


class FakeStrava:
    def __init__(self):
        self.upload_calls = 0
        self.updated = []
        self.fail_next = None  # None | "duplicate" | "error"

    def upload_gpx(self, gpx, *, name, external_id, description=""):
        self.upload_calls += 1
        if self.fail_next == "duplicate":
            self.fail_next = None
            raise DuplicateUpload("duplicate of activity 1")
        if self.fail_next == "error":
            self.fail_next = None
            raise StravaError("upstream boom")
        return UploadResult(
            activity_id=123, activity_url="https://www.strava.com/activities/123"
        )

    def update_activity(self, activity_id, *, sport_type, name=None):
        self.updated.append((activity_id, sport_type))


class FakeGmail:
    def __init__(self, html, ids):
        self._html = html
        self._ids = ids
        self.labelled = []

    def search_message_ids(self, query):
        return list(self._ids)

    def get_html_body(self, message_id):
        return self._html

    def ensure_label(self, name):
        return "label-1"

    def add_label(self, message_id, label_id):
        self.labelled.append(message_id)


def _pipeline(tmp_path, html, ids=("m1",)):
    p = Pipeline(
        _config(tmp_path),
        store=None,
        processed=ProcessedStore(tmp_path / "processed.json"),
    )
    p._strava = FakeStrava()
    p._gmail = FakeGmail(html, ids)
    return p


def test_process_html_uploads_and_caches(tmp_path, receipt_html):
    p = _pipeline(tmp_path, receipt_html)
    r = p.process_html(receipt_html, source_id="file.eml")
    assert r.status == "uploaded"
    assert r.activity_url.endswith("/123")
    assert p._strava.updated == [(123, "EBikeRide")]
    # Receipt id recorded in the cache.
    assert p.processed.contains(r.receipt_id)


def test_process_html_skips_when_cached(tmp_path, receipt_html):
    p = _pipeline(tmp_path, receipt_html)
    first = p.process_html(receipt_html, source_id="file.eml")
    p._strava.upload_calls = 0
    second = p.process_html(receipt_html, source_id="file.eml")
    assert second.status == "skipped"
    assert p._strava.upload_calls == 0  # no network on cache hit
    assert first.receipt_id == second.receipt_id


def test_force_bypasses_cache(tmp_path, receipt_html):
    p = _pipeline(tmp_path, receipt_html)
    p.process_html(receipt_html, source_id="file.eml")
    p._strava.upload_calls = 0
    again = p.process_html(receipt_html, source_id="file.eml", force=True)
    assert again.status == "uploaded"
    assert p._strava.upload_calls == 1


def test_duplicate_marks_cache(tmp_path, receipt_html):
    p = _pipeline(tmp_path, receipt_html)
    p._strava.fail_next = "duplicate"
    r = p.process_html(receipt_html, source_id="file.eml")
    assert r.status == "duplicate"
    assert p.processed.contains(r.receipt_id)


def test_dry_run_does_not_upload_or_cache(tmp_path, receipt_html):
    p = _pipeline(tmp_path, receipt_html)
    r = p.process_html(receipt_html, source_id="file.eml", dry_run=True)
    assert r.status == "dry-run"
    assert p._strava.upload_calls == 0
    assert not p.processed.contains(r.receipt_id)


def test_parse_error_is_reported_not_raised(tmp_path):
    p = _pipeline(tmp_path, "<html>no receipt here</html>")
    r = p.process_html("<html>no receipt here</html>", source_id="bad.eml")
    assert r.status == "error"


def test_process_inbox_isolates_per_ride_failure(tmp_path, receipt_html):
    p = _pipeline(tmp_path, receipt_html, ids=("m1", "m2"))
    p._strava.fail_next = "error"  # first ride blows up
    streamed = []
    results = p.process_inbox(force=True, on_result=streamed.append)
    # One StravaError must NOT abort the batch.
    assert len(results) == 2
    assert results[0].status == "error"
    assert results[1].status == "uploaded"
    assert len(streamed) == 2  # progress streamed as each completed
