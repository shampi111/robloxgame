"""Проверка объявления на соответствие правилу из config.yaml."""

from __future__ import annotations

import re
from functools import lru_cache

from .config import Rule
from .models import Listing


def _norm(text: str) -> str:
    return text.lower().replace("ё", "е")


@lru_cache(maxsize=512)
def _word_pattern(word: str) -> re.Pattern[str]:
    # Слово ищется с начала слова: «аренд» найдёт «аренда», «аренду», «аренды»,
    # а «rent» не найдётся внутри «different» или «current».
    return re.compile(r"(?<!\w)" + re.escape(_norm(word).strip()))


def _has(text: str, word: str) -> bool:
    return bool(word.strip()) and _word_pattern(word).search(text) is not None


def _check_min(value: float | None, minimum: float | None, allow_unknown: bool) -> bool:
    if minimum is None:
        return True
    if value is None:
        return allow_unknown
    return value >= minimum


def _check_max(value: float | None, maximum: float | None, allow_unknown: bool) -> bool:
    if maximum is None:
        return True
    if value is None:
        return allow_unknown
    return value <= maximum


def rule_applies(rule: Rule, listing: Listing) -> bool:
    return listing.game == rule.game and listing.site in rule.sites


def search_text(listing: Listing) -> str:
    """Текст, в котором ищутся слова из include_*/exclude: название, описание и значения параметров."""
    return _norm(" ".join([listing.title, listing.description, *listing.extra.values()]))


def matches(rule: Rule, listing: Listing) -> bool:
    if not rule_applies(rule, listing):
        return False

    # Цены правил — в рублях. LolzMarket уже отфильтровал по цене на своей стороне (мы просим цены
    # в рублях), поэтому там непонятная валюта или пустая цена не повод отбрасывать объявление.
    # На FunPay цену в другой валюте сравнить с рублёвыми условиями нельзя — такое объявление не подходит.
    if listing.site == "lolz" and (listing.price is None or listing.currency != "RUB"):
        price_ok = True
    elif rule.price_min is None and rule.price_max is None:
        price_ok = True
    else:
        price = listing.price if listing.currency == "RUB" else None
        price_ok = _check_min(price, rule.price_min, False) and _check_max(price, rule.price_max, False)
    if not price_ok:
        return False

    # LolzMarket уже отфильтровал по кубкам/бравлерам/уровню на своей стороне (параметры запроса),
    # поэтому пустое поле в ответе не повод выбрасывать объявление.
    unknown = rule.allow_unknown or listing.site == "lolz"
    if not _check_min(listing.trophies, rule.trophies_min, unknown):
        return False
    if not _check_max(listing.trophies, rule.trophies_max, unknown):
        return False
    if not _check_min(listing.brawlers, rule.brawlers_min, unknown):
        return False
    if not _check_min(listing.level, rule.level_min, unknown):
        return False

    text = search_text(listing)
    if any(not _has(text, w) for w in rule.include_all):
        return False
    if rule.include_any and not any(_has(text, w) for w in rule.include_any):
        return False
    if any(_has(text, w) for w in rule.exclude):
        return False

    if listing.site == "funpay":
        if rule.online_only and listing.seller_online is not True:
            return False
        if not _check_min(listing.seller_reviews, rule.min_reviews, False):
            return False
        if not _check_min(listing.seller_rating, rule.min_rating, False):
            return False

    return True
