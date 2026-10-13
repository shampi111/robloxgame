"""Цикл мониторинга: опрос сайтов, отбор по правилам, уведомления, команды бота.

Когда приходит уведомление:
- 🆕 новое объявление подходит под условия;
- 🔔 объявление уже было на сайте, но теперь подходит (продавец изменил описание, вышел в онлайн и т.п.);
- 📉 цена подходящего объявления упала не меньше чем на monitor.min_price_drop_percent процентов
  относительно цены, о которой уже сообщали.

При первом проходе по источнику (первый запуск, изменение условий в config.yaml, источник молчал
больше 30 дней) подходящие объявления только запоминаются — чтобы не прислать сразу сотню старых.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

from .config import Config, ConfigError, Rule, validate_interval
from .filters import matches
from .funpay import FunPaySource
from .http import FetchError
from .lolz import LolzSource
from .models import GAMES, SITES, Listing
from .notify import format_listing, format_overflow
from .storage import State
from .telegram import Telegram, esc

log = logging.getLogger(__name__)

# После скольких неудачных проверок подряд писать в Telegram, что источник не работает.
ALERT_AFTER_FAILURES = 3


@dataclass
class FetchResult:
    source_key: str  # ключ для «первого прохода»: funpay:brawl_stars:<условия>, lolz:<правило>:<запрос>:<условия>
    label: str  # для логов и /status
    listings: list[Listing] = field(default_factory=list)
    origin_rule: str | None = None  # для LolzMarket: по какому правилу был запрос
    error: str | None = None


@dataclass
class Alert:
    listing: Listing
    rules: list[str]
    kind: str  # new | now_matches | price_drop
    old_price: float | None = None
    chats: list[str] | None = None  # None — всем чатам; иначе только тем, куда раньше не дошло


class Monitor:
    def __init__(self, config: Config, telegram: Telegram, *, interval_override: float | None = None, persist: bool = True):
        self.config = config
        self.tg = telegram
        self.state = State(config.state_path, persist=persist)
        proxy = config.monitor.proxy
        self.funpay = FunPaySource(config.funpay, proxy=proxy) if config.funpay.enabled else None
        self.lolz = LolzSource(config.lolz, proxy=proxy) if config.lolz.enabled else None
        # --interval действует только на этот запуск и не сохраняется.
        self.cli_interval = interval_override
        settings = self.state.settings
        if "interval_minutes" in settings and settings.get("interval_config_base") != config.monitor.interval_minutes:
            # После /interval пользователь поменял interval_minutes в config.yaml — значит, теперь главнее конфиг.
            settings.pop("interval_minutes", None)
            settings.pop("interval_config_base", None)
        self.last_cycle_start: float | None = None
        self.last_cycle_seconds: float | None = None
        self.last_cycle_sent = 0
        self._wake = asyncio.Event()
        self._force = False
        self._cycle_lock = asyncio.Lock()
        self._currency_warned: set[str] = set()
        self._quota = config.monitor.max_notifications_per_cycle
        self._telegram_down = False

    # --- настройки, которые меняются из Telegram ---

    @property
    def interval_minutes(self) -> float:
        return self._interval()[0]

    def _interval(self) -> tuple[float, str]:
        if self.cli_interval is not None:
            return self.cli_interval, "задан при запуске (--interval)"
        value = self.state.settings.get("interval_minutes")
        if value is not None:
            try:
                return validate_interval(value), "задан командой /interval"
            except ConfigError:
                pass
        return self.config.monitor.interval_minutes, "из config.yaml"

    @property
    def paused(self) -> bool:
        return bool(self.state.settings.get("paused", False))

    async def close(self) -> None:
        for source in (self.funpay, self.lolz):
            if source:
                await source.close()

    # --- один проход ---

    def _rules_for(self, site: str) -> list[Rule]:
        return [r for r in self.config.rules if site in r.sites]

    async def _fetch_funpay(self, rules_hash: str) -> list[FetchResult]:
        results = []
        unreachable = ""
        games = sorted({r.game for r in self._rules_for("funpay")})
        for game in games:
            res = FetchResult(source_key=f"funpay:{game}:{rules_hash}", label=f"FunPay · {GAMES[game]}")
            if unreachable:
                res.error = unreachable  # сайт недоступен — не тратим время на вторую игру
                results.append(res)
                continue
            try:
                res.listings = await self.funpay.fetch(game)
            except FetchError as e:
                res.error = str(e)
                if e.unreachable:
                    unreachable = str(e)
            except Exception as e:  # неожиданная ошибка парсинга не должна ронять весь бот
                log.exception("FunPay %s: ошибка", game)
                res.error = f"{type(e).__name__}: {e}"
            results.append(res)
        return results

    async def _fetch_lolz(self, rules_hash: str) -> list[FetchResult]:
        results = []
        unreachable = ""
        for rule in self._rules_for("lolz"):
            res = FetchResult(
                source_key=f"lolz:{rule.name}:{self.lolz.query_hash(rule)}:{rules_hash}",
                label=f"Lolz · {rule.name}",
                origin_rule=rule.name,
            )
            if unreachable:
                res.error = unreachable  # сайт недоступен — не тратим время на остальные запросы
                results.append(res)
                continue
            try:
                res.listings = await self.lolz.fetch(rule)
            except FetchError as e:
                res.error = str(e)
                if e.unreachable:
                    unreachable = str(e)
            except Exception as e:
                log.exception("Lolz %s: ошибка", rule.name)
                res.error = f"{type(e).__name__}: {e}"
            results.append(res)
        return results

    async def run_cycle(self) -> int:
        """Один проход по всем источникам. Возвращает число отправленных уведомлений."""
        async with self._cycle_lock:
            started = time.monotonic()
            self.last_cycle_start = time.time()
            rules_hash = self.config.rules_hash()
            jobs = []
            if self.funpay and self._rules_for("funpay"):
                jobs.append(self._fetch_funpay(rules_hash))
            if self.lolz and self._rules_for("lolz"):
                jobs.append(self._fetch_lolz(rules_hash))
            # FunPay и Lolz опрашиваем параллельно (это разные сайты со своими лимитами), и результаты
            # каждого сайта обрабатываем сразу, не дожидаясь другого — если один сайт тормозит,
            # уведомления с другого не задерживаются.
            self._quota = self.config.monitor.max_notifications_per_cycle
            self._telegram_down = False
            # Лимит отдельных уведомлений делим между сайтами поровну; что один сайт не израсходовал,
            # достаётся следующему.
            share = -(-self._quota // max(1, len(jobs)))
            labels: set[str] = set()
            sent = 0
            for done, job in enumerate(asyncio.as_completed(jobs), start=1):
                results = await job
                labels.update(r.label for r in results)
                await self._report_health(results)
                sent += await self._process(results, self._quota if done == len(jobs) else min(share, self._quota))
            self._forget_health(labels)
            self.state.forget_old()
            self.state.save()
            self.last_cycle_seconds = time.monotonic() - started
            self.last_cycle_sent = sent
            log.info("Проверка заняла %.1f с, уведомлений: %d", self.last_cycle_seconds, sent)
            return sent

    def _decide(self, listing: Listing, matched: list[str], before: dict | None, first_run: bool) -> Alert | None:
        key = listing.key
        if before and before.get("currency") not in (None, listing.currency):
            # Сайт стал показывать цены в другой валюте — старые цены сравнивать нельзя.
            if before.get("notified_price") is not None:
                self.state.mark_notified(key, listing.price)
                return None
            before = dict(before, price=None)

        pending = before.get("pending") if before else None
        if pending:
            # В прошлый раз уведомление дошло не во все чаты — досылаем туда, куда не дошло.
            return Alert(listing, matched, pending.get("kind", "new"), pending.get("old_price"), pending.get("chats"))

        notified = before.get("notified_price") if before else None
        if notified is None:
            if first_run and not self.config.monitor.notify_on_first_run:
                self.state.mark_notified(key, listing.price)  # запомнили без уведомления
                return None
            old = before.get("price") if before else None
            if old is None or listing.price is None or listing.price >= old:
                old = None
            return Alert(listing, matched, "new" if before is None else "now_matches", old)

        if not self.config.monitor.notify_price_drop or listing.price is None or notified <= 0:
            return None
        threshold = notified * (1 - self.config.monitor.min_price_drop_percent / 100)
        if listing.price < notified and listing.price <= threshold:
            return Alert(listing, matched, "price_drop", notified)
        return None

    async def _process(self, results: list[FetchResult], quota: int | None = None) -> int:
        # Одно и то же объявление может прийти из нескольких запросов (разные правила Lolz).
        merged: dict[str, Listing] = {}
        origins: dict[str, set[str]] = {}
        sources: dict[str, set[str]] = {}
        for res in results:
            if res.error:
                continue
            for listing in res.listings:
                merged.setdefault(listing.key, listing)
                sources.setdefault(listing.key, set()).add(res.source_key)
                if res.origin_rule:
                    origins.setdefault(listing.key, set()).add(res.origin_rule)

        alerts: list[Alert] = []
        foreign_currency: set[str] = set()
        for key, listing in merged.items():
            if listing.site == "funpay" and listing.currency != "RUB":
                foreign_currency.add(listing.currency)
            before = self.state.get(key)
            before = dict(before) if before else None
            self.state.touch(key, listing.price, listing.currency)

            matched = [
                r.name for r in self.config.rules
                if matches(r, listing) and (listing.site != "lolz" or r.name in origins.get(key, ()))
            ]
            if not matched:
                if before and before.get("pending"):
                    self.state.clear_pending(key)
                continue
            first_run = all(not self.state.source_initialized(s) for s in sources[key])
            alert = self._decide(listing, matched, before, first_run)
            if alert:
                alerts.append(alert)

        for res in results:
            if not res.error:
                self.state.mark_source_ok(res.source_key)

        if foreign_currency and "funpay" not in self._currency_warned:
            self._currency_warned.add("funpay")
            await self.tg.send(
                f"⚠️ FunPay показывает цены в {esc(', '.join(sorted(foreign_currency)))}, а не в рублях. "
                f"Условия price_min/price_max для FunPay сейчас не срабатывают. Обычно так бывает, "
                f"если бот запущен с зарубежного IP. См. README, раздел «Если что-то не работает»."
            )
        return await self._deliver(alerts, self._quota if quota is None else quota)

    async def _deliver(self, alerts: list[Alert], quota: int) -> int:
        alerts = _interleave_sites(alerts)
        limit = self.config.monitor.max_notifications_per_cycle
        quota = max(0, quota)
        sent = 0
        for alert in alerts[:quota]:
            listing = alert.listing
            targets = alert.chats if alert.chats is not None else self.tg.chat_ids
            if self._telegram_down:
                # Telegram в этой проверке уже не отвечал — не ждём таймаутов на каждом сообщении,
                # а откладываем до следующей проверки.
                failed = set(targets)
            else:
                failed = await self.tg.send(
                    format_listing(listing, alert.rules, alert.kind, alert.old_price),
                    chats=alert.chats,
                    button=("Открыть объявление", listing.url),
                )
                if targets and len(failed) == len(targets):
                    self._telegram_down = True
            self.state.mark_notified(listing.key, listing.price)
            if failed:
                self.state.set_pending(listing.key, sorted(failed), alert.kind, alert.old_price)
            if len(failed) < len(targets):
                sent += 1
            # Сохраняем сразу: если бота остановят посреди рассылки, после перезапуска не будет повторов.
            self.state.save()
        self._quota -= min(quota, len(alerts))

        overflow = alerts[quota:]
        if overflow and not self._telegram_down:
            for chunk_text, chunk in format_overflow([(a.listing, a.old_price) for a in overflow], limit):
                failed = await self.tg.send(chunk_text)
                if len(failed) < len(self.tg.chat_ids):
                    for listing, _old in chunk:
                        self.state.mark_notified(listing.key, listing.price)
                # Не дошло никуда — эти объявления придут в следующий раз как «теперь подходит».
            self.state.save()
        return sent

    async def _report_health(self, results: list[FetchResult]) -> None:
        for res in results:
            h = self.state.health.setdefault(res.label, {"failures": 0, "alerted": False, "last_error": "", "last_count": 0})
            if res.error:
                h["failures"] = h.get("failures", 0) + 1
                h["last_error"] = res.error
                log.warning("%s: %s", res.label, res.error)
                if h["failures"] >= ALERT_AFTER_FAILURES and not h.get("alerted"):
                    h["alerted"] = True
                    await self.tg.send(
                        f"⚠️ <b>{esc(res.label)}</b> не отвечает уже {h['failures']} проверки подряд.\n"
                        f"<code>{esc(res.error[:500])}</code>"
                    )
            else:
                if h.get("alerted"):
                    await self.tg.send(f"✅ <b>{esc(res.label)}</b> снова работает.")
                h.update(failures=0, alerted=False, last_error="", last_count=len(res.listings))
                log.info("%s: объявлений в выдаче: %d", res.label, len(res.listings))

    def _forget_health(self, current: set[str]) -> None:
        """Источники, которых больше нет в конфиге, убираем из /status."""
        if current:
            for label in [k for k in self.state.health if k not in current]:
                self.state.health.pop(label, None)

    # --- бесконечный режим ---

    async def run_forever(self) -> None:
        poller = None
        if self.config.telegram.commands:
            poller = asyncio.create_task(self.tg.poll_commands(self.handle_command))
            poller.add_done_callback(_log_poller_exit)
        try:
            forced = False
            while True:
                if forced or not self.paused:
                    try:
                        await self.run_cycle()
                    except Exception:
                        log.exception("Ошибка в цикле проверки")
                forced = await self._sleep_until_next()
        finally:
            if poller:
                poller.cancel()

    async def _sleep_until_next(self) -> bool:
        """Ждёт до следующей проверки. True — если разбудили командой /check или /resume."""
        # ±10% случайного разброса, чтобы обращения к сайтам не шли строго по часам.
        jitter = random.uniform(0.9, 1.1)
        start = time.monotonic()
        while True:
            if self._force:
                self._force = False
                return True
            remaining = start + self.interval_minutes * 60 * jitter - time.monotonic()
            if remaining <= 0:
                return False
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return False
            # Проснулись по команде (/check, /interval, /resume) — пересчитываем ожидание.

    def _poke(self, force: bool = False) -> None:
        self._force = self._force or force
        self._wake.set()

    # --- команды Telegram ---

    async def handle_command(self, chat_id: str, command: str, args: list[str]) -> None:
        async def reply(text: str) -> None:
            await self.tg.send(text, chat_id=chat_id)

        if command in ("start", "help"):
            await reply(HELP_TEXT.format(interval=_fmt_minutes(self.interval_minutes)))
        elif command == "interval":
            if not args:
                value, source = self._interval()
                await reply(f"Сейчас проверка раз в <b>{_fmt_minutes(value)}</b> ({source}).\n"
                            f"Изменить: /interval 10 (в минутах), вернуть значение из config.yaml: /interval reset")
                return
            if args[0].lower() in ("reset", "сброс"):
                self.state.settings.pop("interval_minutes", None)
                self.state.settings.pop("interval_config_base", None)
            else:
                try:
                    self.state.settings["interval_minutes"] = validate_interval(args[0].replace(",", "."))
                except ConfigError as e:
                    await reply(f"❌ {esc(e)}")
                    return
                self.state.settings["interval_config_base"] = self.config.monitor.interval_minutes
            self.cli_interval = None  # последняя команда главнее флага --interval
            self.state.save()
            self._poke()
            value, source = self._interval()
            await reply(f"✅ Теперь проверка раз в <b>{_fmt_minutes(value)}</b> ({source}).")
        elif command == "pause":
            self.state.settings["paused"] = True
            self.state.save()
            await reply("⏸ Мониторинг на паузе (пауза сохранится и после перезапуска). Продолжить: /resume")
        elif command == "resume":
            self.state.settings["paused"] = False
            self.state.save()
            self._poke(force=True)
            await reply("▶️ Мониторинг продолжен, проверяю сейчас.")
        elif command == "check":
            if self._cycle_lock.locked():
                await reply("⏳ Проверка уже идёт.")
                return
            await reply("🔎 Проверяю сейчас…")
            self._poke(force=True)
        elif command == "status":
            await reply(self.status_text())
        elif command == "rules":
            await reply(self._rules_text())
        else:
            await reply("Неизвестная команда. Список команд: /help")

    def status_text(self) -> str:
        value, source = self._interval()
        lines = [
            "⏸ <b>На паузе</b> (продолжить: /resume)" if self.paused else "▶️ <b>Работает</b>",
            f"Интервал: {_fmt_minutes(value)} ({source})",
        ]
        if self.last_cycle_start:
            ago = int((time.time() - self.last_cycle_start) // 60)
            lines.append(f"Последняя проверка: {ago} мин назад, заняла {self.last_cycle_seconds or 0:.0f} с, "
                         f"уведомлений: {self.last_cycle_sent}")
        else:
            lines.append("С момента запуска проверок ещё не было.")
        lines.append(f"Объявлений в памяти: {len(self.state.seen)}")
        for label, h in self.state.health.items():
            if not h.get("failures"):
                lines.append(f"✅ {esc(label)}: {h.get('last_count', 0)} в выдаче")
            else:
                lines.append(f"❌ {esc(label)}: ошибка {h['failures']} раз подряд — "
                             f"<code>{esc(str(h.get('last_error', ''))[:200])}</code>")
        return "\n".join(lines)

    def _rules_text(self) -> str:
        lines = ["<b>Условия из config.yaml:</b>"]
        for r in self.config.rules:
            parts = [GAMES[r.game], "/".join(SITES[s] for s in r.sites)]
            if r.price_min is not None or r.price_max is not None:
                parts.append(f"цена {r.price_min or 0:g}–{r.price_max if r.price_max is not None else '∞'} ₽")
            if r.trophies_min is not None or r.trophies_max is not None:
                parts.append(f"кубки {r.trophies_min or 0}–{r.trophies_max if r.trophies_max is not None else '∞'}")
            if r.brawlers_min is not None:
                parts.append(f"бравлеров ≥ {r.brawlers_min}")
            if r.level_min is not None:
                parts.append(f"уровень ≥ {r.level_min}")
            if r.include_all:
                parts.append("все слова: " + ", ".join(r.include_all))
            if r.include_any:
                parts.append("любое слово: " + ", ".join(r.include_any))
            if r.exclude:
                parts.append("без слов: " + ", ".join(r.exclude))
            lines.append(f"• <b>{esc(r.name)}</b>: {esc('; '.join(parts))}")
        return "\n".join(lines)


def _interleave_sites(alerts: list[Alert]) -> list[Alert]:
    """Чередуем сайты, чтобы при лимите уведомлений FunPay не вытеснял LolzMarket целиком."""
    queues: dict[str, list[Alert]] = {}
    for a in alerts:
        queues.setdefault(a.listing.site, []).append(a)
    result: list[Alert] = []
    while any(queues.values()):
        for q in queues.values():
            if q:
                result.append(q.pop(0))
    return result


def _log_poller_exit(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        log.error("Приём команд Telegram остановился из-за ошибки", exc_info=task.exception())


def _fmt_minutes(minutes: float) -> str:
    return f"{minutes:g} мин"


HELP_TEXT = """<b>Мониторинг аккаунтов Brawl Stars и Clash Royale</b> (FunPay, LolzMarket)

/status — состояние и последняя проверка
/interval — текущий интервал проверки
/interval 10 — проверять раз в 10 минут (сохраняется и после перезапуска)
/interval reset — вернуть интервал из config.yaml
/check — проверить прямо сейчас
/pause, /resume — приостановить и продолжить (пауза сохраняется и после перезапуска)
/rules — какие условия заданы

Сейчас проверка раз в {interval}. Сами условия меняются в config.yaml (после правки перезапустите бота)."""
