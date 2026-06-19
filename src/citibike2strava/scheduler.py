"""Generate OS scheduler recipes for unattended auto-sync.

We deliberately do NOT ship a long-running daemon. ``citibike2strava run`` is
idempotent and resumable, so the robust "set and forget" story is to let the OS
scheduler invoke it on a timer — it survives reboots and adds no new
crash-recovery, token-refresh, or log-rotation code for us to own. This module
just prints the platform-appropriate recipe; it never modifies the system.
"""

from __future__ import annotations

DEFAULT_COMMAND = "citibike2strava run"


def _cron_schedule(interval_minutes: int) -> str:
    if interval_minutes < 60:
        return f"*/{interval_minutes} * * * *"
    hours = max(1, interval_minutes // 60)
    return f"0 */{hours} * * *"


def recipes(interval_minutes: int = 60, *, command: str = DEFAULT_COMMAND) -> str:
    """Return cron / launchd / Task Scheduler snippets for the given interval."""
    if interval_minutes < 1:
        raise ValueError("interval_minutes must be >= 1")

    cron = _cron_schedule(interval_minutes)
    interval_seconds = interval_minutes * 60
    log_note = (
        "Tip: set CITIBIKE2STRAVA_LOG=<path> in the job's environment to append a "
        "one-line summary of each run, so a silent failure is visible."
    )

    return f"""\
Auto-sync recipes (every {interval_minutes} min). Pick the one for your OS.
The job inherits no shell profile, so use absolute paths and set the env vars
(GOOGLE_*/STRAVA_* or a config.toml the tool can find).

# Linux / macOS — cron (`crontab -e`)
{cron} {command} >> "$HOME/.citibike2strava.log" 2>&1

# macOS — launchd (~/Library/LaunchAgents/com.citibike2strava.sync.plist)
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.citibike2strava.sync</string>
  <key>ProgramArguments</key>
  <array><string>/bin/sh</string><string>-c</string><string>{command}</string></array>
  <key>StartInterval</key><integer>{interval_seconds}</integer>
  <key>StandardOutPath</key><string>/tmp/citibike2strava.log</string>
  <key>StandardErrorPath</key><string>/tmp/citibike2strava.log</string>
</dict></plist>
  Then: launchctl load ~/Library/LaunchAgents/com.citibike2strava.sync.plist

# Windows — Task Scheduler (PowerShell, runs every {interval_minutes} min)
schtasks /Create /SC MINUTE /MO {interval_minutes} /TN citibike2strava ^
  /TR "{command}"

{log_note}
"""
