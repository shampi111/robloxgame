"""Загрузка и проверка config.yaml."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import GAMES, SITES

# Известные id разделов «Аккаунты» на FunPay (https://funpay.com/lots/<id>/).
DEFAULT_FUNPAY_CATEGORIES: dict[str, int | str] = {"brawl_stars": 436, "clash_royale": 149}

MIN_INTERVAL_MINUTES = 1.0
MAX_INTERVAL_MINUTES = 24 * 60


class ConfigError(Exception):
    pass


@dataclass
class TelegramConfig:
    bot_token: str
    chat_ids: list[int | str]
    commands: bool = True
    proxy: str | None = None


@dataclass
class MonitorConfig:
    interval_minutes: float = 5.0
    notify_on_first_run: bool = False
    notify_price_drop: bool = True
    max_notifications_per_cycle: int = 25
    state_file: str = "state.json"
    proxy: str | None = None


@dataclass
class FunPayConfig:
    enabled: bool = True
    # id подкатегорий «Аккаунты» на FunPay (https://funpay.com/lots/<id>/) или "auto" — найти на главной.
    categories: dict[str, int | str] = field(default_factory=lambda: dict(DEFAULT_FUNPAY_CATEGORIES))
    request_delay_seconds: float = 5.0
    cookies: dict[str, str] = field(default_factory=dict)


@dataclass
class LolzConfig:
    enabled: bool = True
    token: str = ""
    base_url: str = "https://api.lzt.market"
    item_url: str = "https://lzt.market/{id}/"
    request_delay_seconds: float = 3.5
    pages: int = 1


@dataclass
class Rule:
    name: str
    game: str
    sites: list[str] = field(default_factory=lambda: list(SITES))
    price_min: float | None = None
    price_max: float | None = None
    trophies_min: int | None = None
    trophies_max: int | None = None
    brawlers_min: int | None = None
    level_min: int | None = None
    include_all: list[str] = field(default_factory=list)
    include_any: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    # Что делать, если число (кубки и т.п.) в объявлении не найдено: true — считать подходящим.
    allow_unknown: bool = False
    # FunPay: требования к продавцу.
    online_only: bool = False
    min_reviews: int | None = None
    min_rating: float | None = None
    # LolzMarket: дополнительные параметры поиска API, передаются как есть.
    lolz_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    telegram: TelegramConfig
    monitor: MonitorConfig
    funpay: FunPayConfig
    lolz: LolzConfig
    rules: list[Rule]
    base_dir: Path = Path(".")

    @property
    def state_path(self) -> Path:
        p = Path(self.monitor.state_file)
        return p if p.is_absolute() else self.base_dir / p


def _section(raw: dict, name: str) -> dict:
    value = raw.get(name) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"Раздел «{name}» должен быть словарём (ключ: значение)")
    return value


def _build(cls, data: dict, where: str):
    known = cls.__dataclass_fields__.keys()
    unknown = set(data) - set(known)
    if unknown:
        raise ConfigError(f"{where}: неизвестные параметры {', '.join(sorted(unknown))}")
    try:
        return cls(**data)
    except TypeError as e:
        raise ConfigError(f"{where}: {e}") from None


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def parse_rule(data: dict, index: int) -> Rule:
    if not isinstance(data, dict):
        raise ConfigError(f"rules[{index}] должно быть словарём")
    data = dict(data)
    where = f"правило «{data.get('name', index + 1)}»"
    data.setdefault("name", f"Правило {index + 1}")
    for key in ("sites", "include_all", "include_any", "exclude"):
        if key in data:
            data[key] = [str(x) for x in _as_list(data[key])]
    if data.get("lolz_params") is None:
        data.pop("lolz_params", None)
    rule = _build(Rule, data, where)
    if rule.game not in GAMES:
        raise ConfigError(f"{where}: game должен быть одним из: {', '.join(GAMES)}")
    bad_sites = set(rule.sites) - set(SITES)
    if bad_sites or not rule.sites:
        raise ConfigError(f"{where}: sites может содержать только {', '.join(SITES)}")
    for key in ("price_min", "price_max", "trophies_min", "trophies_max", "brawlers_min", "level_min", "min_reviews", "min_rating"):
        value = getattr(rule, key)
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0):
            raise ConfigError(f"{where}: {key} должен быть неотрицательным числом")
    if rule.price_min is not None and rule.price_max is not None and rule.price_min > rule.price_max:
        raise ConfigError(f"{where}: price_min больше price_max")
    if rule.brawlers_min is not None and rule.game != "brawl_stars":
        raise ConfigError(f"{where}: brawlers_min бывает только у Brawl Stars")
    if not isinstance(rule.lolz_params, dict):
        raise ConfigError(f"{where}: lolz_params должен быть словарём")
    return rule


def validate_interval(minutes: Any) -> float:
    try:
        value = float(minutes)
    except (TypeError, ValueError):
        raise ConfigError("Интервал должен быть числом (минуты)") from None
    if not MIN_INTERVAL_MINUTES <= value <= MAX_INTERVAL_MINUTES:
        raise ConfigError(f"Интервал должен быть от {MIN_INTERVAL_MINUTES:g} до {MAX_INTERVAL_MINUTES} минут")
    return value


def load_config(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Нет файла {path}. Скопируйте config.example.yaml в config.yaml и заполните его.")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Ошибка в синтаксисе {path}: {e}") from None
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: ожидается словарь с разделами telegram, monitor, funpay, lolz, rules")

    unknown = set(raw) - {"telegram", "monitor", "funpay", "lolz", "rules"}
    if unknown:
        raise ConfigError(f"Неизвестные разделы в конфиге: {', '.join(sorted(unknown))}")

    tg_raw = _section(raw, "telegram")
    tg_raw["chat_ids"] = _as_list(tg_raw.get("chat_ids"))
    telegram = _build(TelegramConfig, tg_raw, "telegram")
    if not telegram.bot_token or "ВАШ" in str(telegram.bot_token) or ":" not in str(telegram.bot_token):
        raise ConfigError("telegram.bot_token не заполнен (получите токен у @BotFather)")
    if not telegram.chat_ids:
        raise ConfigError("telegram.chat_ids пуст — укажите свой chat id (узнать можно у @userinfobot)")

    monitor = _build(MonitorConfig, _section(raw, "monitor"), "monitor")
    monitor.interval_minutes = validate_interval(monitor.interval_minutes)

    fp_raw = _section(raw, "funpay")
    funpay = _build(FunPayConfig, fp_raw, "funpay")
    categories: dict[str, int | str] = dict(DEFAULT_FUNPAY_CATEGORIES)
    for game, value in (funpay.categories or {}).items():
        if str(game) not in GAMES:
            raise ConfigError(f"funpay.categories: неизвестная игра {game} (можно: {', '.join(GAMES)})")
        if value is None or str(value).strip() == "":
            continue
        if str(value).strip().lower() == "auto":
            categories[str(game)] = "auto"
            continue
        m = re.search(r"(\d+)/?$", str(value).strip())
        if not m:
            raise ConfigError(f"funpay.categories.{game}: укажите число (id из ссылки funpay.com/lots/<id>/) или auto")
        categories[str(game)] = int(m.group(1))
    funpay.categories = categories

    lolz = _build(LolzConfig, _section(raw, "lolz"), "lolz")
    lolz.base_url = lolz.base_url.rstrip("/")
    lolz.pages = max(1, int(lolz.pages))

    rules_raw = raw.get("rules") or []
    if not isinstance(rules_raw, list) or not rules_raw:
        raise ConfigError("Раздел rules пуст — добавьте хотя бы одно условие")
    rules = [parse_rule(r, i) for i, r in enumerate(rules_raw)]
    names = [r.name for r in rules]
    if len(set(names)) != len(names):
        raise ConfigError("У правил должны быть разные name")

    if lolz.enabled and any("lolz" in r.sites for r in rules) and (not lolz.token or "ВАШ" in lolz.token):
        raise ConfigError("lolz.token не заполнен. Получите токен API на LolzMarket или выключите lolz (enabled: false)")

    return Config(telegram=telegram, monitor=monitor, funpay=funpay, lolz=lolz, rules=rules, base_dir=path.resolve().parent)
