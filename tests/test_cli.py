"""The command line: arguments, error handling, and what reaches the saved reports."""
from conftest import html, manifest


def course(make_imscc, name, body="Same."):
    return make_imscc(name, {"imsmanifest.xml": manifest(), "wiki_content/a.html": html(body)})


def test_report_files_are_written(make_imscc, run_cli, tmp_path):
    out, err, code = run_cli(course(make_imscc, "old"), course(make_imscc, "new", "Changed."),
                             "--output", str(tmp_path / "r.txt"), "--html", str(tmp_path / "r.html"))
    assert code == 0 and (tmp_path / "r.txt").read_text(encoding="utf-8").count("CANVAS COURSE COMPARISON REPORT") == 1
    assert "<h1>Canvas Course Comparison</h1>" in (tmp_path / "r.html").read_text(encoding="utf-8")


def test_a_default_report_says_nothing_about_options(make_imscc, run_cli, tmp_path):
    run_cli(course(make_imscc, "old"), course(make_imscc, "new"), "--output", str(tmp_path / "r.txt"))
    text = (tmp_path / "r.txt").read_text(encoding="utf-8")
    assert "Not compared" not in text and "Skipped entirely" not in text


def test_the_report_states_what_was_left_out(make_imscc, run_cli, tmp_path):
    run_cli(course(make_imscc, "old"), course(make_imscc, "new"), "--ignore", "published", "--skip", "media",
            "--output", str(tmp_path / "r.txt"), "--html", str(tmp_path / "r.html"))
    for name in ("r.txt", "r.html"):
        text = (tmp_path / name).read_text(encoding="utf-8")
        assert "Not compared: published / unpublished state" in text and "Skipped entirely: media" in text


def test_a_misspelled_field_name_is_reported_not_silently_accepted(make_imscc, run_cli):
    out, _, code = run_cli(course(make_imscc, "old"), course(make_imscc, "new"), "--ignore", "lockdwon")
    assert code == 0 and "no field called 'lockdwon' was found" in out


def test_an_unknown_section_is_an_error(make_imscc, run_cli):
    _, err, code = run_cli(course(make_imscc, "old"), course(make_imscc, "new"), "--skip", "rubrix")
    assert code == 2 and "unknown section(s) for --skip: rubrix" in err


def test_two_files_are_required(make_imscc, run_cli):
    _, err, code = run_cli(course(make_imscc, "old"))
    assert code == 2 and "two .imscc files are required" in err


def test_list_options_needs_no_files(run_cli):
    out, _, code = run_cli("--list-options")
    assert code == 0 and "rubrics" in out and "lockdown" in out and "published" in out


def test_error_paths(make_imscc, run_cli, tmp_path):
    good = course(make_imscc, "good")
    _, err, code = run_cli(str(tmp_path / "nope.imscc"), good)
    assert code == 1 and "file not found" in err
    bad = tmp_path / "bad.imscc"
    bad.write_text("not a zip")
    _, err, code = run_cli(str(bad), good)
    assert code == 1 and "isn't a valid .imscc/zip file" in err
    _, err, code = run_cli(make_imscc("nomanifest", {"x.txt": "x"}), good)
    assert code == 1 and "doesn't contain an imsmanifest.xml" in err


def test_an_unexpected_keyerror_is_not_mistaken_for_a_missing_manifest(make_imscc, run_cli, monkeypatch):
    import canvas_compare.cli as cli
    monkeypatch.setattr(cli, "load_course", lambda *a, **k: (_ for _ in ()).throw(KeyError("a real bug")))
    try:
        run_cli(course(make_imscc, "old"), course(make_imscc, "new"))
    except KeyError as e:
        assert "a real bug" in str(e)
    else:
        raise AssertionError("the KeyError was swallowed")


def test_warnings_reach_the_saved_report(make_imscc, run_cli, tmp_path):
    import pytest
    pytest.importorskip("docx")
    files = {"imsmanifest.xml": manifest(), "web_resources/bad.docx": b"not a docx"}
    run_cli(make_imscc("old", files), make_imscc("new", files), "--output", str(tmp_path / "r.txt"))
    text = (tmp_path / "r.txt").read_text(encoding="utf-8")
    assert "DIAGNOSTIC WARNINGS" in text and "could not read web_resources/bad.docx" in text
