"""Минимальный клиент Telegram Bot API: отправка сообщений и приём команд (long polling)."""

from __future__ import annotations

import asyncio
import html
import logging
import re
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
    def __init__(self, message: str, *, permanent: bool = False, status: int | None = None):
        super().__init__(message)
        # permanent — повтор не поможет: неверный токен, чат не найден, бот заблокирован и т.п.
        self.permanent = permanent
        self.status = status


def explain(error: TelegramError) -> str:
    """Понятное объяснение ошибки Telegram для пользователя."""
    text = str(error).lower()
    if error.status == 401 or "unauthorized" in text:
        return "неверный telegram.bot_token (проверьте токен у @BotFather)"
    if "chat not found" in text:
        return "чат не найден — проверьте chat_ids и нажмите Start в своём боте"
    if error.status == 403:
        return "бот не может писать в этот чат — нажмите Start в боте (или бот заблокирован / удалён из группы)"
    if not error.permanent:
        return "нет связи с Telegram — проверьте интернет или задайте telegram.proxy"
    return str(error)


def _plain(text: str) -> str:
    """HTML → обычный текст (для слишком длинных сообщений, которые приходится обрезать)."""
    return html.unescape(re.sub(r"<[^>]+>", "", text))


class Telegram:
    def __init__(self, token: str, chat_ids: list[int | str], *, proxy: str | None = None, dry_run: bool = False):
        self.token = token
        self.chat_ids = [str(c) for c in chat_ids]
        self.dry_run = dry_run
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(70.0, connect=15.0), proxy=proxy)
        self._last_sent: dict[str, float] = {}
        self._send_lock = asyncio.Lock()
        self._offset: int | None = None
        self._broken_chats_logged: set[str] = set()

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, payload: dict, *, retries: int = 5) -> dict:
        url = API.format(token=self.token, method=method)
        last = ""
        for attempt in range(retries):
            try:
                r = await self._client.post(url, json=payload)
            except httpx.HTTPError as e:
                # В тексте ошибки httpx может быть URL с токеном — не пишем его в лог.
                last = type(e).__name__
                wait = min(60, 2 ** attempt)
                log.warning("Telegram %s: сетевая ошибка %s, повтор через %s с", method, last, wait)
                if attempt < retries - 1:
                    await asyncio.sleep(wait)
                continue
            try:
                data = r.json()
            except ValueError:
                data = {"ok": False, "description": r.text[:200]}
            if data.get("ok"):
                return data
            last = f"{r.status_code} {data.get('description')}"
            if r.status_code == 429:
                wait = int((data.get("parameters") or {}).get("retry_after", 5)) + 1
                log.warning("Telegram просит подождать %s с (429)", wait)
                if attempt < retries - 1:
                    await asyncio.sleep(wait)
                continue
            if r.status_code >= 500:
                if attempt < retries - 1:
                    await asyncio.sleep(min(60, 2 ** attempt))
                continue
            # 400/401/403 и т.п. повторять бессмысленно: неверный токен, chat_id, бот заблокирован и т.д.
            raise TelegramError(f"{method}: {last}", permanent=True, status=r.status_code)
        raise TelegramError(f"{method}: не удалось после {retries} попыток ({last})", permanent=False)

    async def send(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        chats: list[str] | None = None,
        button: tuple[str, str] | None = None,
    ) -> set[str]:
        """Отправить сообщение (HTML). По умолчанию — всем chat_ids.

        Возвращает чаты, куда не удалось доставить из-за временной проблемы (стоит повторить позже).
        Чаты с постоянной ошибкой (бот заблокирован, чат не найден) пишутся в лог и не повторяются.
        """
        targets = [str(chat_id)] if chat_id else (chats if chats is not None else self.chat_ids)
        parse_mode: str | None = "HTML"
        if len(text) > MAX_MESSAGE_LEN:
            # Обрезать HTML посередине тега нельзя (Telegram вернёт ошибку) — шлём обычным текстом.
            text = _plain(text)[: MAX_MESSAGE_LEN - 1] + "…"
            parse_mode = None
        failed: set[str] = set()
        for target in targets:
            if self.dry_run:
                print(f"\n----- [dry-run → {target}] -----\n{text}" + (f"\n[{button[0]}] {button[1]}" if button else ""))
                continue
            payload: dict = {"chat_id": target, "text": text, "link_preview_options": {"is_disabled": True}}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            if button:
                payload["reply_markup"] = {"inline_keyboard": [[{"text": button[0], "url": button[1]}]]}
            async with self._send_lock:
                wait = self._last_sent.get(target, 0) + PER_CHAT_DELAY - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    await self._call("sendMessage", payload, retries=3)
                except TelegramError as e:
                    if e.permanent:
                        if target not in self._broken_chats_logged:
                            self._broken_chats_logged.add(target)
                            log.error("Чат %s: сообщения не доставляются — %s", target, explain(e))
                    else:
                        failed.add(target)
                        log.error("Не удалось отправить сообщение в чат %s: %s", target, e)
                finally:
                    self._last_sent[target] = time.monotonic()
        return failed

    async def check(self) -> str:
        """Проверка токена. Возвращает @username бота."""
        data = await self._call("getMe", {}, retries=2)
        return "@" + data["result"].get("username", "?")

    async def send_test(self, text: str) -> dict[str, str]:
        """Тестовое сообщение каждому чату. Возвращает {chat_id: ошибка} для недоставленных."""
        errors = {}
        for target in self.chat_ids:
            try:
                await self._call("sendMessage", {"chat_id": target, "text": text}, retries=2)
            except TelegramError as e:
                errors[target] = explain(e)
        return errors

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
                if e.status == 409:
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
