"""Arabic text helpers: fold spelling variants so 'اسطنبول' finds 'إسطنبول'."""
from __future__ import annotations

import re

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_DIACRITICS = re.compile(r"[ً-ْٰـ]")   # harakat, dagger alef, tatweel
_ARABIC = re.compile(r"[؀-ۿ]")


def to_western_digits(text: str) -> str:
    return text.translate(_DIGITS)


def fold(text: str) -> str:
    """Lower-case, strip diacritics and unify the letters people swap when typing fast.

    Only for matching. Never shown to a user, never sent to the model.
    """
    t = _DIACRITICS.sub("", to_western_digits(str(text))).lower().strip()
    t = re.sub("[أإآٱ]", "ا", t)
    t = t.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    return re.sub(r"\s+", " ", t)


def is_arabic(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    return bool(letters) and sum(bool(_ARABIC.match(ch)) for ch in letters) / len(letters) > 0.3
