"""Plain text (and ANSI-colored terminal) report formatter."""

from __future__ import annotations

from .utils import short_label


def format_report(report: dict, old_path: str, new_path: str, use_colors: bool = False,
                   warnings: list = None) -> str:
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
        f"{C_MOD}{len(m['changed'])} changed{C_RST} | {len(m['unchanged'])} unchanged",
        SEP, "",
    ]

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

    section(f"UNCHANGED ({n_unc})", "",
            report["unchanged"],
            lambda t: f"  ✓ {t}")

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

    lines.append(SEP)
    return "\n".join(lines)
