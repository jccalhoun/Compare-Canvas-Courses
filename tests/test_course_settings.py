"""Assignment groups, course settings and the late policy (structures taken from a real export)."""
from conftest import LAR, html, labels_for, manifest, modified_titles

COURSE = """<course identifier="gC" xmlns="http://canvas.instructure.com/xsd/cccv1p0">
  <title>{title}</title><course_code>{code}</course_code><start_at>{start}</start_at>
  <tab_configuration>[{{"id":"context_external_tool_{tool}"}}]</tab_configuration>
  <image_identifier_ref>{img}</image_identifier_ref><root_account_uuid>{uuid}</root_account_uuid>
  <group_weighting_scheme>{scheme}</group_weighting_scheme><default_view>syllabus</default_view>
  <default_post_policy><post_manually>{manual}</post_manually></default_post_policy><overridden_course_visibility/>
</course>"""
LATE = """<late_policy identifier="{lid}"><late_submission_deduction_enabled>true</late_submission_deduction_enabled>
  <late_submission_deduction>{deduction}</late_submission_deduction></late_policy>"""


def group(gid, title, position, weight="0.0", rules=""):
    return (f'<assignmentGroup identifier="{gid}"><title>{title}</title><position>{position}</position>'
            f'<group_weight>{weight}</group_weight>{rules}</assignmentGroup>')


def groups_xml(*groups):
    return f'<assignmentGroups xmlns="http://canvas.instructure.com/xsd/cccv1p0">{"".join(groups)}</assignmentGroups>'


def assignment(aid, title, group_ref):
    return (f'<assignment identifier="{aid}"><title>{title}</title>'
            f'<assignment_group_identifierref>{group_ref}</assignment_group_identifierref><points_possible>5</points_possible></assignment>')


def course(make_imscc, name, files, assignments=()):
    res = [f'<resource identifier="{aid}" type="{LAR}" href="{aid}/a.html"><file href="{aid}/a.html"/>'
           f'<file href="{aid}/assignment_settings.xml"/></resource>' for aid, _, _ in assignments]
    all_files = {"imsmanifest.xml": manifest([(aid, aid, t) for aid, t, _ in assignments], res), **files}
    for aid, title, ref in assignments:
        all_files[f"{aid}/a.html"] = html("x")
        all_files[f"{aid}/assignment_settings.xml"] = assignment(aid, title, ref)
    return make_imscc(name, all_files)


def settings_files(**kw):
    values = dict(title="Fall 2026", code="C-1", start="2026-08-22", tool="gT1", img="gI1", uuid="U1",
                  scheme="equal", manual="false", lid="gL1", deduction="5.0")
    values.update(kw)
    return {"course_settings/course_settings.xml": COURSE.format(**values),
            "course_settings/late_policy.xml": LATE.format(**values)}


def test_identity_dates_ids_and_navigation_are_not_compared(make_imscc, compare):
    old = course(make_imscc, "old", settings_files())
    new = course(make_imscc, "new", settings_files(title="Spring 2027", code="C-2", start="2027-01-10",
                                                   tool="gT2", img="gI2", uuid="U2", lid="gL2"))
    report, loaded, _ = compare(old, new)
    assert modified_titles(report) == []
    fields = loaded.text_items[("settings", "Course settings")]["fields"]
    assert fields == {"group_weighting_scheme": "equal", "default_view": "syllabus", "default_post_policy.post_manually": "false"}


def test_real_setting_changes_are_reported(make_imscc, compare):
    report, *_ = compare(course(make_imscc, "old", settings_files()),
                         course(make_imscc, "new", settings_files(scheme="percent", manual="true", deduction="10.0")))
    assert sorted(labels_for(report, "[Settings] Course settings")) == [
        "Field: default_post_policy.post_manually", "Field: group_weighting_scheme"]
    assert labels_for(report, "[Settings] Late policy") == ["Field: late_submission_deduction"]


def test_assignment_groups_outline_shows_order_and_weights(make_imscc, compare):
    old = course(make_imscc, "old", {"course_settings/assignment_groups.xml": groups_xml(
        group("g1", "Homework", 1), group("g2", "Exams", 2))})
    new = course(make_imscc, "new", {"course_settings/assignment_groups.xml": groups_xml(
        group("gX", "Exams", 1, "60.0"), group("gY", "Homework", 2, "40.0"))})          # reordered, weighted, new ids
    report, *_ = compare(old, new)
    diff = report["modified"][0][1][0]["diff"]
    assert modified_titles(report) == ["[Grading] Assignment groups"]
    assert "+Exams  (weight 60%)" in diff and "+Homework  (weight 40%)" in diff and "g1" not in diff


def test_an_assignment_names_its_group_by_title(make_imscc, compare):
    groups = {"course_settings/assignment_groups.xml": groups_xml(group("gA", "Goal Setting", 1), group("gB", "Discussions", 2))}
    old = course(make_imscc, "old", groups, [("a1", "Goal Week 7", "gA")])
    new = course(make_imscc, "new", groups, [("a1", "Goal Week 7", "gB")])
    report, *_ = compare(old, new)
    change = report["modified"][0][1][0]
    assert (change["label"], change["old"], change["new"]) == ("Field: assignment_group", "Goal Setting", "Discussions")


def test_a_pointer_to_a_missing_group_says_so(make_imscc, compare):
    groups = {"course_settings/assignment_groups.xml": groups_xml(group("gA", "Goal Setting", 1))}
    _, loaded, _ = compare(*(course(make_imscc, n, groups, [("a1", "Essay", "gGONE")]) for n in ("o", "n")))
    assert loaded.text_items[("item", "Essay")]["fields"]["assignment_group"] == "[assignment group not found in this export]"


def test_drop_rules_are_shown_with_assignment_titles_not_ids(make_imscc, compare):
    """Rule format from Canvas's published schema (the real export used to build these tests has no rules)."""
    rules = ("<rules><rule><drop_type>drop_lowest</drop_type><drop_count>1</drop_count></rule>"
             "<rule><drop_type>never_drop</drop_type><identifierref>a1</identifierref></rule></rules>")
    files = {"course_settings/assignment_groups.xml": groups_xml(group("gQ", "Quizzes", 1, rules=rules))}
    _, loaded, _ = compare(*(course(make_imscc, n, files, [("a1", "Final Quiz", "gQ")]) for n in ("o", "n")))
    assert loaded.text_items[("groups", "Assignment groups")]["instructions"].splitlines() == [
        "Quizzes", "  drop lowest 1", "  never drop: Final Quiz"]


def test_skip_groups_and_settings(make_imscc, compare):
    files = {**settings_files(), "course_settings/assignment_groups.xml": groups_xml(group("gA", "Goal Setting", 1))}
    path = course(make_imscc, "c", files, [("a1", "Essay", "gA")])
    _, full, _ = compare(path, path)
    assert {k[0] for k in full.text_items} >= {"groups", "settings"} and "assignment_group" in full.text_items[("item", "Essay")]["fields"]
    _, skipped, _ = compare(path, path, skip=["groups", "settings"])
    assert {k[0] for k in skipped.text_items} == {"item"}
    assert "assignment_group" not in skipped.text_items[("item", "Essay")]["fields"]
