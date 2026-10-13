"""HTTP-клиент для сайтов: паузы между запросами, повторы при ошибках, уважение к Retry-After."""

from __future__ import annotations

import asyncio
import logging
import random
import time

import httpx

log = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


class FetchError(Exception):
    """Источник не ответил нормально. Цикл мониторинга пропускает его и пробует в следующий раз.

    unreachable=True — сайт недоступен (сеть, таймаут, ошибки сервера): имеет смысл попробовать
    запасной адрес. Для ответов вида 4xx (неверный токен, бан, неверный параметр) — False.
    """

    def __init__(self, message: str, *, unreachable: bool = False):
        super().__init__(message)
        self.unreachable = unreachable


class RateLimitedClient:
    """Обёртка над httpx.AsyncClient для одного сайта.

    min_delay — минимальная пауза между запросами к этому сайту (секунды).
    auth_hint — пояснение, которое добавляется к ошибкам 401/403 (например, про токен).
    """

    def __init__(
        self,
        name: str,
        *,
        min_delay: float,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        proxy: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        auth_hint: str = "",
    ):
        self.name = name
        self.min_delay = min_delay
        self.max_retries = max_retries
        self.auth_hint = auth_hint
        self._client = httpx.AsyncClient(
            headers={**BROWSER_HEADERS, **(headers or {})},
            cookies=cookies,
            proxy=proxy,
            timeout=httpx.Timeout(timeout, connect=10.0),
            follow_redirects=True,
        )
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def close(self) -> None:
        await self._client.aclose()

    async def _pace(self) -> None:
        # Небольшой случайный разброс, чтобы запросы не шли с идеально ровным шагом.
        wait = self._last + self.min_delay * random.uniform(1.0, 1.3) - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)

    async def get(self, url: str, **kwargs) -> httpx.Response:
        last_error = ""
        for attempt in range(self.max_retries + 1):
            async with self._lock:
                await self._pace()
                try:
                    r = await self._client.get(url, **kwargs)
                except httpx.HTTPError as e:
                    r = None
                    last_error = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                finally:
                    self._last = time.monotonic()
            if r is not None:
                if r.status_code < 400:
                    return r
                last_error = f"HTTP {r.status_code}"
                if r.status_code == 429 or r.status_code >= 500:
                    wait = _retry_after(r) or min(60, 5 * 2 ** attempt)
                elif r.status_code in (401, 403):
                    # 401 — неверный токен; 403 — защита от ботов / бан по IP / нет прав у токена.
                    hint = f" — {self.auth_hint}" if self.auth_hint else ""
                    raise FetchError(f"{self.name}: {last_error}{hint} ({_snippet(r)})")
                else:
                    raise FetchError(f"{self.name}: {last_error} — {_snippet(r)}")
            else:
                wait = min(60, 3 * 2 ** attempt)
            if attempt < self.max_retries:
                log.warning("%s: %s, повтор через %.0f с", self.name, last_error, wait)
                await asyncio.sleep(wait)
        unreachable = not last_error.startswith("HTTP 429")
        raise FetchError(f"{self.name}: {last_error} (после {self.max_retries + 1} попыток)", unreachable=unreachable)


def _retry_after(r: httpx.Response) -> float | None:
    """Сколько ждать перед повтором: Retry-After (секунды) или X-RateLimit-Reset (unix-время, LolzMarket)."""
    # Ждём не дольше 2 минут: дольше — пусть лучше эта проверка пропустит сайт, следующая попробует снова.
    value = r.headers.get("Retry-After")
    if value:
        try:
            return min(120.0, max(1.0, float(value)))
        except ValueError:
            pass
    reset = r.headers.get("X-RateLimit-Reset")
    if reset and r.status_code == 429:
        try:
            return min(120.0, max(1.0, float(reset) - time.time() + 1))
        except ValueError:
            pass
    return None


def _snippet(r: httpx.Response) -> str:
    """Короткое объяснение ответа с ошибкой: текст ошибок API или признак защиты от ботов."""
    try:
        data = r.json()
    except ValueError:
        data = None
    if isinstance(data, dict) and data.get("errors"):
        errors = data["errors"]
        return "; ".join(map(str, errors if isinstance(errors, list) else [errors]))[:300]
    text = " ".join(r.text[:500].split())
    lowered = text.lower()
    if "cloudflare" in lowered or any(h.lower().startswith("cf-") for h in r.headers.keys()):
        return "похоже на защиту Cloudflare (проверка браузера)"
    if "ddos-guard" in lowered or "ddos-guard" in r.headers.get("server", "").lower():
        return "похоже на защиту DDoS-Guard"
    if "qrator" in lowered or "qrator" in r.headers.get("server", "").lower():
        return "похоже на защиту Qrator"
    return text[:200] or "пустой ответ"
