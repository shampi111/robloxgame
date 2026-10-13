"""Мониторинг аккаунтов Brawl Stars и Clash Royale на FunPay и LolzMarket с уведомлениями в Telegram.

Запуск:
    python main.py                      # работать постоянно
    python main.py --once               # одна проверка и выход
    python main.py --once --dry-run     # одна проверка, уведомления печатаются в консоль вместо Telegram
    python main.py --interval 10        # интервал 10 минут (перекрывает config.yaml и команду /interval)
    python main.py --test-telegram      # проверить токен бота и chat_id
    python main.py --inspect-funpay     # показать, что парсер видит на страницах FunPay (для отладки)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from parser_bot.config import ConfigError, load_config, validate_interval
from parser_bot.funpay import FunPaySource, category_url, describe_page
from parser_bot.http import FetchError
from parser_bot.lolz import token_problems
from parser_bot.monitor import Monitor
from parser_bot.telegram import Telegram, TelegramError


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


async def run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.inspect_funpay:
        return await inspect_funpay(config)
    telegram = Telegram(
        config.telegram.bot_token,
        config.telegram.chat_ids,
        proxy=config.telegram.proxy,
        dry_run=args.dry_run,
    )
    log = logging.getLogger("main")
    try:
        if args.test_telegram:
            name = await telegram.check()
            await telegram.send(f"✅ Бот {name} подключён. Уведомления будут приходить сюда.")
            log.info("Telegram работает: %s. Проверьте сообщение в чате.", name)
            return 0

        if not args.dry_run:
            try:
                name = await telegram.check()
                log.info("Telegram-бот: %s", name)
            except TelegramError as e:
                log.error("Telegram не отвечает: %s. Проверьте telegram.bot_token.", e)
                return 2

        if config.lolz.enabled and any("lolz" in r.sites for r in config.rules):
            for problem in token_problems(config.lolz.token):
                log.warning("%s", problem)

        interval = validate_interval(args.interval) if args.interval is not None else None
        monitor = Monitor(config, telegram, interval_override=interval)
        try:
            if args.once:
                sent = await monitor.run_cycle()
                log.info("Готово, отправлено уведомлений: %d", sent)
                return 0
            log.info("Мониторинг запущен, интервал %g мин. Остановить: Ctrl+C", monitor.interval_minutes)
            if not args.dry_run:
                await telegram.send(
                    f"▶️ Мониторинг запущен, проверка раз в {monitor.interval_minutes:g} мин. Команды: /help"
                )
            await monitor.run_forever()
        finally:
            await monitor.close()
    finally:
        await telegram.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Мониторинг аккаунтов BS/CR на FunPay и LolzMarket")
    parser.add_argument("-c", "--config", default="config.yaml", help="путь к конфигу (по умолчанию config.yaml)")
    parser.add_argument("--once", action="store_true", help="одна проверка и выход")
    parser.add_argument("--dry-run", action="store_true", help="не слать в Telegram, а печатать в консоль")
    parser.add_argument("--interval", type=float, help="интервал проверки в минутах")
    parser.add_argument("--test-telegram", action="store_true", help="отправить тестовое сообщение и выйти")
    parser.add_argument("--inspect-funpay", action="store_true", help="показать, что парсер видит на FunPay, и выйти")
    parser.add_argument("-v", "--verbose", action="store_true", help="подробный лог")
    parser.add_argument("--log-file", type=Path, default=None, help="писать лог ещё и в файл")
    args = parser.parse_args()

    setup_logging(args.verbose, args.log_file)
    try:
        return asyncio.run(run(args))
    except ConfigError as e:
        logging.getLogger("main").error("Ошибка конфига: %s", e)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
