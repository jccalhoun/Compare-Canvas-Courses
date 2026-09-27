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

Known limitations:
    - Matching a duplicate-titled item (e.g. two "Overview" pages) across
      two SEPARATE exports is best-effort, not guaranteed: there's no
      persistent id to key on (Canvas regenerates them per export), so
      duplicates are matched by their content path instead. If a
      duplicate's content genuinely moves to a different path between the
      two exports being compared, it may be matched to the wrong sibling
      duplicate or misreported as added/removed instead of modified.
    - A link's target is only tracked when it resolves to one of Canvas's
      own reference tokens ($WIKI_REFERENCE$ and similar — see
      CANVAS_REFERENCE_TOKENS). An ordinary relative href with no token
      (e.g. straight to another file in the export) isn't specially
      surfaced, and a change to one won't show up in the diff.
"""

from __future__ import annotations

import zipfile
import argparse
import difflib
import html
import io
import re
import sys
from urllib.parse import unquote
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

# Tag names known to legitimately repeat at the same level with distinct
# values (e.g. an assignment allowing both file upload and text entry
# produces two <submission_type> tags). See parse_xml_fields for why this
# is a narrow allowlist rather than "aggregate any repeated tag."
MULTI_VALUE_FIELDS = {"submission_type"}

MEDIA_EXTENSIONS   = ('.mp4', '.mp3', '.wav', '.avi', '.mov', '.mkv', '.m4a', '.webm', '.flac', '.aac')
DOCX_EXTENSIONS    = ('.docx',)
PPTX_EXTENSIONS    = ('.pptx',)
TEXT_EXTENSIONS    = ('.txt', '.csv', '.md', '.markdown')

# Canvas replaces links to other content in the *same course* with inert
# placeholder tokens on export (e.g. "$WIKI_REFERENCE$/pages/<id>"), meant
# to be rewritten by Canvas's own importer into a real link when the
# cartridge is re-imported somewhere. They're never real URLs on their own
# and will 404 if you try to follow them directly — swap them for a short
# readable label instead of leaving raw tokens (and a trailing internal id)
# sitting in the report.
CANVAS_REFERENCE_TOKENS = {
    "$WIKI_REFERENCE$":                  "link to another page",
    "$CANVAS_OBJECT_REFERENCE$":         "link to another course item",
    "$CANVAS_COURSE_REFERENCE$":         "link within this course",
    "$IMS-CC-FILEBASE$":                 "link to a file in this export",
    "$CANVAS_WEB_CONFERENCE_REFERENCE$": "link to a web conference",
    "$CANVAS_CONTENT_LINK_REFERENCE$":   "link to course content",
}
# Sorted longest-token-first: a regex alternation matches the first
# alternative that fits at a position, so if a future token were ever a
# prefix of another (e.g. adding "$WIKI_REFERENCE_EXT$" alongside
# "$WIKI_REFERENCE$"), an unsorted alternation could match the shorter one
# and silently leave part of the longer token unconsumed.
_TOKEN_PATTERN = re.compile(
    "(" + "|".join(re.escape(t) for t in sorted(CANVAS_REFERENCE_TOKENS, key=len, reverse=True))
    + r")(/\S*)?"
)


def _format_reference_token(match: "re.Match") -> str:
    """
    Keep the trailing migration id (e.g. the "g111" in
    "$WIKI_REFERENCE$/pages/g111") after cleaning up the token, so that a
    link genuinely changing targets between exports still shows up as a
    real diff instead of two different ids collapsing into one label.
    """
    token     = match.group(1)
    remainder = (match.group(2) or "").strip("/")
    label     = CANVAS_REFERENCE_TOKENS[token]
    if not remainder:
        return f"[{label}]"
    ref_id = remainder.rsplit("/", 1)[-1]
    return f"[{label}: {ref_id}]"


def strip_canvas_reference_tokens(text: str) -> str:
    """Replace inert Canvas export reference tokens with a readable label."""
    if "$" not in text:
        return text
    return _TOKEN_PATTERN.sub(_format_reference_token, text)


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def clean_html(raw: str) -> str:
    """
    Strip HTML tags and normalize whitespace for plain-text comparison.

    Canvas's normal "insert course link" workflow puts descriptive text
    (e.g. "Getting Started") as the link's visible text, with the actual
    target only in href — which get_text() drops along with every other
    attribute. Without special handling, a link's TARGET changing (moved
    to point at a different page) would be completely invisible even
    though its visible text stayed the same. So: walk <a href> tags first
    and append a resolved-reference marker after any link whose href is a
    Canvas token and whose visible text doesn't already say the same
    thing (a raw pasted URL, where visible text and href are identical,
    is already covered by the text-level pass below and would otherwise
    get double-marked).
    """
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        resolved_href = strip_canvas_reference_tokens(href)
        if resolved_href == href:
            continue  # not a Canvas reference token — leave external links alone
        if strip_canvas_reference_tokens(a.get_text()) == resolved_href:
            continue  # visible text already encodes the same reference
        a.append(soup.new_string(f" {resolved_href}"))
    lines = [l.strip() for l in soup.get_text(separator="\n").splitlines()]
    text = "\n".join(l for l in lines if l)
    return strip_canvas_reference_tokens(text)


def parse_xml_fields(raw: str) -> dict:
    """
    Parse leaf-node tag values from a Canvas assignment_settings.xml,
    skipping any fields in IGNORED_FIELDS and any tag ending in "_id" or
    "_identifierref" (e.g. migration_id) — internal bookkeeping noise, not
    content. Note: this does NOT catch every noisy internal field —
    workflow_state (published/unpublished) is a real example that slips
    through, since it doesn't match either filter. Left unfiltered on
    purpose: whether a publish-state change is noise or exactly what you
    want flagged is a judgment call, not a bug — add it to IGNORED_FIELDS
    if you'd rather it stay quiet.

    A tag name in MULTI_VALUE_FIELDS repeated at the same level (e.g.
    multiple <submission_type> entries when an assignment allows more than
    one submission type) is aggregated into a comma-separated value rather
    than the last one silently overwriting the rest. Deliberately scoped
    to a known allowlist rather than aggregating ANY repeated tag name:
    this only walks leaf tags, with no awareness of *where* in the tree
    they sit, so a blanket "merge any repeat" rule would also merge, say,
    a <title> that legitimately appears both at the assignment level and
    inside a nested rubric criterion — turning an unrelated rubric detail
    into false "Field: title" noise on every comparison.
    """
    soup = BeautifulSoup(raw, "xml")
    fields = {}
    for tag in soup.find_all(True):
        if not tag.find(True) and tag.text.strip() and tag.name not in IGNORED_FIELDS:
            if tag.name.endswith("_identifierref") or tag.name.endswith("_id"):
                continue
            val = tag.text.strip()
            if tag.name in fields and tag.name in MULTI_VALUE_FIELDS:
                fields[tag.name] = f"{fields[tag.name]}, {val}"
            else:
                fields[tag.name] = val
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

    Multi-answer ("select all that apply") questions commonly express the
    scoring condition as an AND of several varequal checks, where one or
    more of them is wrapped in <not> — meaning "this choice must NOT be
    selected" for the item to score. find_all("varequal") finds those too;
    without excluding ones nested inside <not>, a choice that should stay
    unselected gets mislabeled "(correct)" instead.
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
            if ve.find_parent("not") is not None:
                continue
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
    """
    Unified diff between two strings; returns empty string if identical.
    Uses splitlines() (no keepends) so each line has no embedded newline —
    keepends=True here would double-space every line once "\n".join()
    adds its own separator on top of the one each line already carries.
    """
    diff = list(difflib.unified_diff(
        old_text.splitlines(),
        new_text.splitlines(),
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
    raw = z.read("imsmanifest.xml").decode("utf-8-sig", errors="replace")
    soup = BeautifulSoup(raw, "xml")

    # --- Build resource id -> info map ---
    resources = {}
    for res in soup.find_all("resource"):
        rid   = res.get("identifier", "")
        rtype = res.get("type", "").lower()
        # unquote() is a no-op on an already-decoded string, so this is
        # safe insurance either way: some exports percent-encode href
        # attributes (spaces as %20, etc.) since they're technically URI
        # references, while zip member names are stored as plain decoded
        # text — without unquoting, a path with a space or special
        # character would never match `all_files` and its content would
        # silently come back empty.
        href = unquote(res.get("href", ""))

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
                    fhref = unquote(f.get("href", ""))
                    if fhref.endswith(".xml"):
                        quiz_path = fhref
                        break
        elif "learning-application-resource" in rtype or "assignment" in href:
            # Check the resource's own href first — the settings_path
            # resolution above already does this (a resource's href is
            # normally its primary file, redundantly re-listed as a
            # <file> child too), but this branch previously only checked
            # <file> children. When an export lists the HTML only as
            # href with no redundant <file> child, html_path stayed
            # unresolved, the item's own entry kept its fields but lost
            # its instructions, and the same HTML separately fell through
            # to the unlinked-file loop as an orphan "[Page] ..." entry —
            # fragmenting one logical item into two unrelated diff lines.
            if href.endswith((".html", ".htm")):
                html_path = href
            else:
                for f in res.find_all("file"):
                    fhref = unquote(f.get("href", ""))
                    if fhref.endswith((".html", ".htm")):
                        html_path = fhref
                        break
            res_type = "assignment"
        else:
            if href.endswith((".html", ".htm")):
                html_path = href
            else:
                for f in res.find_all("file"):
                    fhref = unquote(f.get("href", ""))
                    if fhref.endswith((".html", ".htm")):
                        html_path = fhref
                        break
            res_type = "other"

        resources[rid] = {
            "type":             res_type,
            "html_path":        html_path,
            "settings_path":    settings_path,
            "discussion_path":  discussion_path,
            "quiz_path":        quiz_path,
            "href":             href,
            "file_hrefs":       [unquote(f.get("href", "")) for f in res.find_all("file")],
            "title":            res.get("title", ""),
            "dep_ids":          [d.get("identifierref", "") for d in res.find_all("dependency")],
        }

    # Resolve dependency → settings XML path. A dependency's own href is
    # the normal case (and what's been verified against real exports), but
    # fall back to its <file> children too — cheap insurance in case some
    # export declares the settings XML only as a file, not as the
    # resource's href.
    for rid, info in resources.items():
        for dep_id in info["dep_ids"]:
            dep = resources.get(dep_id)
            if not dep:
                continue
            candidates = [dep.get("href", "")] + dep.get("file_hrefs", [])
            resolved = False
            for cand in candidates:
                if cand.endswith(".xml"):
                    info["settings_path"] = cand
                    resolved = True
                    break
            # Stop at the first dependency that resolves to an XML path —
            # a resource with more than one dependency (uncommon, but
            # possible) would otherwise have settings_path silently
            # overwritten by whichever dependency happened to be listed
            # last, rather than the first (equally arbitrary, but at
            # least deterministic and not order-dependent on top of that).
            if resolved:
                break

    # --- Walk <item> tree for human-readable titles ---
    # Duplicate titles are common across modules ("Overview", "Week 1
    # Discussion" repeated per week/module) — a bare title-keyed dict would
    # silently drop every item but the last with that title. Disambiguate
    # with a "(2)", "(3)", ... suffix on repeats, leaving the first (and
    # the common non-colliding case) untouched for readability.
    #
    # Which duplicate gets which suffix matters for cross-export matching:
    # if it were assigned by raw manifest traversal order, and the two
    # exports being compared happen to list the same duplicates in a
    # different order (or one has an extra duplicate inserted earlier in
    # the tree), the suffixes would shift and unrelated items would look
    # "modified"/"added" against each other. There's no persistent id to
    # key on instead — Canvas's own identifierref/migration-id values
    # regenerate per export (the same instability behind why quiz
    # questions are diffed as one text blob rather than matched by ident,
    # elsewhere in this file) — so instead: group by title first, then
    # order each group by its own content path (html_path/quiz_path/
    # discussion_path/href) rather than tree position. That's still not
    # airtight if content genuinely moves between paths between exports,
    # but it removes the arbitrary, unrelated instability of pure
    # traversal order.
    raw_items = []
    for item in soup.find_all("item"):
        title_tag = item.find("title")
        if not title_tag:
            continue
        title = title_tag.text.strip()
        ref   = item.get("identifierref", "")
        if title and ref and ref in resources:
            raw_items.append((title, resources[ref]))

    by_title = {}
    for title, info in raw_items:
        by_title.setdefault(title, []).append(info)

    def _content_sort_key(info):
        return (info.get("html_path") or info.get("quiz_path")
                or info.get("discussion_path") or info.get("href") or "")

    items = {}
    for title, group in by_title.items():
        ordered = sorted(group, key=_content_sort_key) if len(group) > 1 else group
        for info in ordered:
            # Guard against colliding with a genuinely, separately titled
            # item that happens to match the auto-generated pattern (an
            # instructor who titled something literally "Overview (2)" of
            # their own accord) — check against the real, growing `items`
            # dict rather than just assuming "(2)", "(3)", ... in order
            # within this title's own duplicate group are free.
            key = title
            suffix = 2
            while key in items:
                key = f"{title} ({suffix})"
                suffix += 1
            items[key] = info

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


def load_course(imscc_path: str, parse_quizzes: bool = False, label: str = "") -> tuple[dict, dict, int, list]:
    """
    Open an imscc file and return:
        text_items      : title -> content dict  (assignments, discussions,
                                                   pages, docx, pptx, plain-
                                                   text files, and quizzes
                                                   when parse_quizzes=True)
        media_items     : title -> (size, CRC32)  (audio/video only)
        skipped_office  : count of .docx/.pptx files skipped because
                          python-docx/python-pptx isn't installed. These
                          are left out of text_items entirely rather than
                          included with a placeholder string — both courses
                          would get the exact same placeholder text, which
                          would make every one of them compare as silently
                          "unchanged" even if the real content differs.
        warnings        : list of diagnostic message strings (parse-path
                          resolution concerns — see below). Also printed
                          to stderr immediately, but returned too so the
                          caller can fold them into a saved --output/--html
                          report; a warning that only showed up once in a
                          terminal someone wasn't watching is easy to miss
                          when reviewing a report later.

    Classic Quiz questions are only parsed (and only appear in text_items)
    when parse_quizzes is True — it's an extra XML-parsing pass per quiz
    and can be slow on courses with large question banks, so it stays
    opt-in via the --quizzes flag. `label` is used only for the two
    diagnostic warnings below (e.g. "last summer's course").
    """
    text_items     = {}
    media_items    = {}
    skipped_office = 0
    warnings       = []

    # Diagnostic counters — tallied from EVERY manifest item of the given
    # type, before the "drop fully-blank entries" filter below runs. If
    # they were instead derived from text_items after filtering, an
    # assignment/quiz whose content genuinely failed to parse would be
    # silently dropped from text_items by that same filter and vanish
    # from these counts too — defeating the exact diagnostic meant to
    # catch that failure.
    assignment_total, assignment_with_fields = 0, 0
    quiz_total, quiz_with_questions = 0, 0

    with zipfile.ZipFile(imscc_path, "r") as z:
        all_files      = {info.filename: info for info in z.infolist()}
        manifest_items, href_index = parse_manifest(z)
        processed      = set()

        # ── Manifest-linked items (assignments, discussions, pages, quizzes) ─
        for title, info in manifest_items.items():
            entry = _blank_entry(info["type"])

            if info.get("html_path") and info["html_path"] in all_files:
                raw = z.read(info["html_path"]).decode("utf-8-sig", errors="replace")
                entry["instructions"] = clean_html(raw)
                processed.add(info["html_path"])

            if info.get("settings_path") and info["settings_path"] in all_files:
                raw = z.read(info["settings_path"]).decode("utf-8-sig", errors="replace")
                entry["fields"] = parse_xml_fields(raw)
                processed.add(info["settings_path"])

            # Discussion XML — try declared path, then href fallback
            disc_path = info.get("discussion_path") or (
                info["href"] if info["type"] == "discussion" else None
            )
            if disc_path and disc_path in all_files:
                raw   = z.read(disc_path).decode("utf-8-sig", errors="replace")
                soup  = BeautifulSoup(raw, "xml")
                topic = soup.find("topic")
                # Prefer <text>/<message> scoped inside <topic> — course
                # exports don't include student entries/attachments, but
                # scoping here is free insurance against grabbing an
                # unrelated <text> tag elsewhere in the document.
                tag = (topic.find("text") or topic.find("message")) if topic else None
                tag = tag or soup.find("text") or soup.find("message")
                if tag:
                    entry["discussion_text"] = clean_html(tag.text.strip())
                processed.add(disc_path)

            # Quiz QTI XML — question text + answer choices. This is the
            # one expensive part (extra XML parse per quiz), so it's the
            # only thing --quizzes actually gates; the quiz's own entry
            # (and its cheap metadata fields above — points, shuffle,
            # time limit) is always present regardless of the flag.
            if info["type"] == "quiz" and parse_quizzes and info.get("quiz_path") and info["quiz_path"] in all_files:
                raw = z.read(info["quiz_path"]).decode("utf-8-sig", errors="replace")
                entry["instructions"] = extract_quiz_questions(raw)
                processed.add(info["quiz_path"])

            if info["type"] == "assignment":
                assignment_total += 1
                if entry["fields"]:
                    assignment_with_fields += 1
            if info["type"] == "quiz":
                quiz_total += 1
                if entry["instructions"].strip():
                    quiz_with_questions += 1

            # Keep an item whenever the manifest pointed it at a path this
            # loop is responsible for (html_path, settings_path, a
            # discussion path, or a quiz) — regardless of whether
            # extraction from that path actually produced anything.
            # That "regardless" matters: checking extracted CONTENT
            # instead of the ORIGINAL PATH would conflate two different
            # situations. A resource with no known path at all (a docx/
            # pptx/media file linked directly as a module item — type
            # "other", since this loop only reads .html/.htm) really does
            # belong to the unlinked-file loop below instead; keeping a
            # blank duplicate of it here would just be the phantom-item
            # bug this filter exists to prevent. But a resource that DOES
            # have a known path — where the file is simply missing from
            # this particular export, or decodes to empty — is still a
            # real course item. Dropping that one because it came up
            # blank would make it vanish from text_items on just this
            # side, so the diff sees it as "removed" (implying an
            # instructor deleted it) instead of "modified" or "broken" —
            # a materially misleading claim for a tool whose whole job is
            # telling someone what actually changed.
            has_known_path = bool(
                info.get("html_path") or info.get("settings_path")
                or disc_path or info["type"] == "quiz"
            )
            if has_known_path:
                key = f"[Quiz] {title}" if info["type"] == "quiz" else title
                text_items[key] = entry

        if assignment_total and not assignment_with_fields:
            msg = (f"{label} has {assignment_total} assignment(s) but none produced "
                   f"any metadata fields (points, submission type, etc). settings_path "
                   f"resolution may be failing on this export's manifest structure.")
            warnings.append(msg)
            print(f"  Warning: {msg}", file=sys.stderr)
        if parse_quizzes and quiz_total and not quiz_with_questions:
            msg = (f"{label} has {quiz_total} quiz(zes) but none produced any "
                   f"question text. quiz_path may be resolving to the wrong file on this "
                   f"export's manifest structure — check imsmanifest.xml for how the quiz "
                   f"resource is wrapped.")
            warnings.append(msg)
            print(f"  Warning: {msg}", file=sys.stderr)

        # ── Unlinked / attached files (docx, pptx, media, plain text, orphan pages) ─
        for filename, file_info in all_files.items():
            if file_info.is_dir() or filename in processed or filename == "imsmanifest.xml":
                continue

            name_lower = filename.lower()
            # Fall back to the full archive-relative path (not just the
            # basename) when there's no manifest-linked title — two files
            # with the same basename in different folders (e.g. two
            # "handout.docx") are common in real exports and a bare
            # basename would silently collide and overwrite one entry.
            display_name = href_index.get(filename, filename)

            # Media: record size + CRC32 (both already sit in the zip's
            # central directory, so this costs nothing extra). Size alone
            # would call a same-size re-encode/replacement "unchanged".
            if name_lower.endswith(MEDIA_EXTENSIONS):
                media_items[display_name] = (file_info.file_size, file_info.CRC)
                continue

            # Office / text / orphan HTML documents: extract and compare content
            try:
                raw_bytes = z.read(filename)

                if name_lower.endswith(DOCX_EXTENSIONS):
                    if _docx is None:
                        skipped_office += 1
                        continue
                    entry = _blank_entry("docx")
                    entry["instructions"] = extract_docx_text(raw_bytes)
                    text_items[f"[Document] {display_name}"] = entry

                elif name_lower.endswith(PPTX_EXTENSIONS):
                    if _Presentation is None:
                        skipped_office += 1
                        continue
                    entry = _blank_entry("pptx")
                    entry["instructions"] = extract_pptx_text(raw_bytes)
                    text_items[f"[Presentation] {display_name}"] = entry

                elif name_lower.endswith((".html", ".htm")):
                    # A page/file not referenced anywhere in the manifest
                    # item tree — e.g. a leftover or hand-added page.
                    # Exclude Canvas's own auto-generated quiz preview/
                    # landing pages (non_cc_assessments/) — these aren't
                    # authored course content, and since they typically
                    # embed a per-export quiz id in their path or markup,
                    # including them here would add noise (or even false
                    # "modified"/"added" entries) on every quiz-enabled run
                    # regardless of whether anything a person actually
                    # wrote changed.
                    if "non_cc_assessments" in filename:
                        continue
                    entry = _blank_entry("page")
                    raw = raw_bytes.decode("utf-8-sig", errors="replace")
                    entry["instructions"] = clean_html(raw)
                    text_items[f"[Page] {display_name}"] = entry

                elif name_lower.endswith(TEXT_EXTENSIONS):
                    entry = _blank_entry("text")
                    entry["instructions"] = raw_bytes.decode("utf-8-sig", errors="replace").strip()
                    text_items[f"[File] {display_name}"] = entry

            except Exception as e:
                print(f"  Warning: could not read {filename}: {e}", file=sys.stderr)

    return text_items, media_items, skipped_office, warnings


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

    # Media: flag any size OR content (CRC32) difference — cheap since
    # both come straight from the zip directory, no decompression needed.
    old_med = set(old_media)
    new_med = set(new_media)
    media_report = {
        "added":    sorted(new_med - old_med),
        "removed":  sorted(old_med - new_med),
        "changed":  [
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

def format_report(report: dict, old_path: str, new_path: str, use_colors: bool = False,
                   warnings: list = None) -> str:
    """
    Render the plain-text report. When use_colors is True, wraps added/
    removed/modified lines (and diff +/- lines) in ANSI escape codes for
    a readable terminal view; leave it False for the version written to
    --output, since a saved file shouldn't be full of escape codes.
    `warnings` (from load_course, see there) are rendered up top when
    present, so a parse-path problem is still visible to anyone reviewing
    a saved report later — not just someone watching the terminal live.
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
        f"{C_MOD}{len(m['changed'])} changed{C_RST} | {len(m['unchanged'])} unchanged",
        SEP, "",
    ]

    if warnings:
        lines.append(DASH)
        lines.append(f"{C_MOD}  DIAGNOSTIC WARNINGS ({len(warnings)}){C_RST}")
        lines.append(DASH)
        for w in warnings:
            lines.append(f"{C_MOD}  ⚠ {w}{C_RST}")
        lines.append("")

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

    lines.append(f"  Changed — different size or content, possible replacement ({len(m['changed'])}):")
    for t, (old_sz, old_crc), (new_sz, new_crc) in m["changed"]:
        lines.append(f"{C_MOD}    ▸ {t}{C_RST}")
        if old_sz != new_sz:
            delta = new_sz - old_sz
            sign  = "+" if delta >= 0 else ""
            lines.append(f"{C_MOD}      {old_sz:,} bytes → {new_sz:,} bytes  ({sign}{delta:,}){C_RST}")
        else:
            lines.append(f"{C_MOD}      same size ({old_sz:,} bytes) — content differs{C_RST}")
    if not m["changed"]:
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

def format_html_report(report: dict, old_path: str, new_path: str, warnings: list = None) -> str:
    """
    Generates a standalone HTML dashboard with tables and side-by-side
    diffs. `warnings` (from load_course) render as a callout up top when
    present, so a parse-path problem is visible when this report is
    opened later, not just in whatever terminal produced it.
    """
    d = difflib.HtmlDiff(wrapcolumn=90)
    esc = html.escape  # local alias — the list below is named `out`, not
                        # `html`, specifically so it can't shadow this module

    out = [
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
        ".warning-box { margin-bottom: 20px; padding: 12px 16px; background: #fff3cd; border-left: 4px solid #856404; color: #533f03; }",
        ".warning-box ul { margin: 6px 0 0 0; padding-left: 20px; }",
        "</style></head><body><div class='container'>",
        "<h1>Canvas Course Comparison</h1>",
        f"<p><strong>Last Summer:</strong> {esc(old_path)}<br><strong>This Summer:</strong> {esc(new_path)}</p>",
    ]

    if warnings:
        out.append("<div class='warning-box'><strong>Diagnostic warnings</strong><ul>")
        for w in warnings:
            out.append(f"<li>{esc(w)}</li>")
        out.append("</ul></div>")

    out.append("<h2>Content Overview</h2>")
    out.append("<table class='overview'><tr><th>Title</th><th>Status</th></tr>")
    for t in report["added"]:
        out.append(f"<tr><td>{esc(t)}</td><td><span class='badge b-added'>Added</span></td></tr>")
    for t in report["removed"]:
        out.append(f"<tr><td>{esc(t)}</td><td><span class='badge b-removed'>Removed</span></td></tr>")
    for idx, (t, _changes) in enumerate(report["modified"]):
        out.append(f"<tr><td><a href='#mod_{idx}'>{esc(t)}</a></td><td><span class='badge b-modified'>Modified</span></td></tr>")
    out.append("</table>")

    m = report["media"]
    out.append("<h2>Media Overview (Audio/Video)</h2>")
    out.append("<table class='overview'><tr><th>File Name</th><th>Status</th><th>Details</th></tr>")
    for t in m["added"]:
        out.append(f"<tr><td>{esc(t)}</td><td><span class='badge b-added'>Added</span></td><td></td></tr>")
    for t in m["removed"]:
        out.append(f"<tr><td>{esc(t)}</td><td><span class='badge b-removed'>Removed</span></td><td></td></tr>")
    for t, (old_sz, old_crc), (new_sz, new_crc) in m["changed"]:
        if old_sz != new_sz:
            detail = f"{old_sz:,} bytes &rarr; {new_sz:,} bytes"
        else:
            detail = f"same size ({old_sz:,} bytes) &mdash; content differs"
        out.append(f"<tr><td>{esc(t)}</td><td><span class='badge b-modified'>Changed</span></td><td>{detail}</td></tr>")
    out.append("</table>")

    if report["modified"]:
        out.append("<div class='diff-section'><h2>Detailed Modifications</h2>")
        for idx, (t, changes) in enumerate(report["modified"]):
            out.append(f"<h3 id='mod_{idx}'>{esc(t)}</h3>")
            for c in changes:
                if c["kind"] == "text":
                    out.append(f"<h4>{esc(c['label'])}</h4>")
                    # HtmlDiff.make_table escapes cell content internally —
                    # safe to pass raw lines here.
                    diff_table = d.make_table(
                        c["old"].splitlines(), c["new"].splitlines(),
                        "Last Summer", "This Summer", context=True,
                    )
                    out.append(diff_table)
                elif c["kind"] == "field":
                    out.append(
                        f"<div class='field-change'><strong>{esc(c['label'])}</strong><br><br>"
                        f"Last Summer: <code>{esc(c['old'])}</code><br>"
                        f"This Summer: <code>{esc(c['new'])}</code></div>"
                    )
        out.append("</div>")

    out.append("</div></body></html>")
    return "\n".join(out)


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
        print(f"Notice: {', '.join(missing)} not installed. Affected .docx/.pptx files "
              f"will be skipped entirely (not compared) rather than shown as unchanged, "
              f"since without reading them there's no honest way to tell.\n"
              f"  Install with: pip install {' '.join(missing)}\n")

    if args.quizzes:
        print("Quiz comparison enabled — this can take a while on courses with large question banks.\n")

    def _load(path: str, label: str):
        try:
            return load_course(path, parse_quizzes=args.quizzes, label=label)
        except FileNotFoundError:
            print(f"Error: file not found — {path}", file=sys.stderr)
            sys.exit(1)
        except zipfile.BadZipFile:
            print(f"Error: {path} isn't a valid .imscc/zip file (or it's corrupted).", file=sys.stderr)
            sys.exit(1)
        except KeyError:
            print(f"Error: {path} doesn't contain an imsmanifest.xml — "
                  f"is this a Canvas course export?", file=sys.stderr)
            sys.exit(1)

    print(f"Loading last summer's course : {args.last_summer}")
    old_text, old_media, old_skipped, old_warnings = _load(args.last_summer, "last summer's course")
    print(f"  {len(old_text)} content items, {len(old_media)} media files"
          + (f", {old_skipped} docx/pptx skipped" if old_skipped else ""))

    print(f"Loading this summer's course : {args.this_summer}")
    new_text, new_media, new_skipped, new_warnings = _load(args.this_summer, "this summer's course")
    print(f"  {len(new_text)} content items, {len(new_media)} media files"
          + (f", {new_skipped} docx/pptx skipped" if new_skipped else "") + "\n")

    all_warnings = old_warnings + new_warnings

    print("Comparing...")
    report = compare_courses(old_text, old_media, new_text, new_media)

    # Colored version for the terminal; plain version for any saved file
    # (escape codes in a text file you open later are just noise).
    print("\n" + format_report(report, args.last_summer, args.this_summer, use_colors=True, warnings=all_warnings))

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(format_report(report, args.last_summer, args.this_summer, use_colors=False, warnings=all_warnings))
        print(f"Text report saved to: {args.output}")

    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(format_html_report(report, args.last_summer, args.this_summer, warnings=all_warnings))
        print(f"HTML report saved to: {args.html}")


if __name__ == "__main__":
    main()
