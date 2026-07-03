"""Model routing: map a tier to a (provider, model), with an optional fallback."""

from dataclasses import dataclass

from src import config


@dataclass(frozen=True)
class Route:
    provider: str
    model: str


def resolve_route(tier: str) -> Route:
    if tier == "cheap":
        return Route(config.LLM_CHEAP_PROVIDER, config.LLM_CHEAP_MODEL)
    return Route(config.LLM_STRONG_PROVIDER, config.LLM_STRONG_MODEL)


def resolve_fallback() -> Route | None:
    """The fallback route, or None when no fallback is configured."""
    if config.LLM_FALLBACK_PROVIDER and config.LLM_FALLBACK_MODEL:
        return Route(config.LLM_FALLBACK_PROVIDER, config.LLM_FALLBACK_MODEL)
    return None
