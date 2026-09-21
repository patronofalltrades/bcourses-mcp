#!/usr/bin/env python3
"""
Force-sync upcoming bCourses deadlines into a local Apple Calendar.

The subscribed bCourses .ics feed is read-only, carries class meetings rather
than deadlines, and refreshes whenever Calendar feels like it. This writes a
calendar you own and *reconciles* it on every run:

  - new deadlines are created
  - deadlines whose due date, title, points or link changed are rewritten
  - deadlines that vanished from Canvas inside the sync window are deleted

so the calendar mirrors Canvas instead of accumulating stale events.

  python3 sync_calendar.py                    # reconcile the next 30 days
  python3 sync_calendar.py --dry-run          # show the plan, change nothing
  python3 sync_calendar.py --force            # delete every synced event, rebuild
  python3 sync_calendar.py --days 60 --alarm 2880 --alarm 60
  python3 sync_calendar.py --calendar "Haas Deadlines" --no-alarm
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcourses_api
from sync_reminders import escape_applescript

STATE_DIR = Path.home() / ".bcourses-sync"
STATE_FILE = STATE_DIR / "calendar.json"
LAST_RUN_FILE = STATE_DIR / "calendar-last-run"
DEFAULT_CALENDAR = "bCourses Deadlines"
DEFAULT_ALARMS = [1440, 60]          # minutes before the deadline
DEFAULT_DURATION = 30                # minutes of calendar block per deadline

# Stamped into every event description. It is the fallback key for locating an
# event when the stored uid is stale, and the marker --force sweeps on.
MARKER = "[bcourses-id:{}]"

# Class meetings already arrive through the subscribed bCourses .ics feed.
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
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def hours_since_last_run():
    """None if this has never run. Used by --if-stale so the SessionStart hook
    and the weekly agent can both call the script unconditionally."""
    try:
        last = datetime.fromisoformat(LAST_RUN_FILE.read_text().strip())
    except (OSError, ValueError):
        return None
    return (datetime.now(timezone.utc) - last).total_seconds() / 3600.0


def mark_run():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LAST_RUN_FILE.write_text(datetime.now(timezone.utc).isoformat())


def signature(item, duration, alarms):
    """Anything that would change the event on screen belongs in here."""
    return "|".join(str(x) for x in [
        item["due_utc"], item["title"], item["course"],
        item.get("points"), item.get("url"), duration,
        ",".join(str(a) for a in alarms),
    ])


def date_block(var, when, indent="        "):
    """`day` is set to 1 before year/month, or a month-end date rolls forward."""
    seconds = when.hour * 3600 + when.minute * 60 + when.second
    return "\n".join(indent + line for line in [
        "set %s to current date" % var,
        "set day of %s to 1" % var,
        "set year of %s to %d" % (var, when.year),
        "set month of %s to %d" % (var, when.month),
        "set day of %s to %d" % (var, when.day),
        "set time of %s to %d" % (var, seconds),
    ])


def build_script(calendar_name, deletes, creates, purge, reload_subscriptions):
    """One AppleScript for the whole run. Each item is wrapped in its own
    try block so a single failure cannot abort the rest of the sync."""
    cal = escape_applescript(calendar_name)
    out = [
        'tell application "Calendar"',
        "    launch",
        '    if not (exists calendar "%s") then' % cal,
        '        make new calendar with properties {name:"%s"}' % cal,
        "    end if",
        '    set cal to first calendar whose name is "%s"' % cal,
        '    set out to ""',
    ]

    if reload_subscriptions:
        # Forces the subscribed bCourses .ics feed to refresh too, instead of
        # waiting for Calendar's own timer.
        out += ["    try", "        reload calendars", "    end try"]

    if purge:
        out += [
            '    set doomed to (every event of cal whose description contains "[bcourses-id:")',
            "    repeat with i from (count of doomed) to 1 by -1",
            "        try",
            "            delete (item i of doomed)",
            '            set out to out & "DEL" & tab & "*" & linefeed',
            "        end try",
            "    end repeat",
        ]

    for entry in deletes:
        item_id = escape_applescript(entry["item_id"])
        marker = escape_applescript(MARKER.format(entry["item_id"]))
        by_uid = ('delete (first event of cal whose uid is "%s")'
                  % escape_applescript(entry["uid"]) if entry.get("uid") else None)
        by_marker = 'delete (first event of cal whose description contains "%s")' % marker
        out += ["    try"]
        if by_uid:
            # A uid goes stale if the event was edited across iCloud; fall back
            # to the marker before giving up on it.
            out += [
                "        try",
                "            " + by_uid,
                "        on error",
                "            " + by_marker,
                "        end try",
            ]
        else:
            out += ["        " + by_marker]
        out += [
            '        set out to out & "DEL" & tab & "%s" & linefeed' % item_id,
            "    on error errMsg",
            '        set out to out & "DELFAIL" & tab & "%s" & tab & errMsg & linefeed' % item_id,
            "    end try",
        ]

    for entry in creates:
        item_id = escape_applescript(entry["item_id"])
        props = [
            'summary:"%s"' % escape_applescript(entry["title"]),
            "start date:d",
            "end date:(d + %d)" % (entry["duration"] * 60),
            'description:"%s"' % escape_applescript(entry["body"]),
        ]
        if entry.get("url"):
            props.append('url:"%s"' % escape_applescript(entry["url"]))
        out += ["    try", date_block("d", entry["start"])]
        out += ["        set e to make new event at end of events of cal with properties {%s}"
                % ", ".join(props)]
        if entry["alarms"]:
            out += ["        tell e"]
            for minutes in entry["alarms"]:
                out += ["            make new display alarm at end of display alarms "
                        "with properties {trigger interval:-%d}" % minutes]
            out += ["        end tell"]
        out += [
            '        set out to out & "NEW" & tab & "%s" & tab & (uid of e) & linefeed' % item_id,
            "    on error errMsg",
            '        set out to out & "NEWFAIL" & tab & "%s" & tab & errMsg & linefeed' % item_id,
            "    end try",
        ]

    out += ["    return out", "end tell"]
    return "\n".join(out)


def run_applescript(script):
    """Fed through stdin rather than -e: the script grows with the deadline count."""
    result = subprocess.run(["osascript", "-"], input=script,
                            capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "osascript failed")
    return result.stdout


def parse_result(stdout):
    rows = []
    for line in stdout.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip():
            rows.append(line.split("\t"))
    return rows


def build_plan(items, state, args, alarms, now_local):
    """Returns (deletes, creates, unchanged, filtered)."""
    window_end = now_local + timedelta(days=args.days)
    deletes, creates, unchanged, filtered = [], [], 0, 0
    seen = set()

    for item in items:
        due_local = datetime.fromisoformat(item["due_utc"]).astimezone()

        # The planner window starts at "now", yet Canvas still returns items
        # whose plannable_date sits ahead of a due date that already passed.
        if not args.include_past and due_local <= now_local:
            filtered += 1
            continue
        if not args.include_events and item["type"] in SKIP_TYPES:
            filtered += 1
            continue

        seen.add(item["id"])
        sig = signature(item, args.duration, alarms)
        previous = state.get(item["id"])

        if previous and previous.get("signature") == sig and not args.force:
            unchanged += 1
            continue

        if previous and not args.force:
            deletes.append({"item_id": item["id"], "uid": previous.get("uid")})

        course = item["course"] or "bCourses"
        body_lines = [
            "Due %s" % due_local.strftime("%a %d %b %Y, %-I:%M %p"),
            "Type: %s" % item["type"],
        ]
        if item.get("points") is not None:
            body_lines.append("Points: %s" % item["points"])
        if item.get("url"):
            body_lines.append(item["url"])
        body_lines += ["", MARKER.format(item["id"])]

        # An alarm whose trigger time has already passed can fire the moment the
        # event is created. Keep only the ones still ahead; the signature stays
        # keyed on the *requested* alarms so config changes still force a rewrite.
        live_alarms = [m for m in alarms if due_local - timedelta(minutes=m) > now_local]

        creates.append({
            "item_id": item["id"],
            "title": "%s: %s" % (course, item["title"]),
            "body": "\n".join(body_lines),
            "url": item.get("url") or "",
            "start": due_local,
            "duration": args.duration,
            "alarms": live_alarms,
            "signature": sig,
            "due_utc": item["due_utc"],
            "is_update": bool(previous),
        })

    # Anything we synced that Canvas no longer returns *inside the window* is
    # gone for real - unpublished, or deleted by the instructor. Items due
    # outside the window are simply out of scope, not missing.
    if not args.force:
        for item_id, record in state.items():
            if item_id in seen:
                continue
            due = datetime.fromisoformat(record["due_utc"]).astimezone()
            if now_local < due <= window_end:
                deletes.append({"item_id": item_id, "uid": record.get("uid"),
                                "pruned": record.get("title", item_id)})

    return deletes, creates, unchanged, filtered


def main():
    parser = argparse.ArgumentParser(
        description="Force-sync bCourses deadlines into an Apple Calendar")
    parser.add_argument("--days", type=int, default=30, help="how far ahead to look")
    parser.add_argument("--calendar", default=DEFAULT_CALENDAR, help="calendar name")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION,
                        help="minutes each deadline blocks out")
    parser.add_argument("--alarm", type=int, action="append", metavar="MIN",
                        help="alert this many minutes early (repeatable, default 1440 and 60)")
    parser.add_argument("--no-alarm", action="store_true", help="create events without alerts")
    parser.add_argument("--force", action="store_true",
                        help="delete every previously synced event and rebuild from scratch")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    parser.add_argument("--if-stale", type=float, metavar="HOURS", default=None,
                        help="do nothing if a sync already ran within this many hours")
    parser.add_argument("--no-reload", action="store_true",
                        help="skip forcing a refresh of subscribed calendars")
    parser.add_argument("--include-events", action="store_true",
                        help="also sync class meetings, normally left to the .ics feed")
    parser.add_argument("--include-past", action="store_true",
                        help="also sync items already past due")
    args = parser.parse_args()

    if args.if_stale is not None and not args.dry_run:
        age = hours_since_last_run()
        if age is not None and age < args.if_stale:
            print("Calendar synced %.1fh ago; nothing to do (--if-stale %g)."
                  % (age, args.if_stale))
            return 0

    alarms = [] if args.no_alarm else sorted(set(args.alarm or DEFAULT_ALARMS), reverse=True)

    try:
        items = bcourses_api.upcoming(days=args.days)
    except bcourses_api.CanvasError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1

    state = load_state()
    now_local = datetime.now().astimezone()
    deletes, creates, unchanged, filtered = build_plan(items, state, args, alarms, now_local)

    if args.dry_run:
        if args.force:
            print("WOULD PURGE   every event tagged [bcourses-id:] in %r" % args.calendar)
        for entry in deletes:
            if "pruned" in entry:
                print("WOULD DELETE  %s  (gone from bCourses)" % entry["pruned"])
        for entry in creates:
            print("WOULD %s  %s  %s" % ("UPDATE" if entry["is_update"] else "CREATE",
                                        entry["start"].strftime("%Y-%m-%d %H:%M"),
                                        entry["title"]))
        print("\n%d to create, %d to update, %d already in sync, %d filtered out."
              % (sum(1 for c in creates if not c["is_update"]),
                 sum(1 for c in creates if c["is_update"]),
                 unchanged, filtered))
        return 0

    if not deletes and not creates and not args.force and args.no_reload:
        mark_run()
        print("Nothing to do: %d event(s) already in sync, %d filtered out."
              % (unchanged, filtered))
        return 0

    try:
        stdout = run_applescript(build_script(
            args.calendar, deletes, creates, args.force, not args.no_reload))
    except subprocess.TimeoutExpired:
        print("error: Calendar did not respond within 5 minutes.", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print("error: %s" % exc, file=sys.stderr)
        if "-1743" in str(exc):
            print("Grant access under System Settings > Privacy & Security > "
                  "Automation, then re-run.", file=sys.stderr)
        return 1

    if args.force:
        state = {}

    by_id = {c["item_id"]: c for c in creates}
    purged = created = updated = removed = failed = 0

    for row in parse_result(stdout):
        kind, item_id = row[0], row[1] if len(row) > 1 else ""
        if kind == "DEL" and item_id == "*":
            purged += 1
        elif kind in ("DEL", "DELFAIL"):
            # A delete that failed because the event is already gone must still
            # clear state, or the item can never be re-created.
            if item_id not in by_id:
                removed += 1
                print("removed  %s" % state.get(item_id, {}).get("title", item_id))
            state.pop(item_id, None)
            if kind == "DELFAIL":
                failed += 1
                print("could not delete %s: %s" % (item_id, row[-1]), file=sys.stderr)
        elif kind == "NEW":
            entry = by_id.get(item_id)
            if not entry:
                continue
            state[item_id] = {
                "uid": row[2] if len(row) > 2 else "",
                "due_utc": entry["due_utc"],
                "title": entry["title"],
                "signature": entry["signature"],
                "synced_at": datetime.now(timezone.utc).isoformat(),
            }
            if entry["is_update"]:
                updated += 1
                print("updated  %s  %s" % (entry["start"].strftime("%Y-%m-%d %H:%M"), entry["title"]))
            else:
                created += 1
                print("created  %s  %s" % (entry["start"].strftime("%Y-%m-%d %H:%M"), entry["title"]))
        elif kind == "NEWFAIL":
            failed += 1
            print("failed to create %s: %s" % (item_id, row[-1]), file=sys.stderr)

    save_state(state)
    mark_run()

    summary = ("\n%d created, %d updated, %d removed, %d already in sync, %d filtered out."
               % (created, updated, removed, unchanged, filtered))
    if purged:
        summary = "\n%d event(s) purged by --force." % purged + summary
    if failed:
        summary += " %d failed." % failed
    print(summary)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
