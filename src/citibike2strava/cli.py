"""Command-line interface for citibike2strava.

    citibike2strava login [--gmail] [--strava]   authorize one or both services
    citibike2strava status                       show what is authorized
    citibike2strava run [--dry-run] [--limit N]  process all new receipts
    citibike2strava process <message_id>         process one receipt
    citibike2strava export <message_id> -o f.gpx write GPX without uploading
    citibike2strava serve                        run the local one-click backend
    citibike2strava logout                       delete stored tokens
"""

from __future__ import annotations

import argparse
import sys

from .auth import DEFAULT_USER, FileTokenStore
from .auth import google_auth, strava_auth
from .config import ConfigError, load_config
from .gpx import build_gpx
from .pipeline import Pipeline
from .receipt import parse_receipt


def _store_and_config(args):
    config = load_config()
    store = FileTokenStore(config.tokens_dir)
    return config, store


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
    print(f"Config home : {config.home}")
    print(f"Gmail        : {'authorized' if gmail_ok else 'not authorized'}")
    print(f"Strava       : {'authorized' if strava_ok else 'not authorized'}")
    print(f"Gmail query  : {config.gmail_query}")
    print(f"Timezone     : {config.timezone}")
    return 0


def _print_result(r) -> None:
    icons = {"uploaded": "✓", "duplicate": "=", "dry-run": "·", "error": "✗"}
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


def cmd_run(args) -> int:
    config, store = _store_and_config(args)
    pipeline = Pipeline(config, store)
    results = pipeline.process_inbox(dry_run=args.dry_run, limit=args.limit)
    if not results:
        print("No new receipts found.")
        return 0
    errors = 0
    for r in results:
        _print_result(r)
        errors += r.status == "error"
    uploaded = sum(r.status == "uploaded" for r in results)
    print(f"\n{uploaded} uploaded, {errors} errors, {len(results)} total.")
    return 1 if errors else 0


def cmd_process(args) -> int:
    config, store = _store_and_config(args)
    pipeline = Pipeline(config, store)
    _print_result(pipeline.process_message(args.message_id, dry_run=args.dry_run))
    return 0


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="citibike2strava", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="authorize Gmail and/or Strava")
    p_login.add_argument("--gmail", action="store_true", help="only authorize Gmail")
    p_login.add_argument("--strava", action="store_true", help="only authorize Strava")
    p_login.set_defaults(func=cmd_login)

    sub.add_parser("logout", help="delete stored tokens").set_defaults(func=cmd_logout)
    sub.add_parser("status", help="show authorization status").set_defaults(func=cmd_status)

    p_run = sub.add_parser("run", help="process all new receipts")
    p_run.add_argument("--dry-run", action="store_true", help="parse only, do not upload")
    p_run.add_argument("--limit", type=int, default=None, help="process at most N")
    p_run.set_defaults(func=cmd_run)

    p_proc = sub.add_parser("process", help="process one receipt by message id")
    p_proc.add_argument("message_id")
    p_proc.add_argument("--dry-run", action="store_true")
    p_proc.set_defaults(func=cmd_process)

    p_exp = sub.add_parser("export", help="write a receipt's GPX without uploading")
    p_exp.add_argument("message_id")
    p_exp.add_argument("-o", "--output", help="output file (default: stdout)")
    p_exp.set_defaults(func=cmd_export)

    p_serve = sub.add_parser("serve", help="run the local one-click backend (loopback)")
    p_serve.add_argument("--host", default="127.0.0.1", help="loopback host to bind")
    p_serve.add_argument("--port", type=int, default=8722, help="port (default 8722)")
    p_serve.set_defaults(func=cmd_serve)

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
    except (ConfigError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
