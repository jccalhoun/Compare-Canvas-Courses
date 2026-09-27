"""
Canvas Course Comparison Tool — CLI entry point.

Compares two .imscc export files and reports assignments, discussions,
pages, documents (.docx), and presentations (.pptx) that were added,
removed, or modified — ignoring due date changes. Also flags media files
(audio/video) whose file sizes differ between courses.

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
from .parse_office import missing_optional_deps
from .report_html import format_html_report
from .report_text import format_report
from .utils import short_label


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

    old_label = short_label(args.last_summer)
    new_label = short_label(args.this_summer)

    print(f"Loading {old_label} : {args.last_summer}")
    old_text, old_media, old_skipped, old_warnings = _load(args.last_summer, old_label)
    print(f"  {len(old_text)} content items, {len(old_media)} media files"
          + (f", {old_skipped} docx/pptx skipped" if old_skipped else ""))

    print(f"Loading {new_label} : {args.this_summer}")
    new_text, new_media, new_skipped, new_warnings = _load(args.this_summer, new_label)
    print(f"  {len(new_text)} content items, {len(new_media)} media files"
          + (f", {new_skipped} docx/pptx skipped" if new_skipped else "") + "\n")

    all_warnings = old_warnings + new_warnings

    print("Comparing...")
    report = compare_courses(old_text, old_media, new_text, new_media, old_label, new_label)

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
