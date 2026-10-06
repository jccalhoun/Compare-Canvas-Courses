"""
Machine-readable report (--json): the same comparison as the text and HTML
reports, shaped for other programs rather than people.

Everything a script would otherwise have to parse out of display strings is
given its own key: each item's kind ("page", "quiz", "bank", ...) and plain
name, each changed setting's field name, file sizes and checksums. The layout
is versioned by SCHEMA_VERSION so scripts can detect a future change; bump it
whenever a key is renamed or removed (adding keys doesn't need a bump).
"""

from __future__ import annotations

import json

from .diff import _KIND_PREFIX
from .utils import short_label

SCHEMA_VERSION = 1

# Display prefix -> kind, longest first so "[Presentation] " can't be mistaken
# for a shorter prefix. Items with no prefix are ordinary module items.
_PREFIXES = sorted(((p, k) for k, p in _KIND_PREFIX.items() if p), key=lambda pk: -len(pk[0]))


def _split_title(title: str) -> dict:
    for prefix, kind in _PREFIXES:
        if title.startswith(prefix):
            return {"title": title, "kind": kind, "name": title[len(prefix):]}
    return {"title": title, "kind": "item", "name": title}


def _change(c: dict) -> dict:
    field = c["label"][len("Field: "):] if c["label"].startswith("Field: ") else None
    return {"label": c["label"], "field": field, "kind": c["kind"],
            "old": c["old"], "new": c["new"], "diff": c["diff"]}


def _files(section: dict) -> dict:
    def size_crc(prefix, value):
        size, crc = value
        return {f"{prefix}_size": size, f"{prefix}_crc32": f"{crc:08x}"}
    return {
        "added":     section["added"],
        "removed":   section["removed"],
        "renamed":   [{"old": o, "new": n} for o, n in section.get("renamed", [])],
        "changed":   [{"name": t, **size_crc("old", o), **size_crc("new", n)} for t, o, n in section["changed"]],
        "unchanged": section["unchanged"],
    }


def _counts(section: dict, keys) -> dict:
    return {k: len(section.get(k, [])) for k in keys}


def build_json_report(report: dict, old_path: str, new_path: str, *, options=None,
                      warnings: list | None = None, notes: list | None = None) -> dict:
    content = {
        "added":     [_split_title(t) for t in report["added"]],
        "removed":   [_split_title(t) for t in report["removed"]],
        "modified":  [{**_split_title(t), "changes": [_change(c) for c in changes]}
                      for t, changes in report["modified"]],
        "unchanged": [_split_title(t) for t in report["unchanged"]],
    }
    file_keys = ("added", "removed", "renamed", "changed", "unchanged")
    return {
        "schema_version": SCHEMA_VERSION,
        "old_course": {"path": old_path, "name": short_label(old_path)},
        "new_course": {"path": new_path, "name": short_label(new_path)},
        "settings": None if options is None else {
            "quiz_questions": options.quiz_questions,
            "question_banks": options.banks and options.wants("banks"),
            "skipped_sections": sorted(options.skip),
            "ignored_groups": sorted(options.ignore_groups),
            "ignored_fields": sorted(options.ignore_fields),
        },
        "summary": {
            "content": _counts(content, ("added", "removed", "modified", "unchanged")),
            "media": _counts(report["media"], file_keys),
            "other_files": _counts(report.get("other") or {}, file_keys),
        },
        "warnings": list(warnings or []),
        "notes": list(notes or []),
        "content": content,
        "media": _files(report["media"]),
        "other_files": _files(report.get("other") or {k: [] for k in file_keys}),
    }


def format_json_report(report: dict, old_path: str, new_path: str, **kwargs) -> str:
    return json.dumps(build_json_report(report, old_path, new_path, **kwargs), indent=2, ensure_ascii=False)
