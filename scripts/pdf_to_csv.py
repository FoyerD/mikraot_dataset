#!/usr/bin/env python3
"""Convert the source PDFs into wide CSV files (pdf -> csv).

One CSV is written per source into the ``csv/`` directory:

    csv/mikraot_quizlet.csv   <- pdfs/mikrao_quizlet.pdf
    csv/mikraot_qa.csv        <- pdfs/mikraot_qa_tvi.pdf

Columns (wide: one AnswerN column per option, width = max options seen):

    Question, Answer1..AnswerN, Correct, CorrectAnswer, Type[, Category]

  * ``Correct`` is the 1-based index of the single correct option, or blank
    when the card is a ``fill-in``.
  * ``Fill-in`` cards are multi-correct (several options match the answer),
    open questions (no options) or cards whose answer could not be matched to
    any option.  Their ``CorrectAnswer`` holds the correct options joined by
    ", " in the order they appear (falling back to the raw answer text).
  * ``Type`` is ``mc`` for a single-choice card and ``fill-in`` otherwise.
  * ``Category`` (Quizlet CSV only) tags the "missing chapter" a Quizlet-only
    question belongs to - ``medical_first_aid`` / ``weapons_firearms`` /
    ``communications_radio`` - or ``none``.  Questions that also appear in the
    Q&A dataset, or that match no chapter keyword, get ``none``.
    ``build_extra_chapters.py`` reads this column back to build the extra
    decks.  The Q&A CSV has no ``Category`` column.

The PDF text extraction and card parsing live in ``parse_quizlet.py`` and
``parse_mikraot_qa.py``; the answer matching and categorization live in
``mikraot_shared.py``.  Files are written as ``utf-8-sig`` (BOM) so Excel
shows the Hebrew correctly.

Run with:  python3 scripts/pdf_to_csv.py
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mikraot_shared
import parse_mikraot_qa
import parse_quizlet

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_DIR = os.path.join(BASE_DIR, "csv")

# (output stem, parser module); only the Quizlet source gets a Category column.
SOURCES = [
    ("mikraot_quizlet", parse_quizlet),
    ("mikraot_qa", parse_mikraot_qa),
]

QUIZLET_STEM = "mikraot_quizlet"
QA_STEM = "mikraot_qa"


def normalize(text: str) -> str:
    """Whitespace-squashed text, for tolerant question-set comparison."""
    return " ".join(text.split())


def write_csv(stem: str, entries: list, categories: list[str] | None) -> None:
    rows = [
        mikraot_shared.classify(options, answer) for _, options, answer in entries
    ]
    width = max((len(options) for _, options, _ in entries), default=0)

    header = ["Question"]
    header += [f"Answer{i}" for i in range(1, width + 1)]
    header += ["Correct", "CorrectAnswer", "Type"]
    if categories is not None:
        header += ["Category"]

    path = os.path.join(CSV_DIR, f"{stem}.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for index, ((question, options, _), (correct, correct_answer, kind)) in enumerate(
            zip(entries, rows)
        ):
            cells = [question] + options + [""] * (width - len(options))
            cells += [correct, correct_answer, kind]
            if categories is not None:
                cells += [categories[index]]
            writer.writerow(cells)

    fill = sum(1 for _, _, kind in rows if kind == "fill-in")
    mc = len(rows) - fill
    suffix = ""
    if categories is not None:
        tagged = sum(1 for value in categories if value != mikraot_shared.NOCATEGORY)
        suffix = f", {tagged} categorized"
    print(f"{path}  ({len(rows)} rows, {mc} mc, {fill} fill-in, {width} options{suffix})")


def main() -> None:
    os.makedirs(CSV_DIR, exist_ok=True)
    entries_by_stem: dict[str, list] = {}
    for stem, module in SOURCES:
        text = module.extract_layout_text(module.find_pdf())
        entries_by_stem[stem] = module.parse_entries(text)

    # Tag Quizlet-only questions with their chapter; everything else is "none".
    qa_questions = {
        normalize(question) for question, _, _ in entries_by_stem[QA_STEM]
    }
    quizlet_categories = []
    for question, _, _ in entries_by_stem[QUIZLET_STEM]:
        norm = normalize(question)
        if norm in qa_questions:
            quizlet_categories.append(mikraot_shared.NOCATEGORY)
        else:
            quizlet_categories.append(
                mikraot_shared.bucket_of(norm) or mikraot_shared.NOCATEGORY
            )

    for stem, _ in SOURCES:
        categories = quizlet_categories if stem == QUIZLET_STEM else None
        write_csv(stem, entries_by_stem[stem], categories)


if __name__ == "__main__":
    main()
