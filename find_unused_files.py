#!/usr/bin/env python3
"""
Unused course files — entry point shim (see compare_canvas_courses.py for why
this exists). If the package is installed, use the `canvas-unused-files`
console script instead.

Usage:
    python find_unused_files.py course.imscc [--csv files.csv] [--html files.html] [--all]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from canvas_compare.unused_cli import main  # noqa: E402  (import must follow sys.path edit)

if __name__ == "__main__":
    main()
