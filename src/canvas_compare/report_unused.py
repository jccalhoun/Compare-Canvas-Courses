"""Text, CSV and HTML output for unused_files.find_unused_files()."""

from __future__ import annotations

import csv
import html
import io

from .unused_files import (STATUS_REFERENCED, STATUS_UNPUBLISHED_ONLY, STATUS_UNREFERENCED,
                           UnusedFilesResult)


def short_label(path: str) -> str:
    """Base file name, for either / or \\ separators. (Same as utils.short_label, kept
    local so this tool doesn't need the rest of the package.)"""
    return path.replace("\\", "/").rsplit("/", 1)[-1]

CAVEAT = ("Unreferenced is not the same as unused: if the Files page is visible to students they "
          "can still open these there, and links from other courses, Canvas Studio, external "
          "tools or anything outside Canvas can't be seen in an export. Move files to a hidden "
          "folder for a term before deleting them.")


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} bytes" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} bytes"


def _total(files) -> int:
    return sum(f.size for f in files)


def _summary_lines(result: UnusedFilesResult) -> list:
    unref = result.with_status(STATUS_UNREFERENCED)
    unpub = result.with_status(STATUS_UNPUBLISHED_ONLY)
    lines = [
        f"{len(result.files)} course files, {human_size(_total(result.files))}",
        f"{len(unref)} unreferenced ({human_size(_total(unref))})",
        f"{len(unpub)} referenced only by unpublished content ({human_size(_total(unpub))})",
    ]
    if result.missing:
        lines.append(f"{len(result.missing)} link(s) to files that aren't in this export")
    return lines


def format_unused_text(result: UnusedFilesResult, course_path: str, show_all: bool = False) -> str:
    out = [f"UNUSED FILES REPORT: {short_label(course_path)}", ""]
    out += [f"  {line}" for line in _summary_lines(result)]

    def section(title, files, detail):
        if not files:
            return
        out.extend(["", title, "-" * len(title)])
        for f in files:
            out.append(f"  {human_size(f.size):>10}  {f.name}")
            for label in detail(f):
                out.append(f"  {'':>10}    <- {label}")

    section("UNREFERENCED (largest first)", result.with_status(STATUS_UNREFERENCED), lambda f: [])
    section("REFERENCED ONLY BY UNPUBLISHED CONTENT", result.with_status(STATUS_UNPUBLISHED_ONLY),
            lambda f: f.unpublished_by)
    if show_all:
        section("REFERENCED", result.with_status(STATUS_REFERENCED),
                lambda f: f.used_by + [f"{u} (unpublished)" for u in f.unpublished_by])

    if result.missing:
        out.extend(["", "LINKS TO FILES NOT IN THIS EXPORT", "-" * 33])
        out += [f"  {label} -> {target}" for label, target in result.missing]
    if result.warnings:
        out.extend(["", "WARNINGS", "-" * 8])
        out += [f"  {w}" for w in result.warnings]
    out.extend(["", f"Note: {CAVEAT}"])
    return "\n".join(out)


def format_unused_csv(result: UnusedFilesResult) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Status", "Folder", "File", "Size (bytes)", "Size", "Used by",
                     "Used only in unpublished content", "Path in export"])
    for f in result.files:
        writer.writerow([f.status, f.folder, f.filename, f.size, human_size(f.size),
                         "; ".join(f.used_by), "; ".join(f.unpublished_by), f.path])
    return buf.getvalue()


def format_unused_html(result: UnusedFilesResult, course_path: str) -> str:
    esc = html.escape

    def table(files, show_uses):
        rows = []
        for f in files:
            uses = ""
            if show_uses:
                parts = [esc(u) for u in f.used_by] + [f"{esc(u)} <em>(unpublished)</em>"
                                                       for u in f.unpublished_by]
                uses = f"<td>{'<br>'.join(parts)}</td>"
            rows.append(f"<tr><td>{esc(f.folder) or '<em>(top level)</em>'}</td><td>{esc(f.filename)}</td>"
                        f"<td class='num' data-bytes='{f.size}'>{human_size(f.size)}</td>{uses}</tr>")
        head = "<th>Folder</th><th>File</th><th class='num'>Size</th>" + ("<th>Used by</th>" if show_uses else "")
        return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"

    unref = result.with_status(STATUS_UNREFERENCED)
    unpub = result.with_status(STATUS_UNPUBLISHED_ONLY)
    used = result.with_status(STATUS_REFERENCED)
    title = f"Unused files: {short_label(course_path)}"

    out = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>{esc(title)}</title><style>",
        "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 20px; background: #f4f4f9; color: #333; }",
        ".container { max-width: 1400px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }",
        "table { width: 100%; border-collapse: collapse; margin: 10px 0 30px; font-size: 14px; }",
        "th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid #ddd; vertical-align: top; }",
        "th { background: #f8f9fa; } td.num, th.num { text-align: right; white-space: nowrap; }",
        "ul.summary { line-height: 1.7; } .note { background: #fff3cd; color: #856404; padding: 12px 16px; border-radius: 6px; }",
        ".warn { background: #f8d7da; color: #721c24; padding: 12px 16px; border-radius: 6px; }",
        "summary { cursor: pointer; font-size: 1.17em; font-weight: bold; margin: 1em 0; }",
        "</style></head><body><div class='container'>",
        f"<h1>{esc(title)}</h1>",
        "<ul class='summary'>" + "".join(f"<li>{esc(line)}</li>" for line in _summary_lines(result)) + "</ul>",
        f"<p class='note'>{esc(CAVEAT)}</p>",
    ]
    if result.warnings:
        out.append("<div class='warn'><strong>Warnings</strong><ul>"
                   + "".join(f"<li>{esc(w)}</li>" for w in result.warnings) + "</ul></div>")
    out.append(f"<h2>Unreferenced ({len(unref)})</h2>")
    out.append(table(unref, False) if unref else "<p>None.</p>")
    out.append(f"<h2>Referenced only by unpublished content ({len(unpub)})</h2>")
    out.append(table(unpub, True) if unpub else "<p>None.</p>")
    if result.missing:
        out.append(f"<h2>Links to files not in this export ({len(result.missing)})</h2>"
                   "<table><thead><tr><th>Linked from</th><th>Target</th></tr></thead><tbody>"
                   + "".join(f"<tr><td>{esc(l)}</td><td>{esc(t)}</td></tr>" for l, t in result.missing)
                   + "</tbody></table>")
    out.append(f"<details><summary>Referenced ({len(used)})</summary>{table(used, True)}</details>")
    out.append("</div></body></html>")
    return "\n".join(out)
