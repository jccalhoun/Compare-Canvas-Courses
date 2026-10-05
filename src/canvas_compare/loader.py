"""
Opens an .imscc export and builds the (text_items, media_items) pair that
diff.compare_courses() consumes.

The file-extension tuples below (MEDIA_EXTENSIONS etc.) live here rather
than in a shared constants module: they're read nowhere outside this
file's own unlinked-file loop, so a "constants.py" would just be
indirection with a single consumer (CANVAS_REFERENCE_TOKENS is likewise
kept next to its only user, in parse_html.py).
"""

from __future__ import annotations

import sys
import zipfile
from typing import NamedTuple

from bs4 import BeautifulSoup

from .parse_manifest import parse_manifest
from .parse_html import clean_html, extract_page_meta
from .options import CompareOptions
from .parse_assignment import extract_rubric_ref, extract_title, parse_xml_fields
from .parse_modules import parse_module_outline
from .parse_quizzes import extract_quiz_questions, parse_bank
from .parse_rubrics import parse_rubrics
from .parse_office import (HAVE_DOCX, HAVE_PPTX, extract_docx_text, extract_pptx_text,
                           missing_optional_deps)

MEDIA_EXTENSIONS = ('.mp4', '.mp3', '.wav', '.avi', '.mov', '.mkv', '.m4a', '.webm', '.flac', '.aac')
DOCX_EXTENSIONS  = ('.docx',)
PPTX_EXTENSIONS  = ('.pptx',)
TEXT_EXTENSIONS  = ('.txt', '.csv', '.md', '.markdown')

# Files Canvas writes for its own use, not course content.
CANVAS_CONTROL_FILES = {"imsmanifest.xml", "course_settings/canvas_export.txt"}

# Fixed locations Canvas uses for course-level content that isn't part of the
# module item tree (so the manifest never links to them).
RUBRICS_PATH  = "course_settings/rubrics.xml"
MODULES_PATH  = "course_settings/module_meta.xml"
SYLLABUS_PATH = "course_settings/syllabus.html"


class LoadedCourse(NamedTuple):
    """What load_course returns (still unpackable as a plain tuple)."""
    text_items: dict       # (kind, name) -> content dict
    media_items: dict      # audio/video name -> (size, CRC32)
    other_files: dict      # other course files (PDFs, images, ...) name -> (size, CRC32)
    skipped_office: int    # .docx/.pptx skipped because the library isn't installed
    warnings: list         # problems worth attention, shown in the report's warnings box
    notices: list          # information only (e.g. copies paired by content), shown as a quiet note


def _blank_entry() -> dict:
    return {"instructions": "", "fields": {}, "discussion_text": ""}


def _settings_fields(raw: str, rubric_titles: dict, include_rubric: bool = True) -> dict:
    """
    Fields from an assignment_settings.xml (or graded-discussion metadata)
    file, plus a `rubric` field naming the rubric it points at. The pointer
    itself is an identifier that differs between exports, so it is resolved
    to the rubric's title.
    """
    fields = parse_xml_fields(raw)
    ref = extract_rubric_ref(raw) if include_rubric else None
    if ref:
        fields["rubric"] = rubric_titles.get(ref, "[rubric not found in this export]")
    return fields


class _Skipped(Exception):
    """Internal: a section the options leave out (not an error)."""


def _warn(warnings: list, msg: str) -> None:
    """Record a diagnostic (shown in saved reports) and echo it to stderr."""
    warnings.append(msg)
    print(f"  Warning: {msg}", file=sys.stderr)


def _with_suffix(key, n: int):
    """Append " (n)" to a key's name: the second element of a (kind, name) tuple, or a plain string key."""
    if isinstance(key, tuple):
        return (key[0], f"{key[1]} ({n})")
    return f"{key} ({n})"


def _add_item(container: dict, key, value, collisions: list) -> None:
    """
    Insert into `container`, disambiguating on a key collision instead of
    silently overwriting whatever was there.

    text_items keys are (kind, name) tuples — kind is "item" (a titled
    manifest entry), "quiz", or one of the file kinds "document"/
    "presentation"/"page"/"file". Keeping kind out of the name string means
    an instructor's own title like "[Document] Syllabus" can no longer land
    on the same key as an unrelated attached file called "Syllabus": they
    are ("item", "[Document] Syllabus") vs ("document", "Syllabus").

    What's left is two items of the SAME kind sharing a name (copies of a
    question bank, say). The later one gets a numeric suffix, and every
    member of the group is tagged with `dup_group` so the comparison can
    pair copies by CONTENT: which copy gets the "(2)" depends on the order
    the archive lists them in, and that differs between any two exports.
    media_items and other_files use plain string keys and (size, CRC)
    values, so they are only suffixed and reported.
    """
    original_key = key
    suffix = 2
    while key in container:
        key = _with_suffix(original_key, suffix)
        suffix += 1
    if key != original_key:
        kind = original_key[0] if isinstance(original_key, tuple) else "course file"
        shown = original_key[1] if isinstance(original_key, tuple) else original_key
        collisions.append((kind, shown))
        if isinstance(value, dict):
            value["dup_group"] = original_key
            if isinstance(container[original_key], dict):
                container[original_key]["dup_group"] = original_key
    container[key] = value


def _report_collisions(warnings: list, notices: list, label: str, collisions: list) -> None:
    """
    One message per kind, not one per collision: shared names are normal (a
    course full of copied question banks has dozens). For items, the copies
    are paired by content when comparing, so the message is only a notice.
    Course files are paired by archive order instead, so a clash there could
    mis-pair and stays a warning.
    """
    by_kind = {}
    for kind, name in collisions:
        names = by_kind.setdefault(kind, [])
        if name not in names:
            names.append(name)
    for kind, names in by_kind.items():
        shown = ", ".join(repr(n) for n in names[:4]) + (f" (+{len(names) - 4} more)" if len(names) > 4 else "")
        if kind == "course file":
            _warn(warnings, f"{label}: {len(names)} {kind} name(s) are used by more than one {kind}, "
                            f"e.g. {shown}. Check both in Canvas if this looks wrong.")
        else:
            msg = (f"{label}: {len(names)} {kind} name(s) are used by more than one {kind}, e.g. {shown}. "
                   f"Copies were matched to the other course's by content.")
            notices.append(msg)
            print(f"  Note: {msg}", file=sys.stderr)


def load_course(imscc_path: str, parse_quizzes: bool = False, label: str = "",
                options: CompareOptions | None = None) -> LoadedCourse:
    """
    Open an imscc file and return:
        text_items      : (kind, name) -> content dict  (assignments, discussions,
                                                   pages, docx, pptx, plain-
                                                   text files, and quizzes
                                                   when parse_quizzes=True)
        media_items     : title -> (size, CRC32)  (audio/video only)
        other_files     : name -> (size, CRC32)  (everything else under
                          web_resources/ that isn't compared by content:
                          PDFs, images, ... — never opened, since both
                          values come straight from the zip directory)
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
    diagnostic warnings below (e.g. the course's short file name).
    """
    # `parse_quizzes` is the older way to ask for quiz questions and banks;
    # `options` supersedes it.
    options = options or CompareOptions(quiz_questions=parse_quizzes, banks=parse_quizzes)
    text_items     = {}
    media_items    = {}
    other_files    = {}
    skipped_office = 0
    warnings       = []
    notices        = []
    collisions     = []   # (kind, name) pairs, summarised at the end

    # Diagnostic counters — tallied from EVERY manifest item of the given
    # type, before the has_known_path filter below runs. If they were
    # instead derived from text_items after filtering, an assignment/quiz
    # whose paths failed to resolve would be silently dropped from
    # text_items by that same filter and vanish from these counts too —
    # defeating the exact diagnostic meant to catch that failure.
    assignment_total, assignment_with_fields = 0, 0
    quiz_total, quiz_with_questions = 0, 0

    with zipfile.ZipFile(imscc_path, "r") as z:
        all_files      = {info.filename: info for info in z.infolist()}
        manifest_items, href_index = parse_manifest(z)
        processed      = set()

        # ── Rubrics ──────────────────────────────────────────────────────────
        # Loaded before the manifest items because an assignment only holds a
        # pointer to its rubric; this maps pointer -> title. Each rubric is
        # also compared in its own right, matched by title (the identifiers
        # differ between exports, so they never appear in the diff).
        rubric_titles = {}
        if RUBRICS_PATH in all_files:
            processed.add(RUBRICS_PATH)
            try:
                if not options.wants("rubrics"):
                    raise _Skipped
                raw = z.read(RUBRICS_PATH).decode("utf-8-sig", errors="replace")
                for rubric in parse_rubrics(raw):
                    rubric_titles[rubric["identifier"]] = rubric["title"]
                    entry = _blank_entry()
                    entry["instructions"] = rubric["outline"]
                    entry["fields"] = rubric["fields"]
                    _add_item(text_items, ("rubric", rubric["title"]), entry, collisions)
            except _Skipped:
                pass
            except Exception as e:
                _warn(warnings, f"{label}: could not read {RUBRICS_PATH} ({e}); rubrics were not compared.")

        # ── Manifest-linked items (assignments, discussions, pages, quizzes) ─
        for title, info in manifest_items.items():
            entry = _blank_entry()

            if info.get("html_path") and info["html_path"] in all_files:
                raw = z.read(info["html_path"]).decode("utf-8-sig", errors="replace")
                entry["instructions"] = clean_html(raw)
                if info["type"] == "other":
                    # A plain page: its published state etc. sit in the HTML
                    # head. (Assignments and quizzes get theirs from their
                    # settings XML instead.)
                    entry["fields"].update(extract_page_meta(raw))
                processed.add(info["html_path"])

            if info.get("settings_path") and info["settings_path"] in all_files:
                raw = z.read(info["settings_path"]).decode("utf-8-sig", errors="replace")
                entry["fields"] = _settings_fields(raw, rubric_titles, options.wants("rubrics"))
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
            question_text = ""
            if info["type"] == "quiz" and options.quiz_questions and info.get("quiz_path") and info["quiz_path"] in all_files:
                raw = z.read(info["quiz_path"]).decode("utf-8-sig", errors="replace")
                question_text = extract_quiz_questions(raw)
                if question_text:
                    entry["instructions"] = question_text
                elif entry["fields"].get("points_possible"):
                    # Real quiz (has points, a description, etc.) but the
                    # QTI <section> has zero <item> tags — confirmed against
                    # a real export this isn't a parsing bug (the section
                    # is genuinely empty in the file). The two known causes:
                    # a Canvas New Quizzes item (its question content lives
                    # in a newer, separate data model not represented in
                    # this Common Cartridge format at all — Classic Quizzes'
                    # QTI export is kept only as a metadata stub for
                    # backward compatibility), or a quiz drawing questions
                    # from a linked question bank not inlined in this file.
                    # Labeled rather than left blank so it reads as "known
                    # gap" instead of silently looking unchanged/broken.
                    entry["instructions"] = (
                        "[No questions found in this export — likely a New "
                        "Quizzes item (question content isn't included in "
                        "this export format), or a quiz drawing from a "
                        "linked question bank not inlined in this file]"
                    )
                processed.add(info["quiz_path"])

            if info["type"] == "assignment":
                assignment_total += 1
                if entry["fields"]:
                    assignment_with_fields += 1
            if info["type"] == "quiz":
                quiz_total += 1
                # Diagnostic uses the RAW extraction result, not
                # entry["instructions"] — once labeled above, instructions
                # is never empty again, which would silently blind this
                # check to a genuine wholesale extraction failure (every
                # quiz in the course coming back with zero items because
                # quiz_path is resolving to the wrong file, say) by making
                # it look identical to the "known, expected gap" case.
                if question_text.strip():
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
                key = ("quiz", title) if info["type"] == "quiz" else ("item", title)
                _add_item(text_items, key, entry, collisions)

        if assignment_total and not assignment_with_fields:
            msg = (f"{label} has {assignment_total} assignment(s) but none produced "
                   f"any metadata fields (points, submission type, etc). settings_path "
                   f"resolution may be failing on this export's manifest structure.")
            warnings.append(msg)
            print(f"  Warning: {msg}", file=sys.stderr)
        if options.quiz_questions and quiz_total and not quiz_with_questions:
            msg = (f"{label} has {quiz_total} quiz(zes) but none produced any "
                   f"question text. quiz_path may be resolving to the wrong file on this "
                   f"export's manifest structure — check imsmanifest.xml for how the quiz "
                   f"resource is wrapped.")
            warnings.append(msg)
            print(f"  Warning: {msg}", file=sys.stderr)

        # ── Course-level content outside the item tree ───────────────────────
        # Module structure and the syllabus. If a manifest item already read
        # one of these files it is in `processed`, and is skipped here so it
        # isn't listed twice.
        if MODULES_PATH in all_files and MODULES_PATH not in processed:
            processed.add(MODULES_PATH)
            try:
                if not options.wants("modules"):
                    raise _Skipped
                raw = z.read(MODULES_PATH).decode("utf-8-sig", errors="replace")
                entry = _blank_entry()
                entry["instructions"] = parse_module_outline(raw, options.hides_publish_state)
                _add_item(text_items, ("modules", "Module Structure"), entry, collisions)
            except _Skipped:
                pass
            except Exception as e:
                _warn(warnings, f"{label}: could not read {MODULES_PATH} ({e}); module structure was not compared.")
        if SYLLABUS_PATH in all_files and SYLLABUS_PATH not in processed:
            processed.add(SYLLABUS_PATH)
            try:
                if not options.wants("syllabus"):
                    raise _Skipped
                raw = z.read(SYLLABUS_PATH).decode("utf-8-sig", errors="replace")
                entry = _blank_entry()
                entry["instructions"] = clean_html(raw)
                _add_item(text_items, ("syllabus", "Course Syllabus"), entry, collisions)
            except _Skipped:
                pass
            except Exception as e:
                _warn(warnings, f"{label}: could not read {SYLLABUS_PATH} ({e}); the syllabus was not compared.")

        # ── Question banks ───────────────────────────────────────────────────
        # Banks live in non_cc_assessments/ as QTI files that the manifest
        # never links to (quizzes have a second copy there too, which is
        # skipped: a quiz is compared through its own QTI above). Same
        # --quizzes switch as quiz questions: a course can hold thousands of
        # bank questions, so parsing them all is slow. Only the first few KB
        # of each file is read to tell a bank from a quiz.
        if options.banks and options.wants("banks"):
            for filename in sorted(all_files):
                if not (filename.startswith("non_cc_assessments/") and filename.endswith(".qti")):
                    continue
                try:
                    with z.open(filename) as f:
                        head = f.read(4096)
                        if b"<objectbank" not in head:
                            continue
                        raw = (head + f.read()).decode("utf-8-sig", errors="replace")
                    bank = parse_bank(raw)
                    entry = _blank_entry()
                    entry["instructions"] = bank["questions"]
                    if bank["state"]:
                        entry["fields"]["bank_state"] = bank["state"]
                    _add_item(text_items, ("bank", bank["title"] or filename), entry, collisions)
                except Exception as e:
                    _warn(warnings, f"{label}: could not read {filename} ({e}); that question bank was not compared.")

        # ── Assignments not linked into any module ───────────────────────────
        # An assignment that sits in no module isn't in the manifest's item
        # tree, so the loop above never sees it, but its files are still in
        # the archive: <folder>/assignment_settings.xml plus a description
        # HTML. Left to the generic loop below, the HTML became a "[Page]"
        # named after the folder's id (which differs between exports, so the
        # same assignment showed up as removed + added) and the settings were
        # ignored outright. Read them together instead and name the item by
        # its title, like a linked assignment. A folder with any file already
        # read belongs to a linked item and is left alone.
        for filename in sorted(all_files):
            if not filename.endswith("/assignment_settings.xml") or filename in processed:
                continue
            folder = filename[: -len("assignment_settings.xml")]
            if any(p.startswith(folder) for p in processed):
                continue
            try:
                settings = z.read(filename).decode("utf-8-sig", errors="replace")
                title = extract_title(settings) or folder.rstrip("/").rsplit("/", 1)[-1]
                entry = _blank_entry()
                entry["fields"] = _settings_fields(settings, rubric_titles, options.wants("rubrics"))
                processed.add(filename)
                pages = sorted(f for f in all_files
                               if f.startswith(folder) and "/" not in f[len(folder):]
                               and f.lower().endswith((".html", ".htm")) and f not in processed)
                if pages:
                    raw = z.read(pages[0]).decode("utf-8-sig", errors="replace")
                    entry["instructions"] = clean_html(raw)
                    processed.add(pages[0])
                _add_item(text_items, ("item", title), entry, collisions)
            except Exception as e:
                _warn(warnings, f"{label}: could not read {filename} ({e}); that assignment was not compared.")

        # ── Unlinked / attached files (docx, pptx, media, plain text, orphan pages) ─
        # Sorted by archive path so that when two files resolve to the same
        # display name, which one gets the "(2)" suffix (see _add_item) is
        # decided by the files themselves, not by the order this particular
        # export happened to store them in. Otherwise the same two files could
        # swap suffixes between two exports and diff as false changes.
        for filename, file_info in sorted(all_files.items()):
            if file_info.is_dir() or filename in processed or filename in CANVAS_CONTROL_FILES:
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
                if options.wants("media"):
                    _add_item(media_items, display_name, (file_info.file_size, file_info.CRC),
                              collisions)
                continue

            # Only the file types compared below are read at all. Anything else
            # (PDFs, images, Canvas's own XML, ...) is skipped without being
            # opened: reading a zip member decompresses all of it.
            is_docx = name_lower.endswith(DOCX_EXTENSIONS)
            is_pptx = name_lower.endswith(PPTX_EXTENSIONS)
            is_html = name_lower.endswith((".html", ".htm"))
            is_text = name_lower.endswith(TEXT_EXTENSIONS)
            if not (is_docx or is_pptx or is_html or is_text):
                # Other course files (PDFs, images, ...). Limited to
                # web_resources/, where Canvas puts the course's own files,
                # so its own XML bookkeeping elsewhere in the archive isn't
                # reported as "files".
                if name_lower.startswith("web_resources/") and options.wants("files"):
                    _add_item(other_files, display_name, (file_info.file_size, file_info.CRC), collisions)
                continue
            if (is_docx or is_pptx) and not options.wants("documents"):
                continue
            if is_docx and not HAVE_DOCX:
                skipped_office += 1
                continue
            if is_pptx and not HAVE_PPTX:
                skipped_office += 1
                continue
            # An HTML page not referenced anywhere in the manifest item tree
            # (a leftover or hand-added page) is compared, but not Canvas's
            # own auto-generated quiz preview/landing pages
            # (non_cc_assessments/): they aren't authored content, and since
            # they typically embed a per-export quiz id, including them
            # would add false "modified"/"added" entries on every quiz run.
            if is_html and "non_cc_assessments" in filename:
                continue

            try:
                raw_bytes = z.read(filename)
                entry = _blank_entry()
                if is_docx:
                    kind, entry["instructions"] = "document", extract_docx_text(raw_bytes)
                elif is_pptx:
                    kind, entry["instructions"] = "presentation", extract_pptx_text(raw_bytes)
                elif is_html:
                    raw = raw_bytes.decode("utf-8-sig", errors="replace")
                    kind, entry["instructions"] = "page", clean_html(raw)
                    entry["fields"] = extract_page_meta(raw)
                else:
                    kind, entry["instructions"] = "file", raw_bytes.decode("utf-8-sig", errors="replace").strip()
                _add_item(text_items, (kind, display_name), entry, collisions)
            except Exception as e:
                # Left out of the comparison rather than included with an
                # error message as its content: two different unreadable
                # files would both carry the same message and compare as
                # "unchanged". The warning shows up in saved reports too.
                _warn(warnings, f"{label}: could not read {filename} ({e}); it was not compared.")

    _report_collisions(warnings, notices, label, collisions)
    if skipped_office:
        # Also printed once at the start by the command line, but a SAVED report
        # must say so too, or it reads as a complete comparison.
        warnings.append(f"{label}: {skipped_office} .docx/.pptx file(s) were not compared because "
                        f"{' and '.join(missing_optional_deps())} "
                        f"{'is' if len(missing_optional_deps()) == 1 else 'are'} not installed.")
    return LoadedCourse(text_items, media_items, other_files, skipped_office, warnings, notices)
