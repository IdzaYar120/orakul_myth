"""Smoke tests: the Streamlit app and the CLI start, render and navigate without errors."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from delphi.cli import app as cli_app
from tests.paths import REPO_ROOT

MAIN = str(REPO_ROOT / "app" / "main.py")
TABS = ["Оракул", "Енциклопедія", "Карта"]


def _app() -> AppTest:
    return AppTest.from_file(MAIN, default_timeout=60)


def _ok(at: AppTest) -> AppTest:
    assert not at.exception, [e.value for e in at.exception]
    return at


def _button(at: AppTest, key: str):
    return next(b for b in at.button if b.key == key)


def test_no_streamlit_auto_pages_dir():
    # A `pages/` dir next to main.py turns into Streamlit's automatic multipage nav.
    assert not (REPO_ROOT / "app" / "pages").exists()


@pytest.mark.parametrize("tab", TABS)
def test_app_tabs_render(seeded_default_db: Path, tab: str):
    at = _ok(_app().run())
    assert at.sidebar.radio[0].options == TABS
    _ok(at.sidebar.radio[0].set_value(tab).run())
    assert at.header, f"tab {tab} rendered no header"


def test_encyclopedia_search_then_open_card(seeded_default_db: Path):
    at = _ok(_app().run())
    _ok(at.sidebar.radio[0].set_value("Енциклопедія").run())
    _ok(at.text_input(key="enc_query").set_value("Аполлон").run())
    assert at.button(key="res_apollo")

    _ok(_button(at, "res_apollo").click().run())
    assert at.subheader[0].value == "Аполлон"
    assert at.query_params["entity"] == "apollo"
    assert at.session_state["selected_entity"] == "apollo"

    _ok(_button(at, "enc_back").click().run())
    assert "selected_entity" not in at.session_state


def test_card_filters_by_type_and_cycle(seeded_default_db: Path):
    at = _ok(_app().run())
    _ok(at.sidebar.radio[0].set_value("Енциклопедія").run())
    _ok(at.selectbox(key="enc_cycle").set_value("argonauts").run())
    keys = {b.key for b in at.button}
    assert "list_hero_jason" in keys
    assert "list_hero_oedipus" not in keys


def test_shareable_entity_link(seeded_default_db: Path):
    at = _app()
    at.query_params["entity"] = "delphi"
    _ok(at.run())
    assert at.sidebar.radio[0].value == "Енциклопедія"
    assert at.subheader[0].value == "Дельфи"


def test_lineage_navigation_and_ask_oracle(seeded_default_db: Path):
    at = _app()
    at.query_params["entity"] = "zeus"
    _ok(at.run())
    assert at.subheader[0].value == "Зевс"

    # Click a parent chip -> Cronus card
    parents = at.button_group(key="lin_zeus_parents")
    _ok(parents.set_value("cronus").run())
    assert at.subheader[0].value == "Кронос"

    # "Ask the oracle" switches to the oracle tab with the question asked
    _ok(_button(at, "ask_oracle_cronus").click().run())
    assert at.sidebar.radio[0].value == "Оракул"
    assert any("Кронос" in m.markdown[0].value for m in at.chat_message if m.markdown)


def test_map_filters_and_show_on_map(seeded_default_db: Path):
    at = _ok(_app().run())
    _ok(at.sidebar.radio[0].set_value("Карта").run())
    _ok(at.sidebar.selectbox(key="map_god").set_value("zeus").run())
    _ok(at.sidebar.multiselect(key="map_kinds").set_value(["sanctuary"]).run())
    assert any("Місць на карті" in c.value for c in at.caption)

    # Place card -> "show on map" -> map tab with the place selected
    at = _app()
    at.query_params["entity"] = "delphi"
    _ok(at.run())
    _ok(_button(at, "show_on_map_delphi").click().run())
    assert at.sidebar.radio[0].value == "Карта"
    assert at.session_state["map_selected"] == "delphi"
    assert any(md.value == "#### Дельфи" for md in at.markdown)


def test_oracle_chat_roundtrip(seeded_default_db: Path):
    at = _ok(_app().run())
    _ok(at.chat_input[0].set_value("Хто такий Зевс?").run())
    roles = [m.name for m in at.chat_message]
    assert roles[-2:] == ["user", "assistant"]


def test_cli_seed_and_ask(seeded_default_db: Path):
    runner = CliRunner()
    res = runner.invoke(cli_app, ["seed"])
    assert res.exit_code == 0, res.output

    res = runner.invoke(cli_app, ["ask", "Хто виховував Ахілла?"])
    assert res.exit_code == 0, res.output
    assert "achilles" in res.output

    res = runner.invoke(cli_app, ["ingest"])
    assert res.exit_code == 0, res.output

    res = runner.invoke(cli_app, ["wikidata", "--help"])
    assert res.exit_code == 0 and "pull" in res.output
