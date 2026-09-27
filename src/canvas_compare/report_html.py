"""
Standalone HTML dashboard report formatter (ported from
compare_canvas_courses2, adapted to the current data model — text fields
get a true side-by-side difflib.HtmlDiff table).
"""

from __future__ import annotations

import difflib
import html

from .utils import short_label


def format_html_report(report: dict, old_path: str, new_path: str, warnings: list = None) -> str:
    """
    Generates a standalone HTML dashboard with tables and side-by-side
    diffs. `warnings` (from load_course) render as a callout up top when
    present, so a parse-path problem is visible when this report is
    opened later, not just in whatever terminal produced it.
    """
    d = difflib.HtmlDiff(wrapcolumn=90)
    esc = html.escape  # local alias — the list below is named `out`, not
                        # `html`, specifically so it can't shadow this module

    old_label = short_label(old_path)
    new_label = short_label(new_path)

    out = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Course Comparison</title>",
        "<style>",
        "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 20px; background: #f4f4f9; color: #333; }",
        ".container { max-width: 1100px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }",
        "table.overview { width: 100%; border-collapse: collapse; margin-bottom: 30px; font-size: 15px; }",
        "table.overview th, table.overview td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }",
        "table.overview th { background-color: #f8f9fa; }",
        ".badge { padding: 4px 8px; border-radius: 4px; font-size: 0.85em; font-weight: bold; }",
        ".b-added { background: #d4edda; color: #155724; }",
        ".b-removed { background: #f8d7da; color: #721c24; }",
        ".b-modified { background: #fff3cd; color: #856404; }",
        ".diff-section { margin-top: 40px; border-top: 2px solid #eee; padding-top: 20px; }",
        "table.diff { width: 100%; border: 1px solid #ddd; font-family: Consolas, monospace; font-size: 13px; margin-bottom: 20px; }",
        "table.diff td { padding: 4px; }",
        "table.diff .diff_header { background: #f0f0f0; width: 1%; text-align: center; color: #999; }",
        "table.diff .diff_add { background: #cfc; }",
        "table.diff .diff_chg { background: #ffd; }",
        "table.diff .diff_sub { background: #fcc; }",
        ".warning-box { margin-bottom: 20px; padding: 12px 16px; background: #fff3cd; border-left: 4px solid #856404; color: #533f03; }",
        ".warning-box ul { margin: 6px 0 0 0; padding-left: 20px; }",
        "</style></head><body><div class='container'>",
        "<h1>Canvas Course Comparison</h1>",
        f"<p><strong>{esc(old_label)}:</strong> {esc(old_path)}<br>"
        f"<strong>{esc(new_label)}:</strong> {esc(new_path)}</p>",
    ]

    if warnings:
        out.append("<div class='warning-box'><strong>Diagnostic warnings</strong><ul>")
        for w in warnings:
            out.append(f"<li>{esc(w)}</li>")
        out.append("</ul></div>")

    out.append("<h2>Content Overview</h2>")
    out.append("<table class='overview'><tr><th>Title</th><th>Status</th></tr>")
    for t in report["added"]:
        out.append(f"<tr><td>{esc(t)}</td><td><span class='badge b-added'>Added</span></td></tr>")
    for t in report["removed"]:
        out.append(f"<tr><td>{esc(t)}</td><td><span class='badge b-removed'>Removed</span></td></tr>")
    for idx, (t, _changes) in enumerate(report["modified"]):
        out.append(f"<tr><td><a href='#mod_{idx}'>{esc(t)}</a></td><td><span class='badge b-modified'>Modified</span></td></tr>")
    out.append("</table>")

    m = report["media"]
    out.append("<h2>Media Overview (Audio/Video)</h2>")
    out.append("<table class='overview'><tr><th>File Name</th><th>Status</th><th>Details</th></tr>")
    for t in m["added"]:
        out.append(f"<tr><td>{esc(t)}</td><td><span class='badge b-added'>Added</span></td><td></td></tr>")
    for t in m["removed"]:
        out.append(f"<tr><td>{esc(t)}</td><td><span class='badge b-removed'>Removed</span></td><td></td></tr>")
    for t, (old_sz, old_crc), (new_sz, new_crc) in m["changed"]:
        if old_sz != new_sz:
            detail = f"{old_sz:,} bytes &rarr; {new_sz:,} bytes"
        else:
            detail = f"same size ({old_sz:,} bytes) &mdash; content differs"
        out.append(f"<tr><td>{esc(t)}</td><td><span class='badge b-modified'>Changed</span></td><td>{detail}</td></tr>")
    out.append("</table>")

    if report["modified"]:
        out.append("<div class='diff-section'><h2>Detailed Modifications</h2>")
        for idx, (t, changes) in enumerate(report["modified"]):
            out.append(f"<h3 id='mod_{idx}'>{esc(t)}</h3>")
            for c in changes:
                out.append(f"<h4>{esc(c['label'])}</h4>")
                # HtmlDiff.make_table escapes cell content internally —
                # safe to pass raw lines here. Field changes are single
                # values rather than multi-line documents, but make_table
                # handles a one-line list fine, so both kinds render the
                # same side-by-side way rather than fields getting a
                # separate, plainer before/after block.
                diff_table = d.make_table(
                    c["old"].splitlines() or [""], c["new"].splitlines() or [""],
                    esc(old_label), esc(new_label), context=True,
                )
                out.append(diff_table)
        out.append("</div>")

    out.append("</div></body></html>")
    return "\n".join(out)
