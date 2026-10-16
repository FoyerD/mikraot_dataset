#!/usr/bin/env python3
"""Build the "missing chapter" Anki decks from the categorized Quizlet CSV.

``pdf_to_csv.py`` tags every Quizlet-only question with a ``Category`` column
(``medical_first_aid`` / ``weapons_firearms`` / ``communications_radio`` /
``none``).  This script reads that column back from
``csv/mikraot_quizlet.csv`` and builds a normal and a multichoice ``.apkg`` for
each of the three chapters, plus a combined package.  No intermediate CSVs are
written - the Quizlet CSV *is* the source.

Chapters:

  * ``medical_first_aid``    - first aid / trauma (CPR, shock, wounds, bites).
  * ``weapons_firearms``     - weapons, stoppages, shooting procedure.
  * ``communications_radio`` - radio sets (``מ.ק``), antennas, frequencies.

Card rendering:

  * ``mc``          - single correct option.  Normal deck: Front = question,
                      Back = CorrectAnswer.  MultiChoice deck: Front = question
                      + options, Back = CorrectAnswer.
  * ``fill-in``     - never type-in: shown as a normal reveal card in both
                      decks.  Front = question + its options (one per line),
                      Back = CorrectAnswer.  Open questions (no options) show
                      just the question.  Tagged ``multi-choice``.

Duplicate questions (the Quizlet export is shuffled and repeats facts) are
dropped, keeping the first copy.

Run with:  python3 scripts/build_extra_chapters.py  (run pdf_to_csv.py first)
"""

import csv
import os
import sys

import genanki

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mikraot_shared

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_DIR = os.path.join(BASE_DIR, "csv")
DECK_DIR = os.path.join(BASE_DIR, "decks")

QUIZLET_CSV = "mikraot_quizlet"

# Anki tag for the ``fill-in`` cards (rendered as option reveal cards).
MULTI_TAG = "multi-choice"

# Per-bucket deck/model configuration:
#   bucket -> (model_id, model_name, deck_id, deck_name, apkg_stem)
MODELS = {
    "medical_first_aid": (
        1607392400,
        "Basic (Mikraot Extra)",
        2059400200,
        "מקראות - עזרה ראשונה",
        "medical_first_aid",
    ),
    "weapons_firearms": (
        1607392402,
        "Basic (Mikraot Extra)",
        2059400201,
        "מקראות - נשק וירי",
        "weapons_firearms",
    ),
    "communications_radio": (
        1607392404,
        "Basic (Mikraot Extra)",
        2059400202,
        "מקראות - קשר ותקשורת",
        "communications_radio",
    ),
}

# The combined package bundles all buckets under one model/deck pair.
COMBINED_MODEL_ID = 1607392410
COMBINED_MODEL_NAME = "Basic (Mikraot Extra Combined)"
COMBINED_DECK_ID = 2059400310
COMBINED_NAME = "מקראות - נושפים משלימים"
COMBINED_STEM = "mikraot_extra_chapters"

BASIC_TEMPLATE = {
    "name": "Card 1",
    "qfmt": "{{Front}}",
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


def read_quizlet_rows() -> list[dict]:
    path = os.path.join(CSV_DIR, f"{QUIZLET_CSV}.csv")
    if not os.path.exists(path):
        sys.exit(f"CSV not found: {path} (run scripts/pdf_to_csv.py first)")
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if "Category" not in (reader.fieldnames or []):
            sys.exit(
                f"{path} has no Category column (re-run scripts/pdf_to_csv.py)"
            )
        return list(reader)


def options_of(row: dict) -> list[str]:
    return [
        row[f"Answer{index}"].strip()
        for index in range(1, 16)
        if row.get(f"Answer{index}", "").strip()
    ]


def normalize(question: str) -> str:
    return " ".join(question.split())


def collect_by_category(rows: list[dict]) -> dict[str, list[dict]]:
    """Group rows by their Category, dropping duplicate questions."""
    chapters: dict[str, list[dict]] = {name: [] for name in mikraot_shared.CATEGORIES}
    seen: set[str] = set()
    duplicates = 0
    for row in rows:
        category = row.get("Category", "").strip()
        if category not in chapters:
            continue
        question = normalize(row["Question"])
        if question in seen:
            duplicates += 1
            continue
        seen.add(question)
        chapters[category].append(row)
    for name, chapter in chapters.items():
        print(f"{name}: {len(chapter)} cards")
    print(f"dropped (duplicate): {duplicates}")
    return chapters


def numbered_options(options: list[str]) -> str:
    return "<br>".join(
        f"{i}. {esc(option)}" for i, option in enumerate(options, 1)
    )


def build_deck(
    model_id: int,
    model_name: str,
    deck_id: int,
    deck_name: str,
    stem: str,
    rows: list[dict],
) -> None:
    deck = genanki.Deck(deck_id, deck_name)
    multi = genanki.Deck(deck_id + 100, deck_name + " (בחירה מרובה)")
    model = make_model(model_id, model_name, BASIC_TEMPLATE)
    multi_model = make_model(model_id + 1, model_name + " MultiChoice", BASIC_TEMPLATE)

    for row in rows:
        question = row["Question"].strip()
        options = options_of(row)
        answer = row["CorrectAnswer"].strip()
        option_block = (
            f"{esc(question)}<br><br>{numbered_options(options)}"
            if options
            else esc(question)
        )

        if row["Type"] == "fill-in":
            # Never type-in: show the options (one per line) and reveal the
            # correct answer(s) on the back.  Open cards have no options.
            deck.add_note(
                genanki.Note(model=model, fields=[option_block, esc(answer)], tags=[MULTI_TAG])
            )
            multi.add_note(
                genanki.Note(
                    model=multi_model,
                    fields=[option_block, esc(answer)],
                    tags=[MULTI_TAG],
                )
            )
        else:
            deck.add_note(
                genanki.Note(model=model, fields=[esc(question), esc(answer)])
            )
            multi.add_note(
                genanki.Note(model=multi_model, fields=[option_block, esc(answer)])
            )

    genanki.Package([deck]).write_to_file(os.path.join(DECK_DIR, f"{stem}.apkg"))
    genanki.Package([multi]).write_to_file(
        os.path.join(DECK_DIR, f"{stem}_multichoice.apkg")
    )
    print(f"built {stem} ({len(rows)} notes)")


def main() -> None:
    os.makedirs(DECK_DIR, exist_ok=True)
    chapters = collect_by_category(read_quizlet_rows())

    for bucket, (model_id, model_name, deck_id, deck_name, stem) in MODELS.items():
        build_deck(model_id, model_name, deck_id, deck_name, stem, chapters[bucket])

    combined = [
        row for name in mikraot_shared.CATEGORIES for row in chapters[name]
    ]
    build_deck(
        COMBINED_MODEL_ID,
        COMBINED_MODEL_NAME,
        COMBINED_DECK_ID,
        COMBINED_NAME,
        COMBINED_STEM,
        combined,
    )


if __name__ == "__main__":
    main()
