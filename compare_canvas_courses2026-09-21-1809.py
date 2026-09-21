#!/usr/bin/env python3
"""
Canvas Course Comparison Tool
Compares two .imscc export files and reports assignments, discussions, pages,
documents (.docx), and presentations (.pptx) that were added, removed, or
modified — ignoring due date changes. Also flags media files (audio/video)
whose file sizes differ between courses.

Usage:
    python compare_canvas_courses.py last_summer.imscc this_summer.imscc

Save a plain text report to file:
    python compare_canvas_courses.py last_summer.imscc this_summer.imscc --output report.txt

Save an HTML report with side-by-side diffs:
    python compare_canvas_courses.py last_summer.imscc this_summer.imscc --html report.html

Also compare Classic Quiz questions (off by default — slower on courses
with many quizzes/question banks):
    python compare_canvas_courses.py last_summer.imscc this_summer.imscc --quizzes

Requirements:
    pip install beautifulsoup4 lxml
    pip install python-docx python-pptx   # optional, for .docx/.pptx support
"""

import zipfile
import argparse
import difflib
import io
from pathlib import Path
from bs4 import BeautifulSoup

# Optional: office document parsing
try:
    import docx as _docx
except ImportError:
    _docx = None

try:
    from pptx import Presentation as _Presentation
except ImportError:
    _Presentation = None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Date/time fields to skip when comparing assignment metadata
IGNORED_FIELDS = {
    "due_at", "lock_at", "unlock_at", "peer_reviews_due_at",
    "all_day_date", "created_at", "updated_at", "last_edited_at",
}

MEDIA_EXTENSIONS   = ('.mp4', '.mp3', '.wav', '.avi', '.mov', '.mkv', '.m4a', '.webm', '.flac', '.aac')
DOCX_EXTENSIONS    = ('.docx',)
PPTX_EXTENSIONS    = ('.pptx',)
TEXT_EXTENSIONS    = ('.txt', '.csv', '.md', '.markdown')


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def clean_html(raw: str) -> str:
    """Strip HTML tags and normalize whitespace for plain-text comparison."""
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    lines = [l.strip() for l in soup.get_text(separator="\n").splitlines()]
    return "\n".join(l for l in lines if l)


def parse_xml_fields(raw: str) -> dict:
    """
    Parse leaf-node tag values from a Canvas assignment_settings.xml,
    skipping any fields in IGNORED_FIELDS and any internal id/reference
    fields (e.g. workflow_state, migration_id) that are just noise for
    a content-review report.
    """
    soup = BeautifulSoup(raw, "xml")
    fields = {}
    for tag in soup.find_all(True):
        if not tag.find(True) and tag.text.strip() and tag.name not in IGNORED_FIELDS:
            if tag.name.endswith("_identifierref") or tag.name.endswith("_id"):
                continue
            fields[tag.name] = tag.text.strip()
    return fields


def extract_docx_text(raw_bytes: bytes) -> str:
    if _docx is None:
        return "[python-docx not installed — install it to compare .docx files]"
    try:
        doc = _docx.Document(io.BytesIO(raw_bytes))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        return f"[Error reading .docx: {e}]"


def extract_pptx_text(raw_bytes: bytes) -> str:
    if _Presentation is None:
        return "[python-pptx not installed — install it to compare .pptx files]"
    try:
        prs = _Presentation(io.BytesIO(raw_bytes))
        lines = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    lines.append(shape.text.strip())
        return "\n".join(lines)
    except Exception as e:
        return f"[Error reading .pptx: {e}]"


def _find_correct_response_idents(item_soup) -> set:
    """
    Given an <item> tag from a QTI 1.2 assessment, return the set of
    response_label idents that resprocessing marks as correct (any
    respcondition that sets a nonzero SCORE).
    """
    correct = set()
    for cond in item_soup.find_all("respcondition"):
        is_correct = any(
            sv.get("action", "").lower() == "set"
            and sv.get("varname", "").upper() == "SCORE"
            and sv.text.strip() not in ("", "0", "0.0")
            for sv in cond.find_all("setvar")
        )
        if not is_correct:
            continue
        for ve in cond.find_all("varequal"):
            correct.add(ve.text.strip())
    return correct


def extract_quiz_questions(raw: str) -> str:
    """
    Parse a QTI 1.2 assessment XML (Canvas Classic Quiz export) into a
    normalized, human-readable block of question text and answer choices
    (correct choices marked), suitable for line-by-line diffing.

    Best-effort: handles multiple choice, true/false, multiple answer,
    and short answer/essay questions cleanly. More exotic question types
    (matching, fill-in-multiple-blanks, formula questions) will still show
    their question text but may not render every sub-part of the answer.
    """
    soup = BeautifulSoup(raw, "xml")
    blocks = []
    for i, item in enumerate(soup.find_all("item"), start=1):
        qtype  = ""
        points = ""
        for f in item.find_all("qtimetadatafield"):
            label = f.find("fieldlabel")
            entry = f.find("fieldentry")
            if not (label and entry):
                continue
            if label.text.strip() == "question_type":
                qtype = entry.text.strip()
            elif label.text.strip() == "points_possible":
                points = entry.text.strip()

        q_text = ""
        presentation = item.find("presentation")
        if presentation:
            material = presentation.find("material", recursive=False)
            if material:
                mt = material.find("mattext")
                if mt:
                    q_text = clean_html(mt.text or "")

        correct_idents = _find_correct_response_idents(item)

        choices = []
        for label_tag in item.find_all("response_label"):
            ident = label_tag.get("ident", "")
            mt = label_tag.find("mattext")
            text = clean_html(mt.text) if mt else ""
            marker = " (correct)" if ident in correct_idents else ""
            choices.append(f"  - {text}{marker}")

        header = f"Q{i}"
        if qtype:
            header += f" [{qtype}]"
        if points:
            header += f" ({points} pts)"

        block = [header]
        if q_text:
            block.append(q_text)
        block.extend(choices)
        blocks.append("\n".join(block))

    return "\n\n".join(blocks)


def make_diff(old_text: str, new_text: str, from_label: str, to_label: str) -> str:
    """Unified diff between two strings; returns empty string if identical."""
    diff = list(difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"Last Summer — {from_label}",
        tofile=f"This Summer — {to_label}",
        lineterm="",
    ))
    return "\n".join(diff)


# ---------------------------------------------------------------------------
# imscc manifest parsing
# ---------------------------------------------------------------------------

def parse_manifest(z: zipfile.ZipFile) -> tuple[dict, dict]:
    """
    Parse imsmanifest.xml.

    Returns:
        items       : title -> resource info dict (titled items from <item> tree)
        href_index  : filepath -> title (for unlinked files like docx/pptx/media)
    """
    raw = z.read("imsmanifest.xml").decode("utf-8", errors="replace")
    soup = BeautifulSoup(raw, "xml")

    # --- Build resource id -> info map ---
    resources = {}
    for res in soup.find_all("resource"):
        rid   = res.get("identifier", "")
        rtype = res.get("type", "").lower()
        href  = res.get("href", "")

        html_path       = None
        settings_path   = None
        discussion_path = None
        quiz_path       = None

        if "imsdt" in rtype or ("discussion" in href and href.endswith(".xml")):
            discussion_path = href
            res_type = "discussion"
        elif "imsqti" in rtype:
            # Classic Quiz: the resource's own href (or its .xml <file>) is
            # the QTI assessment file. Quiz metadata (points, shuffle, time
            # limit) lives in a separate assessment_meta.xml resolved below
            # via the same dependency mechanism used for assignment settings.
            res_type = "quiz"
            if href.endswith(".xml"):
                quiz_path = href
            else:
                for f in res.find_all("file"):
                    fhref = f.get("href", "")
                    if fhref.endswith(".xml"):
                        quiz_path = fhref
                        break
        elif "learning-application-resource" in rtype or "assignment" in href:
            for f in res.find_all("file"):
                fhref = f.get("href", "")
                if fhref.endswith((".html", ".htm")):
                    html_path = fhref
            res_type = "assignment"
        else:
            for f in res.find_all("file"):
                fhref = f.get("href", "")
                if fhref.endswith((".html", ".htm")):
                    html_path = fhref
            res_type = "other"

        resources[rid] = {
            "type":             res_type,
            "html_path":        html_path,
            "settings_path":    settings_path,
            "discussion_path":  discussion_path,
            "quiz_path":        quiz_path,
            "href":             href,
            "title":            res.get("title", ""),
            "dep_ids":          [d.get("identifierref", "") for d in res.find_all("dependency")],
        }

    # Resolve dependency → settings XML path
    for rid, info in resources.items():
        for dep_id in info["dep_ids"]:
            if dep_id in resources:
                dep_href = resources[dep_id].get("href", "")
                if dep_href.endswith(".xml"):
                    info["settings_path"] = dep_href

    # --- Walk <item> tree for human-readable titles ---
    items = {}
    for item in soup.find_all("item"):
        title_tag = item.find("title")
        if not title_tag:
            continue
        title = title_tag.text.strip()
        ref   = item.get("identifierref", "")
        if title and ref and ref in resources:
            items[title] = resources[ref]

    # --- href -> title index for unlinked file lookup ---
    href_index = {
        info["href"]: title
        for title, info in items.items()
        if info.get("href")
    }

    return items, href_index


# ---------------------------------------------------------------------------
# Course loader
# ---------------------------------------------------------------------------

def _blank_entry(item_type: str) -> dict:
    return {"type": item_type, "instructions": "", "fields": {}, "discussion_text": ""}


def load_course(imscc_path: str, parse_quizzes: bool = False) -> tuple[dict, dict]:
    """
    Open an imscc file and return:
        text_items  : title -> content dict  (assignments, discussions, pages,
                                              docx, pptx, plain-text files, and
                                              quizzes when parse_quizzes=True)
        media_items : title -> file size in bytes  (audio/video only)

    Classic Quiz questions are only parsed (and only appear in text_items)
    when parse_quizzes is True — it's an extra XML-parsing pass per quiz
    and can be slow on courses with large question banks, so it stays
    opt-in via the --quizzes flag.
    """
    text_items  = {}
    media_items = {}

    with zipfile.ZipFile(imscc_path, "r") as z:
        all_files      = {info.filename: info for info in z.infolist()}
        manifest_items, href_index = parse_manifest(z)
        processed      = set()

        # ── Manifest-linked items (assignments, discussions, pages, quizzes) ─
        for title, info in manifest_items.items():
            if info["type"] == "quiz" and not parse_quizzes:
                continue

            entry = _blank_entry(info["type"])

            if info.get("html_path") and info["html_path"] in all_files:
                raw = z.read(info["html_path"]).decode("utf-8", errors="replace")
                entry["instructions"] = clean_html(raw)
                processed.add(info["html_path"])

            if info.get("settings_path") and info["settings_path"] in all_files:
                raw = z.read(info["settings_path"]).decode("utf-8", errors="replace")
                entry["fields"] = parse_xml_fields(raw)
                processed.add(info["settings_path"])

            # Discussion XML — try declared path, then href fallback
            disc_path = info.get("discussion_path") or (
                info["href"] if info["type"] == "discussion" else None
            )
            if disc_path and disc_path in all_files:
                raw  = z.read(disc_path).decode("utf-8", errors="replace")
                soup = BeautifulSoup(raw, "xml")
                tag  = soup.find("text") or soup.find("message")
                if tag:
                    entry["discussion_text"] = clean_html(tag.text.strip())
                processed.add(disc_path)

            # Quiz QTI XML — question text + answer choices
            if info["type"] == "quiz" and info.get("quiz_path") and info["quiz_path"] in all_files:
                raw = z.read(info["quiz_path"]).decode("utf-8", errors="replace")
                entry["instructions"] = extract_quiz_questions(raw)
                processed.add(info["quiz_path"])

            key = f"[Quiz] {title}" if info["type"] == "quiz" else title
            text_items[key] = entry

        # ── Unlinked / attached files (docx, pptx, media, plain text) ───────
        for filename, file_info in all_files.items():
            if file_info.is_dir() or filename in processed or filename == "imsmanifest.xml":
                continue

            name_lower   = filename.lower()
            display_name = href_index.get(filename, Path(filename).name)

            # Media: record size only
            if name_lower.endswith(MEDIA_EXTENSIONS):
                media_items[display_name] = file_info.file_size
                continue

            # Office / text documents: extract and compare content
            try:
                raw_bytes = z.read(filename)

                if name_lower.endswith(DOCX_EXTENSIONS):
                    entry = _blank_entry("docx")
                    entry["instructions"] = extract_docx_text(raw_bytes)
                    text_items[f"[Document] {display_name}"] = entry

                elif name_lower.endswith(PPTX_EXTENSIONS):
                    entry = _blank_entry("pptx")
                    entry["instructions"] = extract_pptx_text(raw_bytes)
                    text_items[f"[Presentation] {display_name}"] = entry

                elif name_lower.endswith(TEXT_EXTENSIONS):
                    entry = _blank_entry("text")
                    entry["instructions"] = raw_bytes.decode("utf-8", errors="replace").strip()
                    text_items[f"[File] {display_name}"] = entry

            except Exception as e:
                print(f"  Warning: could not read {filename}: {e}")

    return text_items, media_items


# ---------------------------------------------------------------------------
# Comparison engine
# ---------------------------------------------------------------------------

def compare_courses(old_text, old_media, new_text, new_media) -> dict:
    old_keys = set(old_text)
    new_keys = set(new_text)

    added   = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    common  = old_keys & new_keys

    modified  = []
    unchanged = []

    for title in sorted(common):
        old = old_text[title]
        new = new_text[title]
        changes = []

        # Instructions / document body
        if old["instructions"] != new["instructions"]:
            diff = make_diff(old["instructions"], new["instructions"],
                             "Instructions", "Instructions")
            if diff:
                changes.append({
                    "label": "Instructions / Content",
                    "kind":  "text",
                    "diff":  diff,
                    "old":   old["instructions"],
                    "new":   new["instructions"],
                })

        # Discussion prompt text
        if old["discussion_text"] != new["discussion_text"]:
            diff = make_diff(old["discussion_text"], new["discussion_text"],
                             "Discussion Text", "Discussion Text")
            if diff:
                changes.append({
                    "label": "Discussion Text",
                    "kind":  "text",
                    "diff":  diff,
                    "old":   old["discussion_text"],
                    "new":   new["discussion_text"],
                })

        # Structured metadata fields (points, submission type, etc.)
        all_keys = set(old["fields"]) | set(new["fields"])
        for key in sorted(all_keys):
            ov = old["fields"].get(key, "<not set>")
            nv = new["fields"].get(key, "<not set>")
            if ov != nv:
                changes.append({
                    "label": f"Field: {key}",
                    "kind":  "field",
                    "diff":  f"  Last Summer : {ov}\n  This Summer : {nv}",
                    "old":   ov,
                    "new":   nv,
                })

        if changes:
            modified.append((title, changes))
        else:
            unchanged.append(title)

    # Media: flag only size differences (fast scan, as requested)
    old_med = set(old_media)
    new_med = set(new_media)
    media_report = {
        "added":    sorted(new_med - old_med),
        "removed":  sorted(old_med - new_med),
        "resized":  [
            (t, old_media[t], new_media[t])
            for t in sorted(old_med & new_med)
            if old_media[t] != new_media[t]
        ],
        "unchanged": sorted(t for t in old_med & new_med if old_media[t] == new_media[t]),
    }

    return {
        "added":    added,
        "removed":  removed,
        "modified": modified,
        "unchanged": unchanged,
        "media":    media_report,
    }


# ---------------------------------------------------------------------------
# Plain text report formatter
# ---------------------------------------------------------------------------

def format_report(report: dict, old_path: str, new_path: str, use_colors: bool = False) -> str:
    """
    Render the plain-text report. When use_colors is True, wraps added/
    removed/modified lines (and diff +/- lines) in ANSI escape codes for
    a readable terminal view; leave it False for the version written to
    --output, since a saved file shouldn't be full of escape codes.
    """
    C_ADD = "\033[92m" if use_colors else ""
    C_REM = "\033[91m" if use_colors else ""
    C_MOD = "\033[93m" if use_colors else ""
    C_HDR = "\033[96m" if use_colors else ""
    C_DIM = "\033[90m" if use_colors else ""
    C_RST = "\033[0m"  if use_colors else ""

    SEP  = C_HDR + "=" * 70 + C_RST
    DASH = C_DIM + "─" * 70 + C_RST
    lines = []

    n_add = len(report["added"])
    n_rem = len(report["removed"])
    n_mod = len(report["modified"])
    n_unc = len(report["unchanged"])
    m     = report["media"]

    lines += [
        SEP,
        f"{C_HDR}  CANVAS COURSE COMPARISON REPORT{C_RST}",
        SEP,
        f"  Last Summer : {old_path}",
        f"  This Summer : {new_path}",
        SEP,
        f"  Content  — {C_ADD}{n_add} added{C_RST} | {C_REM}{n_rem} removed{C_RST} | "
        f"{C_MOD}{n_mod} modified{C_RST} | {n_unc} unchanged",
        f"  Media    — {C_ADD}{len(m['added'])} added{C_RST} | {C_REM}{len(m['removed'])} removed{C_RST} | "
        f"{C_MOD}{len(m['resized'])} resized{C_RST} | {len(m['unchanged'])} unchanged",
        SEP, "",
    ]

    # ── Content sections ────────────────────────────────────────────────────

    def section(header, header_color, items, fmt):
        lines.append(DASH)
        lines.append(f"{header_color}  {header}{C_RST}")
        lines.append(DASH)
        if items:
            for i in items:
                lines.append(fmt(i))
        else:
            lines.append("  (none)")
        lines.append("")

    section(f"ADDED TO THIS SUMMER ({n_add})", C_ADD,
            report["added"],
            lambda t: f"{C_ADD}  + {t}{C_RST}")

    section(f"REMOVED FROM THIS SUMMER ({n_rem})", C_REM,
            report["removed"],
            lambda t: f"{C_REM}  - {t}{C_RST}")

    lines.append(DASH)
    lines.append(f"{C_MOD}  MODIFIED ({n_mod}){C_RST}")
    lines.append(DASH)
    if report["modified"]:
        for title, changes in report["modified"]:
            lines.append(f"\n{C_MOD}  ▸ {title}{C_RST}")
            for c in changes:
                lines.append(f"    [{c['label']}]")
                for dl in c["diff"].splitlines():
                    if dl.startswith("+") and not dl.startswith("+++"):
                        lines.append(f"{C_ADD}      {dl}{C_RST}")
                    elif dl.startswith("-") and not dl.startswith("---"):
                        lines.append(f"{C_REM}      {dl}{C_RST}")
                    else:
                        lines.append(f"      {dl}")
    else:
        lines.append("  (none)")
    lines.append("")

    section(f"UNCHANGED ({n_unc})", "",
            report["unchanged"],
            lambda t: f"  ✓ {t}")

    # ── Media section ────────────────────────────────────────────────────────

    lines += [SEP, f"{C_HDR}  MEDIA FILES (audio / video){C_RST}", SEP, ""]

    lines.append(f"  Added ({len(m['added'])}):")
    for t in m["added"]:
        lines.append(f"{C_ADD}    + {t}{C_RST}")
    if not m["added"]:
        lines.append("    (none)")
    lines.append("")

    lines.append(f"  Removed ({len(m['removed'])}):")
    for t in m["removed"]:
        lines.append(f"{C_REM}    - {t}{C_RST}")
    if not m["removed"]:
        lines.append("    (none)")
    lines.append("")

    lines.append(f"  Size changed — possible replacement ({len(m['resized'])}):")
    for t, old_sz, new_sz in m["resized"]:
        delta = new_sz - old_sz
        sign  = "+" if delta >= 0 else ""
        lines.append(f"{C_MOD}    ▸ {t}{C_RST}")
        lines.append(f"{C_MOD}      {old_sz:,} bytes → {new_sz:,} bytes  ({sign}{delta:,}){C_RST}")
    if not m["resized"]:
        lines.append("    (none)")
    lines.append("")

    lines.append(f"  Same size — likely unchanged ({len(m['unchanged'])}):")
    for t in m["unchanged"]:
        lines.append(f"    ✓ {t}")
    if not m["unchanged"]:
        lines.append("    (none)")
    lines.append("")

    lines.append(SEP)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML report formatter
# (ported from compare_canvas_courses2, adapted to the current data model —
# text fields get a true side-by-side difflib.HtmlDiff table)
# ---------------------------------------------------------------------------

def format_html_report(report: dict, old_path: str, new_path: str) -> str:
    """Generates a standalone HTML dashboard with tables and side-by-side diffs."""
    d = difflib.HtmlDiff(wrapcolumn=90)

    html = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Course Comparison</title>",
        "<style>",
        "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 20px; background: #f4f4f9; color: #333; }",
        ".container { max-width: 1100px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }",
        "table.overview { width: 100%; border-collapse: collapse; margin-bottom: 30px; font-size: 15px; }",
        "table.overview th, table.overview td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }",
        "table.overview th { background-color: #f8f9fa; }",
        ".badge { padding: 4px 8px; border-radius: 4px; font-size: 0.85em; font-weight: bold; }",
        ".b-added { background: #d4edda; color: #155724; }",
        ".b-removed { background: #f8d7da; color: #721c24; }",
        ".b-modified { background: #fff3cd; color: #856404; }",
        ".diff-section { margin-top: 40px; border-top: 2px solid #eee; padding-top: 20px; }",
        "table.diff { width: 100%; border: 1px solid #ddd; font-family: Consolas, monospace; font-size: 13px; margin-bottom: 20px; }",
        "table.diff td { padding: 4px; }",
        "table.diff .diff_header { background: #f0f0f0; width: 1%; text-align: center; color: #999; }",
        "table.diff .diff_add { background: #cfc; }",
        "table.diff .diff_chg { background: #ffd; }",
        "table.diff .diff_sub { background: #fcc; }",
        ".field-change { margin-bottom: 15px; padding: 12px; background: #f8f9fa; border-left: 4px solid #ffc107; font-family: monospace; }",
        "</style></head><body><div class='container'>",
        "<h1>Canvas Course Comparison</h1>",
        f"<p><strong>Last Summer:</strong> {old_path}<br><strong>This Summer:</strong> {new_path}</p>",
    ]

    html.append("<h2>Content Overview</h2>")
    html.append("<table class='overview'><tr><th>Title</th><th>Status</th></tr>")
    for t in report["added"]:
        html.append(f"<tr><td>{t}</td><td><span class='badge b-added'>Added</span></td></tr>")
    for t in report["removed"]:
        html.append(f"<tr><td>{t}</td><td><span class='badge b-removed'>Removed</span></td></tr>")
    for idx, (t, _changes) in enumerate(report["modified"]):
        html.append(f"<tr><td><a href='#mod_{idx}'>{t}</a></td><td><span class='badge b-modified'>Modified</span></td></tr>")
    html.append("</table>")

    m = report["media"]
    html.append("<h2>Media Overview (Audio/Video)</h2>")
    html.append("<table class='overview'><tr><th>File Name</th><th>Status</th><th>Details</th></tr>")
    for t in m["added"]:
        html.append(f"<tr><td>{t}</td><td><span class='badge b-added'>Added</span></td><td></td></tr>")
    for t in m["removed"]:
        html.append(f"<tr><td>{t}</td><td><span class='badge b-removed'>Removed</span></td><td></td></tr>")
    for t, old_sz, new_sz in m["resized"]:
        html.append(f"<tr><td>{t}</td><td><span class='badge b-modified'>Size Changed</span></td><td>{old_sz:,} bytes &rarr; {new_sz:,} bytes</td></tr>")
    html.append("</table>")

    if report["modified"]:
        html.append("<div class='diff-section'><h2>Detailed Modifications</h2>")
        for idx, (t, changes) in enumerate(report["modified"]):
            html.append(f"<h3 id='mod_{idx}'>{t}</h3>")
            for c in changes:
                if c["kind"] == "text":
                    html.append(f"<h4>{c['label']}</h4>")
                    diff_table = d.make_table(
                        c["old"].splitlines(), c["new"].splitlines(),
                        "Last Summer", "This Summer", context=True,
                    )
                    html.append(diff_table)
                elif c["kind"] == "field":
                    html.append(
                        f"<div class='field-change'><strong>{c['label']}</strong><br><br>"
                        f"Last Summer: <code>{c['old']}</code><br>"
                        f"This Summer: <code>{c['new']}</code></div>"
                    )
        html.append("</div>")

    html.append("</div></body></html>")
    return "\n".join(html)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compare two Canvas .imscc course exports."
    )
    parser.add_argument("last_summer", help="Path to last summer's .imscc file")
    parser.add_argument("this_summer", help="Path to this summer's .imscc file")
    parser.add_argument("--output", "-o",
                        help="Save a plain text report to this file path (optional)",
                        default=None)
    parser.add_argument("--html",
                        help="Save an HTML report with side-by-side diffs to this file path (optional)",
                        default=None)
    parser.add_argument("--quizzes", action="store_true",
                        help="Also compare Classic Quiz question text and answer choices "
                             "(off by default — slower on courses with many quizzes/questions)")
    args = parser.parse_args()

    if _docx is None or _Presentation is None:
        missing = []
        if _docx is None:         missing.append("python-docx")
        if _Presentation is None: missing.append("python-pptx")
        print(f"Notice: {', '.join(missing)} not installed. "
              f".docx/.pptx files will show a placeholder instead of content.\n"
              f"  Install with: pip install {' '.join(missing)}\n")

    if args.quizzes:
        print("Quiz comparison enabled — this can take a while on courses with large question banks.\n")

    print(f"Loading last summer's course : {args.last_summer}")
    old_text, old_media = load_course(args.last_summer, parse_quizzes=args.quizzes)
    print(f"  {len(old_text)} content items, {len(old_media)} media files")

    print(f"Loading this summer's course : {args.this_summer}")
    new_text, new_media = load_course(args.this_summer, parse_quizzes=args.quizzes)
    print(f"  {len(new_text)} content items, {len(new_media)} media files\n")

    print("Comparing...")
    report = compare_courses(old_text, old_media, new_text, new_media)

    # Colored version for the terminal; plain version for any saved file
    # (escape codes in a text file you open later are just noise).
    print("\n" + format_report(report, args.last_summer, args.this_summer, use_colors=True))

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(format_report(report, args.last_summer, args.this_summer, use_colors=False))
        print(f"Text report saved to: {args.output}")

    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(format_html_report(report, args.last_summer, args.this_summer))
        print(f"HTML report saved to: {args.html}")


if __name__ == "__main__":
    main()
