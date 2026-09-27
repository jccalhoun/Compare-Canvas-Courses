"""
HTML/text normalization for comparison: strips markup down to plain text
and resolves Canvas's inert export reference tokens into readable labels.

Named parse_html (not html.py) purely so it reads as visually distinct
from the stdlib html module that report_html.py imports — NOT to avoid a
shadowing bug. Python 3 imports are absolute by default, so a sibling
module named html.py could never shadow the real stdlib `html` for
another file's `import html`; that was a Python 2 problem. This is a
readability choice for humans scanning the directory, nothing more.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

# Canvas replaces links to other content in the *same course* with inert
# placeholder tokens on export (e.g. "$WIKI_REFERENCE$/pages/<id>"), meant
# to be rewritten by Canvas's own importer into a real link when the
# cartridge is re-imported somewhere. They're never real URLs on their own
# and will 404 if you try to follow them directly — swap them for a short
# readable label instead of leaving raw tokens (and a trailing internal id)
# sitting in the report.
CANVAS_REFERENCE_TOKENS = {
    "$WIKI_REFERENCE$":                  "link to another page",
    "$CANVAS_OBJECT_REFERENCE$":         "link to another course item",
    "$CANVAS_COURSE_REFERENCE$":         "link within this course",
    "$IMS-CC-FILEBASE$":                 "link to a file in this export",
    "$CANVAS_WEB_CONFERENCE_REFERENCE$": "link to a web conference",
    "$CANVAS_CONTENT_LINK_REFERENCE$":   "link to course content",
}
# Sorted longest-token-first: a regex alternation matches the first
# alternative that fits at a position, so if a future token were ever a
# prefix of another (e.g. adding "$WIKI_REFERENCE_EXT$" alongside
# "$WIKI_REFERENCE$"), an unsorted alternation could match the shorter one
# and silently leave part of the longer token unconsumed.
_TOKEN_PATTERN = re.compile(
    "(" + "|".join(re.escape(t) for t in sorted(CANVAS_REFERENCE_TOKENS, key=len, reverse=True))
    + r")(/\S*)?"
)


def _format_reference_token(match: "re.Match") -> str:
    """
    Keep the trailing migration id (e.g. the "g111" in
    "$WIKI_REFERENCE$/pages/g111") after cleaning up the token, so that a
    link genuinely changing targets between exports still shows up as a
    real diff instead of two different ids collapsing into one label.
    """
    token     = match.group(1)
    remainder = (match.group(2) or "").strip("/")
    label     = CANVAS_REFERENCE_TOKENS[token]
    if not remainder:
        return f"[{label}]"
    ref_id = remainder.rsplit("/", 1)[-1]
    return f"[{label}: {ref_id}]"


def strip_canvas_reference_tokens(text: str) -> str:
    """Replace inert Canvas export reference tokens with a readable label."""
    if "$" not in text:
        return text
    return _TOKEN_PATTERN.sub(_format_reference_token, text)


def clean_html(raw: str) -> str:
    """
    Strip HTML tags and normalize whitespace for plain-text comparison.

    Canvas's normal "insert course link" workflow puts descriptive text
    (e.g. "Getting Started") as the link's visible text, with the actual
    target only in href — which get_text() drops along with every other
    attribute. Without special handling, a link's TARGET changing (moved
    to point at a different page) would be completely invisible even
    though its visible text stayed the same. So: walk <a href> tags first
    and append a resolved-reference marker after any link whose href is a
    Canvas token and whose visible text doesn't already say the same
    thing (a raw pasted URL, where visible text and href are identical,
    is already covered by the text-level pass below and would otherwise
    get double-marked).
    """
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        resolved_href = strip_canvas_reference_tokens(href)
        if resolved_href == href:
            continue  # not a Canvas reference token — leave external links alone
        if strip_canvas_reference_tokens(a.get_text()) == resolved_href:
            continue  # visible text already encodes the same reference
        a.append(soup.new_string(f" {resolved_href}"))
    lines = [l.strip() for l in soup.get_text(separator="\n").splitlines()]
    text = "\n".join(l for l in lines if l)
    return strip_canvas_reference_tokens(text)
