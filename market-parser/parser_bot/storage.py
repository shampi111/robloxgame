"""Состояние между запусками: какие объявления уже видели и о каких уже сообщили, когда каждый
источник последний раз отвечал, ошибки источников и настройки, изменённые из Telegram.

Хранится в одном JSON-файле. Запись атомарная (через временный файл), чтобы файл не
повредился, если бота выключат посреди записи.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Объявления, которых не было в выдаче дольше этого срока, забываем, чтобы файл не рос бесконечно.
# Источник, который не отвечал дольше этого срока, считается новым: первый удачный проход по нему
# снова только запоминает объявления, а не присылает их все разом.
FORGET_AFTER_SECONDS = 30 * 24 * 3600


class State:
    def __init__(self, path: str | Path, *, persist: bool = True):
        self.path = Path(path)
        self.persist = persist
        # ключ объявления → {first_seen, last_seen, price, currency, notified_price, pending?}
        self.seen: dict[str, dict[str, Any]] = {}
        # ключ источника → время последнего удачного ответа
        self.sources: dict[str, float] = {}
        # название источника → {failures, alerted, last_error}
        self.health: dict[str, dict[str, Any]] = {}
        # Настройки, изменённые командами бота (например, interval_minutes).
        self.settings: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("ожидался JSON-объект")
        except (OSError, ValueError) as e:
            # Не роняем бота из-за испорченного файла: начинаем с чистого состояния,
            # а старый файл сохраняем рядом для разбора.
            backup = self.path.with_suffix(self.path.suffix + ".broken")
            log.error("Не удалось прочитать %s (%s). Начинаю с пустого состояния, старый файл: %s", self.path, e, backup)
            try:
                os.replace(self.path, backup)
            except OSError:
                pass
            return
        self.seen = data.get("seen") or {}
        self.sources = data.get("sources") or {}
        # Файл от первой версии бота: список источников без времени.
        for key in data.get("initialized") or []:
            self.sources.setdefault(key, time.time())
        self.health = data.get("health") or {}
        self.settings = data.get("settings") or {}

    def save(self) -> None:
        if not self.persist:
            return
        data = {"seen": self.seen, "sources": self.sources, "health": self.health, "settings": self.settings}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def forget_old(self) -> None:
        """Забыть давно пропавшие объявления и давно молчащие источники (вызывается после проверки)."""
        cutoff = time.time() - FORGET_AFTER_SECONDS
        for key in [k for k, v in self.seen.items() if v.get("last_seen", 0) < cutoff]:
            del self.seen[key]
        for key in [k for k, t in self.sources.items() if t < cutoff]:
            del self.sources[key]

    # --- источники ---

    def source_initialized(self, key: str) -> bool:
        last_ok = self.sources.get(key)
        return last_ok is not None and last_ok >= time.time() - FORGET_AFTER_SECONDS

    def mark_source_ok(self, key: str) -> None:
        self.sources[key] = time.time()

    # --- объявления ---

    def get(self, key: str) -> dict[str, Any] | None:
        return self.seen.get(key)

    def touch(self, key: str, price: float | None, currency: str) -> dict[str, Any]:
        """Отметить, что объявление есть в выдаче сейчас. Возвращает его запись."""
        now = time.time()
        entry = self.seen.get(key)
        if entry is None:
            entry = {"first_seen": now, "notified_price": None}
            self.seen[key] = entry
        entry["last_seen"] = now
        entry["price"] = price
        entry["currency"] = currency
        return entry

    def mark_notified(self, key: str, price: float | None) -> None:
        """Об объявлении сообщили (или сознательно не сообщили при первом проходе) по этой цене.

        Цена неизвестна — запоминаем -1, чтобы не слать повторно.
        """
        entry = self.seen.get(key)
        if entry is None:
            return
        entry["notified_price"] = price if price is not None else -1
        entry.pop("pending", None)

    def set_pending(self, key: str, chats: list[str], kind: str, old_price: float | None) -> None:
        """Уведомление не дошло до этих чатов (Telegram недоступен) — повторим в следующую проверку."""
        entry = self.seen.get(key)
        if entry is not None:
            entry["pending"] = {"chats": sorted(chats), "kind": kind, "old_price": old_price}

    def clear_pending(self, key: str) -> None:
        entry = self.seen.get(key)
        if entry is not None:
            entry.pop("pending", None)
