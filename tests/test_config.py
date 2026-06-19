import pytest

from citibike2strava.config import ConfigError, load_config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    # Isolate from the developer's real env / .env so assertions are stable.
    for key in (
        "CITIBIKE2STRAVA_SYSTEM",
        "CITIBIKE2STRAVA_GMAIL_QUERY",
        "CITIBIKE2STRAVA_TZ",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CITIBIKE2STRAVA_HOME", str(tmp_path))
    # load_config reads ./.env; run from an empty dir so the repo's .env (which
    # may set CITIBIKE2STRAVA_TZ etc.) cannot leak into these assertions.
    monkeypatch.chdir(tmp_path)


def test_default_system_is_citibike(tmp_path):
    cfg = load_config(home=tmp_path)
    assert cfg.system == "citibike"
    assert cfg.bikeshare.supported is True
    assert "citibikenyc.com" in cfg.gmail_query
    assert cfg.timezone == "America/New_York"


def test_selecting_system_derives_sender_and_timezone(tmp_path, monkeypatch):
    monkeypatch.setenv("CITIBIKE2STRAVA_SYSTEM", "divvy")
    cfg = load_config(home=tmp_path)
    assert cfg.system == "divvy"
    assert cfg.bikeshare.supported is False  # experimental
    assert "divvybikes.com" in cfg.gmail_query
    assert cfg.timezone == "America/Chicago"


def test_explicit_query_overrides_system(tmp_path, monkeypatch):
    monkeypatch.setenv("CITIBIKE2STRAVA_SYSTEM", "divvy")
    monkeypatch.setenv("CITIBIKE2STRAVA_GMAIL_QUERY", "from:custom subject:Foo")
    cfg = load_config(home=tmp_path)
    assert cfg.gmail_query == "from:custom subject:Foo"


def test_unknown_system_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("CITIBIKE2STRAVA_SYSTEM", "nope")
    with pytest.raises(ConfigError):
        load_config(home=tmp_path)
