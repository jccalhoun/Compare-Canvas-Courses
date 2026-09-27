"""
Optional .docx/.pptx text extraction. python-docx and python-pptx are
soft dependencies — a course export can be compared without them, just
with office documents skipped (see loader.py, which checks HAVE_DOCX/
HAVE_PPTX before deciding whether to skip a file entirely).
"""

from __future__ import annotations

import io

try:
    import docx as _docx
except ImportError:
    _docx = None

try:
    from pptx import Presentation as _Presentation
except ImportError:
    _Presentation = None

# Public availability flags — this is the one place cli.py/loader.py
# should check for these, rather than reaching into the underscore-
# prefixed _docx/_Presentation names directly from another module.
HAVE_DOCX = _docx is not None
HAVE_PPTX = _Presentation is not None


def missing_optional_deps() -> list[str]:
    """Names (for pip install) of optional office packages not installed."""
    missing = []
    if not HAVE_DOCX:
        missing.append("python-docx")
    if not HAVE_PPTX:
        missing.append("python-pptx")
    return missing


def extract_docx_text(raw_bytes: bytes) -> str:
    if _docx is None:
        return "[python-docx not installed — install it to compare .docx files]"
    try:
        doc = _docx.Document(io.BytesIO(raw_bytes))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        return f"[Error reading .docx: {e}]"


def extract_pptx_text(raw_bytes: bytes) -> str:
    if _Presentation is None:
        return "[python-pptx not installed — install it to compare .pptx files]"
    try:
        prs = _Presentation(io.BytesIO(raw_bytes))
        lines = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    lines.append(shape.text.strip())
        return "\n".join(lines)
    except Exception as e:
        return f"[Error reading .pptx: {e}]"
