"""Comparison engine: diffs two loaded courses' text_items/media_items."""

from __future__ import annotations

import difflib
import re


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
    "syllabus": "[Syllabus] ", "modules": "[Modules] ", "rubric": "[Rubric] ",
    "bank": "[Bank] ",
}
# Priority when two different keys would print identically: the first keeps
# the plain label, later ones get a short marker so they can be told apart.
_KIND_ORDER = ["item", "quiz", "document", "presentation", "page", "file",
               "syllabus", "modules", "rubric", "bank"]
_KIND_MARKER = {
    "quiz": "quiz", "document": "attached file", "presentation": "attached file",
    "page": "unlinked page", "file": "attached file",
    "syllabus": "syllabus", "modules": "module structure", "rubric": "rubric",
    "bank": "question bank",
}


def _marker(kind: str) -> str:
    """
    Short disambiguating label for a kind. Falls back to the kind's own name
    so a kind added to _KIND_PREFIX/_KIND_ORDER without a marker still reads
    sensibly in the report instead of crashing it mid-run.
    """
    return _KIND_MARKER.get(kind, kind)


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
            label = base if i == 0 else f"{base} ({_marker(key[0])})"
            n = 2
            # Last resort, needs a very unlucky title. An "item" can reach this
            # (it is first in its group, but another group's marker label may
            # already have taken its plain label); _marker("item") is "item".
            while label in used:
                label = f"{base} ({_marker(key[0])} {n})"
                n += 1
            used.add(label)
            names[key] = label
    return names


def _compare_files(old: dict, new: dict) -> dict:
    """
    Compare two {name: (size, CRC32)} dicts. A file that disappeared under
    one name and appeared under another with the same size AND CRC-32 is
    reported as "renamed" (moved) rather than as one removal plus one
    addition. That is exact content, so it can't pair up different files;
    empty files are excluded since every empty file looks alike. It covers
    the "-1" suffix Canvas adds to re-imported file names.
    """
    old_keys, new_keys = set(old), set(new)
    added, removed = new_keys - old_keys, old_keys - new_keys

    pool = {}
    for name in sorted(removed):
        if old[name][0]:
            pool.setdefault(old[name], []).append(name)
    renamed = []
    for name in sorted(added):
        candidates = pool.get(new[name]) if new[name][0] else None
        if candidates:
            renamed.append((candidates.pop(0), name))
    renamed_old = {o for o, _ in renamed}
    renamed_new = {n for _, n in renamed}

    common = old_keys & new_keys
    return {
        "added":     sorted(added - renamed_new),
        "removed":   sorted(removed - renamed_old),
        "renamed":   sorted(renamed),
        "changed":   [(t, old[t], new[t]) for t in sorted(common) if old[t] != new[t]],
        "unchanged": sorted(t for t in common if old[t] == new[t]),
    }


def _signature(entry: dict) -> tuple:
    return (entry["instructions"], entry["discussion_text"], tuple(sorted(entry["fields"].items())))


def _similarity(a: dict, b: dict) -> float:
    """0..1 line-level similarity of two entries' content."""
    def lines(e):
        return (e["instructions"].splitlines() + e["discussion_text"].splitlines()
                + [f"{k}: {v}" for k, v in sorted(e["fields"].items())])
    la, lb = lines(a), lines(b)
    if not la and not lb:
        return 1.0
    return difflib.SequenceMatcher(None, la, lb, autojunk=False).ratio()


def _align_duplicates(old_text: dict, new_text: dict) -> tuple[dict, dict]:
    """
    Pair up same-named items (copies of a question bank, two assignments with
    one title) by what they contain, not by the order they were listed in.

    The loader gives the 2nd, 3rd, ... item of a name a "(2)", "(3)" suffix in
    archive order, and Canvas regenerates the ids that order comes from for
    every export, so the same copy can be "(2)" in one course and unsuffixed
    in the other. Compared as-is, that pairs a bank with an unrelated copy
    (a whole-bank "rewrite") while its identical twin shows as an addition.

    Per name: items with identical content are paired first, then the rest by
    similarity. Pairs are relabeled first (the plain name, then "(2)", ...),
    followed by the leftover additions and removals, identically on both sides.
    """
    groups = {e["dup_group"] for texts in (old_text, new_text)
              for e in texts.values() if "dup_group" in e}
    if not groups:
        return old_text, new_text
    old2, new2 = dict(old_text), dict(new_text)
    for g in sorted(groups):
        old_members = sorted(k for k, e in old_text.items() if e.get("dup_group") == g) \
            or ([g] if g in old_text else [])
        new_members = sorted(k for k, e in new_text.items() if e.get("dup_group") == g) \
            or ([g] if g in new_text else [])
        if not old_members or not new_members:
            continue                      # the name exists on one side only

        pairs = {}
        free_new = set(new_members)
        by_content = {}
        for k in new_members:
            by_content.setdefault(_signature(new_text[k]), []).append(k)
        for ok in old_members:            # 1. identical content
            candidates = by_content.get(_signature(old_text[ok]))
            if candidates:
                nk = candidates.pop(0)
                pairs[ok] = nk
                free_new.discard(nk)
        scored = sorted((-_similarity(old_text[o], new_text[n]), o, n)
                        for o in old_members if o not in pairs for n in free_new)
        for _, o, n in scored:            # 2. most similar of what is left
            if o not in pairs and n in free_new:
                pairs[o] = n
                free_new.discard(n)

        paired_new = set(pairs.values())
        slots = sorted(pairs.items())
        slots += [(None, nk) for nk in new_members if nk not in paired_new]
        slots += [(ok, None) for ok in old_members if ok not in pairs]
        for k in old_members:
            old2.pop(k, None)
        for k in new_members:
            new2.pop(k, None)
        taken = set(old2) | set(new2)
        n = 1
        for ok, nk in slots:
            while True:
                key = g if n == 1 else (g[0], f"{g[1]} ({n})")
                n += 1
                if key not in taken:
                    break
            taken.add(key)
            if ok is not None:
                old2[key] = old_text[ok]
            if nk is not None:
                new2[key] = new_text[nk]
    return old2, new2


def _plain(name: str) -> str:
    """A title with case, punctuation and spacing removed, for matching only."""
    return re.sub(r"[\W_]+", "", name.lower())


def _align_renamed(old_text: dict, new_text: dict) -> tuple[dict, dict]:
    """
    Treat titles that differ only in capitalization, punctuation or spacing
    ("Week 2 End" / "Week 2 - End") as the same item, which they almost
    certainly are: one course just uses a different naming style. Only items
    present in one course and not the other are considered, and only when
    exactly one item on each side has that spelling, so a pairing is never a
    guess between candidates. The letters and digits must be identical, so
    "Week 2 End" and "Week 3 End" are never paired.
    """
    groups = {}
    for side, texts, other in (("old", old_text, new_text), ("new", new_text, old_text)):
        for key in texts:
            plain = _plain(key[1])
            if key not in other and plain:
                groups.setdefault((key[0], plain), {"old": [], "new": []})[side].append(key)
    renames = {g["old"][0]: g["new"][0] for g in groups.values()
               if len(g["old"]) == 1 and len(g["new"]) == 1}
    if not renames:
        return old_text, new_text
    return {renames.get(k, k): v for k, v in old_text.items()}, new_text


def compare_courses(old_text, old_media, new_text, new_media,
                     old_label: str = "Old", new_label: str = "New",
                     *, old_other=None, new_other=None) -> dict:
    old_text, new_text = _align_duplicates(old_text, new_text)
    old_text, new_text = _align_renamed(old_text, new_text)
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
                if "\n" in ov or "\n" in nv:
                    # A multi-line value (e.g. a cleaned HTML description)
                    # can't be shown as one "old : new" line, so diff it
                    # line by line like any other text.
                    diff = make_diff(ov, nv, old_label, new_label)
                    if diff:
                        changes.append({
                            "label": f"Field: {field}",
                            "kind":  "text",
                            "diff":  diff,
                            "old":   ov,
                            "new":   nv,
                        })
                else:
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

    # Media and other files: a size OR content (CRC32) difference counts as
    # a change — cheap, since both come straight from the zip directory.
    media_report = _compare_files(old_media, new_media)
    other_report = _compare_files(old_other or {}, new_other or {})

    return {
        "added":    added,
        "removed":  removed,
        "modified": modified,
        "unchanged": unchanged,
        "media":    media_report,
        "other":    other_report,
    }
