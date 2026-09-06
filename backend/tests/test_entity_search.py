"""Smoke tests for unified entity search + VASP dossiers."""
import os
import sys
import tempfile

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_PATH"] = _tmp.name
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import entity_search
import config


def setup_module(module):
    """Seed the tables with known data. Re-bind DB_PATH in case another test
    module changed os.environ['DB_PATH'] after config was first imported."""
    import importlib
    importlib.reload(config)
    # Point the engines at the same temp DB config resolved.
    import vasp_directory, sanctions_engine, database, attribution_engine
    for mod in (vasp_directory, sanctions_engine, database, attribution_engine, entity_search):
        mod.DB_PATH = config.DB_PATH
    vasp_directory.init_vasp_tables()
    sanctions_engine.init_sanctions_tables()
    database.init_db()
    attribution_engine.init_attribution_tables()


def test_search_finds_known_vasp():
    """Searching 'Binance' should find the seeded Binance VASP."""
    result = entity_search.search_entities("Binance", limit=10)
    assert result["count"] > 0
    names = [e["name"].lower() for e in result["entities"]]
    assert any("binance" in n for n in names)


def test_search_finds_sanctioned_entity():
    """Searching 'Lazarus' should find the OFAC Lazarus Group entity."""
    result = entity_search.search_entities("Lazarus", limit=10)
    names = [e["name"].lower() for e in result["entities"]]
    assert any("lazarus" in n for n in names), f"expected Lazarus in {names}"


def test_search_finds_tornado():
    """Searching 'Tornado' should find the OFAC Tornado Cash entity."""
    result = entity_search.search_entities("Tornado", limit=10)
    names = [e["name"].lower() for e in result["entities"]]
    assert any("tornado" in n for n in names), f"expected Tornado in {names}"


def test_search_empty_query_returns_nothing():
    result = entity_search.search_entities("", limit=10)
    assert result["count"] == 0


def test_search_short_query_returns_nothing():
    result = entity_search.search_entities("a", limit=10)
    assert result["count"] == 0


def test_search_returns_entity_cards_with_fields():
    result = entity_search.search_entities("Binance", limit=5)
    for entity in result["entities"]:
        assert "entity_id" in entity
        assert "name" in entity
        assert "type" in entity
        assert "category" in entity
        assert "relevance" in entity
        assert 0 <= entity["relevance"] <= 1.0


def test_search_reports_sources_searched():
    result = entity_search.search_entities("test", limit=5)
    sources = {s["source"] for s in result["sources_searched"]}
    assert "vasp_directory" in sources
    assert "sanctions" in sources
