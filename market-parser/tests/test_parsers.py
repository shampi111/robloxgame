import json

import pytest

from conftest import FIXTURES
from parser_bot.config import Rule
from parser_bot.funpay import parse_category
from parser_bot.http import FetchError
from parser_bot.lolz import build_params, parse_response
from parser_bot.textparse import extract_all, extract_number


# --- текст ---

@pytest.mark.parametrize(
    "text, expected",
    [
        ("35к кубков, 70 бравлеров, 150 лвл", {"trophies": 35000, "brawlers": 70, "level": 150}),
        ("Кубков: 35 000 | Бойцов 80", {"trophies": 35000, "brawlers": 80, "level": None}),
        ("🏆 42k, lvl 14", {"trophies": 42000, "brawlers": None, "level": 14}),
        ("Продам акк 35,5к🏆 полный доступ", {"trophies": 35500, "brawlers": None, "level": None}),
        ("Уровень короля 15, 9000 кубков", {"trophies": 9000, "brawlers": None, "level": 15}),
        ("Аккаунт 2019 года, 60к кубков", {"trophies": 60000, "brawlers": None, "level": None}),
        ("Мега аккаунт 3 легендарки", {"trophies": None, "brawlers": None, "level": None}),
        ("10.000 cups", {"trophies": 10000, "brawlers": None, "level": None}),
    ],
)
def test_extract(text, expected):
    assert extract_all(text) == expected


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
        parse_category("<html><title>Just a moment...</title><body></body></html>", "brawl_stars")


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


def test_funpay_empty_category_is_not_error():
    html = '<html><body><div class="showcase" data-section="lot-436"><div class="tc-header"></div></div></body></html>'
    assert parse_category(html, "brawl_stars") == []


def test_funpay_describe_page():
    from parser_bot.funpay import describe_page

    report = describe_page(FILTERED_PAGE, "brawl_stars")
    assert "строк a.tc-item: 1" in report and "кубки 35000" in report
