"""Общая модель объявления, в которую приводятся данные с обоих сайтов."""

from __future__ import annotations

from dataclasses import dataclass, field

GAMES = {
    "brawl_stars": "Brawl Stars",
    "clash_royale": "Clash Royale",
}

SITES = {
    "funpay": "FunPay",
    "lolz": "LolzMarket",
}


@dataclass
class Listing:
    site: str  # "funpay" | "lolz"
    game: str  # "brawl_stars" | "clash_royale"
    id: str
    url: str
    title: str
    price: float | None
    # Полное описание (если сайт его отдаёт). В уведомление не выводится, но по нему ищутся слова из правил.
    description: str = ""
    currency: str = "RUB"
    seller: str | None = None
    seller_reviews: int | None = None
    seller_rating: float | None = None
    seller_online: bool | None = None
    trophies: int | None = None
    brawlers: int | None = None
    level: int | None = None
    # Прочие параметры, которые показываем в уведомлении как есть (сервер, легендарки и т.п.).
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> str:
        # Игра входит в ключ: на LolzMarket один аккаунт Supercell может содержать и BS, и CR,
        # и тогда это два разных «объявления» для наших правил (со своими кубками и уровнем).
        return f"{self.site}:{self.game}:{self.id}"
