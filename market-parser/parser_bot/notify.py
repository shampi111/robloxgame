"""Текст уведомления об объявлении."""

from __future__ import annotations

from .models import GAMES, SITES, Listing
from .telegram import esc

CURRENCY_SIGNS = {"RUB": "₽", "USD": "$", "EUR": "€", "UAH": "₴", "KZT": "₸"}
MAX_TITLE_LEN = 400


def fmt_price(price: float | None, currency: str) -> str:
    if price is None:
        return "?"
    text = f"{price:,.2f}".rstrip("0").rstrip(".").replace(",", " ")
    return f"{text} {CURRENCY_SIGNS.get(currency.upper(), currency)}"


def format_listing(listing: Listing, rule_names: list[str], old_price: float | None = None) -> str:
    head = "📉 <b>Цена снижена</b>" if old_price is not None else "🆕 <b>Новое объявление</b>"
    lines = [
        f"{head} · {esc(GAMES.get(listing.game, listing.game))} · {esc(SITES.get(listing.site, listing.site))}",
        f"🎯 {esc(', '.join(rule_names))}",
    ]
    price = fmt_price(listing.price, listing.currency)
    if old_price is not None:
        price = f"<s>{esc(fmt_price(old_price, listing.currency))}</s> → <b>{esc(price)}</b>"
    else:
        price = f"<b>{esc(price)}</b>"
    lines.append(f"💰 {price}")

    stats = []
    if listing.trophies is not None:
        stats.append(f"🏆 {listing.trophies:,}".replace(",", " "))
    if listing.brawlers is not None:
        stats.append(f"🥊 бравлеров: {listing.brawlers}")
    if listing.level is not None:
        stats.append(f"⭐ уровень: {listing.level}")
    if stats:
        lines.append(" · ".join(stats))
    for key, value in listing.extra.items():
        lines.append(f"• {esc(key)}: {esc(value)}")

    if listing.seller:
        seller = f"👤 {esc(listing.seller)}"
        details = []
        if listing.seller_rating is not None:
            details.append(f"рейтинг {listing.seller_rating:g}")
        if listing.seller_reviews is not None:
            details.append(f"отзывов {listing.seller_reviews}")
        if listing.seller_online:
            details.append("онлайн")
        if details:
            seller += f" ({esc(', '.join(details))})"
        lines.append(seller)

    title = listing.title.strip()
    if len(title) > MAX_TITLE_LEN:
        title = title[: MAX_TITLE_LEN - 1] + "…"
    if title:
        lines.append(f"\n📝 {esc(title)}")
    lines.append(f"\n🔗 {esc(listing.url)}")
    return "\n".join(lines)
