import asyncio

from parser_bot.config import Config, FunPayConfig, LolzConfig, MonitorConfig, Rule, TelegramConfig
from parser_bot.http import FetchError
from parser_bot.models import Listing
from parser_bot.monitor import Monitor


class FakeTelegram:
    def __init__(self):
        self.sent = []
        self.down = False

    async def send(self, text, *, chat_id=None, button=None):
        if self.down:
            return False
        self.sent.append((chat_id, text, button))
        return True

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

    @staticmethod
    def query_hash(rule):
        return "h"

    async def fetch(self, rule):
        return list(self.data.get(rule.name, []))

    async def close(self):
        pass


def fp(id_, price, text="акк 40к кубков", game="brawl_stars"):
    return Listing(site="funpay", game=game, id=id_, url=f"https://funpay.com/lots/offer?id={id_}",
                   title=text, price=price, trophies=40000 if "40к" in text else None, seller="s",
                   seller_online=True, seller_reviews=50, seller_rating=5)


def lz(id_, price, game="brawl_stars"):
    return Listing(site="lolz", game=game, id=id_, url=f"https://lzt.market/{id_}/", title="lolz", price=price)


def make(tmp_path, rules, **monitor_kw):
    cfg = Config(
        telegram=TelegramConfig(bot_token="1:x", chat_ids=[1]),
        monitor=MonitorConfig(state_file=str(tmp_path / "state.json"), **monitor_kw),
        funpay=FunPayConfig(enabled=False, categories={"brawl_stars": 1, "clash_royale": 2}),
        lolz=LolzConfig(enabled=False, token="t"),
        rules=rules,
        base_dir=tmp_path,
    )
    tg = FakeTelegram()
    m = Monitor(cfg, tg)
    m.funpay, m.lolz = FakeFunPay(), FakeLolz()
    return m, tg


def run(coro):
    return asyncio.run(coro)


def test_first_run_is_silent_then_new_items_notify(tmp_path):
    m, tg = make(tmp_path, [Rule(name="bs", game="brawl_stars", sites=["funpay"], price_max=1000)])
    m.funpay.data["brawl_stars"] = [fp("1", 500), fp("2", 5000)]
    assert run(m.run_cycle()) == 0  # первый проход только запоминает

    m.funpay.data["brawl_stars"] = [fp("1", 500), fp("2", 5000), fp("3", 900), fp("4", 2000)]
    assert run(m.run_cycle()) == 1
    assert "id=3" in tg.sent[-1][1]
    assert tg.sent[-1][2] == ("Открыть объявление", "https://funpay.com/lots/offer?id=3")

    assert run(m.run_cycle()) == 0  # повторно не шлёт


def test_undelivered_notification_is_retried(tmp_path):
    m, tg = make(tmp_path, [Rule(name="bs", game="brawl_stars", sites=["funpay"])])
    m.funpay.data["brawl_stars"] = []
    run(m.run_cycle())
    m.funpay.data["brawl_stars"] = [fp("1", 500)]
    tg.down = True
    assert run(m.run_cycle()) == 0
    tg.down = False
    assert run(m.run_cycle()) == 1  # Telegram ожил — уведомление досылается
    assert run(m.run_cycle()) == 0


def test_notify_on_first_run_option(tmp_path):
    m, tg = make(tmp_path, [Rule(name="bs", game="brawl_stars", sites=["funpay"])], notify_on_first_run=True)
    m.funpay.data["brawl_stars"] = [fp("1", 500)]
    assert run(m.run_cycle()) == 1


def test_price_drop(tmp_path):
    m, tg = make(tmp_path, [Rule(name="bs", game="brawl_stars", sites=["funpay"], price_max=1000)])
    m.funpay.data["brawl_stars"] = []
    run(m.run_cycle())
    m.funpay.data["brawl_stars"] = [fp("1", 1500)]  # новое, но дороже лимита
    assert run(m.run_cycle()) == 0
    m.funpay.data["brawl_stars"] = [fp("1", 800)]  # подешевело и стало подходить
    assert run(m.run_cycle()) == 1
    assert "Цена снижена" in tg.sent[-1][1]
    m.funpay.data["brawl_stars"] = [fp("1", 700)]  # подешевело ещё
    assert run(m.run_cycle()) == 1
    m.funpay.data["brawl_stars"] = [fp("1", 750)]  # подорожало — молчим
    assert run(m.run_cycle()) == 0


def test_price_drop_can_be_disabled(tmp_path):
    m, tg = make(tmp_path, [Rule(name="bs", game="brawl_stars", sites=["funpay"], price_max=1000)],
                 notify_price_drop=False)
    m.funpay.data["brawl_stars"] = []
    run(m.run_cycle())
    m.funpay.data["brawl_stars"] = [fp("1", 1500)]
    run(m.run_cycle())
    m.funpay.data["brawl_stars"] = [fp("1", 800)]
    assert run(m.run_cycle()) == 0


def test_state_survives_restart(tmp_path):
    rules = [Rule(name="bs", game="brawl_stars", sites=["funpay"])]
    m, _ = make(tmp_path, rules)
    m.funpay.data["brawl_stars"] = [fp("1", 500)]
    run(m.run_cycle())
    m2, tg2 = make(tmp_path, rules)
    m2.funpay.data["brawl_stars"] = [fp("1", 500), fp("2", 600)]
    assert run(m2.run_cycle()) == 1
    assert "id=2" in tg2.sent[-1][1]


def test_failed_source_does_not_count_as_first_run(tmp_path):
    m, tg = make(tmp_path, [Rule(name="bs", game="brawl_stars", sites=["funpay"])])
    m.funpay.error = "HTTP 403"
    for _ in range(3):
        run(m.run_cycle())
    assert any("не отвечает" in t for _, t, _ in tg.sent)  # предупреждение после 3 ошибок подряд
    m.funpay.error = None
    m.funpay.data["brawl_stars"] = [fp("1", 500)]
    assert run(m.run_cycle()) == 0  # первый удачный проход — тоже только запоминает
    assert any("снова работает" in t for _, t, _ in tg.sent)


def test_cap_per_cycle(tmp_path):
    m, tg = make(tmp_path, [Rule(name="bs", game="brawl_stars", sites=["funpay"])],
                 notify_on_first_run=True, max_notifications_per_cycle=2)
    m.funpay.data["brawl_stars"] = [fp(str(i), 100) for i in range(5)]
    assert run(m.run_cycle()) == 2
    assert "ещё 3" in tg.sent[-1][1]
    assert run(m.run_cycle()) == 0  # остальные не прилетят лавиной позже


def test_lolz_rule_only_matches_own_query(tmp_path):
    rules = [
        Rule(name="cheap", game="brawl_stars", sites=["lolz"], price_max=1000),
        Rule(name="any", game="brawl_stars", sites=["lolz"]),
    ]
    m, tg = make(tmp_path, rules, notify_on_first_run=True)
    m.lolz.data = {"cheap": [lz("1", 500)], "any": [lz("1", 500), lz("2", 3000)]}
    assert run(m.run_cycle()) == 2
    texts = [t for _, t, _ in tg.sent]
    one = next(t for t in texts if "lzt.market/1/" in t)
    two = next(t for t in texts if "lzt.market/2/" in t)
    assert "cheap, any" in one
    assert "cheap" not in two


def test_keywords_and_seller_filters(tmp_path):
    rule = Rule(name="bs", game="brawl_stars", sites=["funpay"], include_any=["почта"], exclude=["аренда"],
                min_reviews=10, online_only=True)
    m, tg = make(tmp_path, [rule], notify_on_first_run=True)
    good = fp("1", 100, "акк, родная ПОЧТА")
    rent = fp("2", 100, "аренда, почта")
    offline = fp("3", 100, "почта")
    offline.seller_online = False
    newbie = fp("4", 100, "почта")
    newbie.seller_reviews = 2
    m.funpay.data["brawl_stars"] = [good, rent, offline, newbie]
    assert run(m.run_cycle()) == 1
    assert "id=1" in tg.sent[-1][1]


def test_unknown_trophies(tmp_path):
    strict = Rule(name="strict", game="brawl_stars", sites=["funpay"], trophies_min=30000)
    loose = Rule(name="loose", game="brawl_stars", sites=["funpay"], trophies_min=30000, allow_unknown=True)
    m, tg = make(tmp_path, [strict, loose], notify_on_first_run=True)
    m.funpay.data["brawl_stars"] = [fp("1", 100, "без цифр"), fp("2", 100, "акк 40к кубков")]
    run(m.run_cycle())
    texts = {t.split("id=")[-1][:1]: t for _, t, _ in tg.sent}
    assert "loose" in texts["1"] and "strict" not in texts["1"]
    assert "strict, loose" in texts["2"]


def test_commands(tmp_path):
    m, tg = make(tmp_path, [Rule(name="bs", game="brawl_stars", sites=["funpay"])], interval_minutes=5)

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
        await m.handle_command("1", "status", [])
        await m.handle_command("1", "rules", [])
        await m.handle_command("1", "help", [])

    run(scenario())
    assert any("❌" in t for _, t, _ in tg.sent)
    # интервал, заданный командой, переживает перезапуск
    m2, _ = make(tmp_path, [Rule(name="bs", game="brawl_stars", sites=["funpay"])], interval_minutes=5)
    assert m2.interval_minutes == 7.5


def test_sleep_wakes_on_check(tmp_path):
    m, _ = make(tmp_path, [Rule(name="bs", game="brawl_stars", sites=["funpay"])], interval_minutes=60)

    async def scenario():
        sleeper = asyncio.create_task(m._sleep_until_next())
        await asyncio.sleep(0.05)
        assert not sleeper.done()
        await m.handle_command("1", "check", [])
        await asyncio.wait_for(sleeper, timeout=1)

    run(scenario())


def test_lolz_account_with_both_games(tmp_path):
    rules = [
        Rule(name="bs", game="brawl_stars", sites=["lolz"], price_max=100),  # по цене не подходит
        Rule(name="cr", game="clash_royale", sites=["lolz"]),
    ]
    m, tg = make(tmp_path, rules, notify_on_first_run=True)
    # Один и тот же товар 7 пришёл и в поиске BS, и в поиске CR.
    m.lolz.data = {"bs": [lz("7", 500, "brawl_stars")], "cr": [lz("7", 500, "clash_royale")]}
    assert run(m.run_cycle()) == 1
    assert "Clash Royale" in tg.sent[-1][1] and "🎯 cr" in tg.sent[-1][1]
