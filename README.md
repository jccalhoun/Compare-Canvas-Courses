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
| Word documents (`.docx`) | Full paragraph text |
| PowerPoint files (`.pptx`) | All slide text |
| Plain text files (`.txt`, `.csv`, `.md`, `.markdown`) | Full file content |

For every item found in both courses, the report shows a line-by-line diff of
anything that changed, so you can see exactly what was added or removed — not just
that *something* changed.

### Media files (size comparison only)
Audio and video files (`.mp4`, `.mp3`, `.wav`, `.avi`, `.mov`, `.mkv`, `.m4a`,
`.webm`, `.flac`, `.aac`) are compared by file size only. A size difference flags
a likely replacement; identical size is reported as likely unchanged.

### What is always ignored
- Due dates, lock dates, unlock dates
- Peer review due dates
- System timestamps (`created_at`, `updated_at`, `last_edited_at`)

---

## What It Does Not Cover

- **Canvas Quizzes** — quiz questions are stored in a separate format inside `.imscc`
  files and are not currently parsed
- **Rubrics** — rubric criteria attached to assignments in Canvas's grading interface
  are not exported as standalone files and are not compared
- **Grade weights / assignment groups** — course grading structure is not examined
- **Course settings** — enrollment dates, grading schemes, and other course-level
  settings are not compared
- **Embedded images** — images inside assignment instructions are not compared;
  only the surrounding text is
- **External URLs** — links to outside resources are not followed or validated

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

**Python 3.10 or later** is required (the script uses `tuple[x, y]` type hints).

### Required libraries
```
pip install beautifulsoup4 lxml
```

### Optional libraries (needed to compare `.docx` and `.pptx` files)
```
pip install python-docx python-pptx
```
If these are not installed, the script still runs — `.docx` and `.pptx` files will
appear in the report with a placeholder message instead of a content diff.

---

## Usage

Place `compare_canvas_courses.py` and both `.imscc` files in the same folder,
then open a terminal in that folder.

### Print the report to the terminal
```
python compare_canvas_courses.py last_summer.imscc this_summer.imscc
```

### Save the report to a text file
```
python compare_canvas_courses.py last_summer.imscc this_summer.imscc --output report.txt
```

The file names can be anything — they do not have to be called `last_summer.imscc`
and `this_summer.imscc`. The first argument is always treated as the *old* course
and the second as the *new* course.

---

## Reading the Report

The report has two sections.

### Content section

```
  Summary: 2 added | 1 removed | 3 modified | 8 unchanged
```

**ADDED** — items that exist in the new course but not the old one.

**REMOVED** — items that exist in the old course but not the new one.

**MODIFIED** — items present in both courses whose content changed. Each entry
shows what specifically changed:

```
  ▸ Essay 1
    [Instructions / Content]
      --- Last Summer — Instructions
      +++ This Summer — Instructions
      @@ -1,2 +1,2 @@
       Essay 1

      -Write a 500-word essay. Submit as PDF.
      +Write a 750-word essay. Submit as Word document. Include a bibliography.
    [Field: points_possible]
        Last Summer : 50
        This Summer : 75
```

Lines starting with `-` were in last summer's version only.
Lines starting with `+` are in this summer's version only.
Lines with no prefix are unchanged.

**UNCHANGED** — items present in both courses with identical content (excluding
dates). These are listed for completeness so you can confirm everything was found.

### Media section

```
  Size changed — possible replacement (1):
    ▸ lecture1.mp4
      1,000,000 bytes → 1,200,000 bytes  (+200,000)

  Same size — likely unchanged (1):
    ✓ intro_music.mp3
```

A changed file size is a strong signal the file was re-recorded or replaced.
Identical size means the file was probably not touched, though this is not
guaranteed — it is a quick scan, not a byte-for-byte comparison.

---

## Troubleshooting

**"No module named 'bs4'"**
Run `pip install beautifulsoup4 lxml` and try again.

**".docx/.pptx files show a placeholder"**
Run `pip install python-docx python-pptx` and try again.

**"python: command not found"**
Try `python3` instead of `python`.

**The report shows everything as added/removed with nothing in common**
This can happen if the two `.imscc` files are from completely different courses.
The script matches items by their title — if titles were renamed between courses,
renamed items will appear as one removal and one addition rather than a modification.
