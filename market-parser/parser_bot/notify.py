"""Тексты уведомлений об объявлениях."""

from __future__ import annotations

from .models import GAMES, SITES, Listing
from .telegram import esc

CURRENCY_SIGNS = {"RUB": "₽", "USD": "$", "EUR": "€", "UAH": "₴", "KZT": "₸"}
MAX_TITLE_LEN = 400
# Запас до лимита Telegram 4096 символов для сводного сообщения.
OVERFLOW_CHUNK_LEN = 3500

HEADERS = {
    "new": "🆕 <b>Новое объявление</b>",
    "now_matches": "🔔 <b>Теперь подходит под условия</b>",
    "price_drop": "📉 <b>Цена снижена</b>",
}


def fmt_price(price: float | None, currency: str) -> str:
    if price is None:
        return "?"
    text = f"{price:,.2f}".rstrip("0").rstrip(".").replace(",", " ")
    return f"{text} {CURRENCY_SIGNS.get(currency.upper(), currency)}"


def format_listing(listing: Listing, rule_names: list[str], kind: str = "new", old_price: float | None = None) -> str:
    lines = [
        f"{HEADERS.get(kind, HEADERS['new'])} · {esc(GAMES.get(listing.game, listing.game))} · "
        f"{esc(SITES.get(listing.site, listing.site))}",
        f"🎯 {esc(', '.join(rule_names))}",
    ]
    price = fmt_price(listing.price, listing.currency)
    if old_price is not None:
        price = f"<s>{esc(fmt_price(old_price, listing.currency))}</s> → <b>{esc(price)}</b>"
    else:
        price = f"<b>{esc(price)}</b>"
    original = listing.extra.get("Цена на сайте")
    if original:
        price = f"≈ {price} ({esc(original)} по текущему курсу)"
    lines.append(f"💰 {price}")

    stats = []
    if listing.trophies is not None:
        stats.append(f"🏆 {listing.trophies:,}".replace(",", " "))
    if listing.brawlers is not None:
        stats.append(f"🥊 бравлеров: {listing.brawlers}")
    if listing.level is not None:
        stats.append(("👑 уровень короля: " if listing.game == "clash_royale" else "⭐ уровень: ") + str(listing.level))
    if stats:
        lines.append(" · ".join(stats))
    for key, value in listing.extra.items():
        if key != "Цена на сайте":
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


def format_overflow(items: list[tuple[Listing, float | None]], limit: int) -> list[tuple[str, list[tuple[Listing, float | None]]]]:
    """Сводка по объявлениям сверх лимита на одну проверку: по строке со ссылкой на каждое.

    Возвращает части (текст, объявления в нём), каждая короче лимита Telegram.
    """
    head = (f"📋 Ещё подходящих объявлений: {len(items)} (лимит отдельных сообщений — {limit} за проверку, "
            f"monitor.max_notifications_per_cycle):\n")
    chunks: list[tuple[str, list[tuple[Listing, float | None]]]] = []
    text, part = head, []
    for listing, old_price in items:
        title = listing.title.strip() or "без названия"
        if len(title) > 70:
            title = title[:69] + "…"
        price = fmt_price(listing.price, listing.currency)
        if old_price is not None:
            price = f"{fmt_price(old_price, listing.currency)} → {price}"
        line = (f"\n• {esc(GAMES.get(listing.game, ''))}, {esc(SITES.get(listing.site, ''))}: <b>{esc(price)}</b> — "
                f"<a href=\"{esc(listing.url).replace(chr(34), '&quot;')}\">{esc(title)}</a>")
        if len(text) + len(line) > OVERFLOW_CHUNK_LEN and part:
            chunks.append((text, part))
            text, part = "📋 Продолжение:\n", []
        text += line
        part.append((listing, old_price))
    if part:
        chunks.append((text, part))
    return chunks
