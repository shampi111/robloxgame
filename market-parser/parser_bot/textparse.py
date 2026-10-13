"""Вытаскивание кубков / бравлеров / уровня из текста объявления.

На FunPay продавцы пишут параметры аккаунта прямо в описании («35к кубков, 70 бравлеров»),
поэтому, если сайт не отдал число в отдельном поле, пробуем найти его в тексте.
Это эвристика: она понимает распространённые формы записи, но не всё подряд.

Порядок разбора:
1. «ключ → число» («Кубков: 35к», «Бравлеры - 70», «Уровень короля 14») — самый надёжный вид,
   числа, найденные так, «заняты» и другим ключам не достаются;
2. «число → ключ» («35к кубков», «70 бравлеров») — между числом и словом допускаются только пробелы
   и эмодзи, чтобы в записи «Бравлеров: 70, Кубков: 35000» число 70 не приписалось кубкам.
"""

from __future__ import annotations

import re

# 35000 | 35 000 | 35.000 | 35,5 | 35 ; плюс необязательный множитель тысяч «к», «k», «тыс».
# «к» не должна быть началом слова («35кубков» — это 35, а не 35 000).
_NUM = (
    r"(?P<num>\d{1,3}(?:[  .,]\d{3})+(?!\d)|\d+(?:[.,]\d+)?)"
    r"\s?(?P<k>[кkКK](?![a-zа-яё])|тыс(?:яч[аи]?|\.)?)?"
)
# Диапазон или дробь перед числом: «30-35к», «80/82».
_RANGE_PREFIX = re.compile(r"(\d+(?:[.,]\d+)?)([кkКK])?[-–/]$")
_KV_SEP = r"\s*[-–—:=]?\s*"
# Слова, которые могут стоять между ключевым словом и числом.
_FILLER = r"(?:\s+(?:на\s+аккаунте|на\s+акке|аккаунта|акка|опыта|account|exp|всего|больше|более|около|примерно|от))?"

_KEYWORDS = {
    "trophies": r"(?:кубк|кубок|куб\.|трофе|trophies|trophy|cups?\b|🏆)",
    "brawlers": r"(?:бравлер|бравл\.|бойц|персонаж|brawlers?\b)",
    # Уровень аккаунта (для Brawl Stars) — общие слова.
    "level": r"(?:уровень|уровня|уровне|ур\.|ур\b|лвл|lvl|level|lv\b)",
}
# Для Clash Royale уровень — это уровень короля (King Tower).
_KING = r"(?:уровень\s+короля|ур\.?\s+короля|лвл\s+короля|king\s+tower|king\s+level|король|короля|кинг|кб\b)"

# Уровень рядом с этими словами относится не к аккаунту, а к картам / пропуску / клану.
_LEVEL_STOP = re.compile(r"карт|пасс|pass|клан|clan|бравл\.?\s*пас|сезон", re.IGNORECASE)

_RANGES = {
    "brawl_stars": {"trophies": (1, 300_000), "brawlers": (1, 300), "level": (1, 2_000)},
    "clash_royale": {"trophies": (1, 30_000), "brawlers": (1, 300), "level": (1, 20)},
}


def _to_int(num: str, k: str | None) -> int | None:
    raw = num.replace(" ", " ")
    if k:
        # «35,5к» → 35500; «35к» → 35000
        try:
            value = float(raw.replace(" ", "").replace(",", "."))
        except ValueError:
            return None
        return int(round(value * 1000))
    if re.fullmatch(r"\d{1,3}(?:[ .,]\d{3})+", raw):
        return int(re.sub(r"[ .,]", "", raw))
    try:
        return int(float(raw.replace(",", ".")))
    except ValueError:
        return None


def _level_kw(game: str | None) -> str:
    if game == "clash_royale":
        return _KING + "|" + _KEYWORDS["level"]
    return _KEYWORDS["level"]


def _kv_pattern(kw: str) -> re.Pattern[str]:
    # «Кубков: 35к», «🏆 35000», «lvl 14», «Уровень короля 15», «Кубков на аккаунте 35к»
    return re.compile(r"(?:" + kw + r")[a-zа-яё]*\.?" + _FILLER + _KV_SEP + r"[^\w\s,;|/]{0,2}\s*" + _NUM
                      + r"(?:[-–/](?P<to>\d+(?:[.,]\d+)?)\s?(?P<k2>[кkКK](?![a-zа-яё])|тыс(?:яч[аи]?|\.)?)?)?", re.IGNORECASE)


def _vk_pattern(kw: str) -> re.Pattern[str]:
    # «35к кубков», «35 000 🏆», «70 бравлеров» — между числом и словом только пробел/эмодзи/плюс.
    return re.compile(_NUM + r"\s*\+?\s*[^\w\s,;|./₽$€:]{0,2}\s*(?:" + kw + r")", re.IGNORECASE)


_CLAUSE = re.compile(r"[,;|.(\n]")
_KING_RE = re.compile(_KING, re.IGNORECASE)


def _stop_context(text: str, start: int, end: int, style: str = "vk") -> bool:
    """Уровень записан про карты/пропуск («карты 14 уровня», «70 уровень бравл пасса»)."""
    if _KING_RE.search(text, start, end):
        return False
    before = _CLAUSE.split(text[max(0, start - 12):start])[-1]
    after = _CLAUSE.split(text[end:end + 14])[0] if style == "vk" else ""
    return bool(_LEVEL_STOP.search(before) or _LEVEL_STOP.search(after))


def _value(m: re.Match[str], text: str) -> int | None:
    k = m.group("k")
    gd = m.groupdict()
    if not k and gd.get("k2") and _to_int(m.group("num"), None) is not None and _to_int(gd["to"], None) is not None \
            and _to_int(m.group("num"), None) <= _to_int(gd["to"], None):
        k = gd["k2"]  # «Кубков 30-35к»: множитель второго числа относится и к первому
    value = _to_int(m.group("num"), k)
    # «30-35к кубков» / «80/82 бравлеров» — берём меньшее (первое) число.
    prefix = _RANGE_PREFIX.search(text[: m.start("num")])
    if prefix and value is not None:
        first = _to_int(prefix.group(1), prefix.group(2) or m.group("k"))
        if first is not None and value / 2 <= first < value:
            value = first
    return value


def extract_all(text: str, game: str | None = None) -> dict[str, int | None]:
    """Кубки, бравлеры и уровень из текста. game уточняет смысл уровня (для CR — уровень короля)."""
    result: dict[str, int | None] = {"trophies": None, "brawlers": None, "level": None}
    if not text:
        return result
    ranges = _RANGES.get(game or "brawl_stars", _RANGES["brawl_stars"])
    keywords = {"trophies": _KEYWORDS["trophies"], "brawlers": _KEYWORDS["brawlers"], "level": _level_kw(game)}
    if game == "clash_royale":
        keywords.pop("brawlers")

    # Все правдоподобные совпадения обоих видов: (вид записи, параметр, начало, позиция числа, значение).
    candidates: list[tuple[str, str, int, tuple[int, int], int]] = []
    for kind, kw in keywords.items():
        lo, hi = ranges[kind]
        for style, pattern in (("kv", _kv_pattern(kw)), ("vk", _vk_pattern(kw))):
            for m in pattern.finditer(text):
                if kind == "level" and _stop_context(text, m.start(), m.end(), style):
                    continue
                value = _value(m, text)
                if value is not None and lo <= value <= hi:
                    candidates.append((style, kind, m.start(), m.span("num"), value))
    if not candidates:
        return result

    # Как написан текст: «Кубки 25000 Бравлеры 60» (ключ → число) или «35к кубков 70 бравлеров»
    # (число → ключ). Смотрим, какой вид встречается раньше, и сначала разбираем им.
    first = min(candidates, key=lambda c: c[2])[0]

    def assign(order):
        res = dict(result)
        claimed: list[tuple[int, int]] = []
        for style in order:
            for c_style, kind, _start, span, value in sorted(candidates, key=lambda c: c[2]):
                if c_style != style or res[kind] is not None:
                    continue
                if any(span[0] < ce and cs < span[1] for cs, ce in claimed):
                    continue
                res[kind] = value
                claimed.append(span)
        orphans = sum(1 for c in candidates if c[0] == "vk" and c[3] not in claimed)
        filled = sum(v is not None for v in res.values())
        return (filled, -orphans, order[0] == first), res

    return max(assign(("kv", "vk")), assign(("vk", "kv")), key=lambda x: x[0])[1]


def extract_number(text: str, kind: str, game: str | None = None) -> int | None:
    """Первое правдоподобное число нужного вида из текста или None."""
    return extract_all(text, game).get(kind)
