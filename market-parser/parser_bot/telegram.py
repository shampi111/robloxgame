"""Минимальный клиент Telegram Bot API: отправка сообщений и приём команд (long polling)."""

from __future__ import annotations

import asyncio
import html
import logging
import time
from collections.abc import Awaitable, Callable

import httpx

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
MAX_MESSAGE_LEN = 4096
# Telegram просит не больше ~1 сообщения в секунду в один чат (в группу — 20 в минуту).
PER_CHAT_DELAY = 1.1


def esc(text: object) -> str:
    """Экранирование для parse_mode=HTML."""
    return html.escape(str(text), quote=False)


class TelegramError(Exception):
    pass


class Telegram:
    def __init__(self, token: str, chat_ids: list[int | str], *, proxy: str | None = None, dry_run: bool = False):
        self.token = token
        self.chat_ids = [str(c) for c in chat_ids]
        self.dry_run = dry_run
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(70.0, connect=15.0), proxy=proxy)
        self._last_sent: dict[str, float] = {}
        self._send_lock = asyncio.Lock()
        self._offset: int | None = None

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, payload: dict, *, retries: int = 5) -> dict:
        url = API.format(token=self.token, method=method)
        for attempt in range(retries):
            try:
                r = await self._client.post(url, json=payload)
            except httpx.HTTPError as e:
                wait = min(60, 2 ** attempt)
                log.warning("Telegram %s: сетевая ошибка %s, повтор через %s с", method, e, wait)
                await asyncio.sleep(wait)
                continue
            try:
                data = r.json()
            except ValueError:
                data = {"ok": False, "description": r.text[:200]}
            if data.get("ok"):
                return data
            if r.status_code == 429:
                wait = int(data.get("parameters", {}).get("retry_after", 5)) + 1
                log.warning("Telegram просит подождать %s с (429)", wait)
                await asyncio.sleep(wait)
                continue
            if r.status_code >= 500:
                await asyncio.sleep(min(60, 2 ** attempt))
                continue
            # 400/401/403 и т.п. повторять бессмысленно: неверный токен, chat_id, бот заблокирован и т.д.
            raise TelegramError(f"{method}: {r.status_code} {data.get('description')}")
        raise TelegramError(f"{method}: не удалось после {retries} попыток")

    async def send(self, text: str, *, chat_id: str | None = None, button: tuple[str, str] | None = None) -> bool:
        """Отправить сообщение (HTML) одному чату или всем из chat_ids. True — если дошло до всех."""
        targets = [str(chat_id)] if chat_id else self.chat_ids
        if len(text) > MAX_MESSAGE_LEN:
            text = text[: MAX_MESSAGE_LEN - 1] + "…"
        delivered = True
        for target in targets:
            if self.dry_run:
                print(f"\n----- [dry-run → {target}] -----\n{text}" + (f"\n[{button[0]}] {button[1]}" if button else ""))
                continue
            payload: dict = {
                "chat_id": target,
                "text": text,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            }
            if button:
                payload["reply_markup"] = {"inline_keyboard": [[{"text": button[0], "url": button[1]}]]}
            async with self._send_lock:
                wait = self._last_sent.get(target, 0) + PER_CHAT_DELAY - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    await self._call("sendMessage", payload)
                except TelegramError as e:
                    delivered = False
                    log.error("Не удалось отправить сообщение в чат %s: %s", target, e)
                finally:
                    self._last_sent[target] = time.monotonic()
        return delivered

    async def check(self) -> str:
        """Проверка токена. Возвращает @username бота."""
        data = await self._call("getMe", {}, retries=2)
        return "@" + data["result"].get("username", "?")

    async def poll_commands(self, handler: Callable[[str, str, list[str]], Awaitable[None]]) -> None:
        """Бесконечно принимает команды. handler(chat_id, команда, аргументы).

        Команды от чатов, которых нет в chat_ids, игнорируются: управлять ботом может только владелец.
        """
        if self.dry_run:
            return
        while True:
            payload: dict = {"timeout": 50, "allowed_updates": ["message"]}
            if self._offset is not None:
                payload["offset"] = self._offset
            try:
                data = await self._call("getUpdates", payload, retries=1)
            except TelegramError as e:
                if "409" in str(e):
                    log.error("Telegram: этот токен уже опрашивает другая копия бота или включён webhook. "
                              "Команды не будут работать, пока она запущена.")
                    await asyncio.sleep(60)
                else:
                    log.warning("getUpdates: %s", e)
                    await asyncio.sleep(10)
                continue
            for upd in data.get("result", []):
                self._offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                text = (msg.get("text") or "").strip()
                chat_id = str((msg.get("chat") or {}).get("id", ""))
                if not text.startswith("/"):
                    continue
                if chat_id not in self.chat_ids:
                    log.warning("Команда из чужого чата %s проигнорирована: %s", chat_id, text[:50])
                    continue
                parts = text.split()
                command = parts[0][1:].split("@", 1)[0].lower()
                try:
                    await handler(chat_id, command, parts[1:])
                except Exception:  # одна сломанная команда не должна останавливать бота
                    log.exception("Ошибка при обработке команды %s", text)
