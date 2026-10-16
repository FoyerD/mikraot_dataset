# AGENTS.md

Tooling that turns two Hebrew study PDFs into Anki decks. The canonical flow
is **PDF -> CSV -> Anki**; the two `parse_*.py` scripts hold the PDF parsing
logic and can also build decks directly.

Beyond the two main sources, `scripts/build_extra_chapters.py` carves three
supplemental "missing chapters" (first aid, weapons, communications) out of the
Quizlet CSV - the technical-training content that the Q&A source lacks.

## Directory layout

```
pdfs/    source PDFs (mikrao_quizlet.pdf, mikraot_qa_tvi.pdf)
scripts/ parsers and builders
csv/     generated CSVs (intermediate, wide format)
decks/   generated .apkg packages
```

## Commands

```sh
python3 scripts/pdf_to_csv.py    # pdf  -> csv/   (both PDFs)
python3 scripts/csv_to_anki.py   # csv  -> decks/ (all four decks)
```

Regenerate the decks end-to-end by running both in that order. The legacy
direct paths `python3 scripts/parse_quizlet.py` and
`python3 scripts/parse_mikraot_qa.py` still write their decks from the PDF
without the CSV step (no `fill-in` handling there).

The three supplemental chapters are built separately, on top of the Quizlet CSV
(so run `pdf_to_csv.py` first):

```sh
python3 scripts/build_extra_chapters.py   # quizlet csv -> 3 chapter csv/ + extra decks
```

Requires `poppler-utils` (`pdftotext`) and the `genanki` Python package.

## CSV format (`csv/`)

Wide layout, one file per source, `utf-8-sig` (BOM) so Excel renders Hebrew:

```
Question, Answer1..AnswerN, Correct, CorrectAnswer, Type
```

* `Answer1..AnswerN` - the options; `N` is the max number of options in that
  source (quizlet: 15, QA: 4). Unused cells are empty.
* `Correct` - 1-based index of the single correct option, or blank for
  `fill-in` cards.
* `CorrectAnswer` - the canonical answer text. For a `fill-in` card it is the
  correct options joined by `", "` **in the order they appear** (falling back
  to the raw answer text when nothing could be matched).
* `Type` - `mc` (single correct answer) or `fill-in` (see below).

## Parsing rules (Quizlet PDF)

* Each card has a left column (question + options) and a right column (the
  correct answer). `pdftotext -layout` is used because it applies bidi
  reordering and returns logical Hebrew. Do **not** use `-bbox` (it reverses
  the Hebrew).
* An option **starts on a line that contains a `-` marker**; the following
  marker-less lines are its wrapped continuation and are appended to it.
* Marker-less lines that appear **before the first option are statements**
  (e.g. `4תשובות נכונות`, `תשובות (`) and are **not** options - they are
  dropped.
* A short suffix token such as `ה80` / `ה70` (regex
  `^[אבגדהוזחטיכלמסעפצקרשת]{1,2}\d+$`) that carries a marker is a wrapped
  tail of the option above it, not a new option.
* True/False cards are detected by the `נכון /לא נכון` marker that precedes
  the statement; they get the options `נכון` / `לא נכון`.
* Some answers are scrambled by bidi (numbers/quotes), so a card may end up
  with no option matching its answer; such cards become `fill-in`.
* The export is shuffled and repeats some facts. `parse_quizlet.apply_fixups`
  handles the un-recoverable quirks (see the module constants):
  * `DROP_QUESTIONS` - question substrings whose card is an option-less
    duplicate of another card and is dropped (e.g. `שנת הפירוק של ארגון` vs
    `מתי פורק ארגון ההגנה?`).
  * `EXTRA_OPTIONS` - options missing from a card's list, keyed by a question
    substring (e.g. `1948` added to `מתי פורק ארגון ההגנה?`, which only listed
    `1947` / `1949`). The added option becomes the correct one via matching.

## Parsing rules (Q&A PDF)

* Three-column table; each card starts with the repeated header row
  `answer ... type` and lists four options, exactly one marked `true`.
* Wrapped option lines are grouped by their nearest `true`/`false` anchor
  (by line index), then the `true` option is the answer.

## `fill-in` convention

A card is `fill-in` when it is **multi-correct** (several options match the
answer), **open** (no options) or **unresolved** (the answer could not be
matched to any option). In the decks it becomes a **type-in-the-answer** card
(`{{type:Back}}`) rendered the same way in both the normal and multichoice
decks:

* Front = question
* Back = `CorrectAnswer` (the correct answers joined by `", "`)

`fill-in` notes carry the Anki tag `fill-in`.

## Extra chapters (first aid / weapons / communications)

`scripts/build_extra_chapters.py` derives three supplemental chapters from the
Quizlet CSV - the technical-training content the Q&A source does not cover. It
takes every Quizlet question whose text is **not** present in
`csv/mikraot_qa.csv` and buckets it by keyword into:

* `medical_first_aid` - first aid / trauma (CPR, shock, wounds, bites).
* `weapons_firearms` - weapons, stoppages, shooting procedure.
* `communications_radio` - radio sets (`מ.ק`), antennas, frequencies.

Each bucket is written as a wide CSV (`csv/medical_first_aid.csv`, etc.) using
the same layout as the Q&A CSV (four answer slots, `utf-8-sig`), plus a combined
`csv/mikraot_extra_chapters.csv` holding all three. Questions matching no bucket
keyword are dropped and the count is printed. The script then builds a normal
and a multichoice `.apkg` per bucket, and for the combined set.

Extraction rules:

* Keywords are matched as **whole words**, allowing a one-letter prefix
  (`הירי` matches `ירי`) but never a longer word (`ירי` does not match
  `אסירי`, `נמק` does not match `נמקם`). Short ambiguous keywords (`מטרה`,
  `רשת`, `קשר`) are avoided in favour of specific forms (`מטווח`, `בקשר`).
* Exact-duplicate questions (the Quizlet export is shuffled and repeats facts)
  are dropped, keeping the first copy.
* A card whose correct option falls outside the four slots we keep - e.g. a
  quizlet card with six options where the answer is option 5 - is emitted as a
  `fill-in` card instead, so the deck never shows options that omit the answer.

## Decks

| CSV                  | .apkg                             | deck name                         | model                          |
| -------------------- | --------------------------------- | --------------------------------- | ------------------------------ |
| mikraot_quizlet      | mikraot_quizlet.apkg              | מקראות קוויזלט                     | Basic (Mikraot) 1607392319     |
| mikraot_quizlet      | mikraot_quizlet_multichoice.apkg  | מקראות קוויזלט (בחירה מרובה)      | Basic (Mikraot) MultiChoice 1607392320 |
| mikraot_qa           | mikraot_qa.apkg                   | מקראות                            | Basic (Mikraot Q&A) 1607392321 |
| mikraot_qa           | mikraot_qa_multichoice.apkg       | מקראות (בחירה מרובה)             | Basic (Mikraot Q&A) MultiChoice 1607392322 |
| medical_first_aid    | medical_first_aid.apkg            | מקראות - עזרה ראשונה               | Basic (Mikraot Extra) 1607392400 |
| medical_first_aid    | medical_first_aid_multichoice.apkg| מקראות - עזרה ראשונה (בחירה מרובה)| Basic (Mikraot Extra) MultiChoice 1607392401 |
| weapons_firearms     | weapons_firearms.apkg             | מקראות - נשק וירי                  | Basic (Mikraot Extra) 1607392402 |
| weapons_firearms     | weapons_firearms_multichoice.apkg | מקראות - נשק וירי (בחירה מרובה)   | Basic (Mikraot Extra) MultiChoice 1607392403 |
| communications_radio  | communications_radio.apkg         | מקראות - קשר ותקשורת              | Basic (Mikraot Extra) 1607392404 |
| communications_radio  | communications_radio_multichoice.apkg | מקראות - קשר ותקשורת (בחירה מרובה)| Basic (Mikraot Extra) MultiChoice 1607392405 |
| mikraot_extra_chapters | mikraot_extra_chapters.apkg     | מקראות - נושפים משלימים           | Basic (Mikraot Extra Combined) 1607392410 |
| mikraot_extra_chapters | mikraot_extra_chapters_multichoice.apkg | מקראות - נושפים משלימים (בחירה מרובה) | Basic (Mikraot Extra Combined) MultiChoice 1607392411 |

Deck ids: quizlet 2059400110 / 2059400112, QA 2059400114 / 2059400115. Extra
chapters are `2059400200-2059400202` (normal) and `2059400300-2059400302`
(multichoice); the combined extra deck is `2059400310` / `2059400410`. The
shared `fill-in` model is `Fill-in (Mikraot)` id `1607392330`.

The three `medical_first_aid` / `weapons_firearms` / `communications_radio`
models all share the name `Basic (Mikraot Extra)` but have distinct ids
(`1607392400`/`1607392402`/`1607392404` normal, `+1` for multichoice); the
combined deck uses `Basic (Mikraot Extra Combined)` `1607392410`/`1607392411`.
Rebuild the extra decks with `python3 scripts/build_extra_chapters.py`.

* **Normal deck**: Front = question, Back = answer.
* **MultiChoice deck**: Front = question + numbered options, Back = answer
  (except `fill-in` cards, which stay type-in-the-answer).

genanki also adds an empty `Default` deck to every package; it is harmless.
