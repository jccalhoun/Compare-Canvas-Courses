"""
Canvas Course Comparison Tool — CLI entry point.

Compares two .imscc export files and reports assignments, discussions,
pages, documents (.docx), and presentations (.pptx) that were added,
removed, or modified — ignoring due date changes. Also flags media files
(audio/video) whose file sizes differ between courses.

Usage:
    python compare_canvas_courses.py old_course.imscc new_course.imscc

Save a plain text report to file:
    python compare_canvas_courses.py old_course.imscc new_course.imscc --output report.txt

Save an HTML report with side-by-side diffs:
    python compare_canvas_courses.py old_course.imscc new_course.imscc --html report.html

Also compare Classic Quiz questions (off by default — slower on courses
with many quizzes/question banks):
    python compare_canvas_courses.py old_course.imscc new_course.imscc --quizzes

Leave settings out of the comparison, or whole sections out:
    python compare_canvas_courses.py old_course.imscc new_course.imscc --ignore lockdown,published
    python compare_canvas_courses.py old_course.imscc new_course.imscc --skip files,media
    python compare_canvas_courses.py --list-options        # everything these accept

Requirements:
    pip install beautifulsoup4 lxml
    pip install python-docx python-pptx   # optional, for .docx/.pptx support
    (or: pip install "canvas-compare[office]" if installed as a package)

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
      CANVAS_REFERENCE_TOKENS in parse_html.py). An ordinary relative href
      with no token (e.g. straight to another file in the export) isn't
      specially surfaced, and a change to one won't show up in the diff.

This is the composition root: the one module allowed to import from
every other module in the package. Nothing else should import cli.py.
"""

from __future__ import annotations

import argparse
import sys
import zipfile

from .diff import compare_courses
from .loader import load_course
from .options import (IGNORE_GROUPS, SECTIONS, CompareOptions, apply_ignored_fields,
                      parse_names)
from .parse_manifest import MissingManifestError
from .parse_office import missing_optional_deps
from .report_html import format_html_report
from .report_json import format_json_report
from .report_text import format_report
from .utils import short_label


def main():
    parser = argparse.ArgumentParser(
        description="Compare two Canvas .imscc course exports."
    )
    parser.add_argument("old_course", nargs="?", help="Path to the older course's .imscc export")
    parser.add_argument("new_course", nargs="?", help="Path to the newer course's .imscc export")
    parser.add_argument("--output", "-o",
                        help="Save a plain text report to this file path (optional)",
                        default=None)
    parser.add_argument("--html",
                        help="Save an HTML report with side-by-side diffs to this file path (optional)",
                        default=None)
    parser.add_argument("--json", metavar="PATH", default=None,
                        help="Save a machine-readable JSON report to this file path (optional)")
    parser.add_argument("--quizzes", action="store_true",
                        help="Also compare Classic Quiz questions and question banks "
                             "(off by default — slower on courses with many quizzes/questions)")
    parser.add_argument("--skip", action="append", metavar="SECTIONS",
                        help="Leave whole sections out, comma-separated (see --list-options)")
    parser.add_argument("--ignore", action="append", metavar="NAMES",
                        help="Leave settings out of the comparison, comma-separated: a group "
                             "name (see --list-options) or any individual field name")
    parser.add_argument("--list-options", action="store_true",
                        help="Show what --skip and --ignore accept, then exit")
    args = parser.parse_args()

    if args.list_options:
        print("--skip takes any of (the section is not read at all):")
        for name, desc in SECTIONS.items():
            print(f"    {name:<10} {desc}")
        print("\n--ignore takes any of (the setting is read but left out of the comparison):")
        for name, (desc, _, _) in IGNORE_GROUPS.items():
            print(f"    {name:<10} {desc}")
        print("    ...or the name of any field shown as 'Field: name' in a report, "
              "e.g. --ignore points_possible,submission_types")
        return
    if not (args.old_course and args.new_course):
        parser.error("two .imscc files are required (the old course, then the new one)")

    skip = set(parse_names(args.skip))
    unknown = skip - set(SECTIONS)
    if unknown:
        parser.error(f"unknown section(s) for --skip: {', '.join(sorted(unknown))} "
                     f"(choose from: {', '.join(SECTIONS)})")
    ignore = parse_names(args.ignore)
    options = CompareOptions(
        quiz_questions=args.quizzes,
        banks=args.quizzes,
        skip=frozenset(skip),
        ignore_groups=frozenset(n for n in ignore if n in IGNORE_GROUPS),
        ignore_fields=frozenset(n for n in ignore if n not in IGNORE_GROUPS),
    )

    missing = missing_optional_deps()
    if missing:
        print(f"Notice: {', '.join(missing)} not installed. Affected .docx/.pptx files "
              f"will be skipped entirely (not compared) rather than shown as unchanged, "
              f"since without reading them there's no honest way to tell.\n"
              f"  Install with: pip install {' '.join(missing)}\n")

    if args.quizzes:
        print("Quiz comparison enabled — this can take a while on courses with large question banks.\n")

    def _load(path: str, label: str):
        try:
            return load_course(path, label=label, options=options)
        except FileNotFoundError:
            print(f"Error: file not found — {path}", file=sys.stderr)
            sys.exit(1)
        except zipfile.BadZipFile:
            print(f"Error: {path} isn't a valid .imscc/zip file (or it's corrupted).", file=sys.stderr)
            sys.exit(1)
        except MissingManifestError:
            print(f"Error: {path} doesn't contain an imsmanifest.xml — "
                  f"is this a Canvas course export?", file=sys.stderr)
            sys.exit(1)

    old_label = short_label(args.old_course)
    new_label = short_label(args.new_course)

    print(f"Loading {old_label} : {args.old_course}")
    old = _load(args.old_course, old_label)
    print(f"  {len(old.text_items)} content items, {len(old.media_items)} media files"
          + (f", {len(old.other_files)} other files" if old.other_files else "")
          + (f", {old.skipped_office} docx/pptx skipped" if old.skipped_office else ""))

    print(f"Loading {new_label} : {args.new_course}")
    new = _load(args.new_course, new_label)
    print(f"  {len(new.text_items)} content items, {len(new.media_items)} media files"
          + (f", {len(new.other_files)} other files" if new.other_files else "")
          + (f", {new.skipped_office} docx/pptx skipped" if new.skipped_office else "") + "\n")

    all_warnings = old.warnings + new.warnings

    # Settings the options leave out are removed from both courses before comparing.
    dropped = apply_ignored_fields(old.text_items, options) | apply_ignored_fields(new.text_items, options)
    for name in sorted(options.ignore_fields - dropped):
        print(f"Notice: no field called '{name}' was found in either course, so --ignore {name} "
              f"had no effect. (Groups: {', '.join(IGNORE_GROUPS)}.)\n")
    notes = options.describe(dropped) + old.notices + new.notices

    print("Comparing...")
    report = compare_courses(old.text_items, old.media_items, new.text_items, new.media_items,
                             old_label, new_label,
                             old_other=old.other_files, new_other=new.other_files)
    notes += report["notes"]

    # Colored version for the terminal; plain version for any saved file
    # (escape codes in a text file you open later are just noise).
    print("\n" + format_report(report, args.old_course, args.new_course, use_colors=True, warnings=all_warnings, notes=notes))

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(format_report(report, args.old_course, args.new_course, use_colors=False, warnings=all_warnings, notes=notes))
        print(f"Text report saved to: {args.output}")

    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(format_html_report(report, args.old_course, args.new_course, warnings=all_warnings, notes=notes))
        print(f"HTML report saved to: {args.html}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            f.write(format_json_report(report, args.old_course, args.new_course,
                                       options=options, warnings=all_warnings, notes=notes))
        print(f"JSON report saved to: {args.json}")


if __name__ == "__main__":
    main()
