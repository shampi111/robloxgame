"""Курсы валют для пересчёта цен в рубли.

FunPay показывает цены в валюте посетителя: с российского IP — в рублях, из других стран
(например, из Грузии) — в долларах или евро. Условия price_min/price_max в config.yaml — в рублях,
поэтому такие цены пересчитываются по текущему курсу.

Курс берётся из бесплатных источников без ключа (open.er-api.com, запасной — cbr-xml-daily.ru)
и обновляется раз в 12 часов. Если оба недоступны, используются курсы из monitor.currency_rates.
"""

from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger(__name__)

REFRESH_SECONDS = 12 * 3600
RETRY_SECONDS = 15 * 60
SOURCES = (
    "https://open.er-api.com/v6/latest/RUB",
    "https://www.cbr-xml-daily.ru/daily_json.js",
)


def parse_rates(url: str, data: dict) -> dict[str, float]:
    """Ответ источника → {валюта: сколько рублей за 1 единицу}."""
    result: dict[str, float] = {}
    if "er-api" in url:
        if data.get("result") != "success":
            return {}
        for code, per_rub in (data.get("rates") or {}).items():
            try:
                value = float(per_rub)
            except (TypeError, ValueError):
                continue
            if value > 0:
                result[str(code).upper()] = 1 / value
    else:
        for code, item in (data.get("Valute") or {}).items():
            try:
                value = float(item["Value"]) / float(item.get("Nominal") or 1)
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                continue
            if value > 0:
                result[str(code).upper()] = value
    result["RUB"] = 1.0
    return result


class Rates:
    def __init__(self, manual: dict[str, float] | None = None, *, proxy: str | None = None):
        self.manual = {k.upper(): float(v) for k, v in (manual or {}).items()}
        self._proxy = proxy
        self._rates: dict[str, float] = {}
        self._next_refresh = 0.0

    async def _refresh(self) -> None:
        async with httpx.AsyncClient(timeout=15.0, proxy=self._proxy, follow_redirects=True) as client:
            for url in SOURCES:
                try:
                    r = await client.get(url)
                    data = r.json() if r.status_code == 200 else {}
                    rates = parse_rates(url, data) if isinstance(data, dict) else {}
                except (httpx.HTTPError, ValueError) as e:
                    log.warning("Курсы валют: %s недоступен (%s)", url, type(e).__name__)
                    continue
                if len(rates) > 1:
                    self._rates = rates
                    self._next_refresh = time.time() + REFRESH_SECONDS
                    log.info("Курсы валют обновлены (%s): 1 USD = %.2f ₽", url.split("/")[2], rates.get("USD", 0))
                    return
        self._next_refresh = time.time() + RETRY_SECONDS

    async def rub_per_unit(self, currency: str) -> float | None:
        currency = currency.upper()
        if currency == "RUB":
            return 1.0
        if currency in self.manual:
            return self.manual[currency]
        if time.time() >= self._next_refresh:
            await self._refresh()
        return self._rates.get(currency)

    async def to_rub(self, amount: float, currency: str) -> float | None:
        rate = await self.rub_per_unit(currency)
        return round(amount * rate, 2) if rate else None
