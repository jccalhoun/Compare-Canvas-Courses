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
    # Size in bytes comes right after Folder so it sorts correctly in Excel/Sheets
    # (the readable "4.0 KB" column sorts as text).
    writer.writerow(["File", "Folder", "Size (bytes)", "Size", "Status", "Used by",
                     "Used only in unpublished content", "Path in export"])
    for f in result.files:
        writer.writerow([f.filename, f.folder, f.size, human_size(f.size), f.status,
                         "; ".join(f.used_by), "; ".join(f.unpublished_by), f.path])
    return buf.getvalue()


# Click a column heading to sort that table; click again to reverse. Size
# starts largest-first, text columns A to Z. Folder ties are broken by file
# name, so files stay alphabetical within each folder.
_SORT_SCRIPT = """
<script>
document.querySelectorAll("table.sortable").forEach(function (table) {
  var heads = table.querySelectorAll("th[data-type]");
  heads.forEach(function (th, col) {
    th.querySelector("button").addEventListener("click", function () {
      var numeric = th.dataset.type === "size";
      var current = th.getAttribute("aria-sort");
      var dir = current ? (current === "ascending" ? -1 : 1) : (numeric ? -1 : 1);
      var body = table.tBodies[0];
      var rows = Array.prototype.slice.call(body.rows);
      function key(row, i) { var c = row.cells[i]; return c.dataset.sort !== undefined ? c.dataset.sort : c.textContent.trim(); }
      rows.sort(function (a, b) {
        var x = key(a, col), y = key(b, col), r;
        r = numeric ? Number(x) - Number(y) : x.localeCompare(y, undefined, {numeric: true, sensitivity: "base"});
        if (r === 0 && col !== 0) r = key(a, 0).localeCompare(key(b, 0), undefined, {numeric: true, sensitivity: "base"});
        return r * dir;
      });
      rows.forEach(function (row) { body.appendChild(row); });
      heads.forEach(function (h) { h.removeAttribute("aria-sort"); });
      th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
    });
  });
});
</script>
"""


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
            folder = esc(f.folder) or "<em>(top level)</em>"
            rows.append(f"<tr><td>{esc(f.filename)}</td><td data-sort='{esc(f.folder)}'>{folder}</td>"
                        f"<td class='num' data-sort='{f.size}'>{human_size(f.size)}</td>{uses}</tr>")

        def th(label, kind, extra=""):
            # Rows arrive largest-first, so Size starts marked as the current sort.
            state = " aria-sort='descending'" if kind == "size" else ""
            return f"<th data-type='{kind}'{extra}{state}><button type='button'>{label}</button></th>"

        head = (th("File", "text") + th("Folder", "text") + th("Size", "size", " class='num'")
                + (th("Used by", "text") if show_uses else ""))
        return f"<table class='sortable'><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"

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
        "th button { all: unset; cursor: pointer; font-weight: bold; } th button:focus-visible { outline: 2px solid #0366d6; outline-offset: 2px; }",
        "th button::after { content: ' \\2195'; color: #aaa; font-weight: normal; }",
        "th[aria-sort='ascending'] button::after { content: ' \\25B2'; color: #333; }",
        "th[aria-sort='descending'] button::after { content: ' \\25BC'; color: #333; }",
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
    out.append("</div>" + _SORT_SCRIPT + "</body></html>")
    return "\n".join(out)
