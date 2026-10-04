"""
What to compare, and what to leave out.

One object, built from the command line today and from a GUI's checkboxes
later, so the two can never drift apart. There are two kinds of switch:

* SECTIONS are parts of the export that can be left out entirely. Skipping
  one also skips the work of reading it.
* IGNORE_GROUPS are named settings that are still read but left out of the
  comparison (everything else about the item is still compared). Any other
  field can be ignored by its own name too.

To add a switch: add an entry below, and for a section add one line in
loader.py that checks `options.wants("name")`.
"""

from __future__ import annotations

from dataclasses import dataclass

# Parts of the export that can be switched off entirely: name -> description.
SECTIONS = {
    "rubrics":   "rubric definitions, and the rubric each assignment uses",
    "modules":   "the module outline (order, prerequisites, completion requirements)",
    "syllabus":  "the course syllabus",
    "banks":     "question banks (they are only read when quizzes are compared)",
    "files":     "other course files (PDFs, images, ...)",
    "media":     "audio and video files",
    "documents": "Word and PowerPoint files",
}

# Settings that can be left out: name -> (description, exact field names,
# words a field name may contain). Matching on words as well as names means a
# field this tool hasn't seen yet (a new "require_lockdown_browser_monitor")
# is still caught.
IGNORE_GROUPS = {
    "lockdown":  ("lockdown browser settings", set(), ("lockdown",)),
    "published": ("published / unpublished state",
                  {"workflow_state", "available"}, ("publish",)),
}

# A module outline marks unpublished modules and items in the text itself,
# not in a field, so the "published" group also has to reach into that.
PUBLISH_STATES = {"unpublished", "published", "active"}


@dataclass
class CompareOptions:
    quiz_questions: bool = False        # read Classic Quiz questions (slower)
    banks: bool = False                 # read question banks (slower)
    skip: frozenset = frozenset()       # SECTIONS to leave out
    ignore_groups: frozenset = frozenset()   # IGNORE_GROUPS to leave out
    ignore_fields: frozenset = frozenset()   # individual field names to leave out

    def wants(self, section: str) -> bool:
        return section not in self.skip

    @property
    def hides_publish_state(self) -> bool:
        return "published" in self.ignore_groups

    @staticmethod
    def _in_group(group: str, name: str) -> bool:
        _, names, words = IGNORE_GROUPS[group]
        return name in names or any(w in name.lower() for w in words)

    def is_ignored_field(self, name: str) -> bool:
        return name in self.ignore_fields or any(self._in_group(g, name) for g in self.ignore_groups)

    def describe(self, found: set[str] = frozenset()) -> list[str]:
        """Lines for the top of a report saying what was left out. Empty when
        everything is compared, so a default run's report is unchanged.
        `found` is the set of field names actually removed, so the report says
        exactly which fields a group covered in these two courses."""
        lines = []
        left_out = []
        for g in sorted(self.ignore_groups):
            fields = sorted(n for n in found if self._in_group(g, n))
            left_out.append(IGNORE_GROUPS[g][0] + (f" (fields: {', '.join(fields)})" if fields else ""))
        left_out += [f"field '{f}'" for f in sorted(self.ignore_fields)]
        if left_out:
            lines.append("Not compared: " + ", ".join(left_out))
        if self.skip:
            lines.append("Skipped entirely: " + ", ".join(sorted(self.skip)))
        return lines


def parse_names(values: list[str] | None) -> list[str]:
    """['a,b', 'c'] -> ['a', 'b', 'c'] (a flag may be repeated or comma-separated)."""
    return [n.strip() for v in values or [] for n in v.split(",") if n.strip()]


def apply_ignored_fields(text_items: dict, options: CompareOptions) -> set[str]:
    """
    Remove ignored fields from every loaded item and return the names that were
    actually found and removed. Done after loading, on the data itself, so an
    item whose only difference was an ignored field simply compares as unchanged.
    """
    dropped = set()
    for entry in text_items.values():
        for name in [n for n in entry["fields"] if options.is_ignored_field(n)]:
            del entry["fields"][name]
            dropped.add(name)
    return dropped
