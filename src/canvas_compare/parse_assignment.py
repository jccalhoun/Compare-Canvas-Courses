"""Parses Canvas assignment_settings.xml (and similar) into flat fields."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .parse_html import clean_html

# Anything that looks like an HTML tag. Some settings hold a whole HTML
# fragment, e.g. a quiz's <description>; shown raw, it is one unreadable line.
_HTML_RE = re.compile(r"<[A-Za-z/!][^>]*>")

# A setting stored at its default value means the same as not stored at all.
# Canvas writes this one only on assignments that have been saved in a newer
# version, so across two courses it flips between "not set" and "set to off"
# (7 of the 60 modified items in a real comparison) without anything changing.
DEFAULT_VALUES = {
    "lockdown_browser_settings": '{"require_lockdown_browser":false}',
}

# Fields to skip when comparing assignment metadata: dates, and bookkeeping
# that changes whenever something ELSE in the course does.
IGNORED_FIELDS = {
    "due_at", "lock_at", "unlock_at", "peer_reviews_due_at",
    "all_day_date", "created_at", "updated_at", "last_edited_at",
    # all_day only says whether the due time is end-of-day; as far as I can
    # tell it is derived from due_at, which is already ignored.
    "all_day",
    # position is the item's place within its assignment group. It shifts
    # whenever any other assignment is added or removed (in a real 16-week
    # vs 8-week comparison, 12 items were "modified" by nothing else).
    "position",
}

# Tag names known to legitimately repeat at the same level with distinct
# values (e.g. an assignment allowing both file upload and text entry
# produces two <submission_type> tags). See parse_xml_fields for why this
# is a narrow allowlist rather than "aggregate any repeated tag."
MULTI_VALUE_FIELDS = {"submission_type"}


def parse_xml_fields(raw: str) -> dict:
    """
    Parse leaf-node tag values from a Canvas assignment_settings.xml,
    skipping any fields in IGNORED_FIELDS and any tag ending in "_id" or
    "_identifierref" (e.g. migration_id) — internal bookkeeping noise, not
    content. Note: this does NOT catch every noisy internal field —
    workflow_state (published/unpublished) is a real example that slips
    through, since it doesn't match either filter. Left unfiltered on
    purpose: whether a publish-state change is noise or exactly what you
    want flagged is a judgment call, not a bug — add it to IGNORED_FIELDS
    if you'd rather it stay quiet.

    A tag name in MULTI_VALUE_FIELDS repeated at the same level (e.g.
    multiple <submission_type> entries when an assignment allows more than
    one submission type) is aggregated into a comma-separated value rather
    than the last one silently overwriting the rest. Deliberately scoped
    to a known allowlist rather than aggregating ANY repeated tag name:
    this only walks leaf tags, with no awareness of *where* in the tree
    they sit, so a blanket "merge any repeat" rule would also merge, say,
    a <title> that legitimately appears both at the assignment level and
    inside a nested rubric criterion — turning an unrelated rubric detail
    into false "Field: title" noise on every comparison.
    """
    soup = BeautifulSoup(raw, "xml")
    fields = {}
    for tag in soup.find_all(True):
        if not tag.find(True) and tag.text.strip() and tag.name not in IGNORED_FIELDS:
            if tag.name.endswith("_identifierref") or tag.name.endswith("_id"):
                continue
            val = tag.text.strip()
            if _HTML_RE.search(val):
                val = clean_html(val)
            if DEFAULT_VALUES.get(tag.name) == val:
                continue
            if tag.name in fields and tag.name in MULTI_VALUE_FIELDS:
                fields[tag.name] = f"{fields[tag.name]}, {val}"
            else:
                fields[tag.name] = val
    return fields


def extract_rubric_ref(raw: str) -> str | None:
    """
    The identifier of the rubric an assignment (or graded discussion) uses,
    from its <rubric_identifierref> pointer, or None if it has no rubric.
    parse_xml_fields drops this tag along with every other *_identifierref
    (they are meaningless on their own), so it is read separately here and
    resolved to a rubric title by the loader.
    """
    tag = BeautifulSoup(raw, "xml").find("rubric_identifierref")
    return tag.text.strip() if tag is not None and tag.text.strip() else None


def extract_title(raw: str) -> str:
    """
    The item's own <title>: a direct child of the root element when there is
    one, otherwise the first <title> anywhere. Canvas XML can carry a second
    <title> inside a nested element (a graded discussion's metadata has one
    for the topic and one for its assignment), so "first match anywhere"
    could pick the wrong one.
    """
    soup = BeautifulSoup(raw, "xml")
    root = soup.find(True)
    tag = root.find("title", recursive=False) if root is not None else None
    if tag is None:
        tag = soup.find("title")
    return tag.text.strip() if tag is not None else ""
