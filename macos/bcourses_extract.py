"""
Text extraction for files downloaded from bCourses.

Unlike `bcourses_api`, this module has dependencies and therefore requires the
project venv (Python 3.10+):

    uv pip install pypdf python-docx python-pptx openpyxl

The split is deliberate. `bcourses_api` and `sync_reminders` stay standard
library only so the scheduled sync can keep running on macOS system Python 3.9,
which cannot install these packages. Nothing here is imported by the sync path.
"""

import json
import logging
import re
from pathlib import Path

import bcourses_api

# pypdf logs a warning per malformed cross-reference entry. Course PDFs trip this
# constantly and still extract fine, so keep the noise out of the MCP server's log.
logging.getLogger("pypdf").setLevel(logging.ERROR)

# Extensions we can turn into text, mapped to the reader used below.
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".py", ".rtf"}
HTML_SUFFIXES = {".html", ".htm"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".heic", ".webp", ".bmp", ".tiff"}


class ExtractError(RuntimeError):
    pass


def _pdf(path, max_pages):
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - venv guard
        raise ExtractError("pypdf is not installed. Run: uv pip install pypdf") from exc

    reader = PdfReader(str(path))
    total = len(reader.pages)
    limit = min(total, max_pages) if max_pages else total
    chunks = []
    for i in range(limit):
        try:
            chunks.append(reader.pages[i].extract_text() or "")
        except Exception:
            chunks.append("")  # One broken page shouldn't lose the whole document.
    return "\n\n".join(chunks), {"pages": total, "pages_read": limit}


def _docx(path, _max_pages):
    try:
        import docx
    except ImportError as exc:
        raise ExtractError("python-docx is not installed.") from exc

    doc = docx.Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts), {"paragraphs": len(doc.paragraphs), "tables": len(doc.tables)}


def _pptx(path, max_pages):
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise ExtractError("python-pptx is not installed.") from exc

    prs = Presentation(str(path))
    slides = list(prs.slides)
    limit = min(len(slides), max_pages) if max_pages else len(slides)
    out = []
    for n, slide in enumerate(slides[:limit], 1):
        lines = [f"--- Slide {n} ---"]
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                lines.append(shape.text_frame.text.strip())
        # Speaker notes often carry the actual argument, not just the headline.
        if slide.has_notes_slide:
            notes = (slide.notes_slide.notes_text_frame.text or "").strip()
            if notes:
                lines.append(f"[notes] {notes}")
        out.append("\n".join(lines))
    return "\n\n".join(out), {"slides": len(slides), "slides_read": limit}


def _xlsx(path, _max_pages):
    try:
        import openpyxl
    except ImportError as exc:
        raise ExtractError("openpyxl is not installed.") from exc

    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    out = []
    sheet_count = len(wb.worksheets)
    for sheet in wb.worksheets:
        out.append(f"--- Sheet: {sheet.title} ---")
        for row in sheet.iter_rows(values_only=True):
            cells = ["" if v is None else str(v) for v in row]
            if any(c.strip() for c in cells):
                out.append(" | ".join(cells).rstrip(" |"))
    wb.close()  # Count captured first: worksheets is unavailable after close.
    return "\n".join(out), {"sheets": sheet_count}


def _plain(path, _max_pages):
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in HTML_SUFFIXES:
        return bcourses_api.html_to_text(raw), {}
    return raw, {}


READERS = {".pdf": _pdf, ".docx": _docx, ".pptx": _pptx, ".xlsx": _xlsx, ".xlsm": _xlsx}


def extract_text(path, max_chars=None, max_pages=None):
    """Extract text from a local file. Returns a dict, never raises on content."""
    path = Path(path)
    if not path.exists():
        raise ExtractError(f"No such file: {path}")

    suffix = path.suffix.lower()
    result = {"path": str(path), "name": path.name, "kind": suffix.lstrip(".") or "unknown"}

    if suffix in IMAGE_SUFFIXES:
        result.update(text="", note="Image file - no text layer. Read it directly instead.")
        return result

    reader = READERS.get(suffix)
    if reader is None and suffix in TEXT_SUFFIXES | HTML_SUFFIXES:
        reader = _plain
    if reader is None:
        result.update(text="", note=f"No extractor for '{suffix}' files.")
        return result

    text, meta = reader(path, max_pages)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()

    result["chars"] = len(text)
    result.update(meta)
    if max_chars and len(text) > max_chars:
        result["text"] = text[:max_chars]
        result["truncated"] = True
        result["note"] = f"Truncated at {max_chars} of {len(text)} characters."
    else:
        result["text"] = text
        result["truncated"] = False

    if not text.strip():
        result["note"] = (
            "No text layer found. This is most likely a scanned PDF, which needs OCR."
        )
    return result


def read_canvas_file(file_id, max_chars=None, max_pages=None, max_mb=50):
    """Download (or reuse the cached copy of) a Canvas file and extract its text."""
    meta = bcourses_api.file_meta(file_id)
    path = bcourses_api.download_file(file_id, max_mb=max_mb)
    out = extract_text(path, max_chars=max_chars, max_pages=max_pages)
    out["file_id"] = file_id
    out["name"] = meta.get("name") or out["name"]
    out["content_type"] = meta.get("content_type", "")
    out["source_url"] = meta.get("url", "")
    return out


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _snippets(text, pattern, width=140, limit=3):
    out = []
    for match in pattern.finditer(text):
        start = max(0, match.start() - width // 2)
        frag = text[start:match.start() + width // 2].replace("\n", " ").strip()
        out.append(("..." if start else "") + frag + "...")
        if len(out) >= limit:
            break
    return out


def search_course(query, course_id, include_files=False, max_files=25, max_mb=25):
    """Search a course's pages, and optionally the text of its files.

    Pages are searched from the live API. Files are only searched when
    `include_files` is set, because each uncached file has to be downloaded and
    parsed first, which is slow on a large reading list.
    """
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    hits = []

    for pg in bcourses_api.course_pages(course_id):
        found = _snippets(pg["text"], pattern)
        if found:
            hits.append({
                "where": "page",
                "title": pg["title"],
                "module": pg.get("module", ""),
                "url": pg["url"],
                "matches": len(pattern.findall(pg["text"])),
                "snippets": found,
            })

    try:
        for ann in bcourses_api.announcements(course_id):
            found = _snippets(ann["text"], pattern)
            if found:
                hits.append({
                    "where": "announcement",
                    "title": ann["title"],
                    "url": ann["url"],
                    "matches": len(pattern.findall(ann["text"])),
                    "snippets": found,
                })
    except bcourses_api.CanvasError:
        pass

    if include_files:
        checked = 0
        for meta in bcourses_api.course_files(course_id):
            if checked >= max_files:
                break
            if Path(meta["name"]).suffix.lower() in IMAGE_SUFFIXES:
                continue
            if (meta.get("size") or 0) > max_mb * 1e6:
                continue
            checked += 1
            try:
                got = read_canvas_file(meta["id"], max_mb=max_mb)
            except (bcourses_api.CanvasError, ExtractError):
                continue
            found = _snippets(got.get("text", ""), pattern)
            if found:
                hits.append({
                    "where": "file",
                    "title": meta["name"],
                    "file_id": meta["id"],
                    "url": meta.get("url", ""),
                    "matches": len(pattern.findall(got["text"])),
                    "snippets": found,
                })

    hits.sort(key=lambda h: h["matches"], reverse=True)
    return hits


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: bcourses_extract.py <file_id | path> [max_chars]")
        raise SystemExit(2)
    target, cap = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 2000
    got = (read_canvas_file(int(target), max_chars=cap) if target.isdigit()
           else extract_text(target, max_chars=cap))
    print(json.dumps({k: v for k, v in got.items() if k != "text"}, indent=2))
    print("\n" + got.get("text", ""))
