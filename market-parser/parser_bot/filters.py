"""Проверка объявления на соответствие правилу из config.yaml."""

from __future__ import annotations

from .config import Rule
from .models import Listing


def _norm(text: str) -> str:
    return text.lower().replace("ё", "е")


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


def matches(rule: Rule, listing: Listing) -> bool:
    if not rule_applies(rule, listing):
        return False

    # Цена неизвестна — такое объявление по цене никогда не пропускаем.
    if not _check_min(listing.price, rule.price_min, False) or not _check_max(listing.price, rule.price_max, False):
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

    text = _norm(" ".join([listing.title, listing.description, *(f"{k} {v}" for k, v in listing.extra.items())]))
    if any(_norm(w) not in text for w in rule.include_all):
        return False
    if rule.include_any and not any(_norm(w) in text for w in rule.include_any):
        return False
    if any(_norm(w) in text for w in rule.exclude):
        return False

    if listing.site == "funpay":
        if rule.online_only and listing.seller_online is not True:
            return False
        if not _check_min(listing.seller_reviews, rule.min_reviews, False):
            return False
        if not _check_min(listing.seller_rating, rule.min_rating, False):
            return False

    return True
