"""
Turns Canvas's course_settings/module_meta.xml into a readable text outline
so the ordinary text diff can show structural changes: modules or items
added, removed, reordered or unpublished, and changed prerequisites or
completion requirements.

Why one outline for the whole course rather than one item per module:
module titles usually carry that semester's dates ("Week 1 Monday, August
24, 2026"), and a per-module match on title would report every module as
removed-and-added each term. Reordering is also only visible when the whole
sequence is diffed together.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .options import PUBLISH_STATES

_MONTH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
          r"Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
# "August 24", "Sept. 2nd", "October 11, 2022" — a month name followed by a
# day number, with an optional year. A month name alone ("March Madness") is
# left alone, since it isn't a date.
_DATE_RE = re.compile(rf"[,\s]*\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:\s*,?\s*\d{{4}})?",
                      re.IGNORECASE)

_CONTENT_LABEL = {
    "WikiPage": "Page", "Assignment": "Assignment", "Quizzes::Quiz": "Quiz",
    "DiscussionTopic": "Discussion", "ContextExternalTool": "External Tool",
    "ExternalUrl": "External URL", "ContextModuleSubHeader": "Header",
    "Attachment": "File",
}


def strip_dates(title: str) -> str:
    """
    Drop semester-specific dates from a title, e.g.
    "Week 1 Monday, August 24, 2026" -> "Week 1 Monday". A title that is
    nothing but a date is returned unchanged rather than emptied. Applied to
    module headings, prerequisite names and item titles alike: in a real
    course 29 of 252 item titles ("Question of the day  Monday, August 24,
    2026") carried a date, and each would otherwise show as changed every term.
    """
    cleaned = " ".join(_DATE_RE.sub("", title).split())
    return cleaned or title.strip()


def _text(tag, name: str) -> str:
    child = tag.find(name, recursive=False)
    return child.text.strip() if child is not None else ""


def _by_position(tags: list) -> list:
    """Sort by the numeric <position> (document order breaks ties or fills gaps)."""
    def key(pair):
        i, t = pair
        pos = _text(t, "position")
        return (int(pos) if pos.isdigit() else 10**9, i)
    return [t for _, t in sorted(enumerate(tags), key=key)]


def parse_module_outline(raw: str, hide_publish_state: bool = False) -> str:
    soup = BeautifulSoup(raw, "xml")
    root = soup.find("modules")
    if root is None:
        return ""
    lines = []
    for m in _by_position(root.find_all("module", recursive=False)):
        head = f"## {strip_dates(_text(m, 'title'))}"
        state = _text(m, "workflow_state")
        if state and state != "active" and not (hide_publish_state and state in PUBLISH_STATES):
            head += f"  ({state})"
        lines.append(head)

        if _text(m, "require_sequential_progress") == "true":
            lines.append("  items must be completed in order")
        if _text(m, "locked") == "true":
            lines.append("  locked")
        count = _text(m, "requirement_count")
        if count:
            lines.append(f"  students must complete {count} of the requirements")

        prereqs = m.find("prerequisites", recursive=False)
        if prereqs is not None:
            for p in prereqs.find_all("prerequisite", recursive=False):
                lines.append(f"  requires module: {strip_dates(_text(p, 'title'))}")

        # A completion requirement points at the ITEM's own identifier
        # attribute (checked against a real export), not its identifierref.
        requirements = {}
        reqs = m.find("completionRequirements", recursive=False)
        if reqs is not None:
            for c in reqs.find_all("completionRequirement", recursive=False):
                text = c.get("type", "").replace("_", " ")
                min_score = _text(c, "min_score")
                if min_score:
                    text += f" ({min_score})"
                requirements[_text(c, "identifierref")] = text

        items = m.find("items", recursive=False)
        for it in _by_position(items.find_all("item", recursive=False)) if items is not None else []:
            indent = _text(it, "indent")
            level = int(indent) if indent.isdigit() else 0
            kind = _text(it, "content_type")
            line = f"  {'  ' * level}- {strip_dates(_text(it, 'title'))} [{_CONTENT_LABEL.get(kind, kind)}]"
            istate = _text(it, "workflow_state")
            if istate and istate != "active" and not (hide_publish_state and istate in PUBLISH_STATES):
                line += f" ({istate})"
            if _text(it, "new_tab") == "true":
                line += " (opens in new tab)"
            req = requirements.get(it.get("identifier", ""))
            if req:
                line += f" — {req}"
            url = _text(it, "url")
            if url:
                line += f" -> {url}"
            lines.append(line)
        lines.append("")
    return "\n".join(lines).rstrip()
