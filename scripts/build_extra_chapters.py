#!/usr/bin/env python3
"""Extract the "missing chapters" and build their Anki decks.

The Quizlet export contains technical-training content (first aid, weapons,
communications) that never made it into the Q&A dataset.  This script finds the
Quizlet questions that are absent from the Q&A CSV, buckets them into three
chapters, writes one wide CSV per chapter (plus a combined CSV) and builds the
``.apkg`` packages.

Buckets:

  * ``medical_first_aid``    - first aid / trauma (CPR, shock, wounds, bites).
  * ``weapons_firearms``     - weapons, stoppages, shooting procedure.
  * ``communications_radio`` - radio sets (``מ.ק``), antennas, frequencies.

Questions from the Quizlet CSV that do not match any bucket keyword are dropped
(they are either duplicates of Q&A content phrased differently, or genuinely
miscellaneous).  The tally is printed at the end.

Run with:  python3 scripts/build_extra_chapters.py
"""

import csv
import os
import sys

import genanki

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_DIR = os.path.join(BASE_DIR, "csv")
DECK_DIR = os.path.join(BASE_DIR, "decks")

QUIZLET_CSV = "mikraot_quizlet"
QA_CSV = "mikraot_qa"

# Widest source column layout we mirror in the chapter CSVs.  We always emit
# four answer slots so the files line up with the Q&A CSV format.
CSV_HEADER = [
    "Question",
    "Answer1",
    "Answer2",
    "Answer3",
    "Answer4",
    "Correct",
    "CorrectAnswer",
    "Type",
]
MAX_OPTIONS = 4

# Shared "type in the answer" model, same as csv_to_anki.py.
FILLIN_MODEL_ID = 1607392330
FILLIN_MODEL_NAME = "Fill-in (Mikraot)"

# Bucket keyword rules, evaluated in order.  A question is placed in the first
# bucket whose keyword it contains as a whole word (see ``matches``).
#
# Hebrew is prefixing, so a keyword may carry one of the common one-letter
# prefixes (``הכלבמש``).  Short keywords that also occur inside unrelated words
# are avoided on purpose: ``קשר`` matches "connection" (``הקשר`` / ``בהקשר``),
# ``מטרה`` matches "goal" (``מטרת``) and ``רשת`` matches ``מורשת``; the
# specific forms below are used instead.
BUCKETS = (
    (
        "medical_first_aid",
        (
            "חייאת לב",
            "cpr",
            "היפותרמיה",
            "הלם",
            "דימום",
            "ח\"ע",
            "תחבושת",
            "שטפי דם",
            "שטף דם",
            "הכשה",
            "הוכש",
            "ארס",
            "ארסי",
            "נמק",
            "פצוע",
            "כוויה",
            "כווייה",
            "טראומה",
            "התייבשות",
            "מכת חום",
            "מכת קור",
        ),
    ),
    (
        "weapons_firearms",
        (
            "נשק",
            "ירי",
            "מעצור",
            "מחסנית",
            "מכלול",
            "תחמושת",
            "m16",
            "הדק",
            "בריח",
            "מטווח",
            "איפוס",
            "קליעה",
            "כדור",
            "נצור",
            "נצירה",
            "טעינת",
            "טעינה",
            "לוע",
            "רתע",
            "אחיזה",
        ),
    ),
    (
        "communications_radio",
        (
            "מ.ק",
            "אנטנה",
            "תדר",
            "תדרים",
            "בקשר",
            "קשר\"ג",
            "נדב\"ר",
            "קופסת פיקוד",
            "מגבר",
            "מווסת",
            "מכשיר",
            "שידור",
            "קליטה",
            "אפיק",
            "אפיקים",
        ),
    ),
)

# One-letter Hebrew prefixes that may be glued to a keyword (ה/כ/ל/ב/מ/ש).
PREFIXES = frozenset("הכלבמש")


def _is_hebrew(char: str) -> bool:
    return "\u05d0" <= char <= "\u05ea"


def matches(text: str, keyword: str) -> bool:
    """True if *keyword* occurs in *text* as a whole word.

    The keyword may carry a one-letter prefix (``הירי`` matches ``ירי``) but
    may not run into a longer word on the right (``נמק`` does **not** match
    ``נמקם``, ``ירי`` does not match ``אסירי``).
    """
    start = 0
    while True:
        index = text.find(keyword, start)
        if index < 0:
            return False
        end = index + len(keyword)
        after = text[end] if end < len(text) else ""
        before = text[index - 1] if index > 0 else ""
        if (not after or not _is_hebrew(after)) and (
            not before or not _is_hebrew(before) or before in PREFIXES
        ):
            return True
        start = index + 1

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


def read_rows(stem: str) -> list[dict]:
    path = os.path.join(CSV_DIR, f"{stem}.csv")
    if not os.path.exists(path):
        sys.exit(f"CSV not found: {path} (run scripts/pdf_to_csv.py first)")
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def bucket_of(question: str) -> str | None:
    for name, keywords in BUCKETS:
        if any(matches(question, keyword) for keyword in keywords):
            return name
    return None


def to_chapter_row(row: dict) -> list[str]:
    options = []
    for index in range(1, 16):
        value = row.get(f"Answer{index}", "").strip()
        if value:
            options.append(value)
    source_type = row.get("Type", "mc").strip()
    correct = row.get("Correct", "").strip()
    answer = row.get("CorrectAnswer", "").strip()

    correct_index = int(correct) if correct.isdigit() else 0
    # If the correct option falls outside the four slots we keep (or the card
    # has no single correct option), fall back to a type-the-answer card so we
    # never show options that don't contain the right answer.
    keep_options = options[:MAX_OPTIONS]
    if source_type == "fill-in":
        kind = "fill-in"
        correct_out = ""
    elif correct_index and correct_index <= len(keep_options):
        kind = "mc"
        correct_out = str(correct_index)
    else:
        kind = "fill-in"
        correct_out = ""

    keep_options += [""] * (MAX_OPTIONS - len(keep_options))
    return [
        row["Question"].strip(),
        *keep_options,
        correct_out,
        answer,
        kind,
    ]


def write_csv(path: str, rows: list[list[str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        writer.writerows(rows)


def normalize(question: str) -> str:
    return " ".join(question.split())


def extract_chapters() -> dict[str, list[list[str]]]:
    quizlet = read_rows(QUIZLET_CSV)
    qa_questions = {normalize(row["Question"]) for row in read_rows(QA_CSV)}

    chapters: dict[str, list[list[str]]] = {name: [] for name, _ in BUCKETS}
    seen: dict[str, set[str]] = {name: set() for name, _ in BUCKETS}
    dropped = 0
    duplicates = 0
    for row in quizlet:
        question = normalize(row["Question"])
        if question in qa_questions:
            continue
        bucket = bucket_of(question)
        if bucket is None:
            dropped += 1
            continue
        # The Quizlet export is shuffled and repeats facts; keep the first copy.
        if question in seen[bucket]:
            duplicates += 1
            continue
        seen[bucket].add(question)
        chapters[bucket].append(to_chapter_row(row))

    for name, rows in chapters.items():
        write_csv(os.path.join(CSV_DIR, f"{name}.csv"), rows)

    combined = [row for name, _ in BUCKETS for row in chapters[name]]
    write_csv(os.path.join(CSV_DIR, f"{COMBINED_STEM}.csv"), combined)

    for name, rows in chapters.items():
        print(f"{name}: {len(rows)} cards")
    print(f"{COMBINED_STEM}: {len(combined)} cards")
    print(f"dropped (unclassified): {dropped}")
    print(f"dropped (duplicate): {duplicates}")
    return chapters


def build_deck(
    model_id: int,
    model_name: str,
    deck_id: int,
    deck_name: str,
    stem: str,
    rows: list[list[str]],
) -> None:
    deck = genanki.Deck(deck_id, deck_name)
    multi = genanki.Deck(deck_id + 100, deck_name + " (בחירה מרובה)")
    model = make_model(model_id, model_name, BASIC_TEMPLATE)
    multi_model = make_model(model_id + 1, model_name + " MultiChoice", BASIC_TEMPLATE)
    fillin_model = make_model(FILLIN_MODEL_ID, FILLIN_MODEL_NAME, FILLIN_TEMPLATE)

    for row in rows:
        question, *rest = row
        options = rest[:MAX_OPTIONS]
        answer = rest[MAX_OPTIONS + 1]
        kind = rest[MAX_OPTIONS + 2]
        if kind == "fill-in":
            note = genanki.Note(
                model=fillin_model,
                fields=[esc(question), esc(answer)],
                tags=["fill-in"],
            )
            deck.add_note(note)
            multi.add_note(note)
        else:
            numbered = "<br>".join(
                f"{i}. {esc(option)}" for i, option in enumerate(options, 1) if option
            )
            deck.add_note(
                genanki.Note(model=model, fields=[esc(question), esc(answer)])
            )
            front = f"{esc(question)}<br><br>{numbered}" if numbered else esc(question)
            multi.add_note(
                genanki.Note(model=multi_model, fields=[front, esc(answer)])
            )

    genanki.Package([deck]).write_to_file(os.path.join(DECK_DIR, f"{stem}.apkg"))
    genanki.Package([multi]).write_to_file(
        os.path.join(DECK_DIR, f"{stem}_multichoice.apkg")
    )
    print(f"built {stem} ({len(rows)} notes)")


def main() -> None:
    os.makedirs(DECK_DIR, exist_ok=True)
    chapters = extract_chapters()

    for bucket, (model_id, model_name, deck_id, deck_name, stem) in MODELS.items():
        build_deck(model_id, model_name, deck_id, deck_name, stem, chapters[bucket])

    combined = [row for name, _ in BUCKETS for row in chapters[name]]
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
