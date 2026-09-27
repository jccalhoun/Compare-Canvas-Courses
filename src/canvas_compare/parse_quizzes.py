"""Parses Classic Quiz QTI 1.2 assessment XML into readable question text."""

from __future__ import annotations

from bs4 import BeautifulSoup

from .parse_html import clean_html


def _find_correct_response_idents(item_soup) -> set:
    """
    Given an <item> tag from a QTI 1.2 assessment, return the set of
    response_label idents that resprocessing marks as correct (any
    respcondition that sets a nonzero SCORE).

    Multi-answer ("select all that apply") questions commonly express the
    scoring condition as an AND of several varequal checks, where one or
    more of them is wrapped in <not> — meaning "this choice must NOT be
    selected" for the item to score. find_all("varequal") finds those too;
    without excluding ones nested inside <not>, a choice that should stay
    unselected gets mislabeled "(correct)" instead.
    """
    correct = set()
    for cond in item_soup.find_all("respcondition"):
        is_correct = any(
            sv.get("action", "").lower() == "set"
            and sv.get("varname", "").upper() == "SCORE"
            and sv.text.strip() not in ("", "0", "0.0")
            for sv in cond.find_all("setvar")
        )
        if not is_correct:
            continue
        for ve in cond.find_all("varequal"):
            if ve.find_parent("not") is not None:
                continue
            correct.add(ve.text.strip())
    return correct


def extract_quiz_questions(raw: str) -> str:
    """
    Parse a QTI 1.2 assessment XML (Canvas Classic Quiz export) into a
    normalized, human-readable block of question text and answer choices
    (correct choices marked), suitable for line-by-line diffing.

    Best-effort: handles multiple choice, true/false, multiple answer,
    and short answer/essay questions cleanly. More exotic question types
    (matching, fill-in-multiple-blanks, formula questions) will still show
    their question text but may not render every sub-part of the answer.
    """
    soup = BeautifulSoup(raw, "xml")
    blocks = []
    for i, item in enumerate(soup.find_all("item"), start=1):
        qtype  = ""
        points = ""
        for f in item.find_all("qtimetadatafield"):
            label = f.find("fieldlabel")
            entry = f.find("fieldentry")
            if not (label and entry):
                continue
            if label.text.strip() == "question_type":
                qtype = entry.text.strip()
            elif label.text.strip() == "points_possible":
                points = entry.text.strip()

        q_text = ""
        presentation = item.find("presentation")
        if presentation:
            material = presentation.find("material", recursive=False)
            if material:
                mt = material.find("mattext")
                if mt:
                    q_text = clean_html(mt.text or "")

        correct_idents = _find_correct_response_idents(item)

        choices = []
        for label_tag in item.find_all("response_label"):
            ident = label_tag.get("ident", "")
            mt = label_tag.find("mattext")
            text = clean_html(mt.text) if mt else ""
            marker = " (correct)" if ident in correct_idents else ""
            choices.append(f"  - {text}{marker}")

        header = f"Q{i}"
        if qtype:
            header += f" [{qtype}]"
        if points:
            header += f" ({points} pts)"

        block = [header]
        if q_text:
            block.append(q_text)
        block.extend(choices)
        blocks.append("\n".join(block))

    return "\n\n".join(blocks)
