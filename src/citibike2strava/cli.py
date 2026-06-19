"""Command-line interface for citibike2strava.

    citibike2strava login [--gmail] [--strava]   authorize one or both services
    citibike2strava status                       show what is authorized
    citibike2strava run [--dry-run] [--limit N]  process all new receipts
        [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--force]   (backfill window)
    citibike2strava process <message_id>         process one receipt by id
    citibike2strava process-file <path|->        process a saved/forwarded .eml
    citibike2strava export <message_id> -o f.gpx write GPX without uploading
    citibike2strava serve                        run the local one-click backend
    citibike2strava schedule [--interval-minutes N]  print auto-sync recipes
    citibike2strava logout                       delete stored tokens
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

from .auth import DEFAULT_USER, FileTokenStore
from .auth import google_auth, strava_auth
from .config import ConfigError, load_config
from .eml import html_from_eml
from .gpx import build_gpx
from .pipeline import Pipeline
from .receipt import parse_receipt


def _store_and_config(args):
    config = load_config()
    store = FileTokenStore(config.tokens_dir)
    return config, store


def _parse_date(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a date as YYYY-MM-DD, got {s!r}")


def cmd_login(args) -> int:
    config, store = _store_and_config(args)
    do_both = not (args.gmail or args.strava)
    try:
        if args.gmail or do_both:
            print("Authorizing Gmail…")
            google_auth.authorize(config, store, DEFAULT_USER)
            print("  ✓ Gmail authorized")
        if args.strava or do_both:
            print("Authorizing Strava…")
            strava_auth.authorize(config, store, DEFAULT_USER)
            print("  ✓ Strava authorized")
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_logout(args) -> int:
    config, store = _store_and_config(args)
    store.delete("google", DEFAULT_USER)
    store.delete("strava", DEFAULT_USER)
    print("Stored tokens removed.")
    return 0


def cmd_status(args) -> int:
    config, store = _store_and_config(args)
    gmail_ok = store.load("google", DEFAULT_USER) is not None
    strava_ok = store.load("strava", DEFAULT_USER) is not None
    system = config.bikeshare
    tier = "supported" if system.supported else "experimental (unverified)"
    print(f"Config home : {config.home}")
    print(f"Gmail        : {'authorized' if gmail_ok else 'not authorized'}")
    print(f"Strava       : {'authorized' if strava_ok else 'not authorized'}")
    print(f"System       : {system.name} [{system.key}] — {tier}")
    print(f"Gmail query  : {config.gmail_query}")
    print(f"Timezone     : {config.timezone}")
    return 0


def _print_result(r) -> None:
    icons = {
        "uploaded": "✓",
        "duplicate": "=",
        "skipped": "»",
        "dry-run": "·",
        "error": "✗",
    }
    icon = icons.get(r.status, "?")
    bits = [f"{icon} [{r.status}]"]
    if r.receipt_id:
        bits.append(f"receipt #{r.receipt_id}")
    if r.distance_mi is not None:
        bits.append(f"{r.distance_mi} mi")
    if r.detail:
        bits.append(f"— {r.detail}")
    if r.activity_url:
        bits.append(f"\n    {r.activity_url}")
    print(" ".join(bits))


def _summarize(results) -> tuple[str, int]:
    uploaded = sum(r.status == "uploaded" for r in results)
    duplicate = sum(r.status == "duplicate" for r in results)
    skipped = sum(r.status == "skipped" for r in results)
    errors = sum(r.status == "error" for r in results)
    summary = (
        f"{uploaded} uploaded, {duplicate} duplicate, {skipped} skipped, "
        f"{errors} errors, {len(results)} total."
    )
    return summary, errors


def _append_log(summary: str) -> None:
    """Append a timestamped run summary if CITIBIKE2STRAVA_LOG is set.

    Gives unattended (scheduled) runs a visible trail so a silent failure is
    discoverable after the fact.
    """
    path = os.environ.get("CITIBIKE2STRAVA_LOG")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} {summary}\n")
    except OSError as exc:
        print(f"warning: could not write log {path}: {exc}", file=sys.stderr)


def cmd_run(args) -> int:
    config, store = _store_and_config(args)
    pipeline = Pipeline(config, store)
    # Stream each result as it completes so long backfills show progress.
    results = pipeline.process_inbox(
        dry_run=args.dry_run,
        limit=args.limit,
        since=args.since,
        until=args.until,
        force=args.force,
        on_result=_print_result,
    )
    if not results:
        print("No new receipts found.")
        _append_log("0 uploaded, 0 errors, 0 total.")
        return 0
    summary, errors = _summarize(results)
    print(f"\n{summary}")
    _append_log(summary)
    return 1 if errors else 0


def cmd_process(args) -> int:
    config, store = _store_and_config(args)
    pipeline = Pipeline(config, store)
    _print_result(
        pipeline.process_message(args.message_id, dry_run=args.dry_run, force=args.force)
    )
    return 0


def cmd_process_file(args) -> int:
    config, store = _store_and_config(args)
    pipeline = Pipeline(config, store)
    if args.path == "-":
        raw = sys.stdin.buffer.read()
        source = "<stdin>"
    else:
        with open(args.path, "rb") as fh:
            raw = fh.read()
        source = args.path
    html = html_from_eml(raw)
    result = pipeline.process_html(
        html, source_id=source, dry_run=args.dry_run, force=args.force
    )
    _print_result(result)
    return 1 if result.status == "error" else 0


def cmd_export(args) -> int:
    """Parse a receipt and write its GPX, without uploading. Handy for testing."""
    config, store = _store_and_config(args)
    pipeline = Pipeline(config, store)
    html = pipeline.gmail().get_html_body(args.message_id)
    ride = parse_receipt(html, message_id=args.message_id, timezone=config.timezone)
    gpx = build_gpx(ride)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(gpx)
        print(f"Wrote {args.output} ({ride.activity_name})")
    else:
        sys.stdout.write(gpx)
    return 0


def cmd_serve(args) -> int:
    from . import server

    config, _ = _store_and_config(args)
    server.serve(config, host=args.host, port=args.port)
    return 0


def cmd_schedule(args) -> int:
    from . import scheduler

    print(scheduler.recipes(args.interval_minutes))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="citibike2strava", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="authorize Gmail and/or Strava")
    p_login.add_argument("--gmail", action="store_true", help="only authorize Gmail")
    p_login.add_argument("--strava", action="store_true", help="only authorize Strava")
    p_login.set_defaults(func=cmd_login)

    sub.add_parser("logout", help="delete stored tokens").set_defaults(func=cmd_logout)
    sub.add_parser("status", help="show authorization status").set_defaults(func=cmd_status)

    p_run = sub.add_parser(
        "run", help="process all new receipts (use --since/--until to backfill)"
    )
    p_run.add_argument("--dry-run", action="store_true", help="parse only, do not upload")
    p_run.add_argument("--limit", type=int, default=None, help="process at most N")
    p_run.add_argument("--since", type=_parse_date, default=None, metavar="YYYY-MM-DD",
                       help="only receipts on/after this date")
    p_run.add_argument("--until", type=_parse_date, default=None, metavar="YYYY-MM-DD",
                       help="only receipts before this date")
    p_run.add_argument("--force", action="store_true",
                       help="ignore the local processed cache and re-attempt uploads")
    p_run.set_defaults(func=cmd_run)

    p_proc = sub.add_parser("process", help="process one receipt by message id")
    p_proc.add_argument("message_id")
    p_proc.add_argument("--dry-run", action="store_true")
    p_proc.add_argument("--force", action="store_true",
                        help="ignore the local processed cache")
    p_proc.set_defaults(func=cmd_process)

    p_pf = sub.add_parser(
        "process-file", help="process a saved/forwarded .eml file (or '-' for stdin)"
    )
    p_pf.add_argument("path", help="path to an .eml file, or '-' to read stdin")
    p_pf.add_argument("--dry-run", action="store_true")
    p_pf.add_argument("--force", action="store_true",
                      help="ignore the local processed cache")
    p_pf.set_defaults(func=cmd_process_file)

    p_exp = sub.add_parser("export", help="write a receipt's GPX without uploading")
    p_exp.add_argument("message_id")
    p_exp.add_argument("-o", "--output", help="output file (default: stdout)")
    p_exp.set_defaults(func=cmd_export)

    p_serve = sub.add_parser("serve", help="run the local one-click backend (loopback)")
    p_serve.add_argument("--host", default="127.0.0.1", help="loopback host to bind")
    p_serve.add_argument("--port", type=int, default=8722, help="port (default 8722)")
    p_serve.set_defaults(func=cmd_serve)

    p_sched = sub.add_parser(
        "schedule", help="print cron/launchd/Task Scheduler recipes for auto-sync"
    )
    p_sched.add_argument("--interval-minutes", type=int, default=60,
                         help="how often to run (default 60)")
    p_sched.set_defaults(func=cmd_schedule)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Output uses non-ASCII glyphs (status icons, the route arrow "→") and
    # station names with accents. Windows consoles default to cp1252, which
    # can't encode these and raises UnicodeEncodeError on print; force UTF-8.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
