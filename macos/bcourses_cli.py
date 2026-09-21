#!/usr/bin/env python3
"""
JSON CLI over the same bCourses functions the MCP server exposes.

Why this exists: a stdio MCP server can only be launched by a client running on
this Mac. A cloud Cowork session cannot spawn it, but it can run a shell here.
This file gives that shell the identical tool surface, one subcommand per tool,
JSON on stdout, so there is one source of truth rather than two clients.

Usage:
    python3 bcourses_cli.py tools            # the surface, machine readable
    python3 bcourses_cli.py upcoming --days 14
    python3 bcourses_cli.py content 1234567

Every command prints JSON. Failures print {"error": ...} and exit 1, so a
caller can branch on the exit code without parsing prose.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bcourses_api  # noqa: E402

VENV_PYTHON = HERE / ".venv" / "bin" / "python"
NEEDS_EXTRACT = {"read", "search"}


def emit(value):
    """Print JSON and exit clean."""
    json.dump(value, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    sys.exit(0)


def fail(message, **extra):
    """Print a structured error and exit 1."""
    payload = {"error": str(message)}
    payload.update(extra)
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    sys.exit(1)


def degrade(exc, course_id=None):
    """Turn a Canvas failure into an answer rather than a stack trace.

    A 403 means "no longer enrolled" at least as often as "tab hidden", and the
    endpoint gives no way to tell them apart, so say both.
    """
    text = str(exc)
    if "403" in text and course_id is not None:
        fail(
            "No access to course %s." % course_id,
            hint="Either the tab is hidden or the enrollment ended. "
                 "Run `courses` to see whether it is still active.",
            course_id=course_id,
        )
    if "401" in text:
        fail(
            "bCourses rejected the token.",
            hint="It has expired or been revoked. Replace it with: "
                 'security add-generic-password -U -a "$USER" -s bcourses-token -w',
        )
    fail(text, course_id=course_id)


def reexec_in_venv(argv):
    """Text extraction needs the 3.12 venv; the rest must stay stdlib-only."""
    if not VENV_PYTHON.exists():
        fail(
            "Text extraction needs the virtualenv.",
            hint="Expected %s. Recreate with: uv venv --python 3.12" % VENV_PYTHON,
        )
    result = subprocess.run([str(VENV_PYTHON), str(Path(__file__).resolve())] + argv)
    sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# Commands. One per MCP tool, same names where the tool name is already clear.
# ---------------------------------------------------------------------------

TOOLS = [
    ("whoami", "Verify the token and report whose account it is."),
    ("courses", "Active courses for the current term, with numeric IDs."),
    ("upcoming", "Everything due in the next N days, across all courses."),
    ("assignments", "Assignments for one course, by bucket."),
    ("content", "A course's modules and their items. Start here."),
    ("page", "One course page as text, plus the file IDs it embeds."),
    ("syllabus", "Syllabus text, where the instructor posted one."),
    ("announcements", "Announcements for a course, newest first."),
    ("assignment", "Full instructions for one assignment."),
    ("files", "Files in a course, including ones the Files tab hides."),
    ("download", "Fetch one file into the local cache."),
    ("read", "Extract text from a PDF/DOCX/PPTX/XLSX file. Needs the venv."),
    ("search", "Where a term appears in a course, with snippets. Needs the venv."),
    ("calendar-sync", "Reconcile deadlines into Apple Calendar. Preview unless --apply."),
    ("reminders-sync", "Create macOS Reminders for deadlines. Preview unless --apply."),
]


def cmd_tools(a):
    emit({"tools": [{"name": n, "description": d} for n, d in TOOLS]})


def cmd_whoami(a):
    try:
        emit(bcourses_api.whoami())
    except bcourses_api.CanvasError as exc:
        degrade(exc)


def cmd_courses(a):
    try:
        emit(bcourses_api.courses())
    except bcourses_api.CanvasError as exc:
        degrade(exc)


def cmd_upcoming(a):
    try:
        items = bcourses_api.upcoming(days=a.days, include_done=a.include_done)
    except bcourses_api.CanvasError as exc:
        degrade(exc)
    emit({"days": a.days, "count": len(items), "items": items})


def cmd_assignments(a):
    try:
        emit(bcourses_api.assignments(a.course_id, bucket=a.bucket))
    except bcourses_api.CanvasError as exc:
        degrade(exc, a.course_id)


def cmd_content(a):
    try:
        outline = bcourses_api.modules(a.course_id)
    except bcourses_api.CanvasError as exc:
        degrade(exc, a.course_id)
    if not outline:
        emit({"course_id": a.course_id, "modules": [],
              "note": "No modules published in this course yet."})
    emit({"course_id": a.course_id, "modules": outline})


def cmd_page(a):
    try:
        got = bcourses_api.page(a.course_id, a.page_url)
    except bcourses_api.CanvasError as exc:
        degrade(exc, a.course_id)
    if not got:
        fail("No page '%s' in course %s." % (a.page_url, a.course_id))
    if a.max_chars and len(got.get("text", "")) > a.max_chars:
        got["text"] = got["text"][:a.max_chars]
        got["truncated"] = True
    emit(got)


def cmd_syllabus(a):
    try:
        text = bcourses_api.syllabus(a.course_id)
    except bcourses_api.CanvasError as exc:
        degrade(exc, a.course_id)
    emit({"course_id": a.course_id, "syllabus": text or None,
          "note": None if text else "No syllabus posted."})


def cmd_announcements(a):
    try:
        items = bcourses_api.announcements(a.course_id, days=a.days)
    except bcourses_api.CanvasError as exc:
        degrade(exc, a.course_id)
    emit({"course_id": a.course_id, "days": a.days,
          "count": len(items), "announcements": items})


def cmd_assignment(a):
    try:
        got = bcourses_api.assignment_detail(a.course_id, a.assignment_id)
    except bcourses_api.CanvasError as exc:
        degrade(exc, a.course_id)
    if not got:
        fail("Assignment %s not found in course %s." % (a.assignment_id, a.course_id))
    emit(got)


def cmd_files(a):
    try:
        files = bcourses_api.course_files(
            a.course_id, include_embedded=not a.no_embedded, refresh=a.refresh
        )
    except bcourses_api.CanvasError as exc:
        degrade(exc, a.course_id)
    emit({"course_id": a.course_id, "count": len(files), "files": files})


def cmd_download(a):
    try:
        path = bcourses_api.download_file(a.file_id, max_mb=a.max_mb)
    except bcourses_api.CanvasError as exc:
        degrade(exc)
    emit({"file_id": a.file_id, "path": str(path), "size": path.stat().st_size})


def cmd_read(a):
    import bcourses_extract
    try:
        emit(bcourses_extract.read_canvas_file(
            a.file_id, max_chars=a.max_chars or None, max_pages=a.max_pages or None
        ))
    except (bcourses_api.CanvasError, bcourses_extract.ExtractError) as exc:
        degrade(exc)


def cmd_search(a):
    import bcourses_extract
    try:
        hits = bcourses_extract.search_course(
            a.query, a.course_id, include_files=a.include_files
        )
    except (bcourses_api.CanvasError, bcourses_extract.ExtractError) as exc:
        degrade(exc, a.course_id)
    emit({"query": a.query, "course_id": a.course_id,
          "count": len(hits), "hits": hits})


def _run_sync(script, args, apply_it):
    """Sync scripts preview by default; writing is the opt-in."""
    cmd = [sys.executable, str(HERE / script)] + args
    if not apply_it:
        cmd.append("--dry-run")
    done = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
    emit({
        "script": script,
        "applied": bool(apply_it),
        "exit_code": done.returncode,
        "output": (done.stdout + done.stderr).strip() or "No output.",
    })


def cmd_calendar_sync(a):
    args = ["--days", str(a.days)]
    if a.force:
        args.append("--force")
    _run_sync("sync_calendar.py", args, a.apply)


def cmd_reminders_sync(a):
    _run_sync("sync_reminders.py", ["--days", str(a.days), "--lead", str(a.lead)], a.apply)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser(
        prog="bcourses_cli.py",
        description="JSON access to bCourses. Run `tools` for the surface.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, fn, help_text):
        s = sub.add_parser(name, help=help_text)
        s.set_defaults(fn=fn)
        return s

    add("tools", cmd_tools, "List every command as JSON.")
    add("whoami", cmd_whoami, "Verify the token.")
    add("courses", cmd_courses, "Active courses with IDs.")

    s = add("upcoming", cmd_upcoming, "Deadlines in the next N days.")
    s.add_argument("--days", type=int, default=21)
    s.add_argument("--include-done", action="store_true")

    s = add("assignments", cmd_assignments, "Assignments for one course.")
    s.add_argument("course_id", type=int)
    s.add_argument("--bucket", default="upcoming",
                   choices=["past", "overdue", "undated", "ungraded",
                            "unsubmitted", "upcoming", "future"])

    s = add("content", cmd_content, "Modules and items for one course.")
    s.add_argument("course_id", type=int)

    s = add("page", cmd_page, "One page as text.")
    s.add_argument("course_id", type=int)
    s.add_argument("page_url")
    s.add_argument("--max-chars", type=int, default=20000)

    s = add("syllabus", cmd_syllabus, "Syllabus text.")
    s.add_argument("course_id", type=int)

    s = add("announcements", cmd_announcements, "Recent announcements.")
    s.add_argument("course_id", type=int)
    s.add_argument("--days", type=int, default=60)

    s = add("assignment", cmd_assignment, "Full assignment instructions.")
    s.add_argument("course_id", type=int)
    s.add_argument("assignment_id", type=int)

    s = add("files", cmd_files, "Files, including hidden-tab ones.")
    s.add_argument("course_id", type=int)
    s.add_argument("--no-embedded", action="store_true",
                   help="Skip the modules/pages/syllabus walk.")
    s.add_argument("--refresh", action="store_true",
                   help="Rebuild the 6-hour discovery cache.")

    s = add("download", cmd_download, "Cache one file locally.")
    s.add_argument("file_id", type=int)
    s.add_argument("--max-mb", type=float, default=50)

    s = add("read", cmd_read, "Extract text from a file.")
    s.add_argument("file_id", type=int)
    s.add_argument("--max-chars", type=int, default=40000)
    s.add_argument("--max-pages", type=int, default=0)

    s = add("search", cmd_search, "Find a term inside a course.")
    s.add_argument("query")
    s.add_argument("course_id", type=int)
    s.add_argument("--include-files", action="store_true")

    s = add("calendar-sync", cmd_calendar_sync, "Reconcile Apple Calendar.")
    s.add_argument("--days", type=int, default=30)
    s.add_argument("--force", action="store_true",
                   help="Purge and rebuild. Manual repair only, never scheduled.")
    s.add_argument("--apply", action="store_true", help="Write. Otherwise preview.")

    s = add("reminders-sync", cmd_reminders_sync, "Create macOS Reminders.")
    s.add_argument("--days", type=int, default=21)
    s.add_argument("--lead", type=float, default=24)
    s.add_argument("--apply", action="store_true", help="Write. Otherwise preview.")

    return p


def main():
    argv = sys.argv[1:]
    if argv and argv[0] in NEEDS_EXTRACT:
        try:
            import bcourses_extract  # noqa: F401
        except ImportError:
            reexec_in_venv(argv)
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
