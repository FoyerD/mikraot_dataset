#!/usr/bin/env python3
"""Parse the Quizlet PDF export and build Anki decks (.apkg).

Produces two files:
  * ``mikraot_quizlet.apkg``             -> Front = question (options removed).
  * ``mikraot_quizlet_multichoice.apkg`` -> Front = question + numbered options.

Common rules:
  * Skip the first page (cover).
  * Each card -> Basic note (Front, Back = correct answer).
  * Back = right column (the correct answer).
  * Communication-device cards ("מכשיר" / "מ.ק" / "מ״ק") are kept in the main
    deck like every other card.

The PDF was produced by Firefox/Cairo, which stores Hebrew glyphs in visual
(reversed) order.  ``pdftotext -layout`` (Poppler) applies bidi reordering and
returns correct logical Hebrew while keeping the two-column layout, so it is
used instead of a pure-Python PDF reader.
"""

import os
import re
import subprocess
import sys

import genanki

PDF_NAME = "mikrao_quizlet.pdf"
APKG_NAME = "mikraot_quizlet.apkg"
MULTI_APKG_NAME = "mikraot_quizlet_multichoice.apkg"

MODEL_ID = 1607392319
DECK_ID = 2059400110

MULTI_MODEL_ID = 1607392320
MULTI_DECK_ID = 2059400112

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_DIR = os.path.join(BASE_DIR, "pdfs")
DECK_DIR = os.path.join(BASE_DIR, "decks")

# Unicode bidi / direction control characters emitted by pdftotext.
BIDI = re.compile(
    "[\u200e\u200f\u202a-\u202e\u2066-\u2069]"
)
# Column gutter: a run of three or more spaces.  Real gutters are always at
# least three spaces wide, while stray double spaces can appear inside a
# column once the bidi control characters are stripped.
COL_GUTTER = re.compile(r" {3,}")
# Hebrew list marker used by the source, e.g. "א ." / "ב .".
HEB_BULLET = re.compile(r"^[אבגדהוז]\s*\.\s*")
# True/False question marker.
TF_MARKER = re.compile(r"נכון\s*/?\s*לא נכון")

# --- Source quirks that cannot be recovered mechanically -----------------
# The PDF is a shuffled export and repeats some facts twice.  Entries whose
# question contains one of these substrings are an option-less duplicate of
# another card and are dropped.
DROP_QUESTIONS = (
    "שנת הפירוק של ארגון",  # duplicate of 'מתי פורק ארגון ההגנה?'
)
# Options that are missing from a card's option list, keyed by a question
# substring.  They are appended (and become the correct option via matching).
EXTRA_OPTIONS = {
    "פורק ארגון": ["1948"],  # 'מתי פורק ארגון ההגנה?' lists only 1947/1949
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


def split_columns(line: str) -> tuple[str, str]:
    """Split a rendered line into its (left, right) column text.

    The left/right columns are separated by the widest run of spaces on the
    line; the widest run is always the inter-column gutter.
    """
    runs = [(m.start(), m.end()) for m in COL_GUTTER.finditer(line)]
    if not runs:
        return line.strip(), ""
    start, end = max(runs, key=lambda r: r[1] - r[0])
    return line[:start].strip(), line[end:].strip()


def clean_field(text: str) -> str:
    text = BIDI.sub("", text)
    text = " ".join(text.split())
    return text.strip()


def look_like_option(text: str) -> bool:
    """True if a left-column line starts a multiple-choice option."""
    text = text.strip()
    if not text:
        return False
    return "-" in text or bool(HEB_BULLET.match(text))


def strip_bullet(text: str) -> str:
    """Remove a leading Hebrew-letter bullet or a leading/trailing dash."""
    text = HEB_BULLET.sub("", text)
    text = re.sub(r"^[-\s]+", "", text)
    text = re.sub(r"[-\s]+$", "", text)
    return text.strip()


# A short "" kind of token (e.g. "ה80") that is a wrapped tail of the
# option above it rather than an option of its own.
SHORT_SUFFIX = re.compile(r"^[אבגדהוזחטיכלמנסעפצקרשת]{1,2}\d+$")


def group_options(lines: list[str]) -> list[str]:
    """Collapse wrapped option lines into whole options.

    A real option starts on a line carrying a "-" marker; the lines that
    follow it (without a marker) are its wrapped continuation. Marker-less
    lines that appear *before* the first option are statements such as
    "4תשובות נכונות" and are dropped. When no line carries a marker at all
    (some cards list plain values such as "מ-10"), every line is treated as
    one option.
    """
    lines = [line for line in lines if line.strip()]
    if not lines:
        return []
    marks = [look_like_option(line) for line in lines]
    options: list[str] = []
    if any(marks):
        current = None
        for line, marked in zip(lines, marks):
            piece = clean_field(strip_bullet(line))
            if marked:
                if current is not None and SHORT_SUFFIX.match(piece):
                    # Wrapped tail such as "ה80": keep it in the option above.
                    current = f"{current} {piece}".strip()
                else:
                    if current is not None:
                        options.append(current)
                    current = piece
            elif current is not None and piece:
                current = f"{current} {piece}".strip()
        if current is not None:
            options.append(current)
    else:
        options = [clean_field(strip_bullet(line)) for line in lines]

    return [option for option in options if option]


def is_device_card(question: str) -> bool:
    """Card is about a communication device and must be split out for review."""
    if "מכשיר" in question:
        return True
    if re.search(r"מ[.\u05f4]ק", question):  # מ.ק or מ״ק
        return True
    return False


def apply_fixups(entries: list[ENTRY]) -> list[ENTRY]:
    """Drop known duplicate cards and add source-missing options.

    See ``DROP_QUESTIONS`` / ``EXTRA_OPTIONS`` for the quirks handled here.
    """
    fixed: list[ENTRY] = []
    for question, options, answer in entries:
        if any(bad in question for bad in DROP_QUESTIONS):
            continue
        for key, extra in EXTRA_OPTIONS.items():
            if key in question:
                options = options + [o for o in extra if o not in options]
        fixed.append((question, options, answer))
    return fixed


def parse_entries(text: str) -> list[ENTRY]:
    pages = text.split("\f")
    entries: list[ENTRY] = []
    for page in pages[1:]:  # skip the cover page
        if not page.strip():
            continue
        blocks: list[list[str]] = []
        current: list[str] = []
        for line in page.split("\n"):
            if line.strip() == "":
                if current:
                    blocks.append(current)
                    current = []
            else:
                current.append(line)
        if current:
            blocks.append(current)

        for block in blocks:
            lefts: list[str] = []
            rights: list[str] = []
            for line in block:
                left, right = split_columns(BIDI.sub("", line))
                if left:
                    lefts.append(left)
                if right:
                    rights.append(right)

            if not lefts:
                continue

            # True/False cards: a "נכון /לא נכון" label precedes the
            # statement (often joined by a dash that is not an option marker).
            tf_idx = next(
                (i for i, single in enumerate(lefts) if TF_MARKER.search(single)),
                None,
            )
            if tf_idx is not None:
                marker = TF_MARKER.search(lefts[tf_idx])
                head = strip_bullet(lefts[tf_idx][marker.end():])
                statement = clean_field(
                    " ".join(([head] if head else []) + lefts[tf_idx + 1:])
                )
                answer = clean_field(" ".join(rights))
                if statement and answer:
                    entries.append((statement, ["נכון", "לא נכון"], answer))
                continue

            # Question ends at the line carrying "?" (a question) or ":" (a
            # statement) or, failing both, at the first option line.
            end = None
            for marker in ("?", ":"):
                for i, single in enumerate(lefts):
                    if marker in single:
                        end = i
                        break
                if end is not None:
                    break
            if end is None:
                for i, single in enumerate(lefts):
                    if look_like_option(single):
                        end = i - 1
                        break
            if end is None:
                end = len(lefts) - 1

            question = clean_field(" ".join(lefts[: end + 1]))
            answer = clean_field(" ".join(rights))

            # RTL bidi leaves the terminal "?"/":" at the start of its line;
            # move it back to the end.
            if "?" in question:
                if not question.endswith("?"):
                    question = question.replace("?", "") + "?"
            elif ":" in question and not question.endswith(":"):
                question = question.replace(":", "") + ":"

            options = group_options(lefts[end + 1:])

            if not question or not answer:
                continue
            entries.append((question, options, answer))
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
    total = len(entries)

    build_package(
        entries, os.path.join(DECK_DIR, APKG_NAME),
        MODEL_ID, "Basic (Mikraot)",
        DECK_ID, "מקראות קוויזלט",
        multi=False,
    )
    build_package(
        entries, os.path.join(DECK_DIR, MULTI_APKG_NAME),
        MULTI_MODEL_ID, "Basic (Mikraot) MultiChoice",
        MULTI_DECK_ID, "מקראות קוויזלט (בחירה מרובה)",
        multi=True,
    )

    with_options = sum(1 for e in entries if e[1])
    print(f"Cards parsed (pre-filter): {total}")
    print(f"Main deck 'מקראות קוויזלט' : {len(entries)}  (with options: {with_options})")
    print(f"Normal deck     -> {os.path.join(DECK_DIR, APKG_NAME)}")
    print(f"MultiChoice deck-> {os.path.join(DECK_DIR, MULTI_APKG_NAME)}")
    print("\nSample multi-choice front:")
    for entry in entries[:3]:
        print(f"  MODE(multi):\n    {make_front(entry, True)}")


if __name__ == "__main__":
    main()
