#!/usr/bin/env python3
"""Convert the source PDFs into wide CSV files (pdf -> csv).

One CSV is written per source into the ``csv/`` directory:

    csv/mikraot_quizlet.csv   <- pdfs/mikrao_quizlet.pdf
    csv/mikraot_qa.csv        <- pdfs/mikraot_qa_tvi.pdf

Columns (wide: one AnswerN column per option, width = max options seen):

    Question, Answer1..AnswerN, Correct, CorrectAnswer, Type

  * ``Correct`` is the 1-based index of the single correct option, or blank
    when the card is a ``fill-in``.
  * ``Fill-in`` cards are multi-correct (several options match the answer),
    open questions (no options) or cards whose answer could not be matched to
    any option.  Their ``CorrectAnswer`` holds the correct options joined by
    ", " in the order they appear (falling back to the raw answer text).
  * ``Type`` is ``mc`` for a single-choice card and ``fill-in`` otherwise.

The PDF text extraction and card parsing live in ``parse_quizlet.py`` and
``parse_mikraot_qa.py``; this script only reshapes their output.  Files are
written as ``utf-8-sig`` (BOM) so Excel shows the Hebrew correctly.

Run with:  python3 scripts/pdf_to_csv.py
"""

import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import parse_mikraot_qa
import parse_quizlet

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_DIR = os.path.join(BASE_DIR, "csv")

# (output stem, parser module)
SOURCES = [
    ("mikraot_quizlet", parse_quizlet),
    ("mikraot_qa", parse_mikraot_qa),
]

BIDI = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def normalize(text: str) -> str:
    """Squash text to letters/digits only, for tolerant answer matching."""
    return "".join(ch for ch in BIDI.sub("", text) if ch.isalnum())


def match_options(options: list[str], answer: str) -> tuple[list[int], bool]:
    """Return ``(correct_indices, resolved)`` for one card.

    Options are extracted greedily, longest first, consuming the answer as
    they go.  This avoids false positives such as "500" matching inside
    "5000", or "ט' בתמוז" matching inside "כ''ט בתמוז".  ``resolved`` is True
    only when the chosen options account for the whole answer.
    """
    remaining = normalize(answer)
    if not remaining:
        return [], False
    chosen: list[int] = []
    pool = sorted(
        range(len(options)),
        key=lambda i: len(normalize(options[i])),
        reverse=True,
    )
    while remaining:
        hit = None
        for i in pool:
            if i in chosen:
                continue
            token = normalize(options[i])
            if token and token in remaining:
                hit = i
                break
        if hit is None:
            break
        chosen.append(hit)
        remaining = remaining.replace(normalize(options[hit]), "", 1)
    chosen.sort()
    return chosen, not remaining and bool(chosen)


def classify(options: list[str], answer: str) -> tuple[str, str, str]:
    """Return ``(correct, correct_answer, type)`` for one card."""
    chosen, resolved = match_options(options, answer)
    if resolved and len(chosen) == 1:
        index = chosen[0] + 1
        return str(index), options[chosen[0]], "mc"
    if resolved and len(chosen) > 1:
        joined = ", ".join(options[i] for i in chosen)
        return "", joined, "fill-in"
    if chosen:
        joined = ", ".join(options[i] for i in chosen)
        return "", joined, "fill-in"
    return "", answer, "fill-in"


def write_csv(stem: str, module) -> tuple[int, int, int]:
    text = module.extract_layout_text(module.find_pdf())
    entries = module.parse_entries(text)
    rows = [classify(options, answer) for _, options, answer in entries]
    width = max((len(options) for _, options, _ in entries), default=0)

    header = ["Question"]
    header += [f"Answer{i}" for i in range(1, width + 1)]
    header += ["Correct", "CorrectAnswer", "Type"]

    path = os.path.join(CSV_DIR, f"{stem}.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for (question, options, _), (correct, correct_answer, kind) in zip(
            entries, rows
        ):
            cells = [question] + options + [""] * (width - len(options))
            writer.writerow(cells + [correct, correct_answer, kind])

    fill = sum(1 for _, _, kind in rows if kind == "fill-in")
    mc = len(rows) - fill
    print(f"{path}  ({len(rows)} rows, {mc} mc, {fill} fill-in, {width} options)")
    return len(rows), mc, fill


def main() -> None:
    os.makedirs(CSV_DIR, exist_ok=True)
    for stem, module in SOURCES:
        write_csv(stem, module)


if __name__ == "__main__":
    main()
