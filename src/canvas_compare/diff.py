"""Comparison engine: diffs two loaded courses' text_items/media_items."""

from __future__ import annotations

import difflib


def make_diff(old_text: str, new_text: str, old_label: str, new_label: str) -> str:
    """
    Unified diff between two strings; returns empty string if identical.
    Uses splitlines() (no keepends) so each line has no embedded newline —
    keepends=True here would double-space every line once "\n".join()
    adds its own separator on top of the one each line already carries.
    old_label/new_label are the two courses being compared (their short
    file names) — shown as the diff's "---"/"+++" header lines. What's
    actually being diffed (Instructions, Discussion Text, etc.) is shown
    separately as its own header by the caller, so it isn't repeated here.
    """
    diff = list(difflib.unified_diff(
        old_text.splitlines(),
        new_text.splitlines(),
        fromfile=old_label,
        tofile=new_label,
        lineterm="",
    ))
    return "\n".join(diff)


def compare_courses(old_text, old_media, new_text, new_media,
                     old_label: str = "Old", new_label: str = "New") -> dict:
    old_keys = set(old_text)
    new_keys = set(new_text)

    added   = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    common  = old_keys & new_keys

    modified  = []
    unchanged = []

    for title in sorted(common):
        old = old_text[title]
        new = new_text[title]
        changes = []

        # Instructions / document body
        if old["instructions"] != new["instructions"]:
            diff = make_diff(old["instructions"], new["instructions"],
                             old_label, new_label)
            if diff:
                changes.append({
                    "label": "Instructions / Content",
                    "kind":  "text",
                    "diff":  diff,
                    "old":   old["instructions"],
                    "new":   new["instructions"],
                })

        # Discussion prompt text
        if old["discussion_text"] != new["discussion_text"]:
            diff = make_diff(old["discussion_text"], new["discussion_text"],
                             old_label, new_label)
            if diff:
                changes.append({
                    "label": "Discussion Text",
                    "kind":  "text",
                    "diff":  diff,
                    "old":   old["discussion_text"],
                    "new":   new["discussion_text"],
                })

        # Structured metadata fields (points, submission type, etc.)
        all_keys = set(old["fields"]) | set(new["fields"])
        for key in sorted(all_keys):
            ov = old["fields"].get(key, "<not set>")
            nv = new["fields"].get(key, "<not set>")
            if ov != nv:
                changes.append({
                    "label": f"Field: {key}",
                    "kind":  "field",
                    "diff":  f"  {old_label} : {ov}\n  {new_label} : {nv}",
                    "old":   ov,
                    "new":   nv,
                })

        if changes:
            modified.append((title, changes))
        else:
            unchanged.append(title)

    # Media: flag any size OR content (CRC32) difference — cheap since
    # both come straight from the zip directory, no decompression needed.
    old_med = set(old_media)
    new_med = set(new_media)
    media_report = {
        "added":    sorted(new_med - old_med),
        "removed":  sorted(old_med - new_med),
        "changed":  [
            (t, old_media[t], new_media[t])
            for t in sorted(old_med & new_med)
            if old_media[t] != new_media[t]
        ],
        "unchanged": sorted(t for t in old_med & new_med if old_media[t] == new_media[t]),
    }

    return {
        "added":    added,
        "removed":  removed,
        "modified": modified,
        "unchanged": unchanged,
        "media":    media_report,
    }
