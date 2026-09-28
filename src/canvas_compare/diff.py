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


# Display prefix per kind. These reproduce the labels the report has always
# shown ("[Quiz] Quiz 1", "[Document] handout.docx"), so output is unchanged
# whenever nothing collides.
_KIND_PREFIX = {
    "item": "", "quiz": "[Quiz] ", "document": "[Document] ",
    "presentation": "[Presentation] ", "page": "[Page] ", "file": "[File] ",
}
# Priority when two different keys would print identically: the first keeps
# the plain label, later ones get a short marker so they can be told apart.
_KIND_ORDER = ["item", "quiz", "document", "presentation", "page", "file"]
_KIND_MARKER = {
    "quiz": "quiz", "document": "attached file", "presentation": "attached file",
    "page": "unlinked page", "file": "attached file",
}


def build_display_names(keys) -> dict:
    """
    Map each (kind, name) key to the string shown in the report.

    Matching between the two courses is done on the tuple keys, so this only
    affects presentation. It is computed once over the union of BOTH courses'
    keys, so a given key gets the same label on the old and new side even if
    only one course contains the item it would otherwise be confused with
    (e.g. an instructor page titled "[Document] Syllabus" that exists in only
    one export, next to an attached file "Syllabus" that exists in both).
    """
    groups = {}
    for key in keys:
        kind, name = key
        groups.setdefault(_KIND_PREFIX[kind] + name, []).append(key)

    names, used = {}, set()
    # Sorted so the result never depends on set iteration order (which varies
    # between runs under string hash randomization). It only matters when one
    # group's marker label equals another group's plain label.
    for base in sorted(groups):
        group = groups[base]
        group.sort(key=lambda k: (_KIND_ORDER.index(k[0]), k[1]))
        for i, key in enumerate(group):
            # Only non-"item" kinds can be non-first (an item always sorts first
            # and there is at most one per group), and every such kind has a marker.
            label = base if i == 0 else f"{base} ({_KIND_MARKER[key[0]]})"
            n = 2
            # Last resort, needs a very unlucky title. Unlike the line above, an
            # "item" CAN reach this: another group's marker label may already
            # have taken its plain label, hence the "item" default.
            while label in used:
                label = f"{base} ({_KIND_MARKER.get(key[0], 'item')} {n})"
                n += 1
            used.add(label)
            names[key] = label
    return names


def compare_courses(old_text, old_media, new_text, new_media,
                     old_label: str = "Old", new_label: str = "New") -> dict:
    old_keys = set(old_text)
    new_keys = set(new_text)
    label    = build_display_names(old_keys | new_keys)

    # Sorted by display label (not by tuple) so report order is unchanged.
    added   = sorted((label[k] for k in new_keys - old_keys))
    removed = sorted((label[k] for k in old_keys - new_keys))
    common  = old_keys & new_keys

    modified  = []
    unchanged = []

    for key in sorted(common, key=lambda k: label[k]):
        title = label[key]
        old = old_text[key]
        new = new_text[key]
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
        for field in sorted(all_keys):
            ov = old["fields"].get(field, "<not set>")
            nv = new["fields"].get(field, "<not set>")
            if ov != nv:
                changes.append({
                    "label": f"Field: {field}",
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
