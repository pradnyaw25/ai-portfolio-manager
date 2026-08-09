"""Langfuse host resolution.

The keys and the host are configured separately, and a wrong host fails silently:
the client constructs against it happily, logs "Langfuse tracing enabled", and the
traces then never arrive. That is the whole failure mode these tests guard.
"""

import importlib

import pytest

import src.config


def _config_with(monkeypatch, **env):
    # config.py calls load_dotenv() at import, which would repopulate these from a
    # developer's real .env and make the fallback case untestable. Neutralise it so
    # the test describes the environment, not the machine.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    for key in ("LANGFUSE_HOST", "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(src.config)


@pytest.fixture(autouse=True)
def _restore():
    yield
    importlib.reload(src.config)


def test_langfuse_host_is_used_when_set(monkeypatch):
    cfg = _config_with(monkeypatch, LANGFUSE_HOST="https://us.cloud.langfuse.com")
    assert cfg.LANGFUSE_HOST == "https://us.cloud.langfuse.com"


def test_base_url_is_accepted_as_an_alias(monkeypatch):
    """Langfuse's own setup screen calls it LANGFUSE_BASE_URL, so that is the name
    people paste in. Reading only LANGFUSE_HOST silently sent US keys to the EU."""
    cfg = _config_with(monkeypatch, LANGFUSE_BASE_URL="https://us.cloud.langfuse.com")
    assert cfg.LANGFUSE_HOST == "https://us.cloud.langfuse.com"


def test_host_wins_over_base_url_when_both_are_set(monkeypatch):
    cfg = _config_with(
        monkeypatch,
        LANGFUSE_HOST="https://self-hosted.example.com",
        LANGFUSE_BASE_URL="https://us.cloud.langfuse.com",
    )
    assert cfg.LANGFUSE_HOST == "https://self-hosted.example.com"


def test_falls_back_to_the_eu_cloud_default(monkeypatch):
    cfg = _config_with(monkeypatch)
    assert cfg.LANGFUSE_HOST == "https://cloud.langfuse.com"


def test_an_empty_value_does_not_produce_an_empty_host(monkeypatch):
    """An unset secret in CI expands to "", which must not become the host."""
    cfg = _config_with(monkeypatch, LANGFUSE_HOST="", LANGFUSE_BASE_URL="")
    assert cfg.LANGFUSE_HOST == "https://cloud.langfuse.com"
