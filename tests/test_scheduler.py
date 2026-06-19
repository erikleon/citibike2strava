import pytest

from citibike2strava import scheduler


def test_recipes_include_all_three_platforms():
    text = scheduler.recipes(30)
    assert "*/30 * * * *" in text          # cron
    assert "StartInterval" in text         # launchd
    assert "1800" in text                  # 30 min in seconds
    assert "schtasks" in text              # Windows Task Scheduler
    assert "/MO 30" in text


def test_hourly_uses_hour_field():
    text = scheduler.recipes(120)
    assert "0 */2 * * *" in text


def test_invalid_interval_raises():
    with pytest.raises(ValueError):
        scheduler.recipes(0)
