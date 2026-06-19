from citibike2strava.processed import ProcessedStore


def test_add_and_contains(tmp_path):
    store = ProcessedStore(tmp_path / "processed.json")
    assert not store.contains("123")
    store.add("123")
    assert store.contains("123")


def test_persists_across_instances(tmp_path):
    path = tmp_path / "processed.json"
    ProcessedStore(path).add("abc")
    # A fresh instance (new process) must see the persisted id.
    assert ProcessedStore(path).contains("abc")


def test_missing_file_is_empty(tmp_path):
    store = ProcessedStore(tmp_path / "nope.json")
    assert not store.contains("x")


def test_corrupt_file_treated_as_empty(tmp_path):
    path = tmp_path / "processed.json"
    path.write_text("{not json", encoding="utf-8")
    store = ProcessedStore(path)
    # Non-fatal: corrupt cache behaves as empty (Strava external_id still guards).
    assert not store.contains("x")
    store.add("y")
    assert store.contains("y")


def test_add_is_idempotent(tmp_path):
    store = ProcessedStore(tmp_path / "processed.json")
    store.add("dup")
    store.add("dup")
    assert store.contains("dup")
