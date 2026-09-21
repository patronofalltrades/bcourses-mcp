"""
Minimal UC Berkeley bCourses (Canvas) API client.

Standard library only - no pip install required.
The access token is never stored in this file. It is read from, in order:
  1. the CANVAS_TOKEN environment variable
  2. the macOS Keychain (service name "bcourses-token")
"""

import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

BASE_URL = os.environ.get("CANVAS_BASE_URL", "https://bcourses.berkeley.edu").rstrip("/")
KEYCHAIN_SERVICE = os.environ.get("CANVAS_KEYCHAIN_SERVICE", "bcourses-token")

_token_cache = None


class CanvasError(RuntimeError):
    pass


def get_token():
    """Fetch the API token from the environment or the macOS Keychain."""
    global _token_cache
    if _token_cache:
        return _token_cache

    token = os.environ.get("CANVAS_TOKEN")

    if not token:
        try:
            token = subprocess.run(
                ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
        except Exception:
            token = None

    if not token:
        raise CanvasError(
            "No bCourses token found. Store one in the Keychain with:\n"
            '  security add-generic-password -a "$USER" -s bcourses-token -w'
        )

    _token_cache = token
    return token


_NEXT_LINK = re.compile(r'<([^>]+)>\s*;\s*rel="next"')


def api(path, **params):
    """GET a Canvas endpoint, following pagination. Returns a list or dict."""
    url = f"{BASE_URL}/api/v1/{path.lstrip('/')}"
    params.setdefault("per_page", 100)
    url += "?" + urllib.parse.urlencode(params, doseq=True)

    results = []
    while url:
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {get_token()}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.load(resp)
                link_header = resp.headers.get("Link", "") or ""
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise CanvasError(
                    "bCourses rejected the token (401). It is probably revoked or expired."
                ) from exc
            if exc.code == 403:
                raise CanvasError(
                    f"bCourses refused the request (403) for {path}."
                ) from exc
            raise CanvasError(f"bCourses returned HTTP {exc.code} for {path}") from exc

        if not isinstance(payload, list):
            return payload

        results.extend(payload)
        match = _NEXT_LINK.search(link_header)
        url = match.group(1) if match else None

    return results


def _parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _abs_url(path):
    if not path:
        return ""
    return BASE_URL + path if path.startswith("/") else path


def upcoming(days=21, include_done=False):
    """Everything due in the next `days` days across all active courses."""
    now = datetime.now(timezone.utc)
    items = api(
        "planner/items",
        start_date=now.isoformat(),
        end_date=(now + timedelta(days=days)).isoformat(),
    )

    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        plannable = item.get("plannable") or {}
        due = _parse_ts(item.get("plannable_date"))
        if not due:
            continue

        submissions = item.get("submissions")
        submitted = bool(submissions.get("submitted")) if isinstance(submissions, dict) else False
        marked_done = bool((item.get("planner_override") or {}).get("marked_complete"))
        if not include_done and (submitted or marked_done):
            continue

        out.append({
            "id": f"{item.get('plannable_type')}-{plannable.get('id')}",
            "type": item.get("plannable_type") or "item",
            "title": plannable.get("title") or plannable.get("name") or "(untitled)",
            "course": item.get("context_name") or "",
            "due_utc": due.isoformat(),
            "points": plannable.get("points_possible"),
            "url": _abs_url(item.get("html_url", "")),
            "submitted": submitted,
        })

    out.sort(key=lambda x: x["due_utc"])
    return out


def courses():
    """Active course enrollments."""
    raw = api("courses", enrollment_state="active", **{"include[]": ["term"]})
    out = []
    for course in raw:
        if not isinstance(course, dict) or not course.get("id"):
            continue
        out.append({
            "id": course["id"],
            "name": course.get("name") or "",
            "code": course.get("course_code") or "",
            "term": (course.get("term") or {}).get("name", ""),
        })
    return out


def assignments(course_id, bucket="upcoming"):
    """bucket: past | overdue | undated | ungraded | unsubmitted | upcoming | future"""
    raw = api(f"courses/{course_id}/assignments", bucket=bucket)
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        due = _parse_ts(item.get("due_at"))
        out.append({
            "id": f"assignment-{item.get('id')}",
            "title": item.get("name") or "(untitled)",
            "due_utc": due.isoformat() if due else None,
            "points": item.get("points_possible"),
            "url": item.get("html_url") or "",
        })
    out.sort(key=lambda x: (x["due_utc"] is None, x["due_utc"] or ""))
    return out


def whoami():
    """Sanity check that the token works."""
    me = api("users/self")
    return {"id": me.get("id"), "name": me.get("name"), "login": me.get("login_id")}


# ---------------------------------------------------------------------------
# HTML -> text
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    """Flatten Canvas rich-text HTML into readable plain text."""

    DROP = {"script", "style", "head", "noscript"}
    BLOCK = {
        "p", "div", "br", "li", "tr", "table", "section", "article",
        "ul", "ol", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "hr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._dropping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.DROP:
            self._dropping += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.DROP:
            self._dropping = max(0, self._dropping - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._dropping:
            self.parts.append(data)


_BLANKS = re.compile(r"\n\s*\n\s*\n+")
_SPACES = re.compile(r"[ \t\xa0]+")
FILE_REF = re.compile(r"/files/(\d+)")


def html_to_text(html):
    """Plain text from a Canvas HTML body. Collapses runs of blank lines."""
    if not html:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # Malformed markup: fall back to a blunt tag strip rather than failing.
        return _BLANKS.sub("\n\n", _SPACES.sub(" ", re.sub(r"<[^>]+>", " ", html))).strip()
    text = "".join(parser.parts)
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANKS.sub("\n\n", text).strip()


def embedded_file_ids(html):
    """Canvas file IDs referenced anywhere in an HTML body, in order."""
    seen, out = set(), []
    for fid in FILE_REF.findall(html or ""):
        if fid not in seen:
            seen.add(fid)
            out.append(int(fid))
    return out


# ---------------------------------------------------------------------------
# Course content
# ---------------------------------------------------------------------------

def modules(course_id):
    """Modules with their items.

    This is the reliable spine of a course. Instructors routinely disable the
    Files and Pages tabs (which makes those index endpoints 403 or 404), but
    the modules endpoint has stayed readable on every course tested.
    """
    raw = api(f"courses/{course_id}/modules", **{"include[]": ["items"]})
    if not isinstance(raw, list):
        return []
    out = []
    for mod in raw:
        if not isinstance(mod, dict):
            continue
        items = []
        for item in mod.get("items") or []:
            if not isinstance(item, dict):
                continue
            items.append({
                "type": item.get("type") or "",
                "title": item.get("title") or "",
                "page_url": item.get("page_url"),
                "content_id": item.get("content_id"),
                "external_url": item.get("external_url"),
                "url": _abs_url(item.get("html_url") or ""),
            })
        out.append({
            "module": mod.get("name") or "(untitled)",
            "position": mod.get("position"),
            "items": items,
        })
    return out


def page(course_id, page_url):
    """One wiki page, by its URL slug.

    Fetching a page directly works even where `courses/:id/pages` returns 404,
    so always reach pages through `modules()` rather than the index.
    """
    raw = api(f"courses/{course_id}/pages/{urllib.parse.quote(str(page_url), safe='')}")
    if not isinstance(raw, dict):
        return {}
    body = raw.get("body") or ""
    return {
        "title": raw.get("title") or "",
        "page_url": raw.get("url") or page_url,
        "updated_at": raw.get("updated_at"),
        "text": html_to_text(body),
        "file_ids": embedded_file_ids(body),
        "url": _abs_url(raw.get("html_url") or ""),
    }


def course_pages(course_id):
    """Every page reachable through the course's modules, with text.

    Returns [] rather than raising when the Modules tab is closed. Instructors
    change these permissions mid-term - one course here went from readable to
    403 in two days - so callers must degrade instead of failing.
    """
    out = []
    try:
        found = modules(course_id)
    except CanvasError:
        return []
    for mod in found:
        for item in mod["items"]:
            if item["type"] == "Page" and item.get("page_url"):
                try:
                    got = page(course_id, item["page_url"])
                except CanvasError:
                    continue
                if got:
                    got["module"] = mod["module"]
                    out.append(got)
    return out


def syllabus_body(course_id):
    """Raw syllabus HTML. Empty string when the instructor hasn't posted one."""
    raw = api(f"courses/{course_id}", **{"include[]": ["syllabus_body"]})
    if not isinstance(raw, dict):
        return ""
    return raw.get("syllabus_body") or ""


def syllabus(course_id):
    """Syllabus body as text. Empty string when the instructor hasn't posted one."""
    return html_to_text(syllabus_body(course_id))


def announcements(course_id, days=60):
    """Recent announcements for one course, newest first."""
    now = datetime.now(timezone.utc)
    raw = api(
        "announcements",
        **{
            "context_codes[]": [f"course_{course_id}"],
            "start_date": (now - timedelta(days=days)).date().isoformat(),
            "end_date": now.date().isoformat(),
        },
    )
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        body = item.get("message") or ""
        out.append({
            "title": item.get("title") or "(untitled)",
            "posted_at": item.get("posted_at"),
            "author": (item.get("author") or {}).get("display_name", ""),
            "text": html_to_text(body),
            "file_ids": embedded_file_ids(body),
            "url": item.get("html_url") or "",
        })
    out.sort(key=lambda x: x["posted_at"] or "", reverse=True)
    return out


def assignment_detail(course_id, assignment_id):
    """Full assignment record including the description instructors actually write in."""
    raw = api(f"courses/{course_id}/assignments/{assignment_id}")
    if not isinstance(raw, dict):
        return {}
    body = raw.get("description") or ""
    due = _parse_ts(raw.get("due_at"))
    return {
        "id": raw.get("id"),
        "title": raw.get("name") or "(untitled)",
        "due_utc": due.isoformat() if due else None,
        "points": raw.get("points_possible"),
        "submission_types": raw.get("submission_types") or [],
        "instructions": html_to_text(body),
        "file_ids": embedded_file_ids(body),
        "url": raw.get("html_url") or "",
    }


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

CACHE_DIR = Path(
    os.environ.get("BCOURSES_CACHE", Path.home() / ".bcourses-sync" / "files")
)


def file_meta(file_id):
    """Metadata for one file, including a short-lived signed download URL.

    Works for files the student can see even when the course's file index is
    403 - permission is evaluated per file, not per tab.
    """
    raw = api(f"files/{file_id}")
    if not isinstance(raw, dict):
        return {}
    return {
        "id": raw.get("id"),
        "name": raw.get("display_name") or raw.get("filename") or f"file-{file_id}",
        "content_type": raw.get("content-type") or raw.get("content_type") or "",
        "size": raw.get("size") or 0,
        "updated_at": raw.get("updated_at"),
        "download_url": raw.get("url") or "",
        "url": _abs_url(raw.get("html_url") or ""),
    }


DISCOVERY_DIR = CACHE_DIR.parent / "discovery"
DISCOVERY_TTL = 6 * 3600


def _cached_discovery(course_id, refresh):
    """Read a cached file listing if it is fresh enough."""
    path = DISCOVERY_DIR / f"course-{course_id}.json"
    if refresh or not path.exists():
        return None, path
    age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    if age > DISCOVERY_TTL:
        return None, path
    try:
        return json.loads(path.read_text()), path
    except (json.JSONDecodeError, OSError):
        return None, path


def course_files(course_id, include_embedded=True, refresh=False):
    """Files for a course, merging the index with everything embedded in content.

    The plain index (`courses/:id/files`) is 403 on most courses here because
    the Files tab is hidden. Embedded references recover what that misses:
    pages, announcements and the syllabus body all link files by ID, and those
    IDs stay individually fetchable.
    """
    if include_embedded:
        cached, cache_path = _cached_discovery(course_id, refresh)
        if cached is not None:
            return cached
    else:
        cache_path = None

    found, order = {}, []

    def add(entry, source):
        fid = entry.get("id")
        if not fid:
            return
        if fid in found:
            if source not in found[fid]["sources"]:
                found[fid]["sources"].append(source)
            return
        entry["sources"] = [source]
        found[fid] = entry
        order.append(fid)

    try:
        raw = api(f"courses/{course_id}/files")
        for item in raw if isinstance(raw, list) else []:
            if isinstance(item, dict):
                add({
                    "id": item.get("id"),
                    "name": item.get("display_name") or item.get("filename") or "",
                    "content_type": item.get("content-type") or item.get("content_type") or "",
                    "size": item.get("size") or 0,
                    "updated_at": item.get("updated_at"),
                    "url": _abs_url(item.get("html_url") or ""),
                }, "files_tab")
    except CanvasError:
        pass  # Files tab hidden; embedded discovery below is the fallback.

    if include_embedded:
        refs = []
        for pg in course_pages(course_id):
            refs.extend((fid, f"page:{pg['page_url']}") for fid in pg["file_ids"])
        try:
            for ann in announcements(course_id):
                refs.extend((fid, "announcement") for fid in ann["file_ids"])
        except CanvasError:
            pass
        # Instructors attach readings to the syllabus body itself, which is not a
        # page and so is missed by the walk above. New Venture Finance posts its
        # own syllabus PDF and a required reading there and nowhere else.
        try:
            refs.extend(
                (fid, "syllabus") for fid in embedded_file_ids(syllabus_body(course_id))
            )
        except CanvasError:
            pass
        for fid, source in refs:
            if fid in found:
                if source not in found[fid]["sources"]:
                    found[fid]["sources"].append(source)
                continue
            try:
                meta = file_meta(fid)
            except CanvasError:
                continue
            if meta:
                meta.pop("download_url", None)
                add(meta, source)

    result = [found[fid] for fid in order]

    # File records carry no html_url, so build the browser link from the course.
    for entry in result:
        if not entry.get("url"):
            entry["url"] = f"{BASE_URL}/courses/{course_id}/files/{entry['id']}"

    # Discovery walks every page and resolves each file ID one at a time, which
    # runs ~25s on a large reading list. Cache it so repeat calls are instant.
    if cache_path is not None:
        try:
            DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(result, indent=2))
        except OSError:
            pass

    return result


def download_file(file_id, dest_dir=None, overwrite=False, max_mb=50):
    """Download one file into the local cache. Returns the path on disk.

    Cached by file ID, so re-downloading is free and the same ID always maps to
    the same path.
    """
    meta = file_meta(file_id)
    if not meta or not meta.get("download_url"):
        raise CanvasError(f"No downloadable URL for file {file_id}.")

    size_mb = (meta.get("size") or 0) / 1e6
    if size_mb > max_mb:
        raise CanvasError(
            f"File {file_id} is {size_mb:.1f} MB, above the {max_mb} MB limit. "
            "Raise max_mb to fetch it anyway."
        )

    folder = Path(dest_dir) if dest_dir else CACHE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", meta["name"]).strip() or f"file-{file_id}"
    path = folder / f"{file_id}-{safe}"

    if path.exists() and not overwrite:
        return path

    # The signed URL carries its own auth; sending the bearer token too can 401.
    req = urllib.request.Request(meta["download_url"], headers={"Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, open(path, "wb") as out:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                out.write(chunk)
    except urllib.error.HTTPError as exc:
        raise CanvasError(f"Download of file {file_id} failed: HTTP {exc.code}") from exc
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise CanvasError(f"Download of file {file_id} failed: {exc}") from exc

    return path


if __name__ == "__main__":
    import sys

    command = sys.argv[1] if len(sys.argv) > 1 else "whoami"
    try:
        if command == "whoami":
            print(json.dumps(whoami(), indent=2))
        elif command == "courses":
            print(json.dumps(courses(), indent=2))
        elif command == "upcoming":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 21
            print(json.dumps(upcoming(days), indent=2))
        else:
            print("usage: bcourses_api.py [whoami|courses|upcoming [days]]")
    except CanvasError as exc:
        print(f"error: {exc}")
        raise SystemExit(1)
