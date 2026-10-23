"""
Course-level settings that live in course_settings/: the assignment groups
(with their weights and drop rules), the course settings themselves, and the
late policy.

The assignment groups become one outline, like the module outline, so a
reordered, added or removed group shows naturally and position numbers never
cascade. Each assignment also names its group (see loader.py), the same way
it names its rubric.

The settings files are compared field by field with a DENYlist rather than an
allowlist: identity (title, course code), dates, ids and the navigation menu
are left out, and everything else is compared, so settings this tool has never
seen (in other people's courses, or added by Canvas later) are still caught.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

# course_settings.xml fields that are never compared, and why:
_SETTINGS_SKIP = {
    "title", "course_code",      # identity: different for every section/semester by design
    "tab_configuration",         # navigation menu: stored with per-export tool ids
}


def _skip_setting(name: str) -> bool:
    leaf = name.rsplit(".", 1)[-1]
    return (name in _SETTINGS_SKIP or leaf.endswith("_at")              # dates
            or "identifier" in leaf or "uuid" in leaf or leaf.endswith("_id"))   # ids


def _flatten(element, prefix: str = "") -> dict:
    """Leaf values under an element; nested leaves get a dotted name
    (default_post_policy.post_manually). Empty values are left out."""
    fields = {}
    for child in element.find_all(True, recursive=False):
        name = f"{prefix}{child.name}"
        if child.find(True):
            fields.update(_flatten(child, name + "."))
        elif child.text.strip():
            fields[name] = child.text.strip()
    return fields


def parse_settings_file(raw: str) -> dict:
    """Comparable fields of course_settings.xml or late_policy.xml."""
    root = BeautifulSoup(raw, "xml").find(True)
    if root is None:
        return {}
    return {k: v for k, v in _flatten(root).items() if not _skip_setting(k)}


def parse_assignment_groups(raw: str) -> list[dict]:
    """
    One dict per group, in display order: identifier, title, weight, rules.
    Each rule is a dict of its own fields (drop_type, drop_count, ...); a
    rule that names one assignment keeps its identifierref so the loader can
    turn it into that assignment's title.
    """
    soup = BeautifulSoup(raw, "xml")
    groups = []
    for n, g in enumerate(soup.find_all("assignmentGroup")):
        def text(name):
            tag = g.find(name, recursive=False)
            return tag.text.strip() if tag is not None else ""
        rules = []
        rules_tag = g.find("rules", recursive=False)
        for r in rules_tag.find_all("rule", recursive=False) if rules_tag is not None else []:
            rules.append({c.name: c.text.strip() for c in r.find_all(True, recursive=False) if c.text.strip()})
        position = text("position")
        groups.append({
            "identifier": g.get("identifier", ""),
            "title": text("title") or "(untitled group)",
            "weight": text("group_weight"),
            "rules": rules,
            "_order": (int(position) if position.isdigit() else 10**9, n),
        })
    return sorted(groups, key=lambda g: g["_order"])


def _weight(value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return ""
    return "" if number == 0 else f"{number:g}%"


def assignment_groups_outline(groups: list[dict], assignment_titles: dict) -> str:
    """
    The groups as readable lines. A weight is shown only when it is set (a
    course without weighted grades stores 0 for every group). A rule that names
    an assignment is shown with the assignment's title, never its id, since
    ids differ between exports.
    """
    lines = []
    for g in groups:
        weight = _weight(g["weight"])
        lines.append(g["title"] + (f"  (weight {weight})" if weight else ""))
        for rule in g["rules"]:
            ref = rule.get("identifierref")
            kind = rule.get("drop_type", "rule").replace("_", " ")
            if ref:
                lines.append(f"  {kind}: {assignment_titles.get(ref, '[an assignment not in this export]')}")
            else:
                extra = " ".join(v for k, v in sorted(rule.items()) if k != "drop_type")
                lines.append(f"  {kind} {extra}".rstrip())
    return "\n".join(lines)
