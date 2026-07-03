import json

from src.llm.cost import summarize_run_cost


def _write_calls(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def test_summarize_aggregates_only_matching_run(tmp_path):
    log = tmp_path / "llm_calls.jsonl"
    _write_calls(
        log,
        [
            {"run_id": "A", "prompt_tokens": 100, "completion_tokens": 20, "est_cost_usd": 0.001, "latency_ms": 500},
            {"run_id": "A", "prompt_tokens": 50, "completion_tokens": 10, "est_cost_usd": 0.0005, "latency_ms": 300},
            {"run_id": "B", "prompt_tokens": 999, "completion_tokens": 999, "est_cost_usd": 9.9, "latency_ms": 9999},
        ],
    )

    summary = summarize_run_cost("A", path=log)

    assert summary == {
        "calls": 2,
        "prompt_tokens": 150,
        "completion_tokens": 30,
        "cost_usd": 0.0015,
        "latency_ms": 800.0,
    }


def test_summarize_missing_file_returns_zeros(tmp_path):
    summary = summarize_run_cost("A", path=tmp_path / "nope.jsonl")
    assert summary == {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cost_usd": 0.0,
        "latency_ms": 0.0,
    }


def test_summarize_none_run_id_returns_zeros(tmp_path):
    log = tmp_path / "llm_calls.jsonl"
    _write_calls(log, [{"run_id": "A", "prompt_tokens": 1, "completion_tokens": 1, "est_cost_usd": 0.1, "latency_ms": 1}])
    assert summarize_run_cost(None, path=log)["calls"] == 0


def test_summarize_skips_malformed_lines(tmp_path):
    log = tmp_path / "llm_calls.jsonl"
    log.write_text('{"run_id": "A", "est_cost_usd": 0.002}\nnot json\n\n')
    summary = summarize_run_cost("A", path=log)
    assert summary["calls"] == 1
    assert summary["cost_usd"] == 0.002
