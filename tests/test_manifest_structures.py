"""How the loader understands the different ways Canvas lays out an export."""
from conftest import LAR, html, manifest, modified_titles, page_resource


def discussion_topic(text):
    return (f'<topic xmlns="http://www.imsglobal.org/xsd/imsdt_v1p1"><title>Week 1 Discussion</title>'
            f'<text texttype="text/html">&lt;p&gt;{text}&lt;/p&gt;</text></topic>')


def test_discussion_with_href(make_imscc, compare):
    res = ['<resource identifier="d" type="imsdt_xmlv1p1" href="gD.xml"><file href="gD.xml"/></resource>']
    def build(name, text):
        return make_imscc(name, {"imsmanifest.xml": manifest([("1", "d", "Week 1 Discussion")], res),
                                 "gD.xml": discussion_topic(text)})
    report, *_ = compare(build("old", "Introduce yourself."), build("new", "Describe your goals."))
    assert modified_titles(report) == ["Week 1 Discussion"]


def test_discussion_with_no_href_is_not_dropped(make_imscc, compare):
    """A discussion resource may carry its XML only as a <file> child. It used to vanish."""
    res = ['<resource identifier="d" type="imsdt_xmlv1p1"><file href="gD.xml"/></resource>']
    def build(name, text):
        return make_imscc(name, {"imsmanifest.xml": manifest([("1", "d", "Week 1 Discussion")], res),
                                 "gD.xml": discussion_topic(text)})
    report, old, _ = compare(build("old", "Introduce yourself."), build("new", "Describe your goals."))
    assert ("item", "Week 1 Discussion") in old.text_items
    assert modified_titles(report) == ["Week 1 Discussion"]


def test_linked_page_text_change(make_imscc, compare):
    res = [page_resource("p", "wiki_content/rules.html")]
    def build(name, body):
        return make_imscc(name, {"imsmanifest.xml": manifest([("1", "p", "Rules")], res),
                                 "wiki_content/rules.html": html(body)})
    report, *_ = compare(build("old", "Old rules."), build("new", "New rules."))
    assert modified_titles(report) == ["Rules"]


def assignment_settings(title, points):
    return (f"<?xml version='1.0'?><assignment><title>{title}</title>"
            f"<points_possible>{points}</points_possible></assignment>")


def test_unlinked_assignment_matches_by_title_not_folder_id(make_imscc, compare):
    """An assignment in no module has per-export folder ids; it must still pair up by title."""
    def build(name, folder, points, body):
        return make_imscc(name, {"imsmanifest.xml": manifest(),
                                 f"{folder}/assignment_settings.xml": assignment_settings("Discussion Leader", points),
                                 f"{folder}/leader.html": html(body)})
    report, *_ = compare(build("old", "gAAAA", 10, "Sign up."), build("new", "gBBBB", 15, "Sign up now."))
    assert report["added"] == [] and report["removed"] == []
    assert modified_titles(report) == ["Discussion Leader"]


def test_linked_assignment_is_not_duplicated_by_the_unlinked_pass(make_imscc, compare):
    res = [f'<resource identifier="a" type="{LAR}" href="gA/a.html"><file href="gA/a.html"/>'
           f'<file href="gA/assignment_settings.xml"/></resource>']
    path = make_imscc("one", {"imsmanifest.xml": manifest([("1", "a", "Essay")], res),
                              "gA/a.html": html("x"), "gA/assignment_settings.xml": assignment_settings("Essay", 5)})
    report, old, _ = compare(path, path)
    assert [k for k in old.text_items if k[0] == "item"] == [("item", "Essay")]


def test_canvas_control_file_is_not_course_content(make_imscc, compare):
    path = make_imscc("one", {"imsmanifest.xml": manifest(),
                              "course_settings/canvas_export.txt": "Q: Is this a Canvas export?\nA: Yes",
                              "web_resources/notes.txt": "real notes"})
    _, old, _ = compare(path, path)
    assert ("file", "course_settings/canvas_export.txt") not in old.text_items
    assert ("file", "web_resources/notes.txt") in old.text_items


def test_non_authored_quiz_landing_pages_are_ignored(make_imscc, compare):
    path = make_imscc("one", {"imsmanifest.xml": manifest(), "non_cc_assessments/landing.html": html("auto")})
    _, old, _ = compare(path, path)
    assert old.text_items == {}


def test_discussion_exactly_as_canvas_exports_it(make_imscc, compare):
    """
    The layout of real Canvas exports (confirmed in three of them): the topic XML only as a
    <file> child, no href, plus a dependency on the topicMeta file that holds its settings.
    Before the fix the item still appeared (via those settings) but its text was never read,
    so a changed discussion prompt compared as unchanged.
    """
    res = ['<resource identifier="gT" type="imsdt_xmlv1p1"><file href="gT.xml"/><dependency identifierref="gM"/></resource>',
           f'<resource identifier="gM" type="{LAR}" href="gM.xml"><file href="gM.xml"/></resource>']
    meta = ('<topicMeta identifier="gM"><topic_id>gT</topic_id><title>Week 1 Discussion</title><type>topic</type>'
            '<assignment identifier="gA"><title>Week 1 Discussion</title><points_possible>10</points_possible></assignment></topicMeta>')
    def build(name, text):
        return make_imscc(name, {"imsmanifest.xml": manifest([("1", "gT", "Week 1 Discussion")], res),
                                 "gT.xml": discussion_topic(text), "gM.xml": meta})
    report, old, _ = compare(build("old", "Introduce yourself."), build("new", "Describe your goals."))
    assert old.text_items[("item", "Week 1 Discussion")]["fields"]["points_possible"] == "10"
    assert [c["label"] for _, changes in report["modified"] for c in changes] == ["Discussion Text"]


def test_uppercase_html_extension_is_still_a_page(make_imscc, compare):
    """An uploaded file named Week1.HTML, linked from a module, must be read as that module item."""
    res = ['<resource identifier="p" type="webcontent" href="web_resources/Week1.HTML"><file href="web_resources/Week1.HTML"/></resource>']
    def build(name, body):
        return make_imscc(name, {"imsmanifest.xml": manifest([("1", "p", "Week 1 Overview")], res),
                                 "web_resources/Week1.HTML": html(body)})
    report, *_ = compare(build("old", "Old overview."), build("new", "New overview."))
    assert modified_titles(report) == ["Week 1 Overview"]                  # not an orphan "[Page] web_resources/Week1.HTML"



def qti(question):
    return ('<questestinterop><assessment ident="a" title="Quiz 1"><section ident="root">'
            f'<item ident="q1" title="Question"><presentation><material><mattext>{question}</mattext></material>'
            '<response_lid ident="r"><render_choice><response_label ident="x"><material><mattext>Yes</mattext></material>'
            '</response_label></render_choice></response_lid></presentation></item></section></assessment></questestinterop>')


def test_uppercase_quiz_qti_file_is_read(make_imscc, compare):
    """A quiz whose QTI file is named QTI.XML: its questions must still be compared."""
    res = ['<resource identifier="q" type="imsqti_xmlv1p2/imscc_xmlv1p1/assessment"><file href="quiz/QTI.XML"/></resource>']
    def build(name, question):
        return make_imscc(name, {"imsmanifest.xml": manifest([("1", "q", "Quiz 1")], res), "quiz/QTI.XML": qti(question)})
    report, *_ = compare(build("old", "What is 2+2?"), build("new", "What is 3+3?"), quizzes=True)
    assert modified_titles(report) == ["[Quiz] Quiz 1"]
