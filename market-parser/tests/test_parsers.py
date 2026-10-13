import json

import pytest

from conftest import FIXTURES
from parser_bot.config import Rule
from parser_bot.funpay import parse_category
from parser_bot.http import FetchError
from parser_bot.lolz import build_params, parse_response
from parser_bot.textparse import extract_all, extract_number


# --- текст ---

BS_CASES = [
    ("35к кубков, 70 бравлеров, 150 лвл", (35000, 70, 150)),
    ("35к кубков 70 бравлеров 150 лвл", (35000, 70, 150)),
    ("Кубки 25000 Бравлеры 60", (25000, 60, None)),
    ("Кубков: 35 000 | Бойцов 80", (35000, 80, None)),
    ("🏆 42k, lvl 14", (42000, None, 14)),
    ("Продам акк 35,5к🏆 полный доступ", (35500, None, None)),
    ("Аккаунт 2019 года, 60к кубков", (60000, None, None)),
    ("Мега аккаунт 3 легендарки", (None, None, None)),
    ("10.000 cups", (10000, None, None)),
    # число от соседнего параметра не должно «перетекать»
    ("Бравлеров: 70, Кубков: 35000", (35000, 70, None)),
    ("Легендарки: 5 | Кубки: 25000", (25000, None, None)),
    ("Уровень: 200, бравлеров: 70, кубков: 35к", (35000, 70, 200)),
    ("Цена 1500₽ 35к кубков", (35000, None, None)),
    ("191K Trophies 161 Primes", (191000, None, None)),
    # «тыс», диапазоны, слова между ключом и числом
    ("Кубков 35 тыс", (35000, None, None)),
    ("35 тыс. кубков", (35000, None, None)),
    ("80/82 бравлеров", (None, 80, None)),
    ("30-35к кубков", (30000, None, None)),
    ("Кубков на аккаунте 35к", (35000, None, None)),
    ("70 уровень бравл пасса, 30к кубков", (30000, None, None)),
]

CR_CASES = [
    ("Уровень короля 15, 9000 кубков", (9000, 15)),
    ("Кубков 9000, Уровень короля 11", (9000, 11)),
    ("Уровень короля 14 Кубков 9000", (9000, 14)),
    ("Все карты 14 уровня, король 13, 7000 кубков", (7000, 13)),
    ("Карты 15 ур, КБ 14, 9к кубков", (9000, 14)),
    ("Аккаунт с 10 лвл карт", (None, None)),
    ("14 король", (None, 14)),
    ("King Tower 15", (None, 15)),
    ("Уровень 99", (None, None)),  # у короля не бывает 99 уровня
]


@pytest.mark.parametrize("text, expected", BS_CASES)
def test_extract_brawl_stars(text, expected):
    got = extract_all(text, "brawl_stars")
    assert (got["trophies"], got["brawlers"], got["level"]) == expected


@pytest.mark.parametrize("text, expected", CR_CASES)
def test_extract_clash_royale(text, expected):
    got = extract_all(text, "clash_royale")
    assert (got["trophies"], got["level"]) == expected and got["brawlers"] is None


def test_extract_ignores_implausible_values():
    assert extract_number("999999999 кубков", "trophies") is None
    assert extract_number("", "trophies") is None


# --- FunPay ---

def test_funpay_parse_rows():
    html = (FIXTURES / "funpay_brawl_stars.html").read_text(encoding="utf-8")
    rows = {x.id: x for x in parse_category(html, "brawl_stars")}
    assert set(rows) == {"11111111", "22222222", "44444444"}  # лот с class="warning" пропущен

    a = rows["11111111"]
    assert a.url == "https://funpay.com/lots/offer?id=11111111"
    assert a.price == 1499.5 and a.currency == "RUB"
    assert a.seller == "GoodSeller" and a.seller_rating == 5 and a.seller_reviews == 1205
    assert a.seller_online is True
    assert (a.trophies, a.brawlers) == (35000, 70)
    assert a.extra.get("Автовыдача") == "да"

    b = rows["22222222"]
    assert b.seller_online is False and b.seller_reviews == 2 and b.seller_rating is None
    assert b.trophies == 12000
    assert b.extra.get("Сервер") == "Android"

    c = rows["44444444"]
    assert c.price == 2750.5  # без data-s — из текста
    assert c.seller_reviews == 0


def test_funpay_empty_page_is_error():
    with pytest.raises(FetchError):
        parse_category("<html><title>Just a moment...</title><body></body></html>", "brawl_stars", 436)


# --- LolzMarket ---

def test_lolz_parse_items():
    data = json.loads((FIXTURES / "lolz_supercell.json").read_text(encoding="utf-8"))
    bs = {x.id: x for x in parse_response(data, "brawl_stars", "https://lzt.market/{id}/")}
    a = bs["900001"]
    assert a.url == "https://lzt.market/900001/"
    assert (a.price, a.currency, a.seller) == (2500, "RUB", "lolzseller")
    assert (a.trophies, a.brawlers, a.level) == (40123, 80, 210)
    assert "родная почта" in a.description

    cr = {x.id: x for x in parse_response(data, "clash_royale", "https://lzt.market/{id}/")}
    b = cr["900002"]
    assert (b.trophies, b.level, b.brawlers) == (7500, 14, None)
    assert b.extra["Эволюций"] == "3"


def test_lolz_errors():
    with pytest.raises(FetchError):
        parse_response({"errors": ["Bad token"]}, "brawl_stars", "{id}")
    with pytest.raises(FetchError):
        parse_response({"something": 1}, "brawl_stars", "{id}")


def test_lolz_params_from_rule():
    rule = Rule(name="r", game="brawl_stars", price_max=1500, trophies_min=30000, brawlers_min=60,
                lolz_params={"origin": ["personal"], "order_by": "price_to_up"})
    p = build_params(rule)
    assert p["supercell_game[]"] == ["brawl-stars"]
    assert p["pmax"] == 1500 and p["brawl_cup_min"] == 30000 and p["brawlers_min"] == 60
    assert p["origin[]"] == ["personal"]
    assert p["order_by"] == "price_to_up"  # lolz_params перекрывает значения по умолчанию

    cr = build_params(Rule(name="c", game="clash_royale", trophies_min=7000, level_min=14))
    assert cr["supercell_game[]"] == ["clash-royale"]
    assert cr["royale_cup_min"] == 7000 and cr["king_level_min"] == 14


FILTERED_PAGE = """
<html><body>
<div class="showcase" data-section="lot-436" data-game="200">
  <form class="showcase-filters">
    <div class="form-group"><input type="number" name="f-1001-min" placeholder="Кубки от"></div>
    <div class="form-group"><label>Арена</label>
      <select name="f-1002"><option value="">Любая</option><option value="5">Арена 5</option></select></div>
    <input type="checkbox" name="online">
  </form>
  <div class="tc showcase-table">
    <div class="tc-header"><div class="tc-desc">Описание</div><div class="tc-f-1003">Бравлеры</div></div>
    <a href="https://funpay.com/lots/offer?id=1" class="tc-item" data-f-1001="35000" data-f-1002="5" data-f-1003="70">
      <div class="tc-desc"><div class="tc-desc-text">Хороший аккаунт</div></div>
      <div class="tc-f-1003">70</div>
      <div class="tc-price" data-s="999"><div>999 <span class="unit">₽</span></div></div>
    </a>
  </div>
</div>
</body></html>
"""


def test_funpay_params_from_filter_labels():
    (x,) = parse_category(FILTERED_PAGE, "brawl_stars")
    assert x.trophies == 35000  # data-f-1001 подписан в фильтрах как «Кубки от»
    assert x.brawlers == 70  # колонка tc-f-1003 в шапке называется «Бравлеры»
    assert x.extra["Арена"] == "Арена 5"  # id варианта из выпадающего списка переведён в текст
    assert x.extra["Бравлеры"] == "70"


def test_funpay_empty_or_wrong_page_is_error():
    html = '<html><body><div class="showcase" data-section="lot-436"><div class="tc-header"></div></div></body></html>'
    with pytest.raises(FetchError, match="нет ни одного объявления"):
        parse_category(html, "brawl_stars", 436)
    other = (FIXTURES / "funpay_brawl_stars.html").read_text(encoding="utf-8").replace(
        '<div class="tc ', '<div class="showcase" data-section="lot-999"></div><div class="tc ')
    with pytest.raises(FetchError, match="другой"):
        parse_category(other, "brawl_stars", 436)


def test_funpay_label_heuristics():
    html = FILTERED_PAGE.replace(
        '<div class="form-group"><input type="number" name="f-1001-min" placeholder="Кубки от"></div>',
        '<div class="form-group"><label>Кубки</label><input name="f-1001-min" placeholder="от">'
        '<input name="f-1001-max" placeholder="до"></div>',
    ).replace('<input type="checkbox" name="online">', '<input type="checkbox" name="online"><span>Онлайн</span>')
    (x,) = parse_category(html, "brawl_stars")
    assert x.trophies == 35000  # подпись «Кубки» важнее placeholder «от»


def test_funpay_level_from_select_option():
    html = FILTERED_PAGE.replace(
        '<select name="f-1002"><option value="">Любая</option><option value="5">Арена 5</option></select>',
        '<select name="f-1002"><option value="">Уровень короля</option><option value="5">14</option></select>',
    ).replace("<label>Арена</label>", "")
    (x,) = parse_category(html, "clash_royale")
    assert x.level == 14


def test_funpay_seller_flags():
    html = (FIXTURES / "funpay_brawl_stars.html").read_text(encoding="utf-8")
    html = html.replace('data-online="1" data-auto="1"', 'data-online="0" data-auto="0"')
    html = html.replace("rating-stars rating-5", "rating-stars")
    a = {x.id: x for x in parse_category(html, "brawl_stars")}["11111111"]
    assert a.seller_online is False and "Автовыдача" not in a.extra
    assert a.seller_rating is None  # без класса rating-N рейтинг неизвестен (не «5 звёзд»)


def test_funpay_describe_page():
    from parser_bot.funpay import describe_page

    report = describe_page(FILTERED_PAGE, "brawl_stars")
    assert "строк a.tc-item: 1" in report and "кубки 35000" in report


def test_lolz_params_normalization():
    rule = Rule(name="r", game="brawl_stars", lolz_params={
        "supercell_game": "clash-royale", "origin": "personal", "tel": False, "nsb": True,
        "brawler_power": {"SHELLY": 11},
    })
    p = build_params(rule)
    assert p["supercell_game[]"] == ["clash-royale"] and "supercell_game" not in p
    assert p["origin[]"] == ["personal"]
    assert p["tel"] == "no" and p["nsb"] == 1
    assert p["brawler_power[SHELLY]"] == 11


def test_lolz_odd_items_do_not_break_parsing():
    data = {"items": [
        {"item_id": 1, "title": "ok", "price": 100, "seller": "deleted"},
        {"item_id": 2, "title": "usd", "price": 5, "price_currency": "usd", "rub_price": 450},
        {"item_id": 3, "title": "usd-no-rub", "price": 5, "price_currency": "usd"},
        "garbage",
    ], "system_info": {"rate_limit": {"remaining": "1"}}}
    got = {x.id: x for x in parse_response(data, "brawl_stars", "https://lzt.market/{id}/")}
    assert set(got) == {"1", "2", "3"}
    assert got["1"].seller is None
    assert (got["2"].price, got["2"].currency) == (450, "RUB")
    assert got["3"].currency == "USD"
