from src.agents import portfolio_manager
from src.agents.portfolio_manager import PortfolioManagerAgent
from src.llm.schemas import DecisionResponse


def test_decide_returns_plain_dict(monkeypatch):
    """The decision must stay a dict — the risk manager, citation layer, and
    decision journal all consume it via ``.get(...)`` / ``[...]``."""

    captured = {}

    def fake_complete_structured(messages, schema, **kwargs):
        captured["schema"] = schema
        captured["prompt_version"] = kwargs.get("prompt_version")
        return DecisionResponse(
            outlook="BULLISH",
            summary="looks good",
            trades=[{"symbol": "AAPL", "action": "BUY", "shares": 5, "confidence": 0.8}],
        )

    monkeypatch.setattr(portfolio_manager, "complete_structured", fake_complete_structured)

    result = PortfolioManagerAgent().decide(
        portfolio="snapshot", research={"symbols": ["AAPL"]}, benchmark="spy", memory=None
    )

    assert isinstance(result, dict)
    assert result["outlook"] == "BULLISH"
    assert result["trades"][0]["symbol"] == "AAPL"
    assert captured["schema"] is DecisionResponse
    assert captured["prompt_version"] == "portfolio_manager/v1"
