"""Parses Canvas assignment_settings.xml (and similar) into flat fields."""

from __future__ import annotations

from bs4 import BeautifulSoup

# Date/time fields to skip when comparing assignment metadata
IGNORED_FIELDS = {
    "due_at", "lock_at", "unlock_at", "peer_reviews_due_at",
    "all_day_date", "created_at", "updated_at", "last_edited_at",
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
            if tag.name in fields and tag.name in MULTI_VALUE_FIELDS:
                fields[tag.name] = f"{fields[tag.name]}, {val}"
            else:
                fields[tag.name] = val
    return fields
