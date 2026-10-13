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
    if tier == "judge":
        return Route(config.LLM_JUDGE_PROVIDER, config.LLM_JUDGE_MODEL)
    return Route(config.LLM_STRONG_PROVIDER, config.LLM_STRONG_MODEL)


def resolve_fallback() -> Route | None:
    """The fallback route, or None when no fallback is configured."""
    if config.LLM_FALLBACK_PROVIDER and config.LLM_FALLBACK_MODEL:
        return Route(config.LLM_FALLBACK_PROVIDER, config.LLM_FALLBACK_MODEL)
    return None


def parse_route(spec: str) -> Route:
    """``"groq:llama-3.3-70b-versatile"`` → ``Route``. Provider names are lower-case."""
    provider, sep, model = spec.partition(":")
    provider, model = provider.strip().lower(), model.strip()
    if not sep or not provider or not model:
        raise ValueError(f"route {spec!r} must look like provider:model")
    return Route(provider, model)


def shadow_routes() -> list[Route]:
    """The comparison models that see the PM prompt each cycle (config-driven)."""
    return [Route(provider, model) for provider, model in config.CALIBRATION_SHADOW_ROUTES]
