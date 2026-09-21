#!/usr/bin/env python3
"""
Download recent bCourses course materials into per-class folders.

Sorts files into  <Classes>/<Course Name>/[Week N]/  and refuses to create
duplicates: a file already on disk is never fetched twice, whether it is
matched by Canvas file id, by name, or by content hash under a different name.

Standard library only. Run  python3 download_materials.py --dry-run  to preview.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bcourses_api as B

STATE_PATH = os.path.expanduser("~/.bcourses-sync/materials.json")
CONFIG_PATH = os.path.expanduser("~/.bcourses-sync/config.json")

# Where the per-class folders live. Kept out of this file on purpose: the real
# path is personal, so it comes from the environment or from a local config
# outside the repo. Order: $BCOURSES_CLASSES_DIR, then config.json, then a
# neutral default.
DEFAULT_ROOT = "~/Documents/Classes"


def classes_root():
    env = os.environ.get("BCOURSES_CLASSES_DIR")
    if env:
        return os.path.expanduser(env)
    try:
        with open(CONFIG_PATH) as fh:
            configured = json.load(fh).get("classes_dir")
        if configured:
            return os.path.expanduser(configured)
    except (OSError, ValueError):
        pass
    return os.path.expanduser(DEFAULT_ROOT)

# Canvas course id -> (folder name, group files into Week N subfolders?)
#
# YOU MUST EDIT THIS. Run `python3 bcourses_cli.py courses` to get your own
# course IDs, then map each to the folder name you want on disk. Set the second
# value True for courses that post material week by week.
#
# Courses not listed here are discovered at runtime and reported, not
# downloaded, so a new enrollment never silently scatters files into a guessed
# folder name. An empty map is therefore safe: the first run tells you every
# course it found, and you fill this in from that list.
#
# Example:
#     COURSES = {
#         1234567: ("New Venture Finance", True),
#         1234568: ("Intro to Code", False),
#     }
COURSES = {}

# Enrolled, but nothing worth syncing — compliance training, orientation shells.
# Add the course IDs you want skipped silently rather than reported each run.
IGNORE_COURSES = set()

# Page decoration and inline screenshots, not course documents.
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".svg"}

FILE_HREF = re.compile(
    r'href="(https://bcourses\.berkeley\.edu/courses/(\d+)/files/(\d+)[^"]*)"'
)
WEEK_IN_TITLE = re.compile(r"week\s*(\d+)", re.I)


# --------------------------------------------------------------------------- #
# helpers


def safe(name):
    return re.sub(r"[/\x00]", "-", name).strip()


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def newest_ts(f):
    stamps = [parse_ts(f.get("created_at")), parse_ts(f.get("updated_at"))]
    stamps = [s for s in stamps if s]
    return max(stamps) if stamps else None


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_state():
    try:
        with open(STATE_PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)


# --------------------------------------------------------------------------- #
# duplicate detection


class Existing:
    """Index of what is already on disk, so nothing is downloaded twice."""

    def __init__(self, root):
        self.by_name = {}   # lowercased basename -> [paths]
        self.by_size = {}   # size in bytes      -> [paths]
        self._hashes = {}   # path               -> sha256, computed lazily
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                if fn.startswith("."):
                    continue
                path = os.path.join(dirpath, fn)
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                self.by_name.setdefault(fn.lower(), []).append(path)
                self.by_size.setdefault(size, []).append(path)

    def name_match(self, name):
        hits = self.by_name.get(os.path.basename(name).lower())
        return hits[0] if hits else None

    def content_match(self, path, size):
        """A file with identical bytes already filed under a different name."""
        candidates = self.by_size.get(size, [])
        if not candidates:
            return None
        digest = sha256(path)
        for other in candidates:
            if other not in self._hashes:
                try:
                    self._hashes[other] = sha256(other)
                except OSError:
                    continue
            if self._hashes[other] == digest:
                return other
        return None

    def add(self, path):
        self.by_name.setdefault(os.path.basename(path).lower(), []).append(path)
        try:
            self.by_size.setdefault(os.path.getsize(path), []).append(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# discovery


def files_tab(course_id):
    """Courses that expose the Files tab."""
    try:
        raw = B.api(f"courses/{course_id}/files", sort="updated_at", order="desc")
    except B.CanvasError:
        return []
    return [(f, "") for f in raw if isinstance(f, dict)]


def files_from_pages(course_id, unreachable):
    """Courses that hide Files: materials are linked from Modules > Pages."""
    try:
        modules = B.api(f"courses/{course_id}/modules", **{"include[]": ["items"]})
    except B.CanvasError:
        # Modules tab closed. The syllabus may still carry files, so fall through
        # rather than returning early.
        modules = []

    seen, out = set(), []
    for module in modules:
        for item in module.get("items") or []:
            if item.get("type") != "Page" or not item.get("page_url"):
                continue
            try:
                page = B.api(f"courses/{course_id}/pages/{item['page_url']}")
            except B.CanvasError:
                continue

            title = item.get("title") or ""
            match = WEEK_IN_TITLE.search(title)
            week = f"Week {match.group(1)}" if match else "Course Materials"
            body = (page.get("body") or "").replace("&amp;", "&")

            for link, linked_course, file_id in FILE_HREF.findall(body):
                if file_id in seen:
                    continue
                seen.add(file_id)
                try:
                    meta = B.api(f"files/{file_id}")
                except B.CanvasError:
                    # Instructor linked a file from a course we are not in.
                    unreachable.append(
                        {"page": title, "link": link, "course": linked_course}
                    )
                    continue
                out.append((meta, week))

    out.extend(files_from_syllabus(course_id, seen, unreachable))
    return out


def files_from_syllabus(course_id, seen, unreachable):
    """Readings attached to the syllabus body, which is not a page.

    New Venture Finance posts its own syllabus PDF and a required Class 1
    reading here and nowhere else, so the Modules walk above misses both.
    """
    try:
        body = B.syllabus_body(course_id).replace("&amp;", "&")
    except B.CanvasError:
        return []

    out = []
    for link, linked_course, file_id in FILE_HREF.findall(body):
        if file_id in seen:
            continue
        seen.add(file_id)
        try:
            meta = B.api(f"files/{file_id}")
        except B.CanvasError:
            unreachable.append(
                {"page": "Syllabus", "link": link, "course": linked_course}
            )
            continue
        out.append((meta, "Course Materials"))
    return out


def collect(cutoff, unreachable, unknown):
    """Everything newer than `cutoff`, as (course folder, subfolder, metadata)."""
    plan = []
    for course in B.courses():
        cid = course["id"]
        if cid in IGNORE_COURSES:
            continue
        if cid not in COURSES:
            unknown.append(course)
            continue

        folder, by_week = COURSES[cid]
        found = files_from_pages(cid, unreachable) if by_week else files_tab(cid)

        for meta, week in found:
            name = meta.get("display_name") or ""
            if not name or os.path.splitext(name)[1].lower() in IMAGE_EXT:
                continue
            when = newest_ts(meta)
            if not when or when < cutoff:
                continue
            plan.append(
                {
                    "id": str(meta.get("id")),
                    "course": folder,
                    "sub": week if by_week else "",
                    "name": name,
                    "url": meta.get("url"),  # pre-signed; the page href is an HTML wrapper
                    "size": meta.get("size") or 0,
                    "date": when.date().isoformat(),
                    "updated_at": meta.get("updated_at") or "",
                }
            )
    plan.sort(key=lambda r: (r["course"], r["sub"], r["date"]))
    return plan


# --------------------------------------------------------------------------- #
# download


def fetch(url, dest_dir):
    """Download to a temp file. Returns (path, is_html_wrapper)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        ctype = resp.headers.get("Content-Type", "") or ""
        fd, tmp = tempfile.mkstemp(dir=dest_dir, prefix=".bc-")
        with os.fdopen(fd, "wb") as out:
            shutil.copyfileobj(resp, out)

    with open(tmp, "rb") as fh:
        head = fh.read(64).lstrip()
    if ctype.startswith("text/html") or head.startswith(b"<!DOCTYPE html"):
        return tmp, True
    return tmp, False


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=30,
                    help="only files created or updated in this window (default 30)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be downloaded, write nothing")
    ap.add_argument("--root", default=None, help="destination Classes folder")
    args = ap.parse_args()
    if args.root is None:
        args.root = classes_root()

    if not os.path.isdir(args.root):
        print(f"error: destination not found: {args.root}")
        print("Set BCOURSES_CLASSES_DIR, or put {\"classes_dir\": \"...\"} in "
              f"{CONFIG_PATH}, or pass --root.")
        return 1

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    unreachable, unknown = [], []
    plan = collect(cutoff, unreachable, unknown)

    state = load_state()
    existing = Existing(args.root)
    saved = dupes = skipped = failed = 0

    for row in plan:
        dest_dir = os.path.join(args.root, row["course"], row["sub"]) if row["sub"] \
            else os.path.join(args.root, row["course"])
        target = os.path.join(dest_dir, safe(row["name"]))
        rel = os.path.relpath(target, args.root)

        # 1. Seen this exact Canvas file before, unchanged, still on disk.
        prior = state.get(row["id"])
        if prior and prior.get("updated_at") == row["updated_at"] \
                and os.path.exists(prior.get("path", "")):
            skipped += 1
            continue

        # 2. Same filename already filed somewhere under Classes.
        hit = existing.name_match(row["name"])
        if hit and not prior:
            print(f"  = have     {os.path.relpath(hit, args.root)}")
            dupes += 1
            state[row["id"]] = {"path": hit, "updated_at": row["updated_at"],
                                "name": row["name"]}
            continue

        if args.dry_run:
            print(f"  + would get [{row['date']}] {round(row['size']/1024):>6}KB  {rel}")
            saved += 1
            continue

        os.makedirs(dest_dir, exist_ok=True)
        try:
            tmp, is_html = fetch(row["url"], dest_dir)
        except Exception as exc:
            print(f"  ! failed   {rel}: {exc}")
            failed += 1
            continue

        if is_html:
            os.unlink(tmp)
            print(f"  ! wrapper  {rel}: Canvas returned a preview page, not the file")
            failed += 1
            continue

        # 3. Identical bytes already on disk under a different name.
        twin = existing.content_match(tmp, os.path.getsize(tmp))
        if twin and os.path.abspath(twin) != os.path.abspath(target):
            os.unlink(tmp)
            print(f"  = same as  {os.path.relpath(twin, args.root)}  (skipped {row['name']})")
            dupes += 1
            state[row["id"]] = {"path": twin, "updated_at": row["updated_at"],
                                "name": row["name"]}
            continue

        revised = os.path.exists(target)
        os.replace(tmp, target)
        os.chmod(target, 0o644)
        existing.add(target)
        state[row["id"]] = {"path": target, "updated_at": row["updated_at"],
                            "name": row["name"]}
        verb = "updated" if revised else "saved  "
        print(f"  + {verb}  {rel}  ({round(os.path.getsize(target)/1024)}KB)")
        saved += 1

    if not args.dry_run:
        save_state(state)

    verb = "would download" if args.dry_run else "downloaded"
    print(f"\n{saved} {verb}, {dupes} already on disk, {skipped} unchanged since last run"
          + (f", {failed} failed" if failed else ""))

    if unknown:
        print("\nEnrolled courses with no folder mapping (add them to COURSES):")
        for c in unknown:
            print(f"  ? {c['id']}  {c['code']}  {c['name']}")
    if unreachable:
        print(f"\n{len(unreachable)} link(s) point to a course you are not enrolled in:")
        for u in unreachable:
            print(f"  ! {u['page']} -> {u['link']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except B.CanvasError as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
