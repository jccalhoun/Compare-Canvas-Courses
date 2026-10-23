"""Small helpers shared across modules (currently just short_label).
Deliberately not a catch-all: a helper belongs here only if more than one
module needs it."""

from __future__ import annotations


def short_label(path: str) -> str:
    """
    Base filename for display, used anywhere a full path would be too
    long to repeat throughout a report (diff headers, field before/after
    labels, table column headers). Handles both / and \\ separators
    regardless of which OS generated the path vs which OS is rendering
    the report (e.g. a Windows path shown in a report built on Linux).
    """
    return path.replace("\\", "/").rsplit("/", 1)[-1]
