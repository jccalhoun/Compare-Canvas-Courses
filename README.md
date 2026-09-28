# Canvas Course Comparison Tool

Compares two Canvas LMS course exports (`.imscc` files) and produces a report of
what changed between them — useful for reviewing updates before re-teaching a course.
Due dates and other system timestamps are always ignored.

---

## What It Compares

### Content (full text diff)
| Item type | What is compared |
|---|---|
| Assignments | Instructions text, point value, submission type, and other metadata fields |
| Discussions | Prompt text |
| Pages | Body text |
| Classic Quizzes | Quiz-level metadata (e.g. points possible) always; question text, question type, points, and answer choices (correct answers marked) with `--quizzes` |
| Word documents (`.docx`) | Full paragraph text |
| PowerPoint files (`.pptx`) | All slide text |
| Plain text files (`.txt`, `.csv`, `.md`, `.markdown`) | Full file content |

For every item found in both courses, the report shows a line-by-line diff of
anything that changed, so you can see exactly what was added or removed — not just
that *something* changed.

Links to other items in the same course (which Canvas exports as placeholder tokens
such as `$WIKI_REFERENCE$`) are shown as readable labels, e.g.
`[link to another page: g111]`, so a link that now points somewhere else shows up
as a change.

### Media files (size and checksum)
Audio and video files (`.mp4`, `.mp3`, `.wav`, `.avi`, `.mov`, `.mkv`, `.m4a`,
`.webm`, `.flac`, `.aac`) are compared by file size **and** CRC-32 checksum. Both
are already stored in the `.imscc` file, so this is fast and nothing is decompressed.
A different size or checksum flags a likely replacement; identical size and
checksum is reported as likely unchanged.

### What is always ignored
- Due dates, lock dates, unlock dates
- Peer review due dates
- System timestamps (`created_at`, `updated_at`, `last_edited_at`)

---

## What It Does Not Cover

- **Quiz questions unless you pass `--quizzes`** — parsing them is slower on courses
  with many quizzes or large question banks, so it is off by default. Even with the
  flag, exotic question types (matching, fill-in-multiple-blanks, formula) may not show
  every part of the answer.
- **New Quizzes** — question content for New Quizzes isn't included in the Common
  Cartridge export format at all. With `--quizzes`, those quizzes are flagged with a
  "No questions found in this export" note rather than compared.
- **Rubrics** — rubric criteria attached to assignments in Canvas's grading interface
  are not exported as standalone files and are not compared
- **Grade weights / assignment groups** — course grading structure is not examined
- **Course settings** — enrollment dates, grading schemes, and other course-level
  settings are not compared
- **Embedded images** — images inside assignment instructions are not compared;
  only the surrounding text is
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
next to each course as it loads.

---

## Usage

Keep `compare_canvas_courses.py` **together with its `src/` folder** (it loads the
code from there — no install step needed), and put both `.imscc` files wherever you
like. Open a terminal in the folder containing the script.

### Print the report to the terminal
```
python compare_canvas_courses.py last_summer.imscc this_summer.imscc
```

### Save the report to a text file
```
python compare_canvas_courses.py last_summer.imscc this_summer.imscc --output report.txt
```
(`-o report.txt` also works.)

### Save an HTML report with side-by-side diffs
```
python compare_canvas_courses.py last_summer.imscc this_summer.imscc --html report.html
```
Open the file in a browser. Modified items get a side-by-side, color-highlighted diff;
the overview tables at the top link to each one.

### Also compare Classic Quiz questions
```
python compare_canvas_courses.py last_summer.imscc this_summer.imscc --quizzes
```
Off by default because it is slower on courses with many quizzes. Combine with
`--output` and/or `--html` as needed.

The file names can be anything — they do not have to be called `last_summer.imscc`
and `this_summer.imscc`. The first argument is always treated as the *old* course
and the second as the *new* course.

### Optional: install as a command
```
pip install .
canvas-compare last_summer.imscc this_summer.imscc
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
section appears right after this summary. It is also included in saved reports.

### Content section

**ADDED TO THIS SUMMER** — items that exist in the new course but not the old one.

**REMOVED FROM THIS SUMMER** — items that exist in the old course but not the new one.

**MODIFIED** — items present in both courses whose content changed. Each entry
shows what specifically changed. The two file names in the diff header are your two
`.imscc` files:

```
  ▸ Overview
    [Instructions / Content]
      --- last_summer.imscc
      +++ this_summer.imscc
      @@ -1 +1 @@
      -Welcome to the course.
      +Welcome to the updated course! Extra info here.

  ▸ Essay 1
    [Field: points_possible]
        last_summer.imscc : 100
        this_summer.imscc : 90
```

Lines starting with `-` were in last summer's version only.
Lines starting with `+` are in this summer's version only.
Lines with no prefix are unchanged.

**UNCHANGED** — items present in both courses with identical content (excluding
dates). These are listed for completeness so you can confirm everything was found.

**How items are named.** Most items appear under their Canvas title. Items that need
to be told apart from those get a prefix: `[Quiz]`, `[Document]` (`.docx`),
`[Presentation]` (`.pptx`), `[Page]` (an HTML page not linked from the course
modules), and `[File]` (plain text). If two different items would end up with the
same name, the later one gets a short marker such as `(attached file)`, and two items
with an identical title get a `(2)` suffix.

### Media section

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

## Troubleshooting

**"No module named 'bs4'"**
Run `pip install beautifulsoup4 lxml` and try again.

**".docx/.pptx files are missing from the report"**
They are skipped when `python-docx` / `python-pptx` aren't installed. Run
`pip install python-docx python-pptx` and try again.

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

- **Matching items with identical titles** (for example two pages both called
  "Overview") across two separate exports is best-effort. Canvas regenerates its
  internal IDs on every export, so duplicates are matched by their file path
  instead. If a duplicate's content moves to a different path between the two
  exports, it may be matched to the wrong sibling or reported as added/removed
  instead of modified.
