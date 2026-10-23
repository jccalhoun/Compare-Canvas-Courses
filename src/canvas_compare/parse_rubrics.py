"""
Parses Canvas's course_settings/rubrics.xml. In a Canvas export the rubric
definitions live in this one file; an assignment (or graded discussion) only
carries a <rubric_identifierref> pointing at one of them, so the pointer is
resolved to a rubric title elsewhere (see loader.py).

Each rubric becomes an outline of its criteria and rating levels (for the
ordinary text diff) plus a few flat settings (points possible, rating order,
...) for the field diff. Criterion and rating ids are deliberately left out:
they carry no meaning for a reader, and would only add noise to a diff.
"""

from __future__ import annotations

from bs4 import BeautifulSoup


def _text(tag, name: str) -> str:
    child = tag.find(name, recursive=False)
    return " ".join(child.text.split()) if child is not None else ""


def _outline(rubric) -> str:
    lines = []
    criteria = rubric.find("criteria", recursive=False)
    for c in criteria.find_all("criterion", recursive=False) if criteria is not None else []:
        # Bulleted rather than numbered: inserting one criterion would
        # otherwise renumber, and so change, every line after it.
        lines.append(f"- {_text(c, 'description')} ({_text(c, 'points')} pts)")
        long_desc = _text(c, "long_description")
        if long_desc:
            lines.append(f"    {long_desc}")
        ratings = c.find("ratings", recursive=False)
        for r in ratings.find_all("rating", recursive=False) if ratings is not None else []:
            line = f"    * {_text(r, 'description')}: {_text(r, 'points')} pts"
            r_long = _text(r, "long_description")
            lines.append(line + (f" — {r_long}" if r_long else ""))
    return "\n".join(lines)


def parse_rubrics(raw: str) -> list[dict]:
    """
    Return one dict per rubric: identifier, title, fields, outline. Sorted by
    (title, outline) so that which of two same-titled rubrics gets a "(2)"
    suffix never depends on the order the export happened to list them.
    """
    soup = BeautifulSoup(raw, "xml")
    root = soup.find("rubrics")
    if root is None:
        return []
    rubrics = []
    for r in root.find_all("rubric", recursive=False):
        fields = {}
        for child in r.find_all(True, recursive=False):
            # read_only is left out: it looks like Canvas-managed state (only
            # 3 of 69 rubrics in a real export had it set) rather than
            # something an instructor authors, so it could differ between a
            # taught course and a fresh copy with nothing actually edited.
            if child.name in ("title", "criteria", "read_only") or child.find(True):
                continue
            if child.text.strip():
                fields[child.name] = child.text.strip()
        rubrics.append({
            "identifier": r.get("identifier", ""),
            "title":      _text(r, "title") or "(untitled rubric)",
            "fields":     fields,
            "outline":    _outline(r),
        })
    return sorted(rubrics, key=lambda x: (x["title"], x["outline"]))
