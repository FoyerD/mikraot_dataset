#!/usr/bin/env python3
"""Parse the "mikraot_qa_tvi" structured Q&A PDF into Anki decks (.apkg).

Produces two files (in the ``decks/`` directory):
  * ``mikraot_qa.apkg``             -> Front = question (options removed).
  * ``mikraot_qa_multichoice.apkg`` -> Front = question + numbered options.

Common rules:
  * No cover page; every page is content.
  * The PDF is a three-column table: ``question`` | ``answer`` | ``type``.
  * Each card starts with a repeated header row ``answer ... type`` and is
    followed by four answer options, one of which is marked ``true``.
  * Back = the option marked ``true``.
  * There is no device filter here, so each package holds a single deck.

Unlike the Quizlet export, this PDF (Chrome/Skia) renders each option as a
table row that may wrap over several visual lines, and the ``true``/``false``
type label is vertically centred on the row, so it can land on its own line.
A plain line-by-line parse would misgroup those options.  Instead every
answer line is attached to its *nearest* ``true``/``false`` anchor (by line
index, which is monotonic in the vertical position), which reconstructs the
wrapped options correctly.

``pdftotext -layout`` (Poppler) is used because it applies bidi reordering and
returns correct logical Hebrew while preserving the table layout.
"""

import os
import re
import subprocess
import sys

import genanki

PDF_NAME = "mikraot_qa_tvi.pdf"
APKG_NAME = "mikraot_qa.apkg"
MULTI_APKG_NAME = "mikraot_qa_multichoice.apkg"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_DIR = os.path.join(BASE_DIR, "pdfs")
DECK_DIR = os.path.join(BASE_DIR, "decks")

MODEL_ID = 1607392321
DECK_ID = 2059400114

MULTI_MODEL_ID = 1607392322
MULTI_DECK_ID = 2059400115

# Unicode bidi / direction control characters emitted by pdftotext.
BIDI = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
# Card delimiter: the repeated table header row ("answer ... type").
CARD_HEADER = re.compile(r"^\s*answer\s+type\s*$")

# --- Source quirks that cannot be recovered mechanically -----------------
# Option/answer replacements, keyed by a question substring: an exact option
# value (and the answer when it equals that value) is swapped for another.
# The PDF marks ``11`` as the number of Basic Laws; there are 14.
REPLACE_OPTIONS = {
    "כמה חוקי יסוד": [("11", "14")],
}

ENTRY = tuple[str, list[str], str]  # (question, options, answer)


def find_pdf() -> str:
    path = os.path.join(PDF_DIR, PDF_NAME)
    if not os.path.exists(path):
        sys.exit(f"PDF not found: {path}")
    return path


def extract_layout_text(pdf_path: str) -> str:
    """Return the pdftotext -layout text of the whole document."""
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", pdf_path, "-"],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        sys.exit("pdftotext is not installed (package: poppler-utils).")
    return result.stdout


def split_type(rest: str) -> tuple[str, str | None]:
    """Peel a trailing ``true``/``false`` type label off a line's right column.

    Returns ``(answer_text, type_or_None)``.  The type may sit on its own line
    (``rest == "true"``), in which case the answer text is empty.
    """
    parts = rest.rsplit(None, 1)
    if parts and parts[-1] in ("true", "false"):
        return (parts[0] if len(parts) > 1 else ""), parts[-1]
    return rest, None


def clean_field(text: str) -> str:
    text = BIDI.sub("", text)
    text = " ".join(text.split())
    return text.strip()


def attach_options(card: dict) -> list[tuple[str, str]]:
    """Group answer lines into options using the nearest type anchor.

    ``card['anchors']`` is a list of ``(line_index, "true"|"false")`` and
    ``card['units']`` is a list of ``(line_index, answer_text)``.  Every unit
    is assigned to the anchor with the smallest ``|Δ line_index|``; the units
    of an anchor are concatenated in order.  Returns ``[(text, type), ...]``.
    """
    anchors = card["anchors"]
    if not anchors:
        return []
    groups: dict[int, list[tuple[int, str]]] = {}
    for unit_index, unit_text in card["units"]:
        best = min(
            range(len(anchors)),
            key=lambda ai: (abs(anchors[ai][0] - unit_index), anchors[ai][0]),
        )
        groups.setdefault(best, []).append((unit_index, unit_text))
    options = []
    for ai, (_, anchor_type) in enumerate(anchors):
        units = sorted(groups.get(ai, []))
        options.append((" ".join(text for _, text in units).strip(), anchor_type))
    return options


def apply_fixups(entries: list[ENTRY]) -> list[ENTRY]:
    """Apply the source-level corrections in ``REPLACE_OPTIONS``."""
    fixed: list[ENTRY] = []
    for question, options, answer in entries:
        for key, replacements in REPLACE_OPTIONS.items():
            if key not in question:
                continue
            mapping = dict(replacements)
            options = [mapping.get(option, option) for option in options]
            answer = mapping.get(answer, answer)
        fixed.append((question, options, answer))
    return fixed


def parse_entries(text: str) -> list[ENTRY]:
    pages = text.split("\f")
    cards: list[dict] = []
    for page in pages:
        if not page.strip():
            continue
        card: dict | None = None
        ans_start = 0
        for line_index, line in enumerate(page.split("\n")):
            stripped = BIDI.sub("", line)
            if not stripped.strip():
                continue
            if CARD_HEADER.match(stripped):
                if card is not None:
                    cards.append(card)
                ans_start = stripped.index("answer")
                card = {"q": [], "anchors": [], "units": []}
                continue
            if card is None:
                continue
            left = stripped[:ans_start].strip()
            rest = stripped[ans_start:].strip()
            if left:
                card["q"].append(left)
            answer_text, answer_type = split_type(rest)
            if answer_type:
                card["anchors"].append((line_index, answer_type))
            answer_text = answer_text.strip()
            if answer_text:
                card["units"].append((line_index, answer_text))
        if card is not None:
            cards.append(card)

    entries: list[ENTRY] = []
    for card in cards:
        options = attach_options(card)
        if not options:
            continue
        question = clean_field(" ".join(card["q"]))
        answer = clean_field(
            " ".join(text for text, kind in options if kind == "true")
        )

        # RTL bidi leaves the terminal "?"/":" at the start of its line;
        # move it back to the end.
        if "?" in question:
            if not question.endswith("?"):
                question = question.replace("?", "") + "?"
        elif ":" in question and not question.endswith(":"):
            question = question.replace(":", "") + ":"

        option_texts = [clean_field(text) for text, _ in options]
        if not question or not answer:
            continue
        entries.append((question, option_texts, answer))
    return apply_fixups(entries)


def esc(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def make_front(entry: ENTRY, multi: bool) -> str:
    question, options, _ = entry
    if multi and options:
        numbered = "<br>".join(
            f"{i}. {esc(option)}" for i, option in enumerate(options, 1)
        )
        return f"{esc(question)}<br><br>{numbered}"
    return esc(question)


def build_package(
    entries: list[ENTRY],
    apkg_path: str,
    model_id: int,
    model_name: str,
    deck_id: int,
    deck_name: str,
    multi: bool,
) -> None:
    model = genanki.Model(
        model_id,
        model_name,
        fields=[{"name": "Front"}, {"name": "Back"}],
        templates=[
            {
                "name": "Card 1",
                "qfmt": "{{Front}}",
                "afmt": "{{FrontSide}}<hr id=answer>{{Back}}",
            }
        ],
    )
    deck = genanki.Deck(deck_id, deck_name)
    for entry in entries:
        deck.add_note(
            genanki.Note(model=model, fields=[make_front(entry, multi), esc(entry[2])])
        )
    genanki.Package([deck]).write_to_file(apkg_path)


def main() -> None:
    pdf_path = find_pdf()
    text = extract_layout_text(pdf_path)
    entries = parse_entries(text)

    build_package(
        entries, os.path.join(DECK_DIR, APKG_NAME),
        MODEL_ID, "Basic (Mikraot Q&A)",
        DECK_ID, "מקראות",
        multi=False,
    )
    build_package(
        entries, os.path.join(DECK_DIR, MULTI_APKG_NAME),
        MULTI_MODEL_ID, "Basic (Mikraot Q&A) MultiChoice",
        MULTI_DECK_ID, "מקראות (בחירה מרובה)",
        multi=True,
    )

    with_options = sum(1 for e in entries if e[1])
    print(f"Cards parsed            : {len(entries)}")
    print(f"Cards with options      : {with_options}")
    print(f"Normal deck     -> {os.path.join(DECK_DIR, APKG_NAME)}")
    print(f"MultiChoice deck-> {os.path.join(DECK_DIR, MULTI_APKG_NAME)}")
    print("\nSample multi-choice front:")
    for entry in entries[:3]:
        print(f"  MODE(multi):\n    {make_front(entry, True)}")


if __name__ == "__main__":
    main()
