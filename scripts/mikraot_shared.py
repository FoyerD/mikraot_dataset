#!/usr/bin/env python3
"""Shared logic used by the PDF/CSV pipeline and the deck builders.

Two concerns live here so they are not duplicated across scripts:

  * **Categorization** - ``BUCKETS`` / ``bucket_of`` / ``CATEGORIES`` tag a
    Quizlet question as one of the three "missing chapters" (or ``None``).
    Used by ``pdf_to_csv.py`` (to write the ``Category`` column) and by
    ``build_extra_chapters.py`` (which reads that column back).
  * **Answer matching** - ``normalize`` / ``match_options`` / ``classify``
    recover the correct option(s) for a card from its answer text (moved
    verbatim from ``pdf_to_csv.py``).
"""

import re

# --------------------------------------------------------------------------
# Categorization
# --------------------------------------------------------------------------

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
            "התקפי לב",
            "שלב ה",
            "שלב?",
            "לסת",
            "הכרה",
            "פינוי",
            "דם",
            "פגיעת קור",
            "פגיעת אקלים",
            "היפותרמיה",
            "היפו",
            "הלם",
            "דימום",
            "ח\"ע",
            "ח.ע",
            "תחבושת",
            "שטפי דם",
            "שטף דם",
            "הכשה",
            "הוכש",
            "ארס",
            "ארסי",
            "ארסיים",
            "נמק",
            "פצוע",
            "כוויה",
            "כווייה",
            "טראומה",
            "התייבשות",
            "מכת חום",
            "מכת קור",
            "חום",
            "עצבים",
            "חמצן",
            "פיקוח",
            "משולש החיים",
            "משולש לחץ",
            "לחיצה",
            "שט\"ד",
            "שט״ד",
        ),
    ),
    (
        "weapons_firearms",
        (
            "נשק",
            "ירי",
            "מעצור",
            "מחסנית",
            "מחסניות",
            "מכלול",
            "תחמושת",
            "m16",
            "הדק",
            "בריח",
            "מטווח",
            "איפוס",
            "מצב אפס",
            "קליעה",
            "כדור",
            "נצור",
            "נצירה",
            "טעינת",
            "טעינה",
            "לוע",
            "רתע",
            "אחיזה",
            "רוס",
            "שכב חפה",
            "חפה",
            "שכיבה",
            "מצב גוף",
            "עמידה",
            "אוויר בריאות",
            "בריאות",
            "משען",
            "מקבץ",
            "כספית",
            "היורים",
            "סלילים",
            "המכוון",
            "הכרזה",
            "יח״ן",
            "שח\"ף",
            "שח״ף",
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
            "קופסת הפיקוד",
            "מגבר",
            "מווסת",
            "מכשיר",
            "שידור",
            "קליטה",
            "אפיק",
            "אפיקים",
            "אפיקי",
            "תצוגה",
            "כפתור הרחש",
            "שמיעה עצמית",
            "נק\"מ",
            "אבד",
            "פונטי",
            "הק\"ש",
            "הק״ש",
        ),
    ),
)

# The three chapter names, in bucket order.
CATEGORIES = tuple(name for name, _ in BUCKETS)

# One-letter Hebrew prefixes that may be glued to a keyword (ה/כ/ל/ב/מ/ש).
PREFIXES = frozenset("הכלבמש")


def _is_hebrew(char: str) -> bool:
    return "\u05d0" <= char <= "\u05ea"


def matches(text: str, keyword: str) -> bool:
    """True if *keyword* occurs in *text* as a whole word.

    The keyword may carry a one-letter prefix (``הירי`` matches ``ירי``) but
    may not run into a longer word on the right (``נמק`` does **not** match
    ``נמקם``, ``ירי`` does not match ``אסירי``).  Matching is case-insensitive
    so ``m16`` matches ``M16``.
    """
    text = text.lower()
    keyword = keyword.lower()
    # Latin keywords (e.g. ``m16``) are embedded in Hebrew text by the bidi
    # reordering, which often glues them to the next Hebrew word ("M16איזה");
    # the Hebrew word-boundary rules below would wrongly reject them.
    if any("a" <= char <= "z" for char in keyword):
        return keyword in text
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


def bucket_of(question: str) -> str | None:
    """Return the chapter name for *question*, or None if it matches none."""
    for name, keywords in BUCKETS:
        if any(matches(question, keyword) for keyword in keywords):
            return name
    return None


# --------------------------------------------------------------------------
# Answer matching (moved verbatim from pdf_to_csv.py)
# --------------------------------------------------------------------------

BIDI = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")

NOCATEGORY = "none"


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
