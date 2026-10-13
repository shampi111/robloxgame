"""Сквозная проверка с подменёнными сайтами: настоящие HTTP-клиенты, парсеры, фильтры и отправка в Telegram."""

import asyncio
import json

import httpx
import respx

from conftest import FIXTURES
from parser_bot.config import load_config
from parser_bot.funpay import find_accounts_category
from parser_bot.monitor import Monitor
from parser_bot.telegram import Telegram

MAIN_PAGE = """
<html><body>
<div class="promo-game-item">
  <div class="game-title" data-id="200"><a href="https://funpay.com/lots/436/">Brawl Stars</a></div>
  <ul class="list-inline" data-id="200">
    <li><a href="https://funpay.com/chips/111/">Гемы</a></li>
    <li><a href="https://funpay.com/lots/436/">Аккаунты</a></li>
    <li><a href="https://funpay.com/lots/437/">Услуги</a></li>
  </ul>
</div>
<div class="promo-game-item">
  <div class="game-title" data-id="201"><a href="https://funpay.com/lots/149/">Clash Royale</a></div>
  <ul class="list-inline" data-id="201">
    <li><a href="https://funpay.com/lots/149/">Аккаунты</a></li>
  </ul>
</div>
</body></html>
"""

CONFIG = """
telegram: {bot_token: "123:abc", chat_ids: [42]}
monitor: {interval_minutes: 5, notify_on_first_run: true}
funpay: {request_delay_seconds: 0, categories: {brawl_stars: auto}}
lolz: {token: "a.b.c", request_delay_seconds: 0}
rules:
  - name: BS
    game: brawl_stars
    price_max: 3000
    trophies_min: 30000
"""


def test_find_accounts_category():
    assert find_accounts_category(MAIN_PAGE, "brawl_stars") == 436
    assert find_accounts_category(MAIN_PAGE, "clash_royale") == 149
    assert find_accounts_category("<html></html>", "brawl_stars") is None


@respx.mock
def test_full_cycle(tmp_path):
    (tmp_path / "config.yaml").write_text(CONFIG, encoding="utf-8")
    cfg = load_config(tmp_path / "config.yaml")

    respx.get("https://funpay.com/").mock(return_value=httpx.Response(200, text=MAIN_PAGE))
    fp_page = respx.get("https://funpay.com/lots/436/").mock(
        return_value=httpx.Response(200, text=(FIXTURES / "funpay_brawl_stars.html").read_text(encoding="utf-8"))
    )
    lolz = respx.get("https://api.lzt.market/supercell").mock(
        return_value=httpx.Response(200, json=json.loads((FIXTURES / "lolz_supercell.json").read_text(encoding="utf-8")))
    )
    sent = []

    def on_send(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {}})

    respx.post("https://api.telegram.org/bot123:abc/sendMessage").mock(side_effect=on_send)

    async def scenario():
        tg = Telegram(cfg.telegram.bot_token, cfg.telegram.chat_ids)
        m = Monitor(cfg, tg)
        try:
            return await m.run_cycle()
        finally:
            await m.close()
            await tg.close()

    count = asyncio.run(scenario())

    # FunPay: подходит только лот 11111111 (35к кубков, 1500 ₽); 22222222 — мало кубков, 44444444 — кубки неизвестны.
    # Lolz: оба товара пришли из запроса правила; 900001 подходит, 900002 — клиентская проверка кубков (15000) отсекает.
    urls = sorted(m["reply_markup"]["inline_keyboard"][0][0]["url"] for m in sent)
    assert urls == ["https://funpay.com/lots/offer?id=11111111", "https://lzt.market/900001/"]
    assert count == 2
    assert all(m["chat_id"] == "42" and m["parse_mode"] == "HTML" for m in sent)
    assert fp_page.call_count == 1

    q = lolz.calls.last.request.url.params
    assert q.get_list("supercell_game[]") == ["brawl-stars"]
    assert q["order_by"] == "pdate_to_down" and q["pmax"] == "3000" and q["brawl_cup_min"] == "30000"
    assert lolz.calls.last.request.headers["Authorization"] == "Bearer a.b.c"


@respx.mock
def test_lolz_429_is_retried(tmp_path):
    (tmp_path / "config.yaml").write_text(CONFIG.replace("funpay: {request_delay_seconds: 0, categories: {brawl_stars: auto}}", "funpay: {enabled: false}"),
                                          encoding="utf-8")
    cfg = load_config(tmp_path / "config.yaml")
    data = json.loads((FIXTURES / "lolz_supercell.json").read_text(encoding="utf-8"))
    route = respx.get("https://api.lzt.market/supercell").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "1"}, json={"errors": ["Too many"]}),
                     httpx.Response(200, json=data)]
    )
    respx.post("https://api.telegram.org/bot123:abc/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {}})
    )

    async def scenario():
        tg = Telegram(cfg.telegram.bot_token, cfg.telegram.chat_ids)
        m = Monitor(cfg, tg)
        try:
            return await m.run_cycle()
        finally:
            await m.close()
            await tg.close()

    assert asyncio.run(scenario()) == 1
    assert route.call_count == 2


def _lolz_only_config(tmp_path, extra=""):
    text = CONFIG.replace("funpay: {request_delay_seconds: 0, categories: {brawl_stars: auto}}", "funpay: {enabled: false}")
    text = text.replace('lolz: {token: "a.b.c", request_delay_seconds: 0}',
                        'lolz: {token: "a.b.c", request_delay_seconds: 0' + extra + '}')
    (tmp_path / "config.yaml").write_text(text, encoding="utf-8")
    return load_config(tmp_path / "config.yaml")


async def _one_cycle(cfg):
    tg = Telegram(cfg.telegram.bot_token, cfg.telegram.chat_ids)
    m = Monitor(cfg, tg)
    try:
        await m.run_cycle()
        return m
    finally:
        await m.close()
        await tg.close()


@respx.mock
def test_lolz_error_text_reaches_status(tmp_path):
    cfg = _lolz_only_config(tmp_path)
    respx.get("https://api.lzt.market/supercell").mock(
        return_value=httpx.Response(400, json={"errors": ["Unknown parameter tel"]}))
    respx.post("https://api.telegram.org/bot123:abc/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {}}))
    m = asyncio.run(_one_cycle(cfg))
    assert "Unknown parameter tel" in m.status_text()


@respx.mock
def test_lolz_403_explains_access(tmp_path):
    cfg = _lolz_only_config(tmp_path)
    respx.get("https://api.lzt.market/supercell").mock(return_value=httpx.Response(403, json={"errors": ["No access"]}))
    respx.post("https://api.telegram.org/bot123:abc/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {}}))
    m = asyncio.run(_one_cycle(cfg))
    assert "200 симпатий" in m.status_text()


@respx.mock
def test_lolz_fallback_base_url(tmp_path, monkeypatch):
    import parser_bot.http as http_mod

    async def no_sleep(_):
        return None

    monkeypatch.setattr(http_mod.asyncio, "sleep", no_sleep)
    cfg = _lolz_only_config(tmp_path)
    data = json.loads((FIXTURES / "lolz_supercell.json").read_text(encoding="utf-8"))
    respx.get("https://api.lzt.market/supercell").mock(side_effect=httpx.ConnectError("blocked"))
    backup = respx.get("https://prod-api.lzt.market/supercell").mock(return_value=httpx.Response(200, json=data))
    respx.post("https://api.telegram.org/bot123:abc/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {}}))
    m = asyncio.run(_one_cycle(cfg))
    assert backup.call_count == 1
    assert "✅ Lolz" in m.status_text()


@respx.mock
def test_telegram_long_message_and_permanent_errors():
    calls = []

    def on_send(request):
        body = json.loads(request.content)
        calls.append(body)
        if body["chat_id"] == "2":
            return httpx.Response(403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"})
        return httpx.Response(200, json={"ok": True, "result": {}})

    respx.post("https://api.telegram.org/bot1:x/sendMessage").mock(side_effect=on_send)

    async def scenario():
        tg = Telegram("1:x", ["1", "2"])
        try:
            failed = await tg.send("<b>" + "я" * 5000 + "</b>")
        finally:
            await tg.close()
        return failed

    failed = asyncio.run(scenario())
    assert failed == set()  # заблокированный чат — постоянная ошибка, повторять не нужно
    first = calls[0]
    assert len(first["text"]) <= 4096 and "parse_mode" not in first and "<b>" not in first["text"]


@respx.mock
def test_lolz_switches_back_to_main_address(tmp_path, monkeypatch):
    import parser_bot.http as http_mod

    async def no_sleep(_):
        return None

    monkeypatch.setattr(http_mod.asyncio, "sleep", no_sleep)
    cfg = _lolz_only_config(tmp_path)
    data = json.loads((FIXTURES / "lolz_supercell.json").read_text(encoding="utf-8"))
    main = respx.get("https://api.lzt.market/supercell").mock(
        side_effect=[httpx.ConnectError("down")] * 4 + [httpx.Response(200, json=data)] * 5)
    backup = respx.get("https://prod-api.lzt.market/supercell").mock(
        side_effect=[httpx.Response(200, json=data)] + [httpx.ConnectError("down")] * 20)
    respx.post("https://api.telegram.org/bot123:abc/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {}}))

    async def scenario():
        tg = Telegram(cfg.telegram.bot_token, cfg.telegram.chat_ids)
        m = Monitor(cfg, tg)
        try:
            await m.run_cycle()  # основной лежит — переключились на запасной
            await m.run_cycle()  # запасной лёг — вернулись на основной
            return m.status_text()
        finally:
            await m.close()
            await tg.close()

    status = asyncio.run(scenario())
    assert "✅ Lolz" in status and main.call_count >= 5 and backup.call_count >= 2


@respx.mock
def test_rates_sources_and_fallback():
    from parser_bot.rates import Rates

    respx.get("https://open.er-api.com/v6/latest/RUB").mock(side_effect=httpx.ConnectError("blocked"))
    respx.get("https://www.cbr-xml-daily.ru/daily_json.js").mock(return_value=httpx.Response(200, json={
        "Valute": {"USD": {"Nominal": 1, "Value": 90.0}, "GEL": {"Nominal": 1, "Value": 33.0},
                   "KZT": {"Nominal": 100, "Value": 18.0}},
    }))

    async def scenario():
        rates = Rates({"EUR": 100})
        return (await rates.to_rub(10, "USD"), await rates.to_rub(1000, "KZT"),
                await rates.to_rub(2, "eur"), await rates.to_rub(5, "XYZ"))

    assert asyncio.run(scenario()) == (900.0, 180.0, 200.0, None)


def test_er_api_format():
    from parser_bot.rates import parse_rates

    rates = parse_rates("https://open.er-api.com/v6/latest/RUB",
                        {"result": "success", "rates": {"RUB": 1, "USD": 0.0125, "EUR": 0.01}})
    assert rates["USD"] == 80.0 and rates["EUR"] == 100.0 and rates["RUB"] == 1.0
    assert parse_rates("https://open.er-api.com/v6/latest/RUB", {"result": "error"}) == {}
