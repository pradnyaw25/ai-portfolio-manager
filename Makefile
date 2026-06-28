PYTHON ?= .venv/bin/python
PORT ?= 8000

.PHONY: help install test run run-graph run-legacy dashboard ingest-memory ingest-sec-filings memory-eval market-hours benchmark backfill status

help:
	@echo "AI Portfolio Manager commands"
	@echo ""
	@echo "  make install         Install project dependencies into the active Python env"
	@echo "  make test            Run the test suite"
	@echo "  make run             Run the daily portfolio cycle through LangGraph"
	@echo "  make run-graph       Run the daily portfolio cycle through LangGraph"
	@echo "  make run-legacy      Run the legacy sequential daily portfolio cycle"
	@echo "  make dashboard       Serve public/ locally on PORT (default: 8000)"
	@echo "  make ingest-memory   Ingest existing reports into Qdrant memory"
	@echo "  make ingest-sec-filings Ingest latest SEC 10-Ks for watchlist companies"
	@echo "  make memory-eval     Run offline memory retrieval evaluation fixtures"
	@echo "  make market-hours    Check whether a scheduled run should execute now"
	@echo "  make benchmark       Run benchmark script"
	@echo "  make backfill        Run backfill script"
	@echo "  make status          Show git status and latest run status"

install:
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) -m pytest -q

run:
	$(PYTHON) scripts/daily_run.py

run-graph:
	$(PYTHON) scripts/daily_run_graph.py

run-legacy:
	$(PYTHON) scripts/daily_run_legacy.py

dashboard:
	$(PYTHON) -m http.server $(PORT) --directory public

ingest-memory:
	$(PYTHON) -m src.memory.ingest

ingest-sec-filings:
	$(PYTHON) scripts/ingest_sec_filings.py

memory-eval:
	$(PYTHON) scripts/memory_eval.py

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
