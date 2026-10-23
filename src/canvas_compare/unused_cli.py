"""
Unused course files — CLI entry point.

Lists the files in a Canvas .imscc export (the course's Files area) that
nothing in the course links to, and those linked only from unpublished
content.

Usage:
    python find_unused_files.py course.imscc
    python find_unused_files.py course.imscc --csv files.csv --html files.html
    python find_unused_files.py course.imscc --all     # also list what uses each file

Like cli.py, this is a composition root: it may import from any module in
the package, and nothing imports it.
"""

from __future__ import annotations

import argparse
import sys
import zipfile

from .parse_manifest import MissingManifestError
from .report_unused import format_unused_csv, format_unused_html, format_unused_text
from .unused_files import find_unused_files


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="List course files in a Canvas .imscc export that nothing in the course links to."
    )
    parser.add_argument("course", help="Path to the course's .imscc export")
    parser.add_argument("--csv", metavar="PATH", default=None,
                        help="Save every file with its status and uses as CSV (opens in Excel/Sheets)")
    parser.add_argument("--html", metavar="PATH", default=None,
                        help="Save an HTML report")
    parser.add_argument("--all", action="store_true",
                        help="Also list referenced files, and what uses each one, in the terminal report")
    args = parser.parse_args(argv)

    try:
        result = find_unused_files(args.course)
    except FileNotFoundError:
        print(f"Error: file not found — {args.course}", file=sys.stderr)
        sys.exit(1)
    except zipfile.BadZipFile:
        print(f"Error: {args.course} isn't a valid .imscc/zip file (or it's corrupted).", file=sys.stderr)
        sys.exit(1)
    except MissingManifestError:
        print(f"Error: {args.course} doesn't contain an imsmanifest.xml — "
              f"is this a Canvas course export?", file=sys.stderr)
        sys.exit(1)

    print(format_unused_text(result, args.course, show_all=args.all))

    if args.csv:
        # utf-8-sig so Excel opens accented file names correctly.
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as f:
            f.write(format_unused_csv(result))
        print(f"\nCSV saved to: {args.csv}")
    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(format_unused_html(result, args.course))
        print(f"HTML report saved to: {args.html}")


if __name__ == "__main__":
    main()
