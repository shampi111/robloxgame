import pytest

from conftest import ROOT
from parser_bot.config import ConfigError, load_config


def write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def filled_example(tmp_path):
    text = (ROOT / "config.example.yaml").read_text(encoding="utf-8")
    text = text.replace("ВАШ_ТОКЕН_БОТА", "123:abc").replace("ВАШ_ТОКЕН_LOLZ", "a.b.c")
    return write(tmp_path, text)


def test_example_config_loads(tmp_path):
    cfg = load_config(filled_example(tmp_path))
    assert cfg.monitor.interval_minutes == 5
    assert cfg.funpay.categories == {"brawl_stars": 436, "clash_royale": 149}
    assert [r.game for r in cfg.rules] == ["brawl_stars", "clash_royale"]
    assert cfg.rules[0].exclude == ["аренд"]
    assert cfg.state_path == tmp_path / "state.json"


def test_example_placeholders_are_rejected(tmp_path):
    text = (ROOT / "config.example.yaml").read_text(encoding="utf-8")
    with pytest.raises(ConfigError, match="bot_token"):
        load_config(write(tmp_path, text))


def test_category_as_url(tmp_path):
    p = filled_example(tmp_path)
    text = p.read_text(encoding="utf-8")
    text = text.replace("brawl_stars: 436", "brawl_stars: https://funpay.com/lots/999/").replace("clash_royale: 149", "clash_royale: auto")
    p.write_text(text, encoding="utf-8")
    assert load_config(p).funpay.categories == {"brawl_stars": 999, "clash_royale": "auto"}


@pytest.mark.parametrize(
    "rule, message",
    [
        ("{name: a, game: minecraft}", "game"),
        ("{name: a, game: brawl_stars, sites: [avito]}", "sites"),
        ("{name: a, game: brawl_stars, price_min: 10, price_max: 5}", "price_min"),
        ("{name: a, game: clash_royale, brawlers_min: 5}", "brawlers_min"),
        ("{name: a, game: brawl_stars, trophys_min: 5}", "неизвестные"),
        ("{name: a, game: brawl_stars, price_max: дешево}", "price_max"),
    ],
)
def test_bad_rules(tmp_path, rule, message):
    text = f"""
telegram: {{bot_token: "1:x", chat_ids: [1]}}
lolz: {{token: t}}
rules:
  - {rule}
"""
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, text))


def test_bad_interval(tmp_path):
    text = """
telegram: {bot_token: "1:x", chat_ids: [1]}
monitor: {interval_minutes: 0}
lolz: {enabled: false}
rules: [{name: a, game: brawl_stars, sites: [funpay]}]
"""
    with pytest.raises(ConfigError, match="Интервал"):
        load_config(write(tmp_path, text))


def test_lolz_token_required_only_when_used(tmp_path):
    text = """
telegram: {bot_token: "1:x", chat_ids: [1]}
rules: [{name: a, game: brawl_stars, sites: [funpay]}]
"""
    load_config(write(tmp_path, text))
    text = text.replace("sites: [funpay]", "sites: [lolz]")
    with pytest.raises(ConfigError, match="lolz.token"):
        load_config(write(tmp_path, text))


@pytest.mark.parametrize(
    "section, message",
    [
        ("monitor: {max_notifications_per_cycle: 0}", "max_notifications_per_cycle"),
        ("monitor: {min_price_drop_percent: 150}", "min_price_drop_percent"),
        ("monitor: {proxy: 'host:1080'}", "прокси"),
        ("lolz: {token: t, pages: abc}", "lolz.pages"),
    ],
)
def test_bad_settings(tmp_path, section, message):
    text = f"""
telegram: {{bot_token: "1:x", chat_ids: [1]}}
{section}
rules: [{{name: a, game: brawl_stars, sites: [funpay]}}]
"""
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, text))


def test_missing_game_is_explained_in_russian(tmp_path):
    text = """
telegram: {bot_token: "1:x", chat_ids: [1]}
rules: [{name: a, sites: [funpay]}]
"""
    with pytest.raises(ConfigError, match="не указан game"):
        load_config(write(tmp_path, text))


def test_bad_chat_id(tmp_path):
    text = """
telegram: {bot_token: "1:x", chat_ids: [мой_id]}
rules: [{name: a, game: brawl_stars, sites: [funpay]}]
"""
    with pytest.raises(ConfigError, match="chat id"):
        load_config(write(tmp_path, text))


@pytest.mark.parametrize(
    "value, expected",
    [("https://funpay.com/lots/436/?utm_source=tg&utm_id=77", 436), ("https://funpay.com/lots/436/#top", 436), (436, 436)],
)
def test_category_links(tmp_path, value, expected):
    text = f"""
telegram: {{bot_token: "1:x", chat_ids: [1]}}
funpay: {{categories: {{brawl_stars: "{value}"}}}}
rules: [{{name: a, game: brawl_stars, sites: [funpay]}}]
"""
    assert load_config(write(tmp_path, text)).funpay.categories["brawl_stars"] == expected


def test_offer_link_is_not_a_category(tmp_path):
    text = """
telegram: {bot_token: "1:x", chat_ids: [1]}
funpay: {categories: {brawl_stars: "https://funpay.com/lots/offer?id=41234567"}}
rules: [{name: a, game: brawl_stars, sites: [funpay]}]
"""
    with pytest.raises(ConfigError, match="номер раздела"):
        load_config(write(tmp_path, text))
