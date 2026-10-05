"""Plain text (and ANSI-colored terminal) report formatter."""

from __future__ import annotations

from .utils import short_label


def format_report(report: dict, old_path: str, new_path: str, use_colors: bool = False,
                   warnings: list = None, notes: list = None) -> str:
    """
    Render the plain-text report. When use_colors is True, wraps added/
    removed/modified lines (and diff +/- lines) in ANSI escape codes for
    a readable terminal view; leave it False for the version written to
    --output, since a saved file shouldn't be full of escape codes.
    `warnings` (from load_course, see there) are rendered up top when
    present, so a parse-path problem is still visible to anyone reviewing
    a saved report later — not just someone watching the terminal live.
    """
    C_ADD = "\033[92m" if use_colors else ""
    C_REM = "\033[91m" if use_colors else ""
    C_MOD = "\033[93m" if use_colors else ""
    C_HDR = "\033[96m" if use_colors else ""
    C_DIM = "\033[90m" if use_colors else ""
    C_RST = "\033[0m"  if use_colors else ""

    SEP  = C_HDR + "=" * 70 + C_RST
    DASH = C_DIM + "─" * 70 + C_RST
    lines = []

    n_add = len(report["added"])
    n_rem = len(report["removed"])
    n_mod = len(report["modified"])
    n_unc = len(report["unchanged"])
    m     = report["media"]
    o     = report.get("other") or {}
    has_other = any(o.get(k) for k in ("added", "removed", "renamed", "changed", "unchanged"))
    media_renamed = f" | {len(m['renamed'])} renamed" if m.get("renamed") else ""

    lines += [
        SEP,
        f"{C_HDR}  CANVAS COURSE COMPARISON REPORT{C_RST}",
        SEP,
        f"  {short_label(old_path)} : {old_path}",
        f"  {short_label(new_path)} : {new_path}",
        SEP,
        f"  Content  — {C_ADD}{n_add} added{C_RST} | {C_REM}{n_rem} removed{C_RST} | "
        f"{C_MOD}{n_mod} modified{C_RST} | {n_unc} unchanged",
        f"  Media    — {C_ADD}{len(m['added'])} added{C_RST} | {C_REM}{len(m['removed'])} removed{C_RST} | "
        f"{C_MOD}{len(m['changed'])} changed{C_RST}{media_renamed} | {len(m['unchanged'])} unchanged",
    ]
    if has_other:
        lines.append(
            f"  Files    — {C_ADD}{len(o['added'])} added{C_RST} | {C_REM}{len(o['removed'])} removed{C_RST} | "
            f"{C_MOD}{len(o['changed'])} changed{C_RST} | {len(o['renamed'])} renamed | {len(o['unchanged'])} unchanged")
    lines += [f"  {n}" for n in notes or []]   # what the options left out, if anything
    lines += [SEP, ""]

    if warnings:
        lines.append(DASH)
        lines.append(f"{C_MOD}  DIAGNOSTIC WARNINGS ({len(warnings)}){C_RST}")
        lines.append(DASH)
        for w in warnings:
            lines.append(f"{C_MOD}  ⚠ {w}{C_RST}")
        lines.append("")

    # ── Content sections ────────────────────────────────────────────────────

    def section(header, header_color, items, fmt):
        lines.append(DASH)
        lines.append(f"{header_color}  {header}{C_RST}")
        lines.append(DASH)
        if items:
            for i in items:
                lines.append(fmt(i))
        else:
            lines.append("  (none)")
        lines.append("")

    section(f"ADDED TO THIS SUMMER ({n_add})", C_ADD,
            report["added"],
            lambda t: f"{C_ADD}  + {t}{C_RST}")

    section(f"REMOVED FROM THIS SUMMER ({n_rem})", C_REM,
            report["removed"],
            lambda t: f"{C_REM}  - {t}{C_RST}")

    lines.append(DASH)
    lines.append(f"{C_MOD}  MODIFIED ({n_mod}){C_RST}")
    lines.append(DASH)
    if report["modified"]:
        for title, changes in report["modified"]:
            lines.append(f"\n{C_MOD}  ▸ {title}{C_RST}")
            for c in changes:
                lines.append(f"    [{c['label']}]")
                for dl in c["diff"].splitlines():
                    if dl.startswith("+") and not dl.startswith("+++"):
                        lines.append(f"{C_ADD}      {dl}{C_RST}")
                    elif dl.startswith("-") and not dl.startswith("---"):
                        lines.append(f"{C_REM}      {dl}{C_RST}")
                    else:
                        lines.append(f"      {dl}")
    else:
        lines.append("  (none)")
    lines.append("")

    # Unchanged rubrics and question banks are only counted: a course can
    # have well over a hundred of each, and they'd bury everything else.
    collapsed = (("[Bank] ", "question bank(s)"), ("[Rubric] ", "rubric(s)"))
    listed = [t for t in report["unchanged"] if not t.startswith(tuple(p for p, _ in collapsed))]
    lines.append(DASH)
    lines.append(f"  UNCHANGED ({n_unc})")
    lines.append(DASH)
    for t in listed:
        lines.append(f"  ✓ {t}")
    for prefix, noun in collapsed:
        n = sum(1 for t in report["unchanged"] if t.startswith(prefix))
        if n:
            lines.append(f"  ✓ {n} {noun} (not listed)")
    if not report["unchanged"]:
        lines.append("  (none)")
    lines.append("")

    # ── Media section ────────────────────────────────────────────────────────

    lines += [SEP, f"{C_HDR}  MEDIA FILES (audio / video){C_RST}", SEP, ""]

    lines.append(f"  Added ({len(m['added'])}):")
    for t in m["added"]:
        lines.append(f"{C_ADD}    + {t}{C_RST}")
    if not m["added"]:
        lines.append("    (none)")
    lines.append("")

    lines.append(f"  Removed ({len(m['removed'])}):")
    for t in m["removed"]:
        lines.append(f"{C_REM}    - {t}{C_RST}")
    if not m["removed"]:
        lines.append("    (none)")
    lines.append("")

    if m.get("renamed"):
        lines.append(f"  Renamed or moved — same size and checksum ({len(m['renamed'])}):")
        for old_name, new_name in m["renamed"]:
            lines.append(f"{C_MOD}    ▸ {old_name}  →  {new_name}{C_RST}")
        lines.append("")

    lines.append(f"  Changed — different size or content, possible replacement ({len(m['changed'])}):")
    for t, (old_sz, _old_crc), (new_sz, _new_crc) in m["changed"]:
        lines.append(f"{C_MOD}    ▸ {t}{C_RST}")
        if old_sz != new_sz:
            delta = new_sz - old_sz
            sign  = "+" if delta >= 0 else ""
            lines.append(f"{C_MOD}      {old_sz:,} bytes → {new_sz:,} bytes  ({sign}{delta:,}){C_RST}")
        else:
            lines.append(f"{C_MOD}      same size ({old_sz:,} bytes) — content differs{C_RST}")
    if not m["changed"]:
        lines.append("    (none)")
    lines.append("")

    lines.append(f"  Same size — likely unchanged ({len(m['unchanged'])}):")
    for t in m["unchanged"]:
        lines.append(f"    ✓ {t}")
    if not m["unchanged"]:
        lines.append("    (none)")
    lines.append("")

    if has_other:
        lines += [SEP, f"{C_HDR}  OTHER COURSE FILES (PDFs, images, ...){C_RST}", SEP, ""]
        for title, key, color, sign in (("Added", "added", C_ADD, "+"), ("Removed", "removed", C_REM, "-")):
            lines.append(f"  {title} ({len(o[key])}):")
            for t in o[key]:
                lines.append(f"{color}    {sign} {t}{C_RST}")
            if not o[key]:
                lines.append("    (none)")
            lines.append("")
        lines.append(f"  Renamed or moved — same size and checksum ({len(o['renamed'])}):")
        for old_name, new_name in o["renamed"]:
            lines.append(f"{C_MOD}    ▸ {old_name}  →  {new_name}{C_RST}")
        if not o["renamed"]:
            lines.append("    (none)")
        lines.append("")
        lines.append(f"  Changed — different size or content ({len(o['changed'])}):")
        for t, (old_sz, _old_crc), (new_sz, _new_crc) in o["changed"]:
            lines.append(f"{C_MOD}    ▸ {t}{C_RST}")
            if old_sz != new_sz:
                delta = new_sz - old_sz
                lines.append(f"{C_MOD}      {old_sz:,} bytes → {new_sz:,} bytes  ({'+' if delta >= 0 else ''}{delta:,}){C_RST}")
            else:
                lines.append(f"{C_MOD}      same size ({old_sz:,} bytes) — content differs{C_RST}")
        if not o["changed"]:
            lines.append("    (none)")
        lines.append("")
        # Unchanged files are only counted: there can be well over a hundred.
        lines.append(f"  Unchanged: {len(o['unchanged'])} file(s) (not listed)")
        lines.append("")

    lines.append(SEP)
    return "\n".join(lines)
