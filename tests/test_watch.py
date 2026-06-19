from citibike2strava import watch
from citibike2strava.auth.strava_auth import NotAuthorizedError
from citibike2strava.strava_client import StravaError


def _noop_sleep(_):
    pass


def test_runs_immediately_and_repeats():
    calls = []
    code = watch.run_watch(
        lambda: calls.append(1), interval_s=999, sleeper=_noop_sleep, max_ticks=3
    )
    assert code == watch.EXIT_OK
    assert len(calls) == 3


def test_sleeps_between_ticks_not_after_last():
    sleeps = []
    watch.run_watch(lambda: None, interval_s=60, sleeper=sleeps.append, max_ticks=3)
    # Sleep after ticks 1 and 2; the loop returns after tick 3 without sleeping.
    assert sleeps == [60, 60]


def test_transient_error_is_logged_and_loop_continues():
    events = []
    state = {"n": 0}

    def tick():
        state["n"] += 1
        if state["n"] == 1:
            raise StravaError("rate limited")

    code = watch.run_watch(
        tick, interval_s=1, sleeper=_noop_sleep, max_ticks=2,
        on_event=lambda kind, *a: events.append(kind),
    )
    assert code == watch.EXIT_OK
    assert "transient" in events
    assert state["n"] == 2  # kept going after the transient error


def test_fatal_auth_error_exits_without_looping():
    calls = []

    def tick():
        calls.append(1)
        raise NotAuthorizedError("re-run login")

    code = watch.run_watch(tick, interval_s=1, sleeper=_noop_sleep, max_ticks=5)
    assert code == watch.EXIT_FATAL_AUTH
    assert len(calls) == 1  # did not keep spinning on an unfixable error


def test_stop_callback_halts_before_first_tick():
    calls = []
    code = watch.run_watch(
        lambda: calls.append(1), interval_s=1, sleeper=_noop_sleep, stop=lambda: True
    )
    assert code == watch.EXIT_OK
    assert calls == []


def test_keyboard_interrupt_stops_cleanly():
    def tick():
        raise KeyboardInterrupt

    code = watch.run_watch(tick, interval_s=1, sleeper=_noop_sleep, max_ticks=3)
    assert code == watch.EXIT_OK
