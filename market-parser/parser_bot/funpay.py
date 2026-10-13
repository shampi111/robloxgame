"""FunPay: разбор публичной страницы подкатегории https://funpay.com/lots/<id>/.

Официального API у FunPay нет, поэтому разбираем HTML. Вся подкатегория отдаётся одной
страницей (без пагинации), каждое объявление — это ссылка <a class="tc-item"> вида:

  <a href="https://funpay.com/lots/offer?id=123" class="tc-item" data-online="1" data-auto="1" data-user="54321" ...>
    <div class="tc-desc"><div class="tc-desc-text">Описание</div></div>
    <div class="tc-user"> ... <div class="media-user-name">Ник</div>
         <div class="media-user-reviews"><div class="rating-stars rating-5">…</div><span class="rating-mini-count">105</span></div>
    </div>
    <div class="tc-price" data-s="3499.79"><div>3500 <span class="unit">₽</span></div></div>
  </a>

Дополнительные параметры лота (кубки, бравлеры, сервер и т.п.) лежат в атрибутах data-<имя>
у тега <a>, их значения для показа — в <div class="tc-<имя>">, а названия параметров — в шапке
таблицы (.tc-header) и в форме фильтров страницы (.showcase-filters). Точные имена атрибутов
для Brawl Stars / Clash Royale публично нигде не описаны, поэтому парсер сопоставляет их по
названиям («Кубки», «Бравлеры», «Уровень»), а если не вышло — ищет числа в тексте объявления.
Посмотреть, что реально отдаёт страница: python main.py --inspect-funpay
"""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .config import FunPayConfig
from .http import FetchError, RateLimitedClient
from .models import Listing
from .textparse import extract_all

log = logging.getLogger(__name__)

BASE_URL = "https://funpay.com"
CURRENCY_BY_SIGN = {"₽": "RUB", "$": "USD", "€": "EUR"}
# Служебные data-атрибуты строки, которые не показываем как параметры аккаунта.
SERVICE_ATTRS = {"online", "auto", "user", "offer", "href"}
# По каким словам в названии параметра (или имени атрибута) понимать, что это кубки/бравлеры/уровень.
PARAM_KEYWORDS = {
    "trophies": ("кубк", "трофе", "trophies", "trophy", "cup"),
    "brawlers": ("бравлер", "бойц", "brawler"),
    "level": ("уровень", "level", "lvl"),
}


# Как игры называются на главной странице FunPay (для автопоиска id категории).
GAME_TITLES = {
    "brawl_stars": ("brawl stars",),
    "clash_royale": ("clash royale",),
}
ACCOUNTS_TITLES = ("аккаунты", "accounts")


def category_url(category_id: int) -> str:
    return f"{BASE_URL}/lots/{category_id}/"


def find_accounts_category(html: str, game: str) -> int | None:
    """Найти id подкатегории «Аккаунты» игры на главной странице funpay.com.

    Блок игры на главной выглядит так:
      <div class="promo-game-item">
        <div class="game-title" data-id="344"><a href="https://funpay.com/lots/1407/">Название игры</a></div>
        <ul class="list-inline" data-id="344"><li><a href="https://funpay.com/lots/1407/">Аккаунты</a></li>…</ul>
      </div>
    """
    soup = BeautifulSoup(html, "lxml")
    names = GAME_TITLES[game]
    for block in soup.select("div.promo-game-item"):
        for title in block.select("div.game-title"):
            if _text(title).lower() not in names:
                continue
            ul = block.select_one(f'ul.list-inline[data-id="{title.get("data-id")}"]') or block
            for a in ul.select("a[href]"):
                if _text(a).lower() in ACCOUNTS_TITLES:
                    m = re.search(r"/lots/(\d+)", str(a["href"]))
                    if m:
                        return int(m.group(1))
    return None


def _text(tag: Tag | None) -> str:
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""


def _offer_id(a: Tag) -> str | None:
    if a.get("data-offer"):
        return str(a["data-offer"])
    href = str(a.get("href") or "")
    ids = parse_qs(urlparse(href).query).get("id")
    if ids:
        return ids[0]
    m = re.search(r"(\d+)/?$", href)
    return m.group(1) if m else None


def _price(a: Tag) -> tuple[float | None, str]:
    div = a.select_one("div.tc-price")
    if div is None:
        return None, "RUB"
    unit = _text(div.select_one(".unit"))
    currency = CURRENCY_BY_SIGN.get(unit, unit or "RUB")
    raw = div.get("data-s")
    if raw:
        try:
            value = float(str(raw).replace(",", "."))
            if value > 0:
                return value, currency
        except ValueError:
            pass
    # Нет data-s — берём число из текста «3 500 ₽».
    m = re.search(r"\d[\d\s\u00a0]*(?:[.,]\d+)?", _text(div))
    if not m:
        return None, currency
    try:
        return float(re.sub(r"[\s\u00a0]", "", m.group(0)).replace(",", ".")), currency
    except ValueError:
        return None, currency


def _seller(a: Tag) -> tuple[str | None, float | None, int | None]:
    user = a.select_one("div.tc-user")
    if user is None:
        return None, None, None
    name = _text(user.select_one(".media-user-name")) or None
    rating: float | None = None
    stars = user.select_one(".rating-stars")
    if stars is not None:
        for cls in stars.get("class", []):
            m = re.fullmatch(r"rating-(\d+(?:\.\d+)?)", cls)
            if m:
                rating = float(m.group(1))
                break
        if rating is None:
            full = len(stars.select("i.fas"))
            rating = float(full) if full else None
    reviews: int | None = None
    count = user.select_one(".rating-mini-count")
    if count is not None:
        digits = re.sub(r"\D", "", _text(count))
        reviews = int(digits) if digits else None
    else:
        block = _text(user.select_one(".media-user-reviews"))
        m = re.search(r"\d+", block.replace(" ", ""))
        # «Нет отзывов» → 0
        reviews = int(m.group(0)) if m else (0 if block else None)
    return name, rating, reviews


def _attrs(a: Tag) -> dict[str, tuple[str, str]]:
    """data-атрибуты лота: имя → (сырое значение, текст ячейки div.tc-<имя>)."""
    result = {}
    for key, value in a.attrs.items():
        if not key.startswith("data-"):
            continue
        name = key[5:]
        if name in SERVICE_ATTRS or value in (None, ""):
            continue
        result[name] = (str(value), _text(a.select_one(f"div.tc-{name}")))
    return result


class PageMeta:
    """Названия параметров страницы: имя атрибута (без «data-») → подпись, и варианты выпадающих списков."""

    def __init__(self, soup: BeautifulSoup):
        self.labels: dict[str, str] = {}
        self.options: dict[str, dict[str, str]] = {}
        header = soup.select_one(".tc-header")
        if header is not None:
            for div in header.find_all("div"):
                for cls in div.get("class", []):
                    if cls.startswith("tc-") and _text(div):
                        self.labels.setdefault(cls[3:], _text(div))
        for el in soup.select(".showcase-filters [name]"):
            key = re.sub(r"(\[\]|[-_](?:min|max|from|to))$", "", str(el["name"]))
            label = self._label_for(soup, el)
            if label:
                self.labels.setdefault(key, label)
            if el.name == "select":
                opts = {str(o.get("value")): _text(o) for o in el.select("option") if o.get("value") not in (None, "")}
                if opts:
                    self.options[key] = opts

    @staticmethod
    def _label_for(soup: BeautifulSoup, el: Tag) -> str:
        for attr in ("placeholder", "aria-label", "title", "data-title"):
            if el.get(attr):
                return str(el[attr]).strip()
        if el.get("id"):
            label = soup.select_one(f'label[for="{el["id"]}"]')
            if label is not None and _text(label):
                return _text(label)
        parent = el.find_parent(class_=re.compile("form-group|filter|lot-field")) or el.parent
        label = parent.find("label") if parent is not None else None
        if label is not None and _text(label):
            return _text(label)
        if el.name == "select":
            first = el.find("option")
            if first is not None and first.get("value") in (None, ""):
                return _text(first)
        return ""

    def label(self, name: str) -> str:
        return self.labels.get(name) or _LABELS.get(name) or name

    def value(self, name: str, raw: str, cell: str) -> str:
        return cell or self.options.get(name, {}).get(raw) or raw


def _numeric_from_attrs(attrs: dict[str, tuple[str, str]], meta: PageMeta, kind: str) -> int | None:
    for name, (raw, cell) in attrs.items():
        if name in meta.options:
            continue  # значение выпадающего списка — это id варианта, а не число
        title = f"{meta.labels.get(name, '')} {name}".lower()
        if any(k in title for k in PARAM_KEYWORDS[kind]):
            for candidate in (cell, raw):
                digits = re.sub(r"[\s\u00a0]", "", candidate)
                if digits.isdigit():
                    return int(digits)
    return None


def parse_category(html: str, game: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select("a.tc-item")
    if not rows:
        if soup.select_one("div.showcase, .tc-header") is not None:
            return []  # страница категории настоящая, просто объявлений сейчас нет
        # Объявлений нет и таблицы нет — пришла не та страница (защита от ботов, смена вёрстки, неверный id).
        title = _text(soup.title)
        raise FetchError(f"FunPay: на странице нет списка объявлений (title: «{title[:80]}»)")
    meta = PageMeta(soup)
    listings: list[Listing] = []
    for a in rows:
        if "warning" in (a.get("class") or []):
            continue  # лот неактивен
        offer_id = _offer_id(a)
        if not offer_id:
            continue
        description = _text(a.select_one("div.tc-desc-text"))
        price, currency = _price(a)
        seller, rating, reviews = _seller(a)
        attrs = _attrs(a)
        from_text = extract_all(description)

        extra: dict[str, str] = {}
        for name, (raw, cell) in attrs.items():
            value = meta.value(name, raw, cell)
            # Показываем только то, что удалось подписать по-человечески.
            if value and (cell or name in meta.labels or name in _LABELS):
                extra[meta.label(name)] = value
        if a.get("data-auto"):
            extra["Автовыдача"] = "да"

        listings.append(
            Listing(
                site="funpay",
                game=game,
                id=offer_id,
                url=urljoin(BASE_URL, str(a.get("href"))),
                title=description,
                price=price,
                currency=currency,
                seller=seller,
                seller_rating=rating,
                seller_reviews=reviews,
                seller_online=bool(a.get("data-online")),
                trophies=_numeric_from_attrs(attrs, meta, "trophies") or from_text["trophies"],
                brawlers=_numeric_from_attrs(attrs, meta, "brawlers") or from_text["brawlers"],
                level=_numeric_from_attrs(attrs, meta, "level") or from_text["level"],
                extra=extra,
            )
        )
    return listings


def describe_page(html: str, game: str, limit: int = 5) -> str:
    """Отчёт для отладки: что парсер видит на странице категории (python main.py --inspect-funpay)."""
    soup = BeautifulSoup(html, "lxml")
    meta = PageMeta(soup)
    rows = soup.select("a.tc-item")
    out = [f"title: {_text(soup.title)[:100]}", f"строк a.tc-item: {len(rows)}"]
    showcase = soup.select_one("div.showcase")
    if showcase is not None:
        out.append(f"showcase: data-section={showcase.get('data-section')} data-game={showcase.get('data-game')}")
    out.append(f"подписи параметров: {meta.labels}")
    if meta.options:
        out.append(f"выпадающие списки: { {k: dict(list(v.items())[:8]) for k, v in meta.options.items()} }")
    try:
        parsed = {x.id: x for x in parse_category(html, game)}
    except FetchError as e:
        out.append(f"ошибка разбора: {e}")
        parsed = {}
    for a in rows[:limit]:
        oid = _offer_id(a)
        out.append("")
        out.append(f"href: {a.get('href')}")
        out.append(f"  class: {' '.join(a.get('class', []))}")
        out.append(f"  data-*: { {k: v for k, v in a.attrs.items() if k.startswith('data-')} }")
        out.append(f"  описание: {_text(a.select_one('div.tc-desc-text'))[:150]}")
        listing = parsed.get(oid or "")
        if listing:
            out.append(f"  → цена {listing.price} {listing.currency}, продавец {listing.seller} "
                       f"(рейтинг {listing.seller_rating}, отзывов {listing.seller_reviews}, онлайн {listing.seller_online})")
            out.append(f"  → кубки {listing.trophies}, бравлеры {listing.brawlers}, уровень {listing.level}, доп.: {listing.extra}")
    return "\n".join(out)


# Подписи для известных data-атрибутов (остальные выводятся по имени атрибута).
_LABELS = {
    "server": "Сервер",
    "side": "Сторона",
    "f-type": "Тип",
}


class FunPaySource:
    def __init__(self, config: FunPayConfig, *, proxy: str | None = None):
        self.config = config
        self.http = RateLimitedClient(
            "FunPay",
            min_delay=config.request_delay_seconds,
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
            # cookie_prefs=1 — согласие с cookie, как у браузера (так же делают FunPayCardinal и др.)
            cookies={"cookie_prefs": "1", **(config.cookies or {})},
            proxy=proxy,
        )
        self._discovered: dict[str, int] = {}
        self._warned_currency = False

    async def close(self) -> None:
        await self.http.close()

    async def category_id(self, game: str) -> int:
        # Число из config.yaml (по умолчанию известные 436 / 149) или auto — найти раздел на главной странице.
        configured = self.config.categories.get(game, "auto")
        if configured != "auto":
            return int(configured)
        if game not in self._discovered:
            r = await self.http.get(BASE_URL + "/")
            found = find_accounts_category(r.text, game)
            if found is None:
                raise FetchError(
                    f"FunPay: не нашёл раздел «Аккаунты» для {game} на главной странице. "
                    f"Укажите id вручную в funpay.categories (число из ссылки funpay.com/lots/<id>/)"
                )
            log.info("FunPay: категория аккаунтов %s — %s", game, category_url(found))
            self._discovered[game] = found
        return self._discovered[game]

    async def fetch_html(self, game: str) -> str:
        r = await self.http.get(category_url(await self.category_id(game)))
        return r.text

    async def fetch(self, game: str) -> list[Listing]:
        html = await self.fetch_html(game)
        try:
            listings = parse_category(html, game)
        except FetchError:
            # Возможно, id категории сменился — в следующий раз найдём его заново.
            self._discovered.pop(game, None)
            raise
        other = {x.currency for x in listings if x.currency != "RUB"}
        if other and not self._warned_currency:
            self._warned_currency = True
            log.warning("FunPay показывает цены в %s, а не в рублях — учтите это в price_min/price_max", ", ".join(other))
        return listings
