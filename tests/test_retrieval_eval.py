from pathlib import Path

from src.memory.retrieval_eval import load_chunking_scenarios, run_chunking_eval

FIXTURE = Path("tests/fixtures/memory_evals/chunking_scenarios.json")


def test_fixture_has_at_least_20_scenarios():
    assert len(load_chunking_scenarios(FIXTURE)) >= 20


def test_chunking_improves_ranking_over_unchunked():
    result = run_chunking_eval(load_chunking_scenarios(FIXTURE), k=5)
    assert result.chunked.mrr > result.unchunked.mrr
    assert result.chunked.hit_at_1 > result.unchunked.hit_at_1
    assert result.chunked.recall_at_k > result.unchunked.recall_at_k
    assert result.improvement["mrr"] > 0


def test_chunked_retrieval_finds_every_answer():
    result = run_chunking_eval(load_chunking_scenarios(FIXTURE), k=5)
    assert result.chunked.recall_at_k == 1.0


def test_eval_is_deterministic():
    scenarios = load_chunking_scenarios(FIXTURE)
    assert run_chunking_eval(scenarios, k=5).to_dict() == run_chunking_eval(scenarios, k=5).to_dict()
