import importlib

import pytest

from src import config
from src.config import ConfigError, validate_config


def test_default_config_is_valid():
    # The shipped defaults must always pass validation.
    validate_config()


def test_watchlist_loads_from_yaml_and_is_normalized():
    assert isinstance(config.WATCHLIST, list)
    assert config.WATCHLIST, "watchlist should not be empty"
    # Uppercased and de-duplicated.
    assert config.WATCHLIST == [s.upper() for s in config.WATCHLIST]
    assert len(config.WATCHLIST) == len(set(config.WATCHLIST))
    assert "AAPL" in config.WATCHLIST


def test_sector_lookup_maps_known_and_unknown_symbols():
    assert config.sector_for("AAPL") == "Information Technology"
    assert config.sector_for("jpm") == "Financials"  # case-insensitive
    # ETFs / unclassified symbols fall back to the default.
    assert config.sector_for("SPY") == config.DEFAULT_SECTOR
    assert config.sector_for("NOPE") == config.DEFAULT_SECTOR


def test_validate_config_rejects_out_of_range_fraction(monkeypatch):
    monkeypatch.setattr(config, "TARGET_CASH_PCT", 1.5)
    with pytest.raises(ConfigError) as exc:
        validate_config()
    assert "TARGET_CASH_PCT" in str(exc.value)


def test_validate_config_rejects_unsupported_provider(monkeypatch):
    monkeypatch.setattr(config, "LLM_STRONG_PROVIDER", "megacorp")
    with pytest.raises(ConfigError) as exc:
        validate_config()
    assert "LLM_STRONG_PROVIDER" in str(exc.value)


def test_validate_config_rejects_partial_fallback(monkeypatch):
    monkeypatch.setattr(config, "LLM_FALLBACK_PROVIDER", "openai")
    monkeypatch.setattr(config, "LLM_FALLBACK_MODEL", "")
    with pytest.raises(ConfigError) as exc:
        validate_config()
    assert "LLM_FALLBACK" in str(exc.value)


def test_validate_config_rejects_empty_model(monkeypatch):
    monkeypatch.setattr(config, "LLM_STRONG_MODEL", "  ")
    with pytest.raises(ConfigError) as exc:
        validate_config()
    assert "LLM_STRONG_MODEL" in str(exc.value)


def test_validate_config_reports_multiple_errors_at_once(monkeypatch):
    monkeypatch.setattr(config, "INITIAL_CAPITAL", -5)
    monkeypatch.setattr(config, "QDRANT_COLLECTION", "")
    with pytest.raises(ConfigError) as exc:
        validate_config()
    message = str(exc.value)
    assert "INITIAL_CAPITAL" in message
    assert "QDRANT_COLLECTION" in message


def test_missing_watchlist_file_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "WATCHLIST_PATH", tmp_path / "nope.yaml")
    with pytest.raises(ConfigError):
        config._load_watchlist()


def test_watchlist_without_symbols_list_raises(monkeypatch, tmp_path):
    bad = tmp_path / "watchlist.yaml"
    bad.write_text("something_else: 1\n")
    monkeypatch.setattr(config, "WATCHLIST_PATH", bad)
    with pytest.raises(ConfigError):
        config._load_watchlist()


def test_researcher_module_is_removed():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.agents.researcher")
