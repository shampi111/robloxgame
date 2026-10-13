"""Вытаскивание кубков / бравлеров / уровня из текста объявления.

На FunPay продавцы пишут параметры аккаунта прямо в описании («35к кубков, 70 бравлеров»),
поэтому, если сайт не отдал число в отдельном поле, пробуем найти его в тексте.
Это эвристика: она понимает распространённые формы записи, но не всё подряд.
"""

from __future__ import annotations

import re

# 35000 | 35 000 | 35.000 | 35,5 | 35 ; плюс необязательный суффикс тысяч «к»/«k».
# «к» не должна быть началом слова («35кубков» — это 35, а не 35 000).
_NUM = r"(?P<num>\d{1,3}(?:[ \u00a0.,]\d{3})+(?!\d)|\d+(?:[.,]\d+)?)\s?(?P<k>[кkКK](?![a-zа-яё]))?"
_SEP = r"\s*[-–—:=]?\s*"
# Слово-уточнение между ключевым словом и числом: «уровень короля 15», «king level 14».
_QUALIFIER = r"(?:\s+(?:короля|аккаунта|акка|опыта|king|account|exp))?"

_KEYWORDS = {
    "trophies": r"(?:кубк|кубок|куб\.|трофе|trophies|trophy|cups?\b|🏆)",
    "brawlers": r"(?:бравлер|бравл\.|бойц|персонаж|brawlers?\b)",
    "level": r"(?:уровень|уровня|уровне|ур\.|ур\b|лвл|lvl|level|lv\b)",
}

_RANGES = {
    "trophies": (1, 300_000),
    "brawlers": (1, 300),
    "level": (1, 10_000),
}


def _to_int(num: str, k: str | None) -> int | None:
    raw = num.replace("\u00a0", " ")
    if k:
        # «35,5к» → 35500; «35к» → 35000
        value = float(raw.replace(" ", "").replace(",", "."))
        return int(round(value * 1000))
    if re.fullmatch(r"\d{1,3}(?:[ .,]\d{3})+", raw):
        return int(re.sub(r"[ .,]", "", raw))
    try:
        return int(float(raw.replace(",", ".")))
    except ValueError:
        return None


def _patterns(kind: str) -> list[re.Pattern[str]]:
    kw = _KEYWORDS[kind]
    return [
        # «35к кубков», «35 000 🏆», «70 бравлеров»
        re.compile(_NUM + _SEP + r"[^\w\s]{0,2}\s*" + kw, re.IGNORECASE),
        # «Кубков: 35к», «🏆 35000», «lvl 14», «Уровень короля 15»
        re.compile(kw + r"[a-zа-яё]*\.?" + _QUALIFIER + _SEP + r"[^\w\s]{0,2}\s*" + _NUM, re.IGNORECASE),
    ]


_COMPILED = {kind: _patterns(kind) for kind in _KEYWORDS}


def extract_number(text: str, kind: str) -> int | None:
    """Первое правдоподобное число нужного вида из текста или None."""
    if not text:
        return None
    lo, hi = _RANGES[kind]
    best: tuple[int, int] | None = None  # (позиция в тексте, значение)
    for pattern in _COMPILED[kind]:
        for m in pattern.finditer(text):
            value = _to_int(m.group("num"), m.group("k"))
            if value is None or not lo <= value <= hi:
                continue
            if best is None or m.start() < best[0]:
                best = (m.start(), value)
            break
    return best[1] if best else None


def extract_all(text: str) -> dict[str, int | None]:
    return {kind: extract_number(text, kind) for kind in _KEYWORDS}
