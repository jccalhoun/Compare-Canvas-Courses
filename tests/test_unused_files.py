"""The unused-files report: what counts as a link to a course file, and what doesn't."""
from conftest import html, manifest, page_resource

from canvas_compare.report_unused import format_unused_csv, format_unused_html, format_unused_text
from canvas_compare.unused_cli import main as unused_main
from canvas_compare.unused_files import (STATUS_REFERENCED, STATUS_UNPUBLISHED_ONLY,
                                         STATUS_UNREFERENCED, find_unused_files)

FB = "$IMS-CC-FILEBASE$"


def file_resource(rid, path):
    return f'<resource identifier="{rid}" type="webcontent" href="{path}"><file href="{path}"/></resource>'


def page(body, state="active", title="A page"):
    head = f'<title>{title}</title><meta name="workflow_state" content="{state}"/>'
    return html(body, head=head)


def statuses(result):
    return {f.name: f.status for f in result.files}


def build(make_imscc, files, resources=(), items=()):
    files = {"imsmanifest.xml": manifest(items, resources), **files}
    return find_unused_files(make_imscc("course", files))


def test_a_file_linked_from_a_page_is_referenced_and_others_are_not(make_imscc):
    r = build(make_imscc, {
        "wiki_content/a.html": page(f'<img src="{FB}/Uploaded%20Media/photo%201.png?canvas_download=1">'),
        "web_resources/Uploaded Media/photo 1.png": b"x" * 10,
        "web_resources/Uploaded Media/orphan.png": b"x" * 500,
    }, resources=[page_resource("p1", "wiki_content/a.html")], items=[("1", "p1", "Welcome")])
    assert statuses(r) == {"Uploaded Media/photo 1.png": STATUS_REFERENCED,
                           "Uploaded Media/orphan.png": STATUS_UNREFERENCED}
    used = next(f for f in r.files if f.status == STATUS_REFERENCED)
    assert used.used_by == ["Page: Welcome"]
    assert r.files[0].name == "Uploaded Media/orphan.png"     # unreferenced first


def test_a_file_used_only_on_an_unpublished_page_is_reported_separately(make_imscc):
    r = build(make_imscc, {
        "wiki_content/a.html": page(f'<a href="{FB}/old.pdf">old</a>', state="unpublished", title="Old"),
        "web_resources/old.pdf": b"%PDF",
    }, resources=[page_resource("p1", "wiki_content/a.html")])
    f = r.files[0]
    assert f.status == STATUS_UNPUBLISHED_ONLY and f.unpublished_by == ["Page: Old"]


def test_one_published_use_is_enough(make_imscc):
    r = build(make_imscc, {
        "wiki_content/a.html": page(f'<a href="{FB}/x.pdf">x</a>', state="unpublished"),
        "wiki_content/b.html": page(f'<a href="{FB}/x.pdf">x</a>'),
        "web_resources/x.pdf": b"%PDF",
    }, resources=[page_resource("p1", "wiki_content/a.html"), page_resource("p2", "wiki_content/b.html")])
    assert r.files[0].status == STATUS_REFERENCED


def test_images_in_question_banks_count_even_though_the_link_is_escaped(make_imscc):
    bank = ('<questestinterop><objectbank ident="b1"><qtimetadata><qtimetadatafield>'
            '<fieldlabel>bank_title</fieldlabel><fieldentry>Chapter 3</fieldentry></qtimetadatafield>'
            '</qtimetadata><item><mattext texttype="text/html">'
            f'&lt;img src="{FB}/Quiz%20Files/diagram.png" alt=""&gt;</mattext></item></objectbank>'
            '</questestinterop>')
    r = build(make_imscc, {"non_cc_assessments/b1.xml.qti": bank,
                           "web_resources/Quiz Files/diagram.png": b"png"})
    assert r.files[0].status == STATUS_REFERENCED
    assert r.files[0].used_by == ["Question bank: Chapter 3"]


def test_a_file_placed_in_a_module_is_referenced_and_its_publish_state_is_used(make_imscc):
    modules = (
        '<modules><module identifier="m1"><title>Week 1</title><workflow_state>active</workflow_state><items>'
        '<item identifier="it1"><content_type>Attachment</content_type><workflow_state>active</workflow_state>'
        '<title>Syllabus PDF</title><identifierref>f1</identifierref></item>'
        '<item identifier="it2"><content_type>Attachment</content_type><workflow_state>unpublished</workflow_state>'
        '<title>Draft</title><identifierref>f2</identifierref></item>'
        '</items></module></modules>')
    r = build(make_imscc, {"course_settings/module_meta.xml": modules,
                           "web_resources/syllabus.pdf": b"a", "web_resources/draft.pdf": b"b"},
              resources=[file_resource("f1", "web_resources/syllabus.pdf"),
                         file_resource("f2", "web_resources/draft.pdf")])
    assert statuses(r) == {"syllabus.pdf": STATUS_REFERENCED, "draft.pdf": STATUS_UNPUBLISHED_ONLY}


def test_the_course_card_image_and_file_ref_links_count(make_imscc):
    settings = '<course><image_identifier_ref>g0123456789abcdef0123456789abcdef</image_identifier_ref></course>'
    r = build(make_imscc, {
        "course_settings/course_settings.xml": settings,
        "course_settings/syllabus.html": html('<a href="$CANVAS_COURSE_REFERENCE$/file_ref/gfeedfacefeedfacefeedfacefeedface/preview">x</a>'),
        "web_resources/card.jpg": b"j", "web_resources/handout.docx": b"d",
    }, resources=[file_resource("g0123456789abcdef0123456789abcdef", "web_resources/card.jpg"),
                  file_resource("gfeedfacefeedfacefeedfacefeedface", "web_resources/handout.docx")])
    assert statuses(r) == {"card.jpg": STATUS_REFERENCED, "handout.docx": STATUS_REFERENCED}
    assert {f.used_by[0] for f in r.files} == {"Course settings (course card image)", "Syllabus"}


def test_the_manifest_itself_does_not_count_as_a_use(make_imscc):
    r = build(make_imscc, {"web_resources/a.png": b"a"},
              resources=[file_resource("g0123456789abcdef0123456789abcdef", "web_resources/a.png")])
    assert r.files[0].status == STATUS_UNREFERENCED


def test_an_assignment_takes_its_publish_state_from_its_settings(make_imscc):
    res = ('<resource identifier="a1" type="associatedcontent/imscc_xmlv1p1/learning-application-resource" '
           'href="a1/essay.html"><file href="a1/essay.html"/><file href="a1/assignment_settings.xml"/></resource>')
    r = build(make_imscc, {
        "a1/essay.html": html(f'<a href="{FB}/rubric.pdf">rubric</a>'),
        "a1/assignment_settings.xml": '<assignment identifier="a1"><title>Essay 1</title>'
                                      '<workflow_state>unpublished</workflow_state></assignment>',
        "web_resources/rubric.pdf": b"r",
    }, resources=[res])
    f = r.files[0]
    assert f.status == STATUS_UNPUBLISHED_ONLY and f.unpublished_by == ["Assignment: Essay 1"]


def test_links_inside_an_uploaded_html_file_only_count_if_that_file_is_used(make_imscc):
    files = {
        "web_resources/site/index.html": '<img src="img/a.png"><link href="style.css">',
        "web_resources/site/style.css": "body { background: url('img/bg.png') }",
        "web_resources/site/img/a.png": b"a",
        "web_resources/site/img/bg.png": b"b",
    }
    assert set(statuses(build(make_imscc, files)).values()) == {STATUS_UNREFERENCED}

    files["wiki_content/p.html"] = page(f'<a href="{FB}/site/index.html">site</a>')
    r = build(make_imscc, files, resources=[page_resource("p1", "wiki_content/p.html")])
    assert set(statuses(r).values()) == {STATUS_REFERENCED}
    bg = next(f for f in r.files if f.name == "site/img/bg.png")
    assert bg.used_by == ["File: site/style.css"]


def test_links_to_files_missing_from_the_export_are_listed(make_imscc):
    r = build(make_imscc, {"wiki_content/a.html": page(f'<img src="{FB}/gone.png">', title="Week 2")},
              resources=[page_resource("p1", "wiki_content/a.html")], items=[("1", "p1", "Week 2")])
    assert r.missing == [("Page: Week 2", "gone.png")]


def test_decomposed_unicode_file_names_still_match(make_imscc):
    import unicodedata
    stored = unicodedata.normalize("NFD", "web_resources/café.png")
    r = build(make_imscc, {"wiki_content/a.html": page(f'<img src="{FB}/caf%C3%A9.png">'), stored: b"c"},
              resources=[page_resource("p1", "wiki_content/a.html")])
    assert r.files[0].status == STATUS_REFERENCED


def test_reports_and_cli(make_imscc, tmp_path, capsys):
    path = make_imscc("course", {
        "imsmanifest.xml": manifest(),
        "web_resources/big & old.mp4": b"x" * 4096,
    })
    unused_main([path, "--csv", str(tmp_path / "f.csv"), "--html", str(tmp_path / "f.html")])
    out = capsys.readouterr().out
    assert "1 unreferenced (4.0 KB)" in out and "big & old.mp4" in out
    csv_text = (tmp_path / "f.csv").read_text(encoding="utf-8-sig")
    assert csv_text.splitlines()[0].startswith("File,Folder,Size (bytes),Size,Status")
    assert csv_text.splitlines()[1].startswith("big & old.mp4,,4096,4.0 KB,unreferenced")
    page_html = (tmp_path / "f.html").read_text(encoding="utf-8")
    assert "big &amp; old.mp4" in page_html and "big & old" not in page_html
    # File, then folder, then size; each heading is a sort button.
    head = page_html.split("<thead>", 1)[1].split("</thead>", 1)[0]
    assert head.index(">File<") < head.index(">Folder<") < head.index(">Size<")
    assert "table.sortable" in page_html and "data-sort='4096'" in page_html


def test_cli_rejects_a_file_that_is_not_an_export(make_imscc, capsys):
    import pytest
    path = make_imscc("notacourse", {"readme.txt": "hi"})
    with pytest.raises(SystemExit) as e:
        unused_main([path])
    assert e.value.code == 1 and "imsmanifest.xml" in capsys.readouterr().err
