# Canvas Course Comparison Tool

Compares two Canvas LMS course exports (`.imscc` files) and produces a report of
what changed between them — useful for reviewing updates before re-teaching a course.
Due dates and other system timestamps are always ignored.

---

## What It Compares

### Content (full text diff)
| Item type | What is compared |
|---|---|
| Assignments | Instructions text, point value, submission type, and other metadata fields (including assignments that aren't placed in any module) |
| Discussions | Prompt text |
| Pages | Body text, whether the page is published, and who can edit it |
| Course syllabus | Syllabus body text |
| Module structure | Module order, the items in each module and their order, published state, prerequisites, and completion requirements (see below) |
| Question banks (with `--quizzes`) | Every question in each bank: text, answer choices (correct ones marked), type and points. Banks are matched by title, and each question is labeled by its own name rather than a position number. |
| Assignment groups | The groups in order, their weights (when weighted grading is used) and drop rules; each assignment also shows which group it belongs to |
| Course settings and late policy | Every setting in the export's course settings and late policy (weighting scheme, default view, student permissions, late and missing penalties, ...), except identity, dates, ids and the navigation menu |
| Rubrics | Every rubric in the course: criteria, rating levels, and points. An assignment or graded discussion also shows which rubric it uses. |
| Classic Quizzes | Quiz-level metadata (e.g. points possible) always; question text, question type, points, and answer choices (correct answers marked) with `--quizzes` |
| Word documents (`.docx`) | Paragraphs, table cells, and headers/footers |
| PowerPoint files (`.pptx`) | Text boxes (including grouped ones), table cells, and speaker notes |
| Plain text files (`.txt`, `.csv`, `.md`, `.markdown`) | Full file content |

For every item found in both courses, the report shows a line-by-line diff of
anything that changed, so you can see exactly what was added or removed — not just
that *something* changed.

Links to other items in the same course (which Canvas exports as placeholder tokens
such as `$WIKI_REFERENCE$`) are shown as readable labels, e.g.
`[link to another page: g111]`, so a link that now points somewhere else shows up
as a change.

Settings that contain HTML (for example a quiz's description) are shown as plain
text and compared line by line. As elsewhere, only the visible text is compared, so
a change to an ordinary link's address is not shown unless the wording around it
changes.

### Media files (size and checksum)
Audio and video files (`.mp4`, `.mp3`, `.wav`, `.avi`, `.mov`, `.mkv`, `.m4a`,
`.webm`, `.flac`, `.aac`) are compared by file size **and** CRC-32 checksum. Both
are already stored in the `.imscc` file, so this is fast and nothing is decompressed.
A different size or checksum flags a likely replacement; identical size and
checksum is reported as likely unchanged.

### Other course files (size and checksum)
Everything else in the course's files — PDFs, images (`.png`, `.jpg`, `.jpeg`, `.svg`),
spreadsheets, and so on — is compared the same way and listed in its own section of the
report. Unchanged files are only counted, not listed, since there are often a great
many. These files are never opened, so even a large course adds almost nothing to the
run time. (`.docx`, `.pptx` and text files are compared by their contents, as above.)

**Renamed or moved files.** A file that disappears under one name and appears under
another with the same size and CRC-32 checksum is reported as *renamed or moved*, not as
a removal plus an addition. (A checksum match isn't a mathematical proof that two files are
identical, but a false match between two different files is about a 1-in-4-billion event.) This covers the `-1` suffix Canvas adds to re-imported files
and a file moved between folders. Empty files are never paired this way.

### What is always ignored
- Due dates, lock dates, unlock dates
- Peer review due dates
- System timestamps (`created_at`, `updated_at`, `last_edited_at`)
- A lockdown-browser setting stored at its default (`{"require_lockdown_browser":false}`),
  which is the same as not having one
- Bookkeeping that shifts when *other* items change: an assignment's `position` within
  its group, and its `all_day` flag (which follows the due time)

---

## What It Does Not Cover

- **Quiz questions and question banks unless you pass `--quizzes`** — parsing them is slower on courses
  with many quizzes or large question banks, so it is off by default. Even with the
  flag, exotic question types (matching, fill-in-multiple-blanks, formula) may not show
  every part of the answer.
- **New Quizzes** — question content for New Quizzes isn't included in the Common
  Cartridge export format at all. With `--quizzes`, those quizzes are flagged with a
  "No questions found in this export" note rather than compared, and the note at the top
  of the report names them, so "unchanged" is never mistaken for "checked".
- **Course identity, dates and navigation** — the course title, course code, start and end
  dates, and the course navigation menu are left out of the course-settings comparison
  (the first three differ between any two sections by design; the menu is stored with ids
  that change on every export)
- **Grading scheme details** — whether a grading scheme is enabled is compared, but the
  letter-grade cutoffs themselves are not
- **Which image a page uses** — a replaced image file is reported as a changed course
  file, but a page that now points at a different image isn't flagged by its text
- **External URLs** — links to outside resources are not followed or validated, and a
  change to an ordinary link (one that isn't a Canvas placeholder token) is not
  shown in the diff

---

## How to Export Your Courses from Canvas

1. Open the course in Canvas
2. Go to **Settings** (left sidebar, near the bottom)
3. Click **Export Course Content**
4. Under *Export Type*, select **Common Cartridge**
5. Click **Create Export** and wait for it to finish
6. Download the `.imscc` file when the link appears

Repeat for both courses.

---

## Requirements

**Python 3.10 or later.**

### Required libraries
```
pip install beautifulsoup4 lxml
```

### Optional libraries (needed to compare `.docx` and `.pptx` files)
```
pip install python-docx python-pptx
```
If these are not installed, the script still runs, but `.docx` and `.pptx` files are
**skipped entirely** — they do not appear in the report at all. (They are left out
rather than shown with a placeholder, because a placeholder would look identical in
both courses and make every one of them appear "unchanged".) A notice at the start of
the run tells you when this is happening, and how many files were skipped is shown
next to each course as it loads. The saved report lists them under its diagnostic
warnings as well, so it never reads as a complete comparison when it wasn't.

---

## Usage

Keep `compare_canvas_courses.py` **together with its `src/` folder** (it loads the
code from there — no install step needed), and put both `.imscc` files wherever you
like. Open a terminal in the folder containing the script.

### Print the report to the terminal
```
python compare_canvas_courses.py old_course.imscc new_course.imscc
```

### Save the report to a text file
```
python compare_canvas_courses.py old_course.imscc new_course.imscc --output report.txt
```
(`-o report.txt` also works.)

### Save an HTML report with side-by-side diffs
```
python compare_canvas_courses.py old_course.imscc new_course.imscc --html report.html
```
Open the file in a browser. Modified items get a side-by-side, color-highlighted diff;
the overview tables at the top link to each one.

### Also compare Classic Quiz questions and question banks
```
python compare_canvas_courses.py old_course.imscc new_course.imscc --quizzes
```
Off by default because it is slower: reading about 7,000 bank questions (roughly 20 MB
of data) takes around 10 seconds per course. Combine with
`--output` and/or `--html` as needed.

The file names can be anything — they do not have to be called `old_course.imscc`
and `new_course.imscc`. The first argument is always treated as the *old* course
and the second as the *new* course.

### Save a JSON report (for scripts)
```
python compare_canvas_courses.py old_course.imscc new_course.imscc --json report.json
```
The same comparison in a machine-readable form, for use by other programs. It can be
combined with `--output` and `--html`. The top-level keys are:

| Key | Contents |
|---|---|
| `schema_version` | Layout version (currently `1`); changes only if a key is renamed or removed |
| `old_course`, `new_course` | `path` and `name` of each export |
| `settings` | Options the run used: quiz questions, question banks, skipped sections, ignored groups and fields |
| `summary` | Counts for `content`, `media` and `other_files` |
| `warnings`, `notes` | The same messages as at the top of the other reports |
| `content` | `added`, `removed`, `unchanged` and `modified` items. Each has `title` (as shown in the report), `kind` (`item`, `quiz`, `bank`, `rubric`, `page`, `document`, ...) and `name`. Modified items also have `changes`: each with `label`, `field` (the setting's name, or `null` for text), `kind` (`text` or `field`), `old`, `new` and a unified `diff` |
| `media`, `other_files` | `added`, `removed`, `unchanged` (names); `renamed` (`old`, `new`); `changed` (`name`, `old_size`, `new_size`, `old_crc32`, `new_crc32`) |

### Choose what to compare

Two options let you leave things out. Run `--list-options` to see everything they accept.

**`--ignore`** keeps reading an item but leaves a setting out of the comparison:
```
python compare_canvas_courses.py old_course.imscc new_course.imscc --ignore lockdown,published
```
- `lockdown` — lockdown browser settings (any field with "lockdown" in its name)
- `published` — published / unpublished state: the `workflow_state` and `available`
  settings, and the "(unpublished)" marks in the module outline
- or the name of **any field** shown as `Field: name` in a report, for example
  `--ignore points_possible,allowed_attempts`

An item whose only difference was an ignored setting then counts as unchanged. If you
name a field that appears in neither course (a typo, say), the tool tells you.

**`--skip`** leaves out whole sections, and doesn't read them, which also saves time:
```
python compare_canvas_courses.py old_course.imscc new_course.imscc --skip files,media
```
`rubrics`, `modules`, `syllabus`, `banks`, `files` (PDFs, images, ...), `media`
(audio/video) and `documents` (Word and PowerPoint). Skipping `rubrics` also drops the
"which rubric" setting on assignments.

Both can be repeated or comma-separated. The report states what was left out, at the
top, including exactly which fields an `--ignore` group covered in your two courses, so
a report never silently looks more complete than it is.

### Optional: install as a command
```
pip install .
canvas-compare old_course.imscc new_course.imscc
```
Add the optional office libraries with `pip install ".[office]"`.

---

## Reading the Report

The report opens with a one-line count for content and for media:

```
  Content  — 0 added | 0 removed | 4 modified | 1 unchanged
  Media    — 0 added | 0 removed | 1 changed | 0 unchanged
```

If the tool noticed something that may make the results unreliable (for example, it
found assignments but couldn't read any of their settings), a **DIAGNOSTIC WARNINGS**
section appears right after this summary, in saved reports as well as on screen. Purely
informational messages (for example, that several question banks share a name and were
paired by content) appear instead as a short italic note at the top, so the warnings box
is kept for things that need attention.

### Content section

**ADDED (new course only)** — items that exist in the new course but not the old one.

**REMOVED (old course only)** — items that exist in the old course but not the new one.

**MODIFIED** — items present in both courses whose content changed. Each entry
shows what specifically changed. The two file names in the diff header are your two
`.imscc` files:

```
  ▸ Overview
    [Instructions / Content]
      --- old_course.imscc
      +++ new_course.imscc
      @@ -1 +1 @@
      -Welcome to the course.
      +Welcome to the updated course! Extra info here.

  ▸ Essay 1
    [Field: points_possible]
        old_course.imscc : 100
        new_course.imscc : 90
```

Lines starting with `-` are in the old course's version only.
Lines starting with `+` are in the new course's version only.
Lines with no prefix are unchanged.

**UNCHANGED** — items present in both courses with identical content (excluding
dates). These are listed for completeness so you can confirm everything was found.
Unchanged rubrics and question banks are only counted ("131 question bank(s) (not
listed)"), since a course can have well over a hundred of each.

**How items are named.** Most items appear under their Canvas title. Items that need
to be told apart from those get a prefix: `[Quiz]`, `[Document]` (`.docx`),
`[Presentation]` (`.pptx`), `[Page]` (an HTML page not linked from the course
modules), `[File]` (plain text), `[Syllabus]`, `[Modules]` (the whole module
outline, as one item), `[Rubric]` and `[Bank]` (a question bank). If two different kinds of item would end up with
the same name, the later one gets a short marker such as `(attached file)`; two items
of the same kind and name get a `(2)` suffix.

**Titles that differ only in style.** An item is treated as the same one if its title
differs only in capitalization, punctuation or spacing ("Week 2 End" and "Week 2 - End"),
as long as exactly one item on each side has that spelling. The letters and digits must
be identical, so "Week 2 End" and "Week 3 End" are never paired. The note at the top of
the report lists every pair matched this way, since the report itself shows only the
new title.

**Items that share a name.** Copies are common, especially question banks: your course
may well have several banks with the same title. When either course has more than one
item with a name, they are paired **by content** — identical ones first, then the most
similar — not by the order they happen to appear in the file (Canvas regenerates the ids
that order comes from on every export). So a bank is compared with its real counterpart
rather than with an unrelated copy. Leftover copies appear as additions or removals,
numbered `(2)`, `(3)`, ...

### Media and other-file sections

```
  Changed — different size or content, possible replacement (1):
    ▸ lecture.mp4
      900 bytes → 1,350 bytes  (+450)

  Same size — likely unchanged (1):
    ✓ intro_music.mp3
```

A changed size or checksum is a strong signal the file was re-recorded or replaced.
If the size is identical but the checksum differs, the report says
`same size (…) — content differs`. Matching size and checksum means the file was
almost certainly not touched, though a checksum is not a byte-for-byte comparison.

---

## Running the tests

The project has a test suite that builds small example exports in code (no binary files)
and checks how each kind of Canvas content is read and compared:
```
pip install pytest python-docx python-pptx beautifulsoup4 lxml
python -m pytest
```
When a comparison gives a surprising result, the quickest way to make sure it stays fixed
is to reproduce it as a test in `tests/` using the helpers in `tests/conftest.py`.

## Troubleshooting

**"No module named 'bs4'"**
Run `pip install beautifulsoup4 lxml` and try again.

**".docx/.pptx files are missing from the report"**
They are skipped when `python-docx` / `python-pptx` aren't installed. Run
`pip install python-docx python-pptx` and try again.

**A warning says a file "could not be read … it was not compared"**
That `.docx`, `.pptx` or other file couldn't be opened (usually because it is corrupted
in the export), so it is left out of the comparison rather than shown as unchanged. The
same warning appears at the top of saved reports. Re-export the course, or check the
file in Canvas.

**"python: command not found"**
Try `python3` instead of `python`.

**"isn't a valid .imscc/zip file" or "doesn't contain an imsmanifest.xml"**
The file is corrupted, incomplete, or isn't a Canvas Common Cartridge export.
Re-export it from Canvas.

**The report shows everything as added/removed with nothing in common**
This can happen if the two `.imscc` files are from completely different courses.
The script matches items by their title — if titles were renamed between courses,
renamed items will appear as one removal and one addition rather than a modification.

---

## Known Limitations

- **Text boxes and drawings inside a `.docx`**, and any text that is part of an image, are not
  read, so a change there isn't seen.

- **Module structure ignores dates in titles.** Module headings and item titles
  usually carry that semester's dates ("Week 1 Monday, August 24, 2026"), which would
  otherwise show as changed every term, so a month-and-day (with optional year) is
  stripped from them before comparing. Weekday names are kept, so a class moving
  from Monday to Tuesday still shows. Module structure is compared as one outline, so
  a reordered module appears as a moved block.
- **Question banks are matched by title**, so a renamed bank appears as one removal and
  one addition. Within a bank, questions are labeled by their own names (for example
  `Chapter11-02`), so adding or removing a question shows only that question rather than
  renumbering the rest. A bank's `bank_context_uuid` is ignored: it identifies the course,
  so it differs between any two.
- **Drop rules** ("drop lowest 1", "never drop: Final Quiz") follow Canvas's published
  export format; they were tested against constructed examples, not a real export that
  uses them.
- **Rubrics are matched by title**, so a renamed rubric appears as one removal and one
  addition. Every rubric in the course is compared, including ones no assignment uses,
  so the UNCHANGED list gets longer. The rubric's `read_only` flag is ignored: it
  appears to be set by Canvas, not by an instructor.
- **Items whose titles contain dates** (for example "Question of the day  Thursday,
  August 27, 2026") are matched by exact title, so they show as one removal and one
  addition whenever the dates change. They can't be paired automatically: once the date
  is removed, many of them share the same title.
- **Canvas renames re-imported files** by appending `-1`, `-2` and so on
  (`handout.pdf` becomes `handout-1.pdf`). Files with the same size and checksum are paired as
  renamed. A file that was renamed *and* edited shows as one removal plus one addition,
  and link text that mentions the old file name still appears as a text difference.
- **Comparing courses with different structures** (for example a 16-week and an
  8-week section) produces many genuine additions and removals, and a large module
  outline diff. That is expected, not a fault.

- **Matching items with identical titles** (for example two assignments both called
  "Essay") is done by content, since Canvas regenerates its internal IDs on every
  export: identical copies pair first, then the most similar. If two same-titled items
  were both heavily rewritten, the pairing between them is a best guess.
