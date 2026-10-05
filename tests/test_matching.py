"""Pairing the same item across two courses when ids and titles can't be trusted."""
from conftest import html, manifest, modified_titles, page_resource


def bank(title, questions):
    items = "".join(
        f'<item ident="q{i}" title="{name}"><itemmetadata><qtimetadata><qtimetadatafield><fieldlabel>question_type</fieldlabel>'
        f'<fieldentry>multiple_choice_question</fieldentry></qtimetadatafield></qtimetadata></itemmetadata>'
        f'<presentation><material><mattext texttype="text/html">{text}</mattext></material>'
        f'<response_lid ident="r"><render_choice><response_label ident="a"><material><mattext>Yes</mattext></material></response_label>'
        f'</render_choice></response_lid></presentation></item>' for i, (name, text) in enumerate(questions))
    return (f'<questestinterop><objectbank ident="gB"><qtimetadata><qtimetadatafield><fieldlabel>bank_title</fieldlabel>'
            f'<fieldentry>{title}</fieldentry></qtimetadatafield></qtimetadata>{items}</objectbank></questestinterop>')


def banks_course(make_imscc, name, banks):
    """banks: [(file name, title, questions)] — the file name is what decides archive order."""
    files = {"imsmanifest.xml": manifest()}
    files.update({f"non_cc_assessments/{f}.xml.qti": bank(t, q) for f, t, q in banks})
    return make_imscc(name, files)


A = [("A-1", "Alpha question one"), ("A-2", "Alpha question two"), ("A-3", "Alpha question three")]
B = [("B-1", "Beta question one"), ("B-2", "Beta question two")]
A_EDITED = [A[0], ("A-2", "Alpha question TWO, edited"), A[2]]


def test_same_named_banks_pair_with_their_identical_copy(make_imscc, compare):
    """The old bank must pair with its identical twin, not with whichever copy sorts first."""
    old = banks_course(make_imscc, "old", [("gE", "Exact", A)])
    new = banks_course(make_imscc, "new", [("g0", "Exact", B), ("gZ", "Exact", A)])      # unrelated copy sorts FIRST
    report, *_ = compare(old, new, quizzes=True)
    assert modified_titles(report) == [] and report["added"] == ["[Bank] Exact (2)"]


def test_same_named_banks_pair_with_the_most_similar_copy(make_imscc, compare):
    old = banks_course(make_imscc, "old", [("gA", "Shared", A)])
    new = banks_course(make_imscc, "new", [("g0", "Shared", B), ("gZ", "Shared", A_EDITED)])
    report, *_ = compare(old, new, quizzes=True)
    assert modified_titles(report) == ["[Bank] Shared"] and report["added"] == ["[Bank] Shared (2)"]
    diff = report["modified"][0][1][0]["diff"]
    assert "-Alpha question two" in diff and "+Alpha question TWO, edited" in diff and "Beta" not in diff


def test_same_named_banks_in_a_different_file_order_are_unchanged(make_imscc, compare):
    old = banks_course(make_imscc, "old", [("g1", "Twin", A), ("g2", "Twin", B)])
    new = banks_course(make_imscc, "new", [("g1", "Twin", B), ("g2", "Twin", A)])          # same banks, swapped order
    report, *_ = compare(old, new, quizzes=True)
    assert modified_titles(report) == [] and report["added"] == [] and report["removed"] == []


def test_bank_questions_are_labeled_by_name_so_an_insert_shows_only_itself(make_imscc, compare):
    old = banks_course(make_imscc, "old", [("g1", "Bank", A)])
    new = banks_course(make_imscc, "new", [("g1", "Bank", [A[0], ("A-new", "Inserted question"), *A[1:]])])
    report, *_ = compare(old, new, quizzes=True)
    diff = report["modified"][0][1][0]["diff"]
    assert "+A-new" in diff and "+Inserted question" in diff
    assert "-A-2" not in diff and "-A-3" not in diff                                       # nothing after it was renumbered


def test_banks_are_read_only_when_quizzes_are_requested(make_imscc, compare):
    path = banks_course(make_imscc, "one", [("g1", "Bank", A)])
    assert compare(path, path, quizzes=False)[1].text_items == {}
    assert ("bank", "Bank") in compare(path, path, quizzes=True)[1].text_items


def pages(make_imscc, name, titles_and_bodies):
    res = [page_resource(f"p{n}", f"wiki_content/p{n}.html") for n in range(len(titles_and_bodies))]
    items = [(str(n), f"p{n}", t) for n, (t, _) in enumerate(titles_and_bodies)]
    files = {"imsmanifest.xml": manifest(items, res)}
    files.update({f"wiki_content/p{n}.html": html(b) for n, (_, b) in enumerate(titles_and_bodies)})
    return make_imscc(name, files)


def test_titles_differing_only_in_style_are_the_same_item(make_imscc, compare):
    old = pages(make_imscc, "old", [("Week 2 End", "Wrap up."), ("Week 3 Day 1 Start", "Warm-up.")])
    new = pages(make_imscc, "new", [("Week 2 - End", "Wrap up."), ("Week 3 - Day 1 - Start", "NEW warm-up.")])
    report, *_ = compare(old, new)
    assert report["added"] == [] and report["removed"] == []
    assert modified_titles(report) == ["Week 3 - Day 1 - Start"]             # edited one shows its content change


def test_titles_with_different_letters_or_digits_are_never_paired(make_imscc, compare):
    old = pages(make_imscc, "old", [("Week 4 End", "x")])
    new = pages(make_imscc, "new", [("Week 5 End", "x")])
    report, *_ = compare(old, new)
    assert report["removed"] == ["Week 4 End"] and report["added"] == ["Week 5 End"]


def test_an_ambiguous_style_match_is_not_guessed(make_imscc, compare):
    old = pages(make_imscc, "old", [("Plan A B", "x"), ("Plan-A-B", "y")])
    new = pages(make_imscc, "new", [("Plan (A) B", "z")])
    report, *_ = compare(old, new)
    assert len(report["removed"]) == 2 and report["added"] == ["Plan (A) B"]


def files_course(make_imscc, name, files):
    return make_imscc(name, {"imsmanifest.xml": manifest(), **files})


def test_other_files_added_removed_and_changed(make_imscc, compare):
    old = files_course(make_imscc, "old", {"web_resources/a.pdf": b"%PDF old", "web_resources/gone.png": b"png"})
    new = files_course(make_imscc, "new", {"web_resources/a.pdf": b"%PDF NEW edition", "web_resources/new.png": b"other png"})
    other = compare(old, new)[0]["other"]
    assert [c[0] for c in other["changed"]] == ["web_resources/a.pdf"]
    assert other["removed"] == ["web_resources/gone.png"] and other["added"] == ["web_resources/new.png"]


def test_a_renamed_or_moved_file_is_paired_by_size_and_checksum(make_imscc, compare):
    data = b"\x89PNG diagram" * 20
    old = files_course(make_imscc, "old", {"web_resources/Uploaded Media/diagram.png": data})
    new = files_course(make_imscc, "new", {"web_resources/Uploaded Media 3/diagram-1.png": data})
    other = compare(old, new)[0]["other"]
    assert other["renamed"] == [("web_resources/Uploaded Media/diagram.png", "web_resources/Uploaded Media 3/diagram-1.png")]
    assert other["added"] == [] and other["removed"] == []


def test_empty_files_are_never_paired_as_renames(make_imscc, compare):
    old = files_course(make_imscc, "old", {"web_resources/empty_one.png": b""})
    new = files_course(make_imscc, "new", {"web_resources/empty_two.png": b""})
    other = compare(old, new)[0]["other"]
    assert other["renamed"] == [] and other["added"] == ["web_resources/empty_two.png"]


def test_only_web_resources_count_as_course_files(make_imscc, compare):
    path = files_course(make_imscc, "one", {"course_settings/files_meta.xml": "<f/>", "lti_resource_links/x.xml": "<l/>",
                                            "web_resources/a.pdf": b"%PDF"})
    assert list(compare(path, path)[1].other_files) == ["web_resources/a.pdf"]


def test_renamed_media_is_paired(make_imscc, compare):
    old = files_course(make_imscc, "old", {"web_resources/lecture.mp4": b"VIDEO" * 50})
    new = files_course(make_imscc, "new", {"web_resources/lecture-1.mp4": b"VIDEO" * 50})
    media = compare(old, new)[0]["media"]
    assert media["renamed"] == [("web_resources/lecture.mp4", "web_resources/lecture-1.mp4")]


def test_shared_bank_names_are_a_notice_not_a_warning(make_imscc, compare, run_cli, tmp_path):
    old = banks_course(make_imscc, "old", [("g1", "Twin", A), ("g2", "Twin", B)])
    new = banks_course(make_imscc, "new", [("g1", "Twin", B), ("g2", "Twin", A)])
    _, loaded, _ = compare(old, new, quizzes=True)
    assert loaded.warnings == [] and "Copies were matched" in loaded.notices[0]
    run_cli(old, new, "--quizzes", "--output", str(tmp_path / "r.txt"), "--html", str(tmp_path / "r.html"))
    for name in ("r.txt", "r.html"):
        text = (tmp_path / name).read_text(encoding="utf-8")
        assert "Copies were matched" in text and "DIAGNOSTIC WARNINGS" not in text and "warning-box'>" not in text


def test_clashing_course_file_names_are_still_a_warning():
    """Course files are paired by archive order, not content, so a name clash could mis-pair
    them and stays a warning; items are paired by content, so theirs is only a notice."""
    from canvas_compare.loader import _report_collisions
    warnings, notices = [], []
    _report_collisions(warnings, notices, "c", [("course file", "web_resources/a.png"), ("bank", "Twin")])
    assert len(warnings) == 1 and "web_resources/a.png" in warnings[0]
    assert len(notices) == 1 and "Twin" in notices[0]
