#!/usr/bin/env python3
"""
Canvas Course Comparison Tool — entry point shim.

The real implementation lives in src/canvas_compare/. This file adds src/
to sys.path itself, so `python compare_canvas_courses.py ...` still works
straight out of a clone/download with no `pip install -e .` step — the
only requirement is that this file stays next to src/. If the package is
actually installed (pip install .), use the `canvas-compare` console
script instead (see pyproject.toml) and this shim isn't needed at all.

Usage:
    python compare_canvas_courses.py last_summer.imscc this_summer.imscc

See src/canvas_compare/cli.py for full usage, or run with --help.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from canvas_compare.cli import main  # noqa: E402  (import must follow sys.path edit)

if __name__ == "__main__":
    main()
