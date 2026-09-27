"""Small helpers shared across modules. Keep this file short on purpose —
it's for genuinely cross-cutting helpers only (currently just one), not a
catch-all. See constants discussion in parse_html.py/loader.py: something
belongs here only once at least two unrelated modules actually need it."""

from __future__ import annotations


def short_label(path: str) -> str:
    """
    Base filename for display, used anywhere a full path would be too
    long to repeat throughout a report (diff headers, field before/after
    labels, table column headers). Handles both / and \\ separators
    regardless of which OS generated the path vs which OS is rendering
    the report (e.g. a Windows path shown in a report built on Linux).

    Renamed from the original script's _short_label to short_label (no
    leading underscore) on the split: it's called from report_text.py,
    report_html.py, and cli.py, so the underscore — which in the original
    single-file script just meant "not part of the public argparse-driven
    interface" — would now misleadingly read as "private to this module"
    to anyone importing it from elsewhere.
    """
    return path.replace("\\", "/").rsplit("/", 1)[-1]
