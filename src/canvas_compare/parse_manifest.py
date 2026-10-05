"""Parses a Canvas .imscc export's imsmanifest.xml into titled resources."""

from __future__ import annotations

import zipfile
from urllib.parse import unquote

from bs4 import BeautifulSoup


class MissingManifestError(Exception):
    """The archive has no imsmanifest.xml, so it isn't a Canvas course export."""


def parse_manifest(z: zipfile.ZipFile) -> tuple[dict, dict]:
    """
    Parse imsmanifest.xml.

    Returns:
        items       : title -> resource info dict (titled items from <item> tree)
        href_index  : filepath -> title (for unlinked files like docx/pptx/media)
    """
    try:
        raw = z.read("imsmanifest.xml").decode("utf-8-sig", errors="replace")
    except KeyError:
        raise MissingManifestError("imsmanifest.xml not found in archive") from None
    soup = BeautifulSoup(raw, "xml")

    # --- Build resource id -> info map ---
    resources = {}
    for res in soup.find_all("resource"):
        rid   = res.get("identifier", "")
        rtype = res.get("type", "").lower()
        # unquote() is a no-op on an already-decoded string, so this is
        # safe insurance either way: some exports percent-encode href
        # attributes (spaces as %20, etc.) since they're technically URI
        # references, while zip member names are stored as plain decoded
        # text — without unquoting, a path with a space or special
        # character would never match `all_files` and its content would
        # silently come back empty.
        href = unquote(res.get("href", ""))

        html_path       = None
        settings_path   = None
        discussion_path = None
        quiz_path       = None

        if "imsdt" in rtype or ("discussion" in href and href.lower().endswith(".xml")):
            # The topic XML is normally the resource's href, but the
            # Common Cartridge discussion resource type may carry it only as a
            # <file> child. Without this a discussion with no href was
            # dropped from the comparison altogether (no path, so nothing to
            # keep it for).
            discussion_path = href or next(
                (unquote(f.get("href", "")) for f in res.find_all("file")
                 if unquote(f.get("href", "")).lower().endswith(".xml")), None)
            res_type = "discussion"
        elif "imsqti" in rtype:
            # Classic Quiz: the resource's own href (or its .xml <file>) is
            # the QTI assessment file. Quiz metadata (points, shuffle, time
            # limit) lives in a separate assessment_meta.xml resolved below
            # via the same dependency mechanism used for assignment settings.
            res_type = "quiz"
            if href.lower().endswith(".xml"):
                quiz_path = href
            else:
                for f in res.find_all("file"):
                    fhref = unquote(f.get("href", ""))
                    if fhref.lower().endswith(".xml"):
                        quiz_path = fhref
                        break
        elif "learning-application-resource" in rtype or "assignment" in href:
            # Check the resource's own href first — the settings_path
            # resolution above already does this (a resource's href is
            # normally its primary file, redundantly re-listed as a
            # <file> child too), but this branch previously only checked
            # <file> children. When an export lists the HTML only as
            # href with no redundant <file> child, html_path stayed
            # unresolved, the item's own entry kept its fields but lost
            # its instructions, and the same HTML separately fell through
            # to the unlinked-file loop as an orphan "[Page] ..." entry —
            # fragmenting one logical item into two unrelated diff lines.
            if href.lower().endswith((".html", ".htm")):
                html_path = href
            else:
                for f in res.find_all("file"):
                    fhref = unquote(f.get("href", ""))
                    if fhref.lower().endswith((".html", ".htm")):
                        html_path = fhref
                        break
            # Settings XML (assignment_settings.xml) is frequently just a
            # SECOND <file> sibling of this same resource — not always
            # reached via a separate <dependency> resource (verified
            # against a real Canvas export, where this was the only
            # pattern present: 0 of 142 candidate resources used
            # <dependency>, all 142 had the settings XML as a plain file
            # sibling instead). The dependency-based resolution below
            # still runs afterward for exports that DO use that pattern;
            # this just also covers the one that doesn't.
            for f in res.find_all("file"):
                fhref = unquote(f.get("href", ""))
                if fhref.lower().endswith(".xml"):
                    settings_path = fhref
                    break
            res_type = "assignment"
        else:
            if href.lower().endswith((".html", ".htm")):
                html_path = href
            else:
                for f in res.find_all("file"):
                    fhref = unquote(f.get("href", ""))
                    if fhref.lower().endswith((".html", ".htm")):
                        html_path = fhref
                        break
            res_type = "other"

        resources[rid] = {
            "type":             res_type,
            "html_path":        html_path,
            "settings_path":    settings_path,
            "discussion_path":  discussion_path,
            "quiz_path":        quiz_path,
            "href":             href,
            "file_hrefs":       [unquote(f.get("href", "")) for f in res.find_all("file")],
            "title":            res.get("title", ""),
            "dep_ids":          [d.get("identifierref", "") for d in res.find_all("dependency")],
        }

    # Resolve dependency → settings XML path. This is the pattern that's
    # actually verified against a real export for QUIZZES (the QTI
    # resource has no href of its own and points at a separate
    # assessment_meta.xml-holding resource via <dependency>). For
    # assignments/pages, the same real export used a different pattern
    # entirely — settings XML as a second <file> sibling of the SAME
    # resource, no <dependency> involved at all — which is now handled
    # above, before this loop runs. Skip here if that already resolved it,
    # so this loop only fills in the dependency-based case where it's
    # actually needed, rather than assuming every export uses one pattern
    # or the other.
    for rid, info in resources.items():
        if info.get("settings_path"):
            continue
        for dep_id in info["dep_ids"]:
            dep = resources.get(dep_id)
            if not dep:
                continue
            candidates = [dep.get("href", "")] + dep.get("file_hrefs", [])
            resolved = False
            for cand in candidates:
                if cand.lower().endswith(".xml"):
                    info["settings_path"] = cand
                    resolved = True
                    break
            # Stop at the first dependency that resolves to an XML path —
            # a resource with more than one dependency (uncommon, but
            # possible) would otherwise have settings_path silently
            # overwritten by whichever dependency happened to be listed
            # last, rather than the first (equally arbitrary, but at
            # least deterministic and not order-dependent on top of that).
            if resolved:
                break

    # --- Walk <item> tree for human-readable titles ---
    # Duplicate titles are common across modules ("Overview", "Week 1
    # Discussion" repeated per week/module) — a bare title-keyed dict would
    # silently drop every item but the last with that title. Disambiguate
    # with a "(2)", "(3)", ... suffix on repeats, leaving the first (and
    # the common non-colliding case) untouched for readability.
    #
    # Which duplicate gets which suffix matters for cross-export matching:
    # if it were assigned by raw manifest traversal order, and the two
    # exports being compared happen to list the same duplicates in a
    # different order (or one has an extra duplicate inserted earlier in
    # the tree), the suffixes would shift and unrelated items would look
    # "modified"/"added" against each other. There's no persistent id to
    # key on instead — Canvas's own identifierref/migration-id values
    # regenerate per export (the same instability behind why quiz
    # questions are diffed as one text blob rather than matched by ident,
    # elsewhere in this file) — so instead: group by title first, then
    # order each group by its own content path (html_path/quiz_path/
    # discussion_path/href) rather than tree position. That's still not
    # airtight if content genuinely moves between paths between exports,
    # but it removes the arbitrary, unrelated instability of pure
    # traversal order.
    raw_items = []
    for item in soup.find_all("item"):
        title_tag = item.find("title")
        if not title_tag:
            continue
        title = title_tag.text.strip()
        ref   = item.get("identifierref", "")
        if title and ref and ref in resources:
            raw_items.append((title, resources[ref]))

    by_title = {}
    for title, info in raw_items:
        by_title.setdefault(title, []).append(info)

    def _content_sort_key(info):
        return (info.get("html_path") or info.get("quiz_path")
                or info.get("discussion_path") or info.get("href") or "")

    items = {}
    for title, group in by_title.items():
        ordered = sorted(group, key=_content_sort_key) if len(group) > 1 else group
        for info in ordered:
            # Guard against colliding with a genuinely, separately titled
            # item that happens to match the auto-generated pattern (an
            # instructor who titled something literally "Overview (2)" of
            # their own accord) — check against the real, growing `items`
            # dict rather than just assuming "(2)", "(3)", ... in order
            # within this title's own duplicate group are free.
            key = title
            suffix = 2
            while key in items:
                key = f"{title} ({suffix})"
                suffix += 1
            items[key] = info

    # --- href -> title index for unlinked file lookup ---
    href_index = {
        info["href"]: title
        for title, info in items.items()
        if info.get("href")
    }

    return items, href_index
