"""
Finds course files that nothing in a Canvas .imscc export points at.

Canvas has no "where is this file used?" lookup, so this builds one: every
file under web_resources/ (the course's Files area) is the inventory, and
every other text file in the export (pages, assignment and discussion
text, quizzes, question banks, the syllabus, calendar events, course
settings, the module list) is searched for links to those files. A file
nothing links to is "unreferenced". A file linked only from unpublished
content is reported separately, since students can't reach it that way
either.

How a link to a file looks in an export:
    $IMS-CC-FILEBASE$/Uploaded%20Media/photo.png?canvas_download=1
        A path under web_resources/, percent-encoded. This is how Canvas
        writes almost every file link in HTML, including the HTML inside
        quiz and question bank XML (escaped there, so text is unescaped
        before searching).
    $CANVAS_COURSE_REFERENCE$/file_ref/<identifier>   (and similar forms)
        A file's manifest resource identifier instead of its path.
    <identifierref> / <image_identifier_ref> and other bare identifiers
        A module item that is a file, the course card image, and so on.
        Any token in the text that equals a file's identifier counts.
    Ordinary relative links (src="images/a.png") inside an HTML or CSS
        file that is itself in web_resources/. These only count when the
        HTML file is itself reached: an unused HTML file doesn't keep its
        own images "in use".

This is a separate tool from the course comparison: it reads one export,
and none of the comparison modules depend on it (or it on them, apart from
MissingManifestError, so callers can handle a non-export the same way).
"""

from __future__ import annotations

import html
import posixpath
import re
import unicodedata
import zipfile
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import unquote

from bs4 import BeautifulSoup

from .parse_manifest import MissingManifestError

FILES_PREFIX = "web_resources/"

# Canvas's own bookkeeping, not course content. The manifest lists every file
# as a resource and files_meta.xml lists hidden/locked files, so searching
# them would mark everything as used.
_NOT_SOURCES = {
    "imsmanifest.xml",
    "course_settings/canvas_export.txt",
    "course_settings/files_meta.xml",
}
MODULES_PATH = "course_settings/module_meta.xml"
MEDIA_TRACKS_PATH = "course_settings/media_tracks.xml"

# Members outside web_resources/ that are read for links. Anything else
# (binary files Canvas put elsewhere, say) is left unopened.
_SOURCE_EXTENSIONS = (".html", ".htm", ".xml", ".qti", ".json", ".txt")
# Files inside web_resources/ whose own relative links are followed.
_LINKING_FILE_EXTENSIONS = (".html", ".htm", ".css")

# Fixed course-level files with a readable name for the report.
_FIXED_SOURCE_LABELS = {
    "course_settings/syllabus.html": "Syllabus",
    "course_settings/course_settings.xml": "Course settings (course card image)",
    "course_settings/events.xml": "Calendar events",
}

PUBLISHED = "published"
UNPUBLISHED = "unpublished"

STATUS_REFERENCED = "referenced"
STATUS_UNPUBLISHED_ONLY = "unpublished only"
STATUS_UNREFERENCED = "unreferenced"

_FILEBASE_RE = re.compile(r"\$IMS[-_]CC[-_]FILEBASE\$/+([^\"'<>\s?#]+)")
_ID_REF_RE = re.compile(
    r"\$CANVAS_(?:COURSE|OBJECT)_REFERENCE\$/(?:file_ref|files|attachments)/([A-Za-z0-9_-]+)")
# Canvas identifiers are long hashes ("g3f2a..."), so a bare token only counts
# as an identifier at this length or more; a short one could be an ordinary word.
_ID_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{16,}")
_REL_ATTR_RE = re.compile(r"""\b(?:src|href|data|poster)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_CSS_URL_RE = re.compile(r"""url\(\s*["']?([^"')]+?)["']?\s*\)""", re.IGNORECASE)
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_TITLE_RE = re.compile(r"<title>\s*(.*?)\s*</title>", re.IGNORECASE | re.DOTALL)
_BANK_TITLE_RE = re.compile(
    r"<fieldlabel>\s*bank_title\s*</fieldlabel>\s*<fieldentry>\s*(.*?)\s*</fieldentry>", re.DOTALL)
# Unpublished markers: a page's <meta name="workflow_state">, an assignment's
# or discussion's <workflow_state>, a classic quiz's <available>false.
_UNPUBLISHED_RES = (
    re.compile(r"""<meta\s+name=["']workflow_state["']\s+content=["']unpublished["']""", re.IGNORECASE),
    re.compile(r"<workflow_state>\s*unpublished\s*</workflow_state>"),
    re.compile(r"<available>\s*false\s*</available>"),
)


@dataclass
class CourseFile:
    path: str                                   # archive path, web_resources/...
    size: int
    status: str = STATUS_UNREFERENCED
    used_by: list = field(default_factory=list)          # labels of published / always-visible uses
    unpublished_by: list = field(default_factory=list)   # labels of uses in unpublished content

    @property
    def name(self) -> str:
        """The path as it appears in Canvas's Files area."""
        return self.path[len(FILES_PREFIX):]

    @property
    def folder(self) -> str:
        return posixpath.dirname(self.name)

    @property
    def filename(self) -> str:
        return posixpath.basename(self.name)


@dataclass
class UnusedFilesResult:
    files: list                                 # every CourseFile, unreferenced first, then largest first
    missing: list                               # (source label, link target) for links to files not in the export
    warnings: list

    def with_status(self, status: str) -> list:
        return [f for f in self.files if f.status == status]


def _nfc(path: str) -> str:
    # Zips made on a Mac can store names decomposed (NFD); links are usually composed.
    return unicodedata.normalize("NFC", path)


def _unescape(text: str) -> str:
    """HTML-unescape until stable (quiz XML holds HTML that is itself escaped)."""
    for _ in range(3):
        if "&" not in text:
            break
        new = html.unescape(text)
        if new == text:
            break
        text = new
    return text


def _clean_path(path: str) -> str:
    path = unquote(path.split("?", 1)[0].split("#", 1)[0])
    # A path that ends in ")" with no "(" was cut from inside url(...) or prose.
    if path.endswith(")") and "(" not in path:
        path = path[:-1]
    return path


class _FileIndex:
    """Looks up a linked path among the course files, tolerating Unicode form and, if unambiguous, case."""

    def __init__(self, members):
        self.exact = {_nfc(m): m for m in members}
        folded = {}
        for m in members:
            folded.setdefault(_nfc(m).casefold(), []).append(m)
        self.folded = {k: v[0] for k, v in folded.items() if len(v) == 1}

    def lookup(self, path: str):
        key = _nfc(path)
        return self.exact.get(key) or self.folded.get(key.casefold())


@dataclass
class _Scan:
    """What one text member links to, plus what it says about itself."""
    targets: set                 # course file members
    missing: set                 # link targets not in the export
    title: str = ""
    unpublished: bool = False
    bank_title: str | None = None


def _scan_text(raw: str, index: _FileIndex, file_ids: dict, base_dir: str | None = None,
               bare_ids: bool = True) -> _Scan:
    targets, missing = set(), set()
    text = _unescape(raw)

    for m in _FILEBASE_RE.finditer(text):
        path = _clean_path(m.group(1))
        hit = index.lookup(FILES_PREFIX + path)
        if hit:
            targets.add(hit)
        elif path:
            missing.add(path)

    for m in _ID_REF_RE.finditer(text):
        hit = file_ids.get(m.group(1))
        if hit:
            targets.add(hit)
        else:
            missing.add(f"file id {m.group(1)}")

    if bare_ids:
        for token in set(_ID_TOKEN_RE.findall(text)):
            hit = file_ids.get(token)
            if hit:
                targets.add(hit)

    if base_dir is not None:
        for m in list(_REL_ATTR_RE.finditer(text)) + list(_CSS_URL_RE.finditer(text)):
            ref = m.group(1).strip()
            if not ref or ref.startswith(("#", "/", "$", "//")) or _SCHEME_RE.match(ref):
                continue
            path = posixpath.normpath(posixpath.join(base_dir, _clean_path(ref)))
            if path.startswith(FILES_PREFIX):
                hit = index.lookup(path)
                if hit:
                    targets.add(hit)

    title_match = _TITLE_RE.search(raw)
    bank_match = _BANK_TITLE_RE.search(raw) if "<objectbank" in raw[:4096] else None
    return _Scan(
        targets=targets,
        missing=missing,
        title=html.unescape(title_match.group(1)).strip() if title_match else "",
        unpublished=any(r.search(raw) for r in _UNPUBLISHED_RES),
        bank_title=(html.unescape(bank_match.group(1)) if bank_match else ("" if "<objectbank" in raw[:4096] else None)),
    )


def _read(z: zipfile.ZipFile, name: str) -> str:
    return z.read(name).decode("utf-8-sig", errors="replace")


def _parse_manifest(z: zipfile.ZipFile):
    """resources: id -> {type, members, deps}; item_titles: identifierref -> title."""
    try:
        raw = _read(z, "imsmanifest.xml")
    except KeyError:
        raise MissingManifestError("imsmanifest.xml not found in archive") from None
    soup = BeautifulSoup(raw, "xml")
    resources = {}
    for res in soup.find_all("resource"):
        rid = res.get("identifier", "")
        href = unquote(res.get("href", ""))
        members = [href] if href else []
        members += [unquote(f.get("href", "")) for f in res.find_all("file") if f.get("href")]
        resources[rid] = {
            "type": res.get("type", "").lower(),
            "members": list(dict.fromkeys(members)),
            "deps": [d.get("identifierref", "") for d in res.find_all("dependency")],
            "title": res.get("title", ""),
        }
    item_titles = {}
    for item in soup.find_all("item"):
        ref = item.get("identifierref")
        title = item.find("title", recursive=False)
        if ref and title is not None and title.text.strip():
            item_titles.setdefault(ref, title.text.strip())
    return resources, item_titles


def _kind(rtype: str, members) -> str:
    if "imsdt" in rtype:
        return "Discussion"
    if "imsqti" in rtype:
        return "Quiz"
    if any(m.endswith("assignment_settings.xml") for m in members):
        return "Assignment"
    if any(m.startswith("wiki_content/") for m in members):
        return "Page"
    if any(m.startswith("non_cc_assessments/") for m in members):
        return "Quiz"
    return "Item"


def find_unused_files(imscc_path: str) -> UnusedFilesResult:
    with zipfile.ZipFile(imscc_path) as z:
        return _analyze(z)


def _analyze(z: zipfile.ZipFile) -> UnusedFilesResult:
    warnings = []
    infos = [i for i in z.infolist() if not i.is_dir()]
    names = {i.filename for i in infos}
    course_files = {i.filename: CourseFile(i.filename, i.file_size)
                    for i in infos if i.filename.startswith(FILES_PREFIX)}
    index = _FileIndex(course_files)

    resources, item_titles = _parse_manifest(z)

    # A file's manifest identifier, for links that name it by id.
    file_ids = {}
    for rid, res in resources.items():
        for m in res["members"]:
            if m in course_files:
                file_ids[rid] = m
                break

    # ── Scan every non-file text member ─────────────────────────────────────
    scans = {}
    for name in sorted(names):
        if (name.startswith(FILES_PREFIX) or name in _NOT_SOURCES
                or name in (MODULES_PATH, MEDIA_TRACKS_PATH)
                or not name.lower().endswith(_SOURCE_EXTENSIONS)):
            continue
        try:
            scans[name] = _scan_text(_read(z, name), index, file_ids)
        except Exception as e:  # one unreadable member shouldn't stop the report
            warnings.append(f"could not read {name} ({e}); links in it were not counted.")

    # ── Which course item each scanned member belongs to ───────────────────
    # A resource plus the files of the resources it depends on is one item
    # (a quiz's QTI + its assessment_meta.xml; a discussion + its topicMeta).
    # Resources that are only someone's dependency are tried last, so their
    # files are credited to the item that uses them.
    dep_targets = {d for r in resources.values() for d in r["deps"]}
    owners = {}

    def group_members(rid):
        res = resources[rid]
        out = [m for m in res["members"] if m in scans]
        for d in res["deps"]:
            if d in resources and d not in file_ids:
                out += [m for m in resources[d]["members"] if m in scans]
        return out

    for rid in sorted(resources, key=lambda r: r in dep_targets):
        if rid in file_ids:
            continue
        for m in group_members(rid):
            if not (rid in dep_targets and m in owners):
                owners.setdefault(m, []).append(rid)

    # Canvas's own copy of each classic quiz (non_cc_assessments/<quiz id>.xml.qti)
    # belongs to that quiz even when the manifest doesn't say so.
    for name in scans:
        if name.startswith("non_cc_assessments/") and name not in owners:
            stem = posixpath.basename(name).split(".", 1)[0]
            if stem in resources:
                owners[name] = [stem]

    group_cache = {}

    def group_info(rid):
        if rid not in group_cache:
            members = group_members(rid)
            title = (item_titles.get(rid) or resources[rid]["title"]
                     or next((scans[m].title for m in sorted(members, key=lambda m: not m.endswith(".xml"))
                              if scans[m].title), "")
                     or rid)
            unpublished = any(scans[m].unpublished for m in members)
            group_cache[rid] = (f"{_kind(resources[rid]['type'], members)}: {title}", unpublished)
        return group_cache[rid]

    def source_of(name):
        """(label, state) for a scanned member."""
        scan = scans[name]
        if scan.bank_title is not None:
            # Checked first: a bank may also be a manifest resource, but it is
            # still a bank. Banks have no published state; a file used in a
            # bank question counts as in use.
            return f"Question bank: {scan.bank_title or posixpath.basename(name)}", PUBLISHED
        if name in owners:
            infos_ = [group_info(r) for r in owners[name]]
            label = infos_[0][0]
            state = UNPUBLISHED if all(u for _, u in infos_) else PUBLISHED
            return label, state
        if name in _FIXED_SOURCE_LABELS:
            return _FIXED_SOURCE_LABELS[name], PUBLISHED
        folder = posixpath.dirname(name)
        settings = f"{folder}/assignment_settings.xml" if folder else ""
        if settings in scans:   # an assignment the manifest doesn't list
            s = scans[settings]
            return (f"Assignment: {s.title or folder}",
                    UNPUBLISHED if s.unpublished or scan.unpublished else PUBLISHED)
        if name.startswith("wiki_content/"):
            return f"Page: {scan.title or posixpath.basename(name)}", UNPUBLISHED if scan.unpublished else PUBLISHED
        return name, UNPUBLISHED if scan.unpublished else PUBLISHED

    # ── Roots: (file, label, state) ─────────────────────────────────────────
    roots = []
    missing = set()
    for name, scan in scans.items():
        label, state = source_of(name)
        roots += [(t, label, state) for t in scan.targets]
        missing |= {(label, path) for path in scan.missing}

    if MODULES_PATH in names:
        try:
            roots += _module_file_items(_read(z, MODULES_PATH), file_ids)
        except Exception as e:
            warnings.append(f"could not read {MODULES_PATH} ({e}); files placed in modules may be "
                            f"reported as unreferenced.")
    else:
        # Not a Canvas export (or an old one): fall back to the manifest's item tree.
        roots += [(file_ids[ref], f"Module item: {title}", PUBLISHED)
                  for ref, title in item_titles.items() if ref in file_ids]

    # ── Links between course files ─────────────────────────────────────────
    edges = {}
    if MEDIA_TRACKS_PATH in names:
        try:
            for media, track in _media_tracks(_read(z, MEDIA_TRACKS_PATH), file_ids):
                edges.setdefault(media, []).append(track)
        except Exception as e:
            warnings.append(f"could not read {MEDIA_TRACKS_PATH} ({e}); caption files may be "
                            f"reported as unreferenced.")

    linking_cache = {}

    def links_from(member):
        if member not in linking_cache:
            found = list(edges.get(member, []))
            if member.lower().endswith(_LINKING_FILE_EXTENSIONS):
                try:
                    found += _scan_text(_read(z, member), index, file_ids,
                                        base_dir=posixpath.dirname(member), bare_ids=False).targets
                except Exception as e:
                    warnings.append(f"could not read {member} ({e}); links in it were not counted.")
            linking_cache[member] = [t for t in dict.fromkeys(found) if t != member]
        return linking_cache[member]

    reasons = {m: {PUBLISHED: set(), UNPUBLISHED: set()} for m in course_files}
    for state in (PUBLISHED, UNPUBLISHED):
        seen, queue = set(), deque()
        for target, label, s in roots:
            if s == state:
                reasons[target][state].add(label)
                if target not in seen:
                    seen.add(target)
                    queue.append(target)
        while queue:
            current = queue.popleft()
            for target in links_from(current):
                reasons[target][state].add(f"File: {course_files[current].name}")
                if target not in seen:
                    seen.add(target)
                    queue.append(target)

    for member, f in course_files.items():
        f.used_by = sorted(reasons[member][PUBLISHED])
        f.unpublished_by = sorted(reasons[member][UNPUBLISHED])
        f.status = (STATUS_REFERENCED if f.used_by
                    else STATUS_UNPUBLISHED_ONLY if f.unpublished_by
                    else STATUS_UNREFERENCED)

    order = {STATUS_UNREFERENCED: 0, STATUS_UNPUBLISHED_ONLY: 1, STATUS_REFERENCED: 2}
    files = sorted(course_files.values(), key=lambda f: (order[f.status], -f.size, f.path.lower()))
    if not files:
        warnings.append("this export has no course files (nothing under web_resources/).")
    return UnusedFilesResult(files, sorted(missing), warnings)


def _child_text(tag, name: str) -> str:
    child = tag.find(name, recursive=False)
    return child.text.strip() if child is not None else ""


def _module_file_items(raw: str, file_ids: dict) -> list:
    """Files placed directly in a module, as (file, label, state)."""
    soup = BeautifulSoup(raw, "xml")
    out = []
    for module in soup.find_all("module"):
        mtitle = _child_text(module, "title")
        module_off = _child_text(module, "workflow_state") == "unpublished"
        items = module.find("items", recursive=False)
        for it in items.find_all("item", recursive=False) if items is not None else []:
            target = file_ids.get(_child_text(it, "identifierref"))
            if _child_text(it, "content_type") != "Attachment" or not target:
                continue
            off = module_off or _child_text(it, "workflow_state") == "unpublished"
            out.append((target, f"Module: {mtitle} › {_child_text(it, 'title')}",
                        UNPUBLISHED if off else PUBLISHED))
    return out


def _media_tracks(raw: str, file_ids: dict) -> list:
    """
    (media file, caption/track file) pairs. Read without assuming the exact
    element names: within each entry under the root, the first file
    identifier is the media file and any further ones are its tracks.
    """
    soup = BeautifulSoup(raw, "xml")
    root = next((c for c in soup.children if getattr(c, "name", None)), None)
    pairs = []
    for entry in root.find_all(recursive=False) if root is not None else []:
        ids = []
        for tag in [entry] + entry.find_all(True):
            for value in list(tag.attrs.values()) + ([tag.string] if tag.string else []):
                value = str(value).strip()
                if value in file_ids and file_ids[value] not in ids:
                    ids.append(file_ids[value])
        pairs += [(ids[0], track) for track in ids[1:]]
    return pairs
