"""Цикл мониторинга: опрос сайтов, отбор по правилам, уведомления, команды бота."""

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
from .notify import format_listing
from .storage import State
from .telegram import Telegram, esc

log = logging.getLogger(__name__)

# После скольких неудачных проверок подряд писать в Telegram, что источник не работает.
ALERT_AFTER_FAILURES = 3


@dataclass
class SourceStatus:
    ok: bool = True
    failures: int = 0
    alerted: bool = False
    last_count: int = 0
    last_error: str = ""


@dataclass
class FetchResult:
    source_key: str  # ключ для «первого прохода»: funpay:brawl_stars, lolz:<правило>:<хэш запроса>
    label: str  # для логов и /status
    listings: list[Listing] = field(default_factory=list)
    origin_rule: str | None = None  # для LolzMarket: по какому правилу был запрос
    error: str | None = None


class Monitor:
    def __init__(self, config: Config, telegram: Telegram, *, interval_override: float | None = None):
        self.config = config
        self.tg = telegram
        self.state = State(config.state_path)
        proxy = config.monitor.proxy
        self.funpay = FunPaySource(config.funpay, proxy=proxy) if config.funpay.enabled else None
        self.lolz = LolzSource(config.lolz, proxy=proxy) if config.lolz.enabled else None
        if interval_override is not None:
            self.state.settings["interval_minutes"] = interval_override
        self.status: dict[str, SourceStatus] = {}
        self.last_cycle_start: float | None = None
        self.last_cycle_seconds: float | None = None
        self.last_cycle_sent = 0
        self._wake = asyncio.Event()
        self._force = False
        self._cycle_lock = asyncio.Lock()

    # --- настройки, которые меняются из Telegram ---

    @property
    def interval_minutes(self) -> float:
        value = self.state.settings.get("interval_minutes")
        if value is None:
            return self.config.monitor.interval_minutes
        try:
            return validate_interval(value)
        except ConfigError:
            return self.config.monitor.interval_minutes

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

    async def _fetch_funpay(self) -> list[FetchResult]:
        results = []
        games = sorted({r.game for r in self._rules_for("funpay")})
        for game in games:
            res = FetchResult(source_key=f"funpay:{game}", label=f"FunPay · {GAMES[game]}")
            try:
                res.listings = await self.funpay.fetch(game)
            except FetchError as e:
                res.error = str(e)
            except Exception as e:  # неожиданная ошибка парсинга не должна ронять весь бот
                log.exception("FunPay %s: ошибка", game)
                res.error = f"{type(e).__name__}: {e}"
            results.append(res)
        return results

    async def _fetch_lolz(self) -> list[FetchResult]:
        results = []
        for rule in self._rules_for("lolz"):
            res = FetchResult(
                source_key=f"lolz:{rule.name}:{self.lolz.query_hash(rule)}",
                label=f"Lolz · {rule.name}",
                origin_rule=rule.name,
            )
            try:
                res.listings = await self.lolz.fetch(rule)
            except FetchError as e:
                res.error = str(e)
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
            jobs = []
            if self.funpay and self._rules_for("funpay"):
                jobs.append(self._fetch_funpay())
            if self.lolz and self._rules_for("lolz"):
                jobs.append(self._fetch_lolz())
            # FunPay и Lolz опрашиваем параллельно: это разные сайты со своими лимитами.
            results = [r for group in await asyncio.gather(*jobs) for r in group]
            await self._report_health(results)
            sent = await self._process(results)
            self.state.save()
            self.last_cycle_seconds = time.monotonic() - started
            self.last_cycle_sent = sent
            log.info("Проверка заняла %.1f с, уведомлений: %d", self.last_cycle_seconds, sent)
            return sent

    async def _process(self, results: list[FetchResult]) -> int:
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

        to_send: list[tuple[Listing, list[str], float | None]] = []
        for key, listing in merged.items():
            before = self.state.get(key)
            before = dict(before) if before else None
            self.state.touch(key, listing.price)

            matched = [
                r.name for r in self.config.rules
                if matches(r, listing) and (listing.site != "lolz" or r.name in origins.get(key, ()))
            ]
            if not matched:
                continue

            if before is None:
                first_run = all(s not in self.state.initialized for s in sources[key])
                if first_run and not self.config.monitor.notify_on_first_run:
                    continue
                to_send.append((listing, matched, None))
                continue

            if before.get("pending"):
                # В прошлый раз уведомление не дошло — повторяем.
                to_send.append((listing, matched, None))
                continue

            if not self.config.monitor.notify_price_drop or listing.price is None:
                continue
            notified = before.get("notified_price")
            reference = before.get("price") if notified is None else notified
            # notified == -1: уже уведомляли, но цена тогда была неизвестна.
            if reference is not None and reference > 0 and listing.price < reference:
                to_send.append((listing, matched, reference))

        for res in results:
            if not res.error:
                self.state.initialized.add(res.source_key)

        limit = self.config.monitor.max_notifications_per_cycle
        sent = 0
        for listing, rule_names, old_price in to_send[:limit]:
            delivered = await self.tg.send(
                format_listing(listing, rule_names, old_price),
                button=("Открыть объявление", listing.url),
            )
            if delivered:
                self.state.mark_notified(listing.key, listing.price)
                sent += 1
            else:
                self.state.mark_pending(listing.key)
        skipped = to_send[limit:]
        if skipped:
            for listing, _, _ in skipped:
                self.state.mark_notified(listing.key, listing.price)
            await self.tg.send(
                f"…и ещё {len(skipped)} подходящих объявлений. Лимит — {limit} уведомлений за проверку "
                f"(monitor.max_notifications_per_cycle). Сузьте условия, если их слишком много."
            )
        return sent

    async def _report_health(self, results: list[FetchResult]) -> None:
        for res in results:
            st = self.status.setdefault(res.label, SourceStatus())
            if res.error:
                st.ok = False
                st.failures += 1
                st.last_error = res.error
                log.warning("%s: %s", res.label, res.error)
                if st.failures >= ALERT_AFTER_FAILURES and not st.alerted:
                    st.alerted = True
                    await self.tg.send(
                        f"⚠️ <b>{esc(res.label)}</b> не отвечает уже {st.failures} проверки подряд.\n"
                        f"<code>{esc(res.error[:500])}</code>"
                    )
            else:
                if st.alerted:
                    await self.tg.send(f"✅ <b>{esc(res.label)}</b> снова работает.")
                st.ok, st.failures, st.alerted, st.last_error = True, 0, False, ""
                st.last_count = len(res.listings)
                log.info("%s: объявлений в выдаче: %d", res.label, st.last_count)

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
        reply = lambda text: self.tg.send(text, chat_id=chat_id)  # noqa: E731

        if command in ("start", "help"):
            await reply(HELP_TEXT.format(interval=_fmt_minutes(self.interval_minutes)))
        elif command == "interval":
            if not args:
                await reply(f"Сейчас проверка раз в <b>{_fmt_minutes(self.interval_minutes)}</b>.\n"
                            f"Изменить: /interval 10 (в минутах), вернуть значение из конфига: /interval reset")
                return
            if args[0].lower() in ("reset", "сброс"):
                self.state.settings.pop("interval_minutes", None)
            else:
                try:
                    self.state.settings["interval_minutes"] = validate_interval(args[0].replace(",", "."))
                except ConfigError as e:
                    await reply(f"❌ {esc(e)}")
                    return
            self.state.save()
            self._poke()
            await reply(f"✅ Теперь проверка раз в <b>{_fmt_minutes(self.interval_minutes)}</b>.")
        elif command == "pause":
            self.state.settings["paused"] = True
            self.state.save()
            await reply("⏸ Мониторинг на паузе. Продолжить: /resume")
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
            await reply(self._status_text())
        elif command == "rules":
            await reply(self._rules_text())
        else:
            await reply("Неизвестная команда. Список команд: /help")

    def _status_text(self) -> str:
        lines = [
            "⏸ <b>На паузе</b>" if self.paused else "▶️ <b>Работает</b>",
            f"Интервал: {_fmt_minutes(self.interval_minutes)}",
        ]
        if self.last_cycle_start:
            ago = int((time.time() - self.last_cycle_start) // 60)
            lines.append(f"Последняя проверка: {ago} мин назад, заняла {self.last_cycle_seconds or 0:.0f} с, "
                         f"уведомлений: {self.last_cycle_sent}")
        else:
            lines.append("Проверок ещё не было.")
        lines.append(f"Объявлений в памяти: {len(self.state.seen)}")
        for label, st in self.status.items():
            if st.ok:
                lines.append(f"✅ {esc(label)}: {st.last_count} в выдаче")
            else:
                lines.append(f"❌ {esc(label)}: ошибка {st.failures} раз подряд — <code>{esc(st.last_error[:200])}</code>")
        return "\n".join(lines)

    def _rules_text(self) -> str:
        lines = ["<b>Условия из config.yaml:</b>"]
        for r in self.config.rules:
            parts = [GAMES[r.game], "/".join(SITES[s] for s in r.sites)]
            if r.price_min is not None or r.price_max is not None:
                parts.append(f"цена {r.price_min or 0:g}–{r.price_max if r.price_max is not None else '∞'}")
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


def _log_poller_exit(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        log.error("Приём команд Telegram остановился из-за ошибки", exc_info=task.exception())


def _fmt_minutes(minutes: float) -> str:
    return f"{minutes:g} мин"


HELP_TEXT = """<b>Мониторинг аккаунтов Brawl Stars и Clash Royale</b> (FunPay, LolzMarket)

/status — состояние и последняя проверка
/interval — текущий интервал проверки
/interval 10 — проверять раз в 10 минут
/interval reset — вернуть интервал из config.yaml
/check — проверить прямо сейчас
/pause, /resume — приостановить и продолжить
/rules — какие условия заданы

Сейчас проверка раз в {interval}. Сами условия меняются в config.yaml (после правки перезапустите бота)."""
