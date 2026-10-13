"""LolzMarket: поиск аккаунтов через официальный API (категория supercell).

Документация API: https://lzt-market.readme.io (параметры поиска категории Supercell).
В ответе API поля игр называются по внутренним кодам Supercell:
  laser  — Brawl Stars   (supercell_laser_trophies, supercell_laser_level, …)
  scroll — Clash Royale  (supercell_scroll_trophies, supercell_scroll_level, …)
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from typing import Any

from .config import LolzConfig, Rule
from .http import FetchError, RateLimitedClient
from .models import Listing

log = logging.getLogger(__name__)

# Значение для параметра supercell_game[] — аккаунт должен содержать эту игру.
GAME_CODES = {
    "brawl_stars": "brawl-stars",
    "clash_royale": "clash-royale",
}

# Какие поля правила в какие параметры поиска API превращаются (фильтрация на стороне сайта).
RULE_TO_API = {
    "brawl_stars": {
        "trophies_min": "brawl_cup_min",
        "trophies_max": "brawl_cup_max",
        "brawlers_min": "brawlers_min",
        "level_min": "brawl_level_min",
    },
    "clash_royale": {
        "trophies_min": "royale_cup_min",
        "trophies_max": "royale_cup_max",
        "level_min": "king_level_min",
    },
}


def build_params(rule: Rule, page: int = 1) -> dict[str, Any]:
    params: dict[str, Any] = {
        "order_by": "pdate_to_down",  # сначала новые
        "supercell_game[]": [GAME_CODES[rule.game]],
        "currency": "rub",
        "page": page,
    }
    if rule.price_min is not None:
        params["pmin"] = rule.price_min
    if rule.price_max is not None:
        params["pmax"] = rule.price_max
    for rule_field, api_field in RULE_TO_API[rule.game].items():
        value = getattr(rule, rule_field)
        if value is not None:
            params[api_field] = value
    # Свои параметры из config.yaml (lolz_params) перекрывают всё остальное.
    for key, value in rule.lolz_params.items():
        if isinstance(value, (list, tuple)) and not key.endswith("[]"):
            key += "[]"
        params[key] = list(value) if isinstance(value, tuple) else value
    return params


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_item(item: dict[str, Any], game: str, item_url: str) -> Listing | None:
    item_id = item.get("item_id")
    if item_id is None:
        return None
    seller = item.get("seller") or {}
    title = str(item.get("title") or item.get("title_en") or "").strip()
    description = str(item.get("descriptionPlain") or item.get("description") or "").strip()

    if game == "brawl_stars":
        trophies = _int(item.get("supercell_laser_trophies"))
        level = _int(item.get("supercell_laser_level"))
        brawlers = _int(item.get("supercell_brawler_count"))
    else:
        trophies = _int(item.get("supercell_scroll_trophies"))
        level = _int(item.get("supercell_king_level")) or _int(item.get("supercell_scroll_level"))
        brawlers = None

    extra: dict[str, str] = {}
    if game == "brawl_stars":
        legendary = _int(item.get("supercell_legendary_brawler_count"))
        if legendary:
            extra["Легендарных бравлеров"] = str(legendary)
        highest = _int(item.get("supercell_laser_highest_trophies"))
        if highest:
            extra["Макс. кубков"] = f"{highest:,}".replace(",", " ")
    else:
        evolved = _int(item.get("supercell_scroll_evolved_count"))
        if evolved:
            extra["Эволюций"] = str(evolved)
        champions = _int(item.get("supercell_scroll_champion_count"))
        if champions:
            extra["Чемпионов"] = str(champions)
    origin = item.get("itemOriginPhrase") or item.get("item_origin")
    if origin:
        extra["Происхождение"] = str(origin)
    sold = _int(seller.get("sold_items_count"))
    if sold is not None:
        extra["Продаж у продавца"] = str(sold)

    price = _float(item.get("price"))
    currency = str(item.get("price_currency") or "rub").upper()
    # Мы просим цены в рублях (currency=rub), но если API всё же вернул другую валюту,
    # берём нормализованную цену в рублях, чтобы условия price_min/price_max работали одинаково.
    if currency != "RUB" and _float(item.get("rub_price")) is not None:
        price, currency = _float(item.get("rub_price")), "RUB"

    return Listing(
        site="lolz",
        game=game,
        id=str(item_id),
        url=item_url.format(id=item_id),
        title=title,
        description=description,
        price=price,
        currency=currency,
        seller=seller.get("username"),
        trophies=trophies,
        brawlers=brawlers,
        level=level,
        extra=extra,
    )


def parse_response(data: Any, game: str, item_url: str) -> list[Listing]:
    if not isinstance(data, dict):
        raise FetchError("LolzMarket: неожиданный ответ API (не JSON-объект)")
    if data.get("errors"):
        raise FetchError(f"LolzMarket: {'; '.join(map(str, data['errors']))}")
    items = data.get("items")
    if not isinstance(items, list):
        raise FetchError("LolzMarket: в ответе нет списка items")
    listings = []
    for item in items:
        if isinstance(item, dict):
            listing = parse_item(item, game, item_url)
            if listing:
                listings.append(listing)
    return listings


def token_problems(token: str) -> list[str]:
    """Проверка токена без запроса к сайту: токен LolzMarket — это JWT со сроком действия и списком прав."""
    parts = token.split(".")
    if len(parts) != 3:
        return ["lolz.token не похож на токен API (ожидается длинная строка из трёх частей через точку)"]
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except ValueError:
        return ["lolz.token не удалось разобрать — проверьте, что скопировали его целиком"]
    problems = []
    scopes = str(payload.get("scope", "")).split()
    if scopes and "market" not in scopes:
        problems.append("у токена LolzMarket нет права market — создайте токен с правом market")
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and exp:
        days = (exp - time.time()) / 86400
        if days <= 0:
            problems.append("срок действия токена LolzMarket истёк — получите новый")
        elif days < 7:
            problems.append(f"токен LolzMarket истекает через {days:.0f} дн.")
    return problems


class LolzSource:
    def __init__(self, config: LolzConfig, *, proxy: str | None = None):
        self.config = config
        self.http = RateLimitedClient(
            "LolzMarket",
            min_delay=config.request_delay_seconds,
            headers={"Authorization": f"Bearer {config.token}", "Accept": "application/json"},
            proxy=proxy,
        )

    async def close(self) -> None:
        await self.http.close()

    @staticmethod
    def query_hash(rule: Rule) -> str:
        """Короткий хэш запроса: если условия правила поменяли, это новый источник (без лавины старых объявлений)."""
        raw = json.dumps(build_params(rule), sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha1(raw.encode()).hexdigest()[:8]

    async def fetch(self, rule: Rule) -> list[Listing]:
        listings: list[Listing] = []
        for page in range(1, self.config.pages + 1):
            r = await self.http.get(f"{self.config.base_url}/supercell", params=build_params(rule, page))
            try:
                data = r.json()
            except ValueError:
                raise FetchError("LolzMarket: ответ не JSON (возможно, сайт недоступен или изменился адрес API)") from None
            listings.extend(parse_response(data, rule.game, self.config.item_url))
            remaining = ((data.get("system_info") or {}).get("rate_limit") or {}).get("remaining")
            if remaining is not None and remaining <= 2:
                log.warning("LolzMarket: почти исчерпан лимит запросов (осталось %s)", remaining)
            if not data.get("hasNextPage"):
                break
        return listings
