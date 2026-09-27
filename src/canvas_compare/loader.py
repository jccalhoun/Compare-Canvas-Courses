"""
Opens an .imscc export and builds the (text_items, media_items) pair that
diff.compare_courses() consumes.

The file-extension tuples below (MEDIA_EXTENSIONS etc.) live here rather
than in a shared constants module: they're read nowhere outside this
file's own unlinked-file loop, so a "constants.py" would just be
indirection with a single consumer — see the naming note atop
parse_html.py for the same reasoning applied to CANVAS_REFERENCE_TOKENS.
"""

from __future__ import annotations

import sys
import zipfile

from bs4 import BeautifulSoup

from .parse_manifest import parse_manifest
from .parse_html import clean_html
from .parse_assignment import parse_xml_fields
from .parse_quizzes import extract_quiz_questions
from .parse_office import HAVE_DOCX, HAVE_PPTX, extract_docx_text, extract_pptx_text

MEDIA_EXTENSIONS = ('.mp4', '.mp3', '.wav', '.avi', '.mov', '.mkv', '.m4a', '.webm', '.flac', '.aac')
DOCX_EXTENSIONS  = ('.docx',)
PPTX_EXTENSIONS  = ('.pptx',)
TEXT_EXTENSIONS  = ('.txt', '.csv', '.md', '.markdown')


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
    diagnostic warnings below (e.g. the course's short file name).
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
            question_text = ""
            if info["type"] == "quiz" and parse_quizzes and info.get("quiz_path") and info["quiz_path"] in all_files:
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
                    if not HAVE_DOCX:
                        skipped_office += 1
                        continue
                    entry = _blank_entry("docx")
                    entry["instructions"] = extract_docx_text(raw_bytes)
                    text_items[f"[Document] {display_name}"] = entry

                elif name_lower.endswith(PPTX_EXTENSIONS):
                    if not HAVE_PPTX:
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
