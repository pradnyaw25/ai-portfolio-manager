from pathlib import Path

from scripts.memory_eval import FixtureMemoryRetriever
from src.memory.evals import (
    evaluate_group,
    evaluate_memory_retrieval,
    load_memory_eval_scenarios,
)

FIXTURE_PATH = Path("tests/fixtures/memory_evals/retrieval_scenarios.json")


def test_memory_eval_fixtures_pass_with_fixture_retriever():
    scenarios = load_memory_eval_scenarios(FIXTURE_PATH)

    result = evaluate_memory_retrieval(
        scenarios,
        retriever_factory=lambda scenario: FixtureMemoryRetriever(scenario.documents),
    )

    assert result.passed
    assert result.recall == 1.0
    assert result.precision > 0
    assert [scenario.scenario_id for scenario in result.scenarios] == [
        "nvda_concentration_risk",
        "cash_discipline",
        "earnings_and_10q_context",
    ]


def test_memory_eval_group_result_reports_missing_expected_ids():
    result = evaluate_group(
        group="risk_lessons",
        expected_ids=["risk:expected"],
        actual_ids=["risk:other"],
    )

    assert not result.passed
    assert result.recall == 0
    assert result.precision == 0
    assert result.missing_ids == ["risk:expected"]
    assert result.unexpected_ids == ["risk:other"]


def test_memory_eval_result_to_dict_contains_diagnostics():
    scenarios = load_memory_eval_scenarios(FIXTURE_PATH)
    result = evaluate_memory_retrieval(
        scenarios[:1],
        retriever_factory=lambda scenario: FixtureMemoryRetriever(scenario.documents),
    )

    payload = result.to_dict()

    assert payload["passed"]
    assert payload["scenarios"][0]["groups"][0]["expected_ids"]
    assert payload["scenarios"][0]["groups"][0]["actual_ids"]
