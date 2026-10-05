"""--ignore and --skip: they must remove exactly what they name and nothing else."""
from conftest import LAR, html, manifest, modified_titles, labels_for, page_resource

MANIFEST = manifest(
    [("1", "pg", "Rules page"), ("2", "as", "Essay"), ("3", "qz", "Midterm")],
    [page_resource("pg", "wiki_content/rules.html"),
     f'<resource identifier="as" type="{LAR}" href="gAS/e.html"><file href="gAS/e.html"/><file href="gAS/assignment_settings.xml"/></resource>',
     '<resource identifier="qz" type="imsqti_xmlv1p2/imscc_xmlv1p1/assessment"><dependency identifierref="qm"/></resource>',
     f'<resource identifier="qm" type="{LAR}" href="gQZ/assessment_meta.xml"><file href="gQZ/assessment_meta.xml"/></resource>'])


def course(state, points, lockdown_on, available, module_state):
    """One export containing every kind of publish state and lockdown setting."""
    return {
        "imsmanifest.xml": MANIFEST,
        "wiki_content/rules.html": html("Same.", f'<meta name="workflow_state" content="{state[0]}"/>'),
        "gAS/e.html": html("Write it."),
        "gAS/assignment_settings.xml": (f"<assignment><title>Essay</title><workflow_state>{state[1]}</workflow_state>"
                                        f"<points_possible>{points}</points_possible>"
                                        f"<lockdown_browser_settings>{'{\"require_lockdown_browser\":%s}' % str(lockdown_on).lower()}</lockdown_browser_settings></assignment>"),
        "gQZ/assessment_meta.xml": (f"<quiz><title>Midterm</title><available>{available}</available>"
                                    f"<require_lockdown_browser>{str(lockdown_on).lower()}</require_lockdown_browser>"
                                    f"<require_lockdown_browser_monitor>true</require_lockdown_browser_monitor></quiz>"),
        "course_settings/module_meta.xml": (
            f'<modules><module identifier="m"><title>Week 1</title><workflow_state>{module_state}</workflow_state>'
            f'<position>1</position><items><item identifier="x"><content_type>Assignment</content_type>'
            f'<workflow_state>{module_state}</workflow_state><title>Essay</title><position>1</position>'
            f'<indent>0</indent></item></items></module></modules>'),
    }


def pair(make_imscc):
    old = make_imscc("old", course(("active", "published"), 10, False, "true", "active"))
    # new: everything unpublished, lockdown on, and ONE real change (points)
    new = make_imscc("new", course(("unpublished", "unpublished"), 15, True, "false", "unpublished"))
    return old, new


def test_default_run_reports_everything(make_imscc, compare):
    report, *_ = compare(*pair(make_imscc))
    assert set(modified_titles(report)) == {"Rules page", "Essay", "[Quiz] Midterm", "[Modules] Module Structure"}


def test_ignore_published_removes_state_everywhere_but_not_real_changes(make_imscc, compare):
    report, *_ = compare(*pair(make_imscc), ignore=["published"])
    assert set(modified_titles(report)) == {"Essay", "[Quiz] Midterm"}   # page + module outline now unchanged
    assert "Field: points_possible" in labels_for(report, "Essay")        # the real change survives
    assert not any("workflow_state" in l or "available" in l for l in labels_for(report, "Essay") + labels_for(report, "[Quiz] Midterm"))


def test_ignore_lockdown_matches_by_word(make_imscc, compare):
    report, *_ = compare(*pair(make_imscc), ignore=["lockdown"])
    changed = labels_for(report, "Essay") + labels_for(report, "[Quiz] Midterm")
    assert not any("lockdown" in l for l in changed)
    assert "Field: points_possible" in changed


def test_both_groups_leave_only_the_real_change(make_imscc, compare):
    report, *_ = compare(*pair(make_imscc), ignore=["published", "lockdown"])
    assert modified_titles(report) == ["Essay"]
    assert labels_for(report, "Essay") == ["Field: points_possible"]


def test_ignore_an_individual_field_by_name(make_imscc, compare):
    report, *_ = compare(*pair(make_imscc), ignore=["published", "lockdown", "points_possible"])
    assert modified_titles(report) == []


def test_skip_syllabus_leaves_no_stray_page(make_imscc, compare):
    path = make_imscc("one", {"imsmanifest.xml": manifest(), "course_settings/syllabus.html": html("Syllabus")})
    _, old, _ = compare(path, path, skip=["syllabus"])
    assert old.text_items == {} and old.warnings == []                    # silent: no 'could not read'


def test_skip_rubrics_also_drops_the_rubric_field(make_imscc, compare):
    def build(name, rubric_id):
        return make_imscc(name, {
            "imsmanifest.xml": manifest([("1", "a", "Essay")], [
                f'<resource identifier="a" type="{LAR}" href="gA/a.html"><file href="gA/a.html"/><file href="gA/assignment_settings.xml"/></resource>']),
            "gA/a.html": html("x"),
            "gA/assignment_settings.xml": f"<assignment><title>Essay</title><rubric_identifierref>{rubric_id}</rubric_identifierref></assignment>",
            "course_settings/rubrics.xml": ("<rubrics><rubric identifier='r1'><title>Rubric One</title></rubric>"
                                            "<rubric identifier='r2'><title>Rubric Two</title></rubric></rubrics>")})
    old, new = build("old", "r1"), build("new", "r2")
    report, *_ = compare(old, new)
    assert labels_for(report, "Essay") == ["Field: rubric"]               # switching rubrics is a change...
    report, _, loaded = compare(old, new, skip=["rubrics"])
    assert modified_titles(report) == [] and not any(k[0] == "rubric" for k in loaded.text_items)   # ...unless skipped


def test_skip_files_media_and_documents(make_imscc, compare):
    files = {"imsmanifest.xml": manifest(), "web_resources/a.pdf": b"%PDF one", "web_resources/v.mp4": b"VIDEO",
             "web_resources/n.txt": "kept"}
    path = make_imscc("one", files)
    _, loaded, _ = compare(path, path, skip=["files", "media"])
    assert loaded.other_files == {} and loaded.media_items == {}
    assert ("file", "web_resources/n.txt") in loaded.text_items           # other things are untouched


def test_describe_lists_what_was_left_out():
    from canvas_compare.options import CompareOptions
    assert CompareOptions().describe() == []                              # default: nothing to say, report unchanged
    opts = CompareOptions(ignore_groups=frozenset({"published"}), skip=frozenset({"media"}))
    lines = opts.describe({"workflow_state", "available"})
    assert "fields: available, workflow_state" in lines[0] and lines[1] == "Skipped entirely: media"
