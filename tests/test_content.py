"""How individual kinds of content are read and normalised."""
from conftest import LAR, html, labels_for, manifest, modified_titles, page_resource


def page_course(make_imscc, name, state, roles, identifier, editor, linked=True):
    head = (f'<meta name="identifier" content="{identifier}"/><meta name="editing_roles" content="{roles}"/>'
            f'<meta name="workflow_state" content="{state}"/><meta name="editor_type" content="{editor}"/>'
            f'<meta name="todo_date" content="2026-09-01"/>')
    files = {"wiki_content/p.html": html("Same body.", head)}
    files["imsmanifest.xml"] = manifest([("1", "p", "Linked")], [page_resource("p", "wiki_content/p.html")]) if linked else manifest()
    return make_imscc(name, files)


def test_page_state_and_editing_roles_are_compared_but_ids_editor_and_dates_are_not(make_imscc, compare):
    for linked, title in ((True, "Linked"), (False, "[Page] wiki_content/p.html")):
        old = page_course(make_imscc, f"old{linked}", "active", "teachers", "gOLD", "rce", linked)
        new = page_course(make_imscc, f"new{linked}", "unpublished", "teachers,students", "gNEW", "html", linked)
        report, *_ = compare(old, new)
        assert sorted(labels_for(report, title)) == ["Field: editing_roles", "Field: workflow_state"]


def modules(items, module="Week 1 Monday, August 24, 2026", state="active"):
    body = "".join(f'<item identifier="x{n}"><content_type>Assignment</content_type><workflow_state>active</workflow_state>'
                   f'<title>{t}</title><position>{n}</position><indent>0</indent></item>' for n, t in enumerate(items, 1))
    return (f'<modules><module identifier="m"><title>{module}</title><workflow_state>{state}</workflow_state>'
            f'<position>1</position><items>{body}</items></module></modules>')


def test_module_outline_ignores_semester_dates_but_sees_a_reorder(make_imscc, compare):
    def build(name, items, module):
        return make_imscc(name, {"imsmanifest.xml": manifest(), "course_settings/module_meta.xml": modules(items, module)})
    old = build("old", ["Read ch 1", "Question of the day  Monday, August 24, 2026"], "Week 1 Monday, August 24, 2026")
    rolled = build("new", ["Read ch 1", "Question of the day  Monday, August 23, 2027"], "Week 1 Monday, August 23, 2027")
    assert modified_titles(compare(old, rolled)[0]) == []                   # only the dates changed
    reordered = build("re", ["Question of the day  Monday, August 23, 2027", "Read ch 1"], "Week 1 Monday, August 23, 2027")
    assert modified_titles(compare(old, reordered)[0]) == ["[Modules] Module Structure"]


def test_a_changed_completion_requirement_shows_in_the_module_outline(make_imscc, compare):
    def build(name, requirement):
        xml = modules(["Essay"]).replace("</module>",
              f'<completionRequirements><completionRequirement type="{requirement}"><identifierref>x1</identifierref>'
              f'</completionRequirement></completionRequirements></module>')
        return make_imscc(name, {"imsmanifest.xml": manifest(), "course_settings/module_meta.xml": xml})
    report, *_ = compare(build("old", "must_view"), build("new", "must_submit"))
    assert modified_titles(report) == ["[Modules] Module Structure"]
    assert "must submit" in report["modified"][0][1][0]["diff"]


def rubric_course(make_imscc, name, rubric_id, points):
    rubrics = (f"<rubrics><rubric identifier='r1'><title>Speech</title><points_possible>{points}</points_possible><criteria>"
               f"<criterion><description>Clarity</description><points>{points}</points><ratings>"
               f"<rating><description>Full</description><points>{points}</points></rating></ratings></criterion></criteria></rubric>"
               f"<rubric identifier='r2'><title>Essay</title></rubric></rubrics>")
    return make_imscc(name, {
        "imsmanifest.xml": manifest([("1", "a", "Speech")], [
            f'<resource identifier="a" type="{LAR}" href="gA/a.html"><file href="gA/a.html"/><file href="gA/assignment_settings.xml"/></resource>']),
        "gA/a.html": html("x"),
        "gA/assignment_settings.xml": f"<assignment><title>Speech</title><rubric_identifierref>{rubric_id}</rubric_identifierref></assignment>",
        "course_settings/rubrics.xml": rubrics})


def test_rubrics_compare_by_title_and_an_assignment_shows_which_rubric_it_uses(make_imscc, compare):
    report, *_ = compare(rubric_course(make_imscc, "old", "r1", 5), rubric_course(make_imscc, "new", "r2", 4))
    assert "Field: rubric" in labels_for(report, "Speech")                  # pointer resolved to a TITLE, not an id
    assert "[Rubric] Speech" in modified_titles(report)                     # its criteria points changed 5 -> 4


def settings_course(make_imscc, name, **fields):
    xml = "".join(f"<{k}>{v}</{k}>" for k, v in fields.items())
    return make_imscc(name, {
        "imsmanifest.xml": manifest([("1", "a", "Essay")], [
            f'<resource identifier="a" type="{LAR}" href="gA/a.html"><file href="gA/a.html"/><file href="gA/assignment_settings.xml"/></resource>']),
        "gA/a.html": html("x"), "gA/assignment_settings.xml": f"<assignment><title>Essay</title>{xml}</assignment>"})


def test_bookkeeping_fields_and_default_lockdown_are_not_changes(make_imscc, compare):
    old = settings_course(make_imscc, "old", position=4, all_day="false", due_at="2026-01-01",
                          points_possible=10)
    new = settings_course(make_imscc, "new", position=2, all_day="true", due_at="2027-01-01",
                          points_possible=10, lockdown_browser_settings='{"require_lockdown_browser":false}')
    assert modified_titles(compare(old, new)[0]) == []


def test_a_real_lockdown_setting_is_still_a_change(make_imscc, compare):
    old = settings_course(make_imscc, "old", points_possible=10)
    new = settings_course(make_imscc, "new", points_possible=10, lockdown_browser_settings='{"require_lockdown_browser":true}')
    assert labels_for(compare(old, new)[0], "Essay") == ["Field: lockdown_browser_settings"]


def quiz_course(make_imscc, name, description):
    meta = f"<quiz><title>Q</title><description>{description}</description><points_possible>5</points_possible></quiz>"
    return make_imscc(name, {
        "imsmanifest.xml": manifest([("1", "q", "Self-critique")], [
            '<resource identifier="q" type="imsqti_xmlv1p2/imscc_xmlv1p1/assessment"><dependency identifierref="qm"/></resource>',
            f'<resource identifier="qm" type="{LAR}" href="gQ/assessment_meta.xml"><file href="gQ/assessment_meta.xml"/></resource>']),
        "gQ/assessment_meta.xml": meta})


def test_html_in_a_setting_is_shown_as_text_and_diffed_line_by_line(make_imscc, compare):
    two = "&lt;p&gt;Watch the video:&lt;/p&gt;&lt;p&gt;&lt;a href=&quot;http://x&quot;&gt;click here&lt;/a&gt;&lt;/p&gt;"
    one = "&lt;p&gt;Watch the video:&lt;/p&gt;"
    report, *_ = compare(quiz_course(make_imscc, "old", two), quiz_course(make_imscc, "new", one))
    change = report["modified"][0][1][0]
    assert change["label"] == "Field: description" and change["kind"] == "text"
    assert "<p>" not in change["diff"] and "-click here" in change["diff"]


def classic_quiz_course(make_imscc, name, quizzes):
    """quizzes: [(id, title, question-or-None)] — None means the export has no questions (a New Quiz)."""
    res, items, files = [], [], {}
    for qid, title, question in quizzes:
        res.append(f'<resource identifier="{qid}" type="imsqti_xmlv1p2/imscc_xmlv1p1/assessment">'
                   f'<file href="{qid}/qti.xml"/><dependency identifierref="{qid}m"/></resource>'
                   f'<resource identifier="{qid}m" type="{LAR}" href="{qid}/assessment_meta.xml">'
                   f'<file href="{qid}/assessment_meta.xml"/></resource>')
        items.append((qid, qid, title))
        item = (f'<item ident="i" title="Q"><presentation><material><mattext>{question}</mattext></material>'
                f'</presentation></item>') if question else ""
        files[f"{qid}/qti.xml"] = f'<questestinterop><assessment ident="a"><section ident="s">{item}</section></assessment></questestinterop>'
        files[f"{qid}/assessment_meta.xml"] = f"<quiz><title>{title}</title><points_possible>10</points_possible></quiz>"
    files["imsmanifest.xml"] = manifest(items, res)
    return make_imscc(name, files)


def test_quizzes_whose_questions_are_not_in_the_export_are_named_in_a_notice(make_imscc, compare):
    """Such a quiz compares as 'unchanged' in both courses; the report must say its questions weren't compared."""
    path = classic_quiz_course(make_imscc, "c", [("qa", "Classic quiz", "What is 2+2?"), ("qb", "New-style quiz", None)])
    report, loaded, _ = compare(path, path, quizzes=True)
    assert modified_titles(report) == []
    assert loaded.warnings == [] and "1 quiz(zes) had no questions" in loaded.notices[0] and "'New-style quiz'" in loaded.notices[0]


def test_when_no_quiz_has_questions_it_is_a_warning_not_a_notice(make_imscc, compare):
    """All quizzes empty points at a parsing problem, not New Quizzes, so it stays a warning."""
    path = classic_quiz_course(make_imscc, "c", [("qa", "One", None), ("qb", "Two", None)])
    _, loaded, _ = compare(path, path, quizzes=True)
    assert any("none produced any question text" in w for w in loaded.warnings) and loaded.notices == []


def test_a_page_whose_file_is_missing_from_one_export_is_modified_not_removed(make_imscc, compare):
    res = [page_resource("p", "wiki_content/rules.html")]
    old = make_imscc("old", {"imsmanifest.xml": manifest([("1", "p", "Rules")], res), "wiki_content/rules.html": html("Rules.")})
    new = make_imscc("new", {"imsmanifest.xml": manifest([("1", "p", "Rules")], res)})          # file absent
    report, *_ = compare(old, new)
    assert report["removed"] == [] and modified_titles(report) == ["Rules"]


def test_a_changed_link_to_a_course_file_is_detected(make_imscc, compare):
    """Canvas writes links to course files as $IMS-CC-FILEBASE$ tokens; the target is part of the compared text."""
    res = [page_resource("p", "wiki_content/r.html")]
    def build(name, target):
        return make_imscc(name, {"imsmanifest.xml": manifest([("1", "p", "Reading")], res),
                                 "wiki_content/r.html": html(f'<a href="$IMS-CC-FILEBASE$/{target}">Reading</a>')})
    report, *_ = compare(build("old", "chapter1.pdf"), build("new", "chapter2.pdf"))
    assert modified_titles(report) == ["Reading"]
    assert "chapter2.pdf" in report["modified"][0][1][0]["diff"]
