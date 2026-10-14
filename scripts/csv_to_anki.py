#!/usr/bin/env python3
"""Build the Anki decks from the wide CSV files (csv -> anki).

Reads ``csv/mikraot_quizlet.csv`` and ``csv/mikraot_qa.csv`` (produced by
``pdf_to_csv.py``) and writes four packages into ``decks/``:

    mikraot_quizlet.apkg              deck "מקראות קוויזלט"
    mikraot_quizlet_multichoice.apkg  deck "מקראות קוויזלט (בחירה מרובה)"
    mikraot_qa.apkg                   deck "מקראות"
    mikraot_qa_multichoice.apkg       deck "מקראות (בחירה מרובה)"

Card rules (``Type`` column):

  * ``mc``       -> regular card.  Normal deck: Front = question,
                    Back = CorrectAnswer.  MultiChoice deck: Front = question
                    + numbered options, Back = CorrectAnswer.
  * ``fill-in``  -> type-in-the-answer card (``{{type:Back}}``) in *both*
                    decks: Front = question, Back = CorrectAnswer (the correct
                    answers joined by ", ").  The note is tagged ``fill-in``.

Run with:  python3 scripts/csv_to_anki.py
"""

import csv
import os
import sys

import genanki

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_DIR = os.path.join(BASE_DIR, "csv")
DECK_DIR = os.path.join(BASE_DIR, "decks")

# Shared model for the multi-correct / open "type in the answer" cards.
FILLIN_MODEL_ID = 1607392330
FILLIN_MODEL_NAME = "Fill-in (Mikraot)"

# Per-source: output stem -> deck/model configuration.
SOURCES = {
    "mikraot_quizlet": {
        "normal": (1607392319, "Basic (Mikraot)", 2059400110, "מקראות קוויזלט"),
        "multi": (
            1607392320,
            "Basic (Mikraot) MultiChoice",
            2059400112,
            "מקראות קוויזלט (בחירה מרובה)",
        ),
        "normal_apkg": "mikraot_quizlet.apkg",
        "multi_apkg": "mikraot_quizlet_multichoice.apkg",
    },
    "mikraot_qa": {
        "normal": (1607392321, "Basic (Mikraot Q&A)", 2059400114, "מקראות"),
        "multi": (
            1607392322,
            "Basic (Mikraot Q&A) MultiChoice",
            2059400115,
            "מקראות (בחירה מרובה)",
        ),
        "normal_apkg": "mikraot_qa.apkg",
        "multi_apkg": "mikraot_qa_multichoice.apkg",
    },
}

BASIC_TEMPLATE = {
    "name": "Card 1",
    "qfmt": "{{Front}}",
    "afmt": "{{FrontSide}}<hr id=answer>{{Back}}",
}

FILLIN_TEMPLATE = {
    "name": "Fill-in",
    "qfmt": "{{Front}}<br><br>{{type:Back}}",
    "afmt": "{{FrontSide}}<hr id=answer>{{Back}}",
}


def esc(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def make_model(model_id: int, name: str, template: dict) -> genanki.Model:
    return genanki.Model(
        model_id,
        name,
        fields=[{"name": "Front"}, {"name": "Back"}],
        templates=[template],
    )


def read_rows(stem: str) -> tuple[list[str], list[dict]]:
    path = os.path.join(CSV_DIR, f"{stem}.csv")
    if not os.path.exists(path):
        sys.exit(f"CSV not found: {path} (run scripts/pdf_to_csv.py first)")
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        rows = [dict(zip(header, row)) for row in reader]
    return header, rows


def options_of(header: list[str], row: dict) -> list[str]:
    answers = sorted(
        (name for name in header if name.startswith("Answer")),
        key=lambda name: int(name[len("Answer"):]),
    )
    return [row[name] for name in answers if row.get(name)]


def mc_front(question: str, options: list[str], multi: bool) -> str:
    if multi and options:
        numbered = "<br>".join(
            f"{i}. {esc(option)}" for i, option in enumerate(options, 1)
        )
        return f"{esc(question)}<br><br>{numbered}"
    return esc(question)


def build_deck(
    model: genanki.Model,
    fillin_model: genanki.Model,
    deck_id: int,
    deck_name: str,
    apkg_name: str,
    header: list[str],
    rows: list[dict],
    multi: bool,
) -> tuple[int, int]:
    deck = genanki.Deck(deck_id, deck_name)
    mc_count = 0
    fill_count = 0
    for row in rows:
        question = row["Question"]
        answer = row["CorrectAnswer"]
        if row["Type"] == "fill-in":
            deck.add_note(
                genanki.Note(
                    model=fillin_model,
                    fields=[esc(question), esc(answer)],
                    tags=["fill-in"],
                )
            )
            fill_count += 1
        else:
            front = mc_front(question, options_of(header, row), multi)
            deck.add_note(
                genanki.Note(model=model, fields=[front, esc(answer)])
            )
            mc_count += 1

    genanki.Package([deck]).write_to_file(os.path.join(DECK_DIR, apkg_name))
    print(
        f"{deck_name}: {len(rows)} notes "
        f"({mc_count} mc, {fill_count} fill-in) -> {apkg_name}"
    )
    return mc_count, fill_count


def main() -> None:
    os.makedirs(DECK_DIR, exist_ok=True)
    fillin_model = make_model(FILLIN_MODEL_ID, FILLIN_MODEL_NAME, FILLIN_TEMPLATE)

    for stem, config in SOURCES.items():
        header, rows = read_rows(stem)
        normal_id, normal_name, normal_deck_id, normal_deck_name = config["normal"]
        multi_id, multi_name, multi_deck_id, multi_deck_name = config["multi"]

        build_deck(
            make_model(normal_id, normal_name, BASIC_TEMPLATE),
            fillin_model,
            normal_deck_id,
            normal_deck_name,
            config["normal_apkg"],
            header,
            rows,
            multi=False,
        )
        build_deck(
            make_model(multi_id, multi_name, BASIC_TEMPLATE),
            fillin_model,
            multi_deck_id,
            multi_deck_name,
            config["multi_apkg"],
            header,
            rows,
            multi=True,
        )


if __name__ == "__main__":
    main()
