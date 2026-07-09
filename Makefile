PYTHON ?= .venv/bin/python
PORT ?= 8000

.PHONY: help install test eval eval-compare eval-ablate baselines run dashboard ingest-memory ingest-sec-filings memory-eval chunking-eval reflect letter mcp market-hours benchmark backfill status

help:
	@echo "AI Portfolio Manager commands"
	@echo ""
	@echo "  make install         Install project dependencies into the active Python env"
	@echo "  make test            Run the test suite"
	@echo "  make eval            Run the decision eval harness (needs OPENAI_API_KEY)"
	@echo "  make eval-compare    Compare strong-tier models: quality vs cost delta (needs OPENAI_API_KEY)"
	@echo "  make eval-ablate     Ablate memory/debate: does the machinery improve decisions? (needs OPENAI_API_KEY)"
	@echo "  make baselines       Compare the fund vs buy-and-hold SPY/QQQ and random-from-watchlist"
	@echo "  make run             Run the daily portfolio cycle through LangGraph"
	@echo "  make dashboard       Serve public/ locally on PORT (default: 8000)"
	@echo "  make ingest-memory   Ingest existing reports into Qdrant memory"
	@echo "  make ingest-sec-filings Ingest latest SEC 10-Ks for watchlist companies"
	@echo "  make memory-eval     Run offline memory retrieval evaluation fixtures"
	@echo "  make chunking-eval   Compare chunked vs unchunked retrieval (offline, no API key)"
	@echo "  make reflect         Run the weekly lessons-learned reflection"
	@echo "  make letter          Generate the weekly investor letter (grounded)"
	@echo "  make mcp             Start the read-only fund MCP server (stdio)"
	@echo "  make market-hours    Check whether a scheduled run should execute now"
	@echo "  make benchmark       Run benchmark script"
	@echo "  make backfill        Run backfill script"
	@echo "  make status          Show git status and latest run status"

install:
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) -m pytest -q

eval:
	LLM_TEMPERATURE=0 $(PYTHON) -m evals.runner

eval-compare:
	LLM_TEMPERATURE=0 $(PYTHON) scripts/compare_strong_model.py

eval-ablate:
	LLM_TEMPERATURE=0 $(PYTHON) scripts/compare_ablations.py

baselines:
	$(PYTHON) scripts/compare_baselines.py

run:
	$(PYTHON) scripts/daily_run.py

dashboard:
	$(PYTHON) -m http.server $(PORT) --directory public

ingest-memory:
	$(PYTHON) -m src.memory.ingest

ingest-sec-filings:
	$(PYTHON) scripts/ingest_sec_filings.py

memory-eval:
	$(PYTHON) scripts/memory_eval.py

chunking-eval:
	$(PYTHON) scripts/chunking_eval.py

reflect:
	$(PYTHON) scripts/weekly_reflection.py

letter:
	$(PYTHON) scripts/weekly_letter.py

mcp:
	$(PYTHON) mcp_server/server.py

market-hours:
	$(PYTHON) scripts/market_hours_guard.py

benchmark:
	$(PYTHON) scripts/benchmark.py

backfill:
	$(PYTHON) scripts/backfill.py

status:
	git status --short --branch
	@echo ""
	@if [ -f public/run_status.json ]; then \
		$(PYTHON) -m json.tool public/run_status.json; \
	else \
		echo "No public/run_status.json found."; \
	fi
