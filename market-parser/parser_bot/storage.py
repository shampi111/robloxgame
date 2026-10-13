"""Состояние между запусками: какие объявления уже видели, и настройки, изменённые из Telegram.

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
FORGET_AFTER_SECONDS = 30 * 24 * 3600


class State:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.seen: dict[str, dict[str, Any]] = {}
        # Источники (сайт+игра+запрос), по которым уже был первый проход.
        self.initialized: set[str] = set()
        # Настройки, изменённые командами бота (например, interval_minutes).
        self.settings: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
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
        self.seen = data.get("seen", {})
        self.initialized = set(data.get("initialized", []))
        self.settings = data.get("settings", {})

    def save(self) -> None:
        self._forget_old()
        data = {
            "seen": self.seen,
            "initialized": sorted(self.initialized),
            "settings": self.settings,
        }
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

    def _forget_old(self) -> None:
        cutoff = time.time() - FORGET_AFTER_SECONDS
        for key in [k for k, v in self.seen.items() if v.get("last_seen", 0) < cutoff]:
            del self.seen[key]

    # --- работа с объявлениями ---

    def get(self, key: str) -> dict[str, Any] | None:
        return self.seen.get(key)

    def touch(self, key: str, price: float | None) -> dict[str, Any]:
        """Отметить, что объявление есть в выдаче сейчас. Возвращает его запись."""
        now = time.time()
        entry = self.seen.get(key)
        if entry is None:
            entry = {"first_seen": now, "price": price, "notified_price": None}
            self.seen[key] = entry
        entry["last_seen"] = now
        entry["price"] = price
        return entry

    def mark_notified(self, key: str, price: float | None) -> None:
        entry = self.seen.setdefault(key, {"first_seen": time.time(), "last_seen": time.time(), "price": price})
        # Цена неизвестна, но уведомление уже ушло: запоминаем как «уведомлено», чтобы не слать повторно.
        entry["notified_price"] = price if price is not None else -1
        entry.pop("pending", None)

    def mark_pending(self, key: str) -> None:
        """Уведомление не дошло (Telegram недоступен) — попробуем ещё раз в следующую проверку."""
        if key in self.seen:
            self.seen[key]["pending"] = True
