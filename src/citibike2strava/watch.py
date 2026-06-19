"""Foreground auto-sync loop for ``citibike2strava watch``.

A single-command alternative to the OS scheduler recipes (see :mod:`scheduler`):
poll for new receipts now, then every ``interval`` minutes, until interrupted.

Failure policy (chosen deliberately):

* **Transient** errors — a network blip, a Strava rate limit, a single bad
  receipt — are logged and the loop continues. ``Pipeline.process_inbox`` already
  isolates per-ride failures; this also absorbs a failure of the whole pass
  (e.g. the Gmail search call) so one bad tick doesn't kill the daemon.
* **Fatal auth** errors — a revoked/expired refresh token that needs ``login``
  again — stop the loop with a non-zero exit, because retrying forever would just
  spin on an unfixable problem where a human needs to act.

The loop is dependency-free and the sleeper/clock are injectable, so it is unit
tested without real waiting or signals.
"""

from __future__ import annotations

import time
from typing import Callable

from .auth.google_auth import NotAuthorizedError as GoogleNotAuthorized
from .auth.strava_auth import NotAuthorizedError as StravaNotAuthorized
from .pipeline import _ISOLATED_ERRORS

# A refresh token that can't be renewed needs the user to re-run `login`; there
# is no point looping on it.
FATAL_AUTH_ERRORS = (GoogleNotAuthorized, StravaNotAuthorized)

EXIT_OK = 0
EXIT_FATAL_AUTH = 2


def run_watch(
    tick: Callable[[], None],
    *,
    interval_s: float,
    sleeper: Callable[[float], None] = time.sleep,
    max_ticks: int | None = None,
    stop: Callable[[], bool] | None = None,
    on_event: Callable[..., None] | None = None,
) -> int:
    """Run ``tick`` immediately, then every ``interval_s`` seconds.

    Returns an exit code: ``EXIT_OK`` on a clean stop (``stop()`` true, or
    ``max_ticks`` reached, or :class:`KeyboardInterrupt`), ``EXIT_FATAL_AUTH`` if
    a tick raises a fatal auth error. ``max_ticks`` and ``stop`` exist for tests;
    real shutdown is a Ctrl-C / SIGTERM raising :class:`KeyboardInterrupt`.
    """
    emit = on_event or (lambda *a: None)
    ticks = 0
    try:
        while True:
            if stop is not None and stop():
                emit("stopped")
                return EXIT_OK
            try:
                tick()
            except FATAL_AUTH_ERRORS as exc:
                emit("fatal", exc)
                return EXIT_FATAL_AUTH
            except _ISOLATED_ERRORS as exc:
                emit("transient", exc)
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                emit("done")
                return EXIT_OK
            sleeper(interval_s)
    except KeyboardInterrupt:
        emit("interrupted")
        return EXIT_OK
