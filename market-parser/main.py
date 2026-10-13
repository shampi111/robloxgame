"""Мониторинг аккаунтов Brawl Stars и Clash Royale на FunPay и LolzMarket с уведомлениями в Telegram.

Запуск:
    python main.py                      # работать постоянно
    python main.py --once               # одна проверка и выход
    python main.py --once --dry-run     # одна проверка без Telegram: уведомления печатаются в консоль,
                                        # state.json не меняется (можно спокойно пробовать условия)
    python main.py --interval 10        # интервал 10 минут только на этот запуск (главнее config.yaml и /interval)
    python main.py --test-telegram      # проверить токен бота и chat_id
    python main.py --inspect-funpay     # показать, что парсер видит на страницах FunPay (для отладки)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from parser_bot.config import ConfigError, load_config, validate_interval
from parser_bot.funpay import FunPaySource, category_url, describe_page
from parser_bot.http import FetchError
from parser_bot.lolz import token_problems
from parser_bot.monitor import Monitor
from parser_bot.telegram import Telegram, TelegramError, explain

log = logging.getLogger("main")


def setup_console() -> None:
    # В консоли Windows (cp1251/cp866) и при выводе в файл эмодзи и «₽» иначе роняют программу.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def setup_logging(verbose: bool, log_file: Path | None) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    if log_file:
        fh = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    # httpx пишет каждый запрос (вместе с токеном Telegram в URL) — оставляем только предупреждения.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def inspect_funpay(config) -> int:
    source = FunPaySource(config.funpay, proxy=config.monitor.proxy)
    try:
        for game in sorted({r.game for r in config.rules if "funpay" in r.sites}) or ["brawl_stars", "clash_royale"]:
            print(f"\n===== {game} =====")
            try:
                category = await source.category_id(game)
                print(category_url(category))
                print(describe_page(await source.fetch_html(game), game))
            except FetchError as e:
                print(f"Ошибка: {e}")
    finally:
        await source.close()
    return 0


async def test_telegram(telegram: Telegram) -> int:
    try:
        name = await telegram.check()
    except TelegramError as e:
        log.error("Telegram: %s", explain(e))
        return 2
    errors = await telegram.send_test(f"✅ Бот {name} подключён. Уведомления будут приходить сюда.")
    for chat, problem in errors.items():
        log.error("Чат %s: %s", chat, problem)
    if errors:
        return 2
    log.info("Telegram работает: %s. Проверьте сообщение в чате.", name)
    return 0


async def run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.inspect_funpay:
        return await inspect_funpay(config)
    interval = validate_interval(args.interval) if args.interval is not None else None
    telegram = Telegram(config.telegram.bot_token, config.telegram.chat_ids, proxy=config.telegram.proxy, dry_run=args.dry_run)
    try:
        if args.test_telegram:
            return await test_telegram(telegram)

        if not args.dry_run:
            try:
                log.info("Telegram-бот: %s", await telegram.check())
            except TelegramError as e:
                log.error("Telegram: %s", explain(e))
                return 2

        if config.lolz.enabled and any("lolz" in r.sites for r in config.rules):
            for problem in token_problems(config.lolz.token):
                log.warning("%s", problem)

        # В пробном режиме (--dry-run) ничего не запоминаем, чтобы потом настоящие уведомления пришли.
        monitor = Monitor(config, telegram, interval_override=interval, persist=not args.dry_run)
        try:
            if args.once:
                sent = await monitor.run_cycle()
                log.info("Готово, отправлено уведомлений: %d", sent)
                return 0
            commands = " Команды: /help" if config.telegram.commands else ""
            if monitor.paused:
                text = "⏸ Бот запущен, но стоит на паузе (включена командой /pause)."
                text += " Продолжить: /resume" if config.telegram.commands else " Удалите \"paused\" из state.json."
            else:
                text = f"▶️ Мониторинг запущен, проверка раз в {monitor.interval_minutes:g} мин.{commands}"
            log.info("%s Остановить: Ctrl+C", text)
            if not args.dry_run:
                await telegram.send(text)
            await monitor.run_forever()
        finally:
            await monitor.close()
    finally:
        await telegram.close()
    return 0


async def run_until_stopped(args: argparse.Namespace) -> int:
    # systemd / docker останавливают процесс сигналом SIGTERM — завершаемся аккуратно, как по Ctrl+C.
    task = asyncio.current_task()
    if task is not None and hasattr(signal, "SIGTERM"):
        try:
            asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
        except (NotImplementedError, RuntimeError):
            pass  # Windows
    try:
        return await run(args)
    except asyncio.CancelledError:
        log.info("Остановлено.")
        return 0


def main() -> int:
    setup_console()
    parser = argparse.ArgumentParser(description="Мониторинг аккаунтов BS/CR на FunPay и LolzMarket")
    parser.add_argument("-c", "--config", default="config.yaml", help="путь к конфигу (по умолчанию config.yaml)")
    parser.add_argument("--once", action="store_true", help="одна проверка и выход")
    parser.add_argument("--dry-run", action="store_true", help="не слать в Telegram, а печатать в консоль; ничего не запоминать")
    parser.add_argument("--interval", type=float, help="интервал проверки в минутах (только на этот запуск)")
    parser.add_argument("--test-telegram", action="store_true", help="отправить тестовое сообщение и выйти")
    parser.add_argument("--inspect-funpay", action="store_true", help="показать, что парсер видит на FunPay, и выйти")
    parser.add_argument("-v", "--verbose", action="store_true", help="подробный лог")
    parser.add_argument("--log-file", type=Path, default=None, help="писать лог ещё и в файл")
    args = parser.parse_args()

    setup_logging(args.verbose, args.log_file)
    try:
        return asyncio.run(run_until_stopped(args))
    except ConfigError as e:
        log.error("Ошибка конфига: %s", e)
        return 2
    except ImportError as e:
        if "socksio" in str(e):
            log.error("Для socks5-прокси нужен пакет: python -m pip install \"httpx[socks]\"")
        else:
            log.error("Не установлены зависимости (%s). Выполните: python -m pip install -r requirements.txt", e)
        return 2
    except KeyboardInterrupt:
        log.info("Остановлено.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
