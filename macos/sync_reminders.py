#!/usr/bin/env python3
"""
Pull upcoming bCourses deadlines and create native macOS Reminders.

  python3 sync_reminders.py                 # sync next 21 days
  python3 sync_reminders.py --days 30
  python3 sync_reminders.py --lead 48       # remind 48h before the deadline
  python3 sync_reminders.py --dry-run       # print what would happen, change nothing
  python3 sync_reminders.py --include-events --include-past   # keep everything the planner returns
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcourses_api

STATE_DIR = Path.home() / ".bcourses-sync"
STATE_FILE = STATE_DIR / "state.json"
DEFAULT_LIST = "bCourses"

# Class meetings already come through the subscribed bCourses .ics feed in Calendar,
# so turning them into Reminders as well is pure duplication.
SKIP_TYPES = {"calendar_event"}


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def escape_applescript(text):
    """Escape backslashes, quotes, and line breaks for AppleScript literals."""
    return (
        text.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\r\n", "\\n")
            .replace("\n", "\\n")
            .replace("\r", "\\n")
    )


def build_script(list_name, title, body, when):
    """`day of d` is set to 1 before year/month to avoid month-end rollover."""
    seconds = when.hour * 3600 + when.minute * 60
    return f'''
tell application "Reminders"
    if not (exists list "{escape_applescript(list_name)}") then
        make new list with properties {{name:"{escape_applescript(list_name)}"}}
    end if
    set theList to list "{escape_applescript(list_name)}"
    set d to current date
    set day of d to 1
    set year of d to {when.year}
    set month of d to {when.month}
    set day of d to {when.day}
    set time of d to {seconds}
    make new reminder at end of theList with properties {{name:"{escape_applescript(title)}", body:"{escape_applescript(body)}", due date:d, remind me date:d}}
end tell
'''.strip()


def run_applescript(script):
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "osascript failed")
    return result.stdout.strip()


def alert_time(due_local, lead_hours, now_local):
    """Fire `lead_hours` early, but never in the past."""
    proposed = due_local - timedelta(hours=lead_hours)
    floor = now_local + timedelta(minutes=10)
    return proposed if proposed > floor else min(due_local, floor)


def main():
    parser = argparse.ArgumentParser(description="Sync bCourses deadlines to macOS Reminders")
    parser.add_argument("--days", type=int, default=21, help="how far ahead to look")
    parser.add_argument("--lead", type=float, default=24, help="hours before deadline to alert")
    parser.add_argument("--list", default=DEFAULT_LIST, help="Reminders list name")
    parser.add_argument("--dry-run", action="store_true", help="print instead of creating")
    parser.add_argument("--include-events", action="store_true",
                        help="also sync calendar events (class meetings), normally skipped")
    parser.add_argument("--include-past", action="store_true",
                        help="also sync items already past due, normally skipped")
    args = parser.parse_args()

    try:
        items = bcourses_api.upcoming(days=args.days)
    except bcourses_api.CanvasError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    state = load_state()
    now_local = datetime.now().astimezone()
    created = 0
    skipped = 0
    filtered = 0

    for item in items:
        due_local = datetime.fromisoformat(item["due_utc"]).astimezone()

        # The planner window starts at "now", but Canvas still returns items whose
        # plannable_date sits ahead of a due date that has already passed.
        if not args.include_past and due_local <= now_local:
            filtered += 1
            continue
        if not args.include_events and item["type"] in SKIP_TYPES:
            filtered += 1
            continue

        previous = state.get(item["id"])

        if previous and previous.get("due_utc") == item["due_utc"]:
            skipped += 1
            continue

        prefix = "[UPDATED] " if previous else ""
        course = item["course"] or "bCourses"
        title = f"{prefix}{course}: {item['title']}"

        body_lines = [
            f"Due {due_local.strftime('%a %d %b %Y, %-I:%M %p')}",
            f"Type: {item['type']}",
        ]
        if item.get("points") is not None:
            body_lines.append(f"Points: {item['points']}")
        if item.get("url"):
            body_lines.append(item["url"])
        body = "\n".join(body_lines)

        when = alert_time(due_local, args.lead, now_local)

        if args.dry_run:
            print(f"WOULD CREATE  {when.strftime('%Y-%m-%d %H:%M')}  {title}")
        else:
            try:
                run_applescript(build_script(args.list, title, body, when))
            except RuntimeError as exc:
                print(f"failed to create '{title}': {exc}", file=sys.stderr)
                continue
            print(f"created  {when.strftime('%Y-%m-%d %H:%M')}  {title}")

        state[item["id"]] = {
            "due_utc": item["due_utc"],
            "title": item["title"],
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
        created += 1

    if not args.dry_run:
        save_state(state)

    print(f"\n{created} reminder(s) created, {skipped} already in sync, {filtered} filtered out.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
