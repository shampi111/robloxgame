import asyncio
import json

from parser_bot.config import Config, FunPayConfig, LolzConfig, MonitorConfig, Rule, TelegramConfig
from parser_bot.http import FetchError
from parser_bot.models import Listing
from parser_bot.monitor import Monitor
from parser_bot.storage import FORGET_AFTER_SECONDS


class FakeTelegram:
    def __init__(self, chat_ids=("1",)):
        self.chat_ids = list(chat_ids)
        self.sent = []  # (chat, text, button)
        self.down = set()  # чаты, куда временно не доходит

    async def send(self, text, *, chat_id=None, chats=None, button=None):
        targets = [chat_id] if chat_id else (chats if chats is not None else self.chat_ids)
        failed = set()
        for t in targets:
            if t in self.down:
                failed.add(t)
            else:
                self.sent.append((t, text, button))
        return failed

    def texts(self, chat="1"):
        return [t for c, t, _ in self.sent if c == chat]

    async def close(self):
        pass


class FakeFunPay:
    def __init__(self):
        self.data = {}
        self.error = None

    async def fetch(self, game):
        if self.error:
            raise FetchError(self.error)
        return list(self.data.get(game, []))

    async def close(self):
        pass


class FakeLolz:
    def __init__(self):
        self.data = {}
        self.error = None
        self.calls = 0

    @staticmethod
    def query_hash(rule):
        return "h"

    async def fetch(self, rule):
        self.calls += 1
        if self.error:
            raise self.error
        return list(self.data.get(rule.name, []))

    async def close(self):
        pass


def fp(id_, price, text="акк 40к кубков", game="brawl_stars", currency="RUB"):
    return Listing(site="funpay", game=game, id=id_, url=f"https://funpay.com/lots/offer?id={id_}",
                   title=text, price=price, currency=currency, trophies=40000 if "40к" in text else None, seller="s",
                   seller_online=True, seller_reviews=50, seller_rating=5)


def lz(id_, price, game="brawl_stars"):
    return Listing(site="lolz", game=game, id=id_, url=f"https://lzt.market/{id_}/", title="lolz", price=price)


def make(tmp_path, rules, chat_ids=("1",), persist=True, **monitor_kw):
    cfg = Config(
        telegram=TelegramConfig(bot_token="1:x", chat_ids=list(chat_ids)),
        monitor=MonitorConfig(state_file=str(tmp_path / "state.json"), **monitor_kw),
        funpay=FunPayConfig(enabled=False),
        lolz=LolzConfig(enabled=False, token="t"),
        rules=rules,
        base_dir=tmp_path,
    )
    tg = FakeTelegram(chat_ids)
    m = Monitor(cfg, tg, persist=persist)
    m.funpay, m.lolz = FakeFunPay(), FakeLolz()
    m.rates = FakeRates()
    return m, tg


class FakeRates:
    def __init__(self, rates=None):
        self.rates = rates or {}

    async def to_rub(self, amount, currency):
        rate = self.rates.get(currency)
        return round(amount * rate, 2) if rate else None


def run(coro):
    return asyncio.run(coro)


BS = Rule(name="bs", game="brawl_stars", sites=["funpay"], price_max=1000)


def test_first_run_is_silent_then_new_items_notify(tmp_path):
    m, tg = make(tmp_path, [BS])
    m.funpay.data["brawl_stars"] = [fp("1", 500), fp("2", 5000)]
    assert run(m.run_cycle()) == 0  # первый проход только запоминает

    m.funpay.data["brawl_stars"] = [fp("1", 500), fp("2", 5000), fp("3", 900), fp("4", 2000)]
    assert run(m.run_cycle()) == 1
    assert "id=3" in tg.sent[-1][1] and "Новое объявление" in tg.sent[-1][1]
    assert tg.sent[-1][2] == ("Открыть объявление", "https://funpay.com/lots/offer?id=3")
    assert run(m.run_cycle()) == 0  # повторно не шлёт


def test_notify_on_first_run_option(tmp_path):
    m, tg = make(tmp_path, [BS], notify_on_first_run=True)
    m.funpay.data["brawl_stars"] = [fp("1", 500)]
    assert run(m.run_cycle()) == 1


def test_price_drop_uses_fixed_reference_and_threshold(tmp_path):
    m, tg = make(tmp_path, [BS], min_price_drop_percent=5)
    m.funpay.data["brawl_stars"] = []
    run(m.run_cycle())
    m.funpay.data["brawl_stars"] = [fp("1", 900)]
    assert run(m.run_cycle()) == 1  # новое
    for price in (899.99, 880, 860):  # меньше 5% от 900 в сумме — молчим
        m.funpay.data["brawl_stars"] = [fp("1", price)]
        assert run(m.run_cycle()) == 0
    m.funpay.data["brawl_stars"] = [fp("1", 850)]  # 850 ≤ 900·0,95 — снижение
    assert run(m.run_cycle()) == 1
    assert "Цена снижена" in tg.sent[-1][1] and "900" in tg.sent[-1][1]
    m.funpay.data["brawl_stars"] = [fp("1", 900)]  # подорожало — молчим
    assert run(m.run_cycle()) == 0


def test_price_drop_after_first_run_baseline(tmp_path):
    m, tg = make(tmp_path, [BS])
    m.funpay.data["brawl_stars"] = [fp("1", 1000)]
    run(m.run_cycle())  # запомнили без уведомления по цене 1000
    m.funpay.data["brawl_stars"] = [fp("1", 800)]
    assert run(m.run_cycle()) == 1
    assert "Цена снижена" in tg.sent[-1][1]


def test_listing_that_starts_matching_later(tmp_path):
    rule = Rule(name="bs", game="brawl_stars", sites=["funpay"], include_any=["почта"])
    m, tg = make(tmp_path, [rule])
    m.funpay.data["brawl_stars"] = []
    run(m.run_cycle())
    m.funpay.data["brawl_stars"] = [fp("1", 500, "акк")]
    assert run(m.run_cycle()) == 0  # пока не подходит
    m.funpay.data["brawl_stars"] = [fp("1", 500, "акк, родная почта")]  # продавец дописал описание
    assert run(m.run_cycle()) == 1
    assert "Теперь подходит" in tg.sent[-1][1]
    assert run(m.run_cycle()) == 0


def test_became_cheaper_and_matches_is_reported(tmp_path):
    m, tg = make(tmp_path, [BS])
    m.funpay.data["brawl_stars"] = []
    run(m.run_cycle())
    m.funpay.data["brawl_stars"] = [fp("1", 1500)]  # новое, но дороже лимита
    assert run(m.run_cycle()) == 0
    m.funpay.data["brawl_stars"] = [fp("1", 800)]
    assert run(m.run_cycle()) == 1
    assert "Теперь подходит" in tg.sent[-1][1] and "1 500" in tg.sent[-1][1]


def test_price_drop_can_be_disabled(tmp_path):
    m, tg = make(tmp_path, [BS], notify_price_drop=False)
    m.funpay.data["brawl_stars"] = [fp("1", 900)]
    run(m.run_cycle())
    m.funpay.data["brawl_stars"] = [fp("1", 100)]
    assert run(m.run_cycle()) == 0


def test_state_survives_restart(tmp_path):
    m, _ = make(tmp_path, [BS])
    m.funpay.data["brawl_stars"] = [fp("1", 500)]
    run(m.run_cycle())
    m2, tg2 = make(tmp_path, [BS])
    m2.funpay.data["brawl_stars"] = [fp("1", 500), fp("2", 600)]
    assert run(m2.run_cycle()) == 1
    assert "id=2" in tg2.sent[-1][1]


def test_changing_rules_starts_new_baseline(tmp_path):
    m, _ = make(tmp_path, [BS])
    m.funpay.data["brawl_stars"] = [fp("1", 1500), fp("2", 500)]
    run(m.run_cycle())
    wider = Rule(name="bs", game="brawl_stars", sites=["funpay"], price_max=2000)
    m2, tg2 = make(tmp_path, [wider])
    m2.funpay.data["brawl_stars"] = [fp("1", 1500), fp("2", 500)]
    assert run(m2.run_cycle()) == 0  # условия поменяли — старые объявления не сыплются
    m2.funpay.data["brawl_stars"] = [fp("1", 1500), fp("2", 500), fp("3", 1900)]
    assert run(m2.run_cycle()) == 1


def test_failed_source_does_not_count_as_first_run(tmp_path):
    m, tg = make(tmp_path, [BS])
    m.funpay.error = "HTTP 403"
    for _ in range(3):
        run(m.run_cycle())
    assert any("не отвечает" in t for t in tg.texts())  # предупреждение после 3 ошибок подряд
    m.funpay.error = None
    m.funpay.data["brawl_stars"] = [fp("1", 500)]
    assert run(m.run_cycle()) == 0  # первый удачный проход — тоже только запоминает
    assert any("снова работает" in t for t in tg.texts())


def test_failure_counter_survives_restarts(tmp_path):
    # Режим --once из планировщика: каждая проверка — новый процесс.
    for _ in range(3):
        m, tg = make(tmp_path, [BS])
        m.funpay.error = "HTTP 403"
        run(m.run_cycle())
    assert any("не отвечает уже 3" in t for t in tg.texts())


def test_long_silence_does_not_flood(tmp_path, monkeypatch):
    import parser_bot.storage as storage

    m, tg = make(tmp_path, [BS])
    m.funpay.data["brawl_stars"] = [fp(str(i), 500) for i in range(5)]
    run(m.run_cycle())
    real_time = storage.time.time
    monkeypatch.setattr(storage.time, "time", lambda: real_time() + FORGET_AFTER_SECONDS + 3600)
    m2, tg2 = make(tmp_path, [BS])
    m2.funpay.data["brawl_stars"] = [fp(str(i), 500) for i in range(10)]
    assert run(m2.run_cycle()) == 0  # источник молчал больше 30 дней — заново только запоминаем


def test_pause_resume_does_not_forget(tmp_path):
    m, tg = make(tmp_path, [BS])
    m.funpay.data["brawl_stars"] = [fp("1", 500)]
    run(m.run_cycle())
    run(m.handle_command("1", "pause", []))
    run(m.handle_command("1", "resume", []))
    assert m.state.get("funpay:brawl_stars:1") is not None


def test_cap_per_cycle_sends_summary(tmp_path):
    m, tg = make(tmp_path, [Rule(name="bs", game="brawl_stars", sites=["funpay"])],
                 notify_on_first_run=True, max_notifications_per_cycle=2)
    m.funpay.data["brawl_stars"] = [fp(str(i), 100) for i in range(5)]
    assert run(m.run_cycle()) == 2
    summary = tg.sent[-1][1]
    assert "Ещё подходящих объявлений: 3" in summary and summary.count("<a href=") == 3
    assert run(m.run_cycle()) == 0  # остальные не прилетят лавиной позже


def test_unused_share_goes_to_other_site(tmp_path):
    rules = [Rule(name="f", game="brawl_stars", sites=["funpay"]), Rule(name="l", game="brawl_stars", sites=["lolz"])]
    m, tg = make(tmp_path, rules, notify_on_first_run=True, max_notifications_per_cycle=4)
    m.funpay.data["brawl_stars"] = [fp("1", 100)]
    m.lolz.data = {"l": [lz(str(i), 100) for i in range(5)]}
    run(m.run_cycle())
    singles = [t for t in tg.texts() if t.startswith(("🆕", "🔔"))]
    assert len(singles) in (3, 4)  # зависит от того, какой сайт ответил первым, но лимит не превышен
    assert any("Ещё подходящих" in t for t in tg.texts())


def test_cap_is_shared_fairly_between_sites(tmp_path):
    rules = [Rule(name="f", game="brawl_stars", sites=["funpay"]), Rule(name="l", game="brawl_stars", sites=["lolz"])]
    m, tg = make(tmp_path, rules, notify_on_first_run=True, max_notifications_per_cycle=4)
    m.funpay.data["brawl_stars"] = [fp(str(i), 100) for i in range(5)]
    m.lolz.data = {"l": [lz(str(i), 100) for i in range(5)]}
    run(m.run_cycle())
    singles = [t for t in tg.texts() if t.startswith(("🆕", "🔔"))]
    assert len(singles) == 4
    assert sum("lzt.market" in t for t in singles) == 2 and sum("funpay.com" in t for t in singles) == 2


def test_undelivered_notification_is_retried_only_where_missing(tmp_path):
    m, tg = make(tmp_path, [BS], chat_ids=("1", "2"))
    m.funpay.data["brawl_stars"] = []
    run(m.run_cycle())
    m.funpay.data["brawl_stars"] = [fp("1", 500)]
    tg.down = {"2"}
    run(m.run_cycle())
    assert len(tg.texts("1")) == 1 and len(tg.texts("2")) == 0
    tg.down = set()
    run(m.run_cycle())
    assert len(tg.texts("1")) == 1 and len(tg.texts("2")) == 1  # дослали только во второй чат
    run(m.run_cycle())
    assert len(tg.texts("1")) == 1 and len(tg.texts("2")) == 1


def test_telegram_down_stops_trying_for_this_cycle(tmp_path):
    m, tg = make(tmp_path, [Rule(name="bs", game="brawl_stars", sites=["funpay"])], notify_on_first_run=True)
    tg.down = {"1"}
    calls = []
    original = tg.send

    async def counting_send(*a, **kw):
        calls.append(1)
        return await original(*a, **kw)

    tg.send = counting_send
    m.funpay.data["brawl_stars"] = [fp(str(i), 100) for i in range(5)]
    run(m.run_cycle())
    assert len(calls) == 1  # после первой неудачи остальные отложены без попыток
    tg.down = set()
    assert run(m.run_cycle()) == 5  # и пришли в следующий раз


def test_lolz_rule_only_matches_own_query(tmp_path):
    rules = [
        Rule(name="cheap", game="brawl_stars", sites=["lolz"], price_max=1000),
        Rule(name="any", game="brawl_stars", sites=["lolz"]),
    ]
    m, tg = make(tmp_path, rules, notify_on_first_run=True)
    m.lolz.data = {"cheap": [lz("1", 500)], "any": [lz("1", 500), lz("2", 3000)]}
    assert run(m.run_cycle()) == 2
    one = next(t for t in tg.texts() if "lzt.market/1/" in t)
    two = next(t for t in tg.texts() if "lzt.market/2/" in t)
    assert "cheap, any" in one
    assert "cheap" not in two


def test_lolz_unreachable_skips_remaining_rules(tmp_path):
    rules = [Rule(name=f"r{i}", game="brawl_stars", sites=["lolz"]) for i in range(4)]
    m, tg = make(tmp_path, rules)
    m.lolz.error = FetchError("down", unreachable=True)
    run(m.run_cycle())
    assert m.lolz.calls == 1


def test_lolz_account_with_both_games(tmp_path):
    rules = [
        Rule(name="bs", game="brawl_stars", sites=["lolz"], price_max=100),  # по цене не подходит
        Rule(name="cr", game="clash_royale", sites=["lolz"]),
    ]
    m, tg = make(tmp_path, rules, notify_on_first_run=True)
    m.lolz.data = {"bs": [lz("7", 500, "brawl_stars")], "cr": [lz("7", 500, "clash_royale")]}
    assert run(m.run_cycle()) == 1
    assert "Clash Royale" in tg.sent[-1][1] and "🎯 cr" in tg.sent[-1][1]


def test_keywords_and_seller_filters(tmp_path):
    rule = Rule(name="bs", game="brawl_stars", sites=["funpay"], include_any=["почта"], exclude=["аренд", "rent"],
                min_reviews=10, online_only=True)
    m, tg = make(tmp_path, [rule], notify_on_first_run=True)
    good = fp("1", 100, "акк, родная ПОЧТА, different skins")
    rent = fp("2", 100, "сдам в аренду, почта")
    offline = fp("3", 100, "почта")
    offline.seller_online = False
    newbie = fp("4", 100, "почта")
    newbie.seller_reviews = 2
    m.funpay.data["brawl_stars"] = [good, rent, offline, newbie]
    assert run(m.run_cycle()) == 1
    assert "id=1" in tg.sent[-1][1]


def test_funpay_foreign_currency_without_rate(tmp_path):
    m, tg = make(tmp_path, [BS], notify_on_first_run=True)
    m.funpay.data["brawl_stars"] = [fp("1", 10, currency="USD")]
    assert run(m.run_cycle()) == 0  # курса нет — $10 нельзя сравнить с рублёвым price_max
    assert any("курс к рублю" in t for t in tg.texts())


def test_funpay_foreign_currency_is_converted(tmp_path):
    m, tg = make(tmp_path, [BS], notify_on_first_run=True)  # price_max 1000 ₽
    m.rates = FakeRates({"USD": 90.0})
    m.funpay.data["brawl_stars"] = [fp("1", 10, currency="USD"), fp("2", 20, currency="USD")]
    assert run(m.run_cycle()) == 1  # $10 = 900 ₽ подходит, $20 = 1800 ₽ — нет
    text = tg.sent[-1][1]
    assert "id=1" in text and "≈ <b>900 ₽</b> (10 $ по текущему курсу)" in text


def test_currency_switch_does_not_fake_price_drop(tmp_path):
    rule = Rule(name="any", game="brawl_stars", sites=["funpay"])
    m, tg = make(tmp_path, [rule], notify_on_first_run=True)
    m.funpay.data["brawl_stars"] = [fp("1", 1000)]
    run(m.run_cycle())
    m.funpay.data["brawl_stars"] = [fp("1", 11, currency="USD")]
    assert run(m.run_cycle()) == 0
    m.funpay.data["brawl_stars"] = [fp("1", 1000)]
    assert run(m.run_cycle()) == 0


def test_unknown_trophies(tmp_path):
    strict = Rule(name="strict", game="brawl_stars", sites=["funpay"], trophies_min=30000)
    loose = Rule(name="loose", game="brawl_stars", sites=["funpay"], trophies_min=30000, allow_unknown=True)
    m, tg = make(tmp_path, [strict, loose], notify_on_first_run=True)
    m.funpay.data["brawl_stars"] = [fp("1", 100, "без цифр"), fp("2", 100, "акк 40к кубков")]
    run(m.run_cycle())
    texts = {t.split("id=")[-1][:1]: t for t in tg.texts()}
    assert "loose" in texts["1"] and "strict" not in texts["1"]
    assert "strict, loose" in texts["2"]


def test_dry_run_does_not_touch_state(tmp_path):
    m, tg = make(tmp_path, [BS], persist=False, notify_on_first_run=True)
    m.funpay.data["brawl_stars"] = [fp("1", 500)]
    assert run(m.run_cycle()) == 1
    assert not (tmp_path / "state.json").exists()


def test_commands_and_interval_priority(tmp_path):
    m, tg = make(tmp_path, [BS], interval_minutes=5)

    async def scenario():
        await m.handle_command("1", "interval", ["15"])
        assert m.interval_minutes == 15
        await m.handle_command("1", "interval", ["0.1"])  # меньше минимума — отказ
        assert m.interval_minutes == 15
        await m.handle_command("1", "interval", ["reset"])
        assert m.interval_minutes == 5
        await m.handle_command("1", "interval", ["7,5"])
        await m.handle_command("1", "pause", [])
        assert m.paused
        await m.handle_command("1", "resume", [])
        assert not m.paused
        for cmd in ("status", "rules", "help", "interval", "nonsense"):
            await m.handle_command("1", cmd, [])

    run(scenario())
    assert any("❌" in t for t in tg.texts())
    assert any("задан командой /interval" in t for t in tg.texts())
    # интервал, заданный командой, переживает перезапуск…
    m2, _ = make(tmp_path, [BS], interval_minutes=5)
    assert m2.interval_minutes == 7.5
    # …но если потом поменять interval_minutes в config.yaml, главнее становится конфиг
    m3, _ = make(tmp_path, [BS], interval_minutes=20)
    assert m3.interval_minutes == 20


def test_cli_interval_is_not_saved(tmp_path):
    cfg_kw = dict(interval_minutes=5)
    m, _ = make(tmp_path, [BS], **cfg_kw)
    m.cli_interval = 2
    assert m.interval_minutes == 2
    m.funpay.data["brawl_stars"] = []
    run(m.run_cycle())
    saved = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert "interval_minutes" not in saved["settings"]
    m2, _ = make(tmp_path, [BS], **cfg_kw)
    assert m2.interval_minutes == 5


def test_sleep_wakes_on_check(tmp_path):
    m, _ = make(tmp_path, [BS], interval_minutes=60)

    async def scenario():
        sleeper = asyncio.create_task(m._sleep_until_next())
        await asyncio.sleep(0.05)
        assert not sleeper.done()
        await m.handle_command("1", "check", [])
        assert await asyncio.wait_for(sleeper, timeout=1) is True

    run(scenario())


def test_upgrade_from_first_version_state(tmp_path):
    rules = [BS]
    (tmp_path / "state.json").write_text(json.dumps({
        "seen": {
            "funpay:brawl_stars:1": {"first_seen": 1, "last_seen": 9e9, "price": 500, "notified_price": 500,
                                     "pending": True},
        },
        "initialized": ["funpay:brawl_stars"],
        "settings": {"interval_minutes": 10},
    }), encoding="utf-8")
    m, tg = make(tmp_path, rules, interval_minutes=5)
    assert m.interval_minutes == 10  # /interval из первой версии не потерялся
    m.funpay.data["brawl_stars"] = [fp("1", 500), fp("2", 400)]
    # Старый pending: true не роняет бота и досылается; источник уже был «запомнен» — новое тоже приходит.
    assert run(m.run_cycle()) == 2


def test_pending_survives_temporary_mismatch(tmp_path):
    rule = Rule(name="bs", game="brawl_stars", sites=["funpay"], online_only=True)
    m, tg = make(tmp_path, [rule])
    m.funpay.data["brawl_stars"] = []
    run(m.run_cycle())
    m.funpay.data["brawl_stars"] = [fp("1", 500)]
    tg.down = {"1"}
    run(m.run_cycle())  # Telegram недоступен — уведомление отложено
    offline = fp("1", 500)
    offline.seller_online = False
    tg.down = set()
    m.funpay.data["brawl_stars"] = [offline]
    run(m.run_cycle())  # продавец вышел из сети — пока не подходит
    m.funpay.data["brawl_stars"] = [fp("1", 500)]
    run(m.run_cycle())
    assert sum("id=1" in t for t in tg.texts()) == 1  # но уведомление всё равно дошло


def test_no_summary_when_total_is_under_limit(tmp_path):
    rules = [Rule(name="f", game="brawl_stars", sites=["funpay"]), Rule(name="l", game="brawl_stars", sites=["lolz"])]
    m, tg = make(tmp_path, rules, notify_on_first_run=True, max_notifications_per_cycle=25)
    m.funpay.data["brawl_stars"] = [fp(str(i), 100) for i in range(18)]
    m.lolz.data = {"l": [lz(str(i), 100) for i in range(2)]}
    assert run(m.run_cycle()) == 20
    assert not any("Ещё подходящих" in t for t in tg.texts())


def test_health_warning_retried_if_not_delivered(tmp_path):
    m, tg = make(tmp_path, [BS])
    m.funpay.error = "HTTP 403"
    tg.down = {"1"}
    for _ in range(3):
        run(m.run_cycle())
    tg.down = set()
    run(m.run_cycle())
    assert any("не отвечает" in t for t in tg.texts())
