"""Decision eval harness.

Runs the portfolio manager agent against golden scenarios and scores its output
with deterministic scorers (schema validity, risk compliance, citation validity)
plus an optional LLM-as-judge grounding scorer. Used both by ``make eval`` (live,
against the real model) and by pytest (with an injected fake gateway, no API key).
"""
