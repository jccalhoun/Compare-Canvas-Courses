"""
Shared helpers for the tests. Every fixture is built in code, so there are no
binary files to commit and each test shows exactly what structure it relies on.

Run from the project folder:   python -m pytest
"""
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from canvas_compare.cli import main as cli_main            # noqa: E402
from canvas_compare.diff import compare_courses            # noqa: E402
from canvas_compare.loader import load_course              # noqa: E402
from canvas_compare.options import CompareOptions, apply_ignored_fields  # noqa: E402

NS = "http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1"
LAR = "associatedcontent/imscc_xmlv1p1/learning-application-resource"


def manifest(items=(), resources=()) -> str:
    """items: (identifier, resource-id, title); resources: raw <resource> XML strings."""
    tree = "".join(f'<item identifier="i-{i}" identifierref="{ref}"><title>{title}</title></item>'
                   for i, ref, title in items)
    return (f'<?xml version="1.0"?><manifest identifier="m" xmlns="{NS}"><organizations>'
            f'<organization identifier="o">{tree}</organization></organizations>'
            f'<resources>{"".join(resources)}</resources></manifest>')


def page_resource(rid: str, path: str) -> str:
    return f'<resource identifier="{rid}" type="webcontent" href="{path}"><file href="{path}"/></resource>'


def html(body: str, head: str = "") -> str:
    return f"<html><head>{head}</head><body><p>{body}</p></body></html>"


@pytest.fixture
def make_imscc(tmp_path):
    """make_imscc("name", {"member/path": str-or-bytes, ...}) -> path of a new .imscc"""
    def build(name: str, files: dict) -> str:
        path = tmp_path / f"{name}.imscc"
        with zipfile.ZipFile(path, "w") as z:
            for member, data in files.items():
                z.writestr(member, data)
        return str(path)
    return build


@pytest.fixture
def compare():
    """compare(old_path, new_path, **options) -> (report, old, new). Mirrors cli.main()."""
    def run(old_path, new_path, quizzes=False, ignore=(), skip=()):
        from canvas_compare.options import IGNORE_GROUPS
        options = CompareOptions(
            quiz_questions=quizzes, banks=quizzes, skip=frozenset(skip),
            ignore_groups=frozenset(n for n in ignore if n in IGNORE_GROUPS),
            ignore_fields=frozenset(n for n in ignore if n not in IGNORE_GROUPS))
        old = load_course(old_path, label="old", options=options)
        new = load_course(new_path, label="new", options=options)
        apply_ignored_fields(old.text_items, options)
        apply_ignored_fields(new.text_items, options)
        report = compare_courses(old.text_items, old.media_items, new.text_items, new.media_items,
                                 "old", "new", old_other=old.other_files, new_other=new.other_files)
        return report, old, new
    return run


def modified_titles(report) -> list[str]:
    return [title for title, _ in report["modified"]]


def labels_for(report, title: str) -> list[str]:
    return [c["label"] for t, changes in report["modified"] if t == title for c in changes]


@pytest.fixture
def run_cli(capsys, monkeypatch):
    """run_cli("old", "new", "--ignore", "x") -> (stdout, stderr, exit_code)"""
    def run(*args):
        monkeypatch.setattr(sys, "argv", ["compare_canvas_courses.py", *args])
        code = 0
        try:
            cli_main()
        except SystemExit as e:
            code = e.code
        out = capsys.readouterr()
        return out.out, out.err, code
    return run
