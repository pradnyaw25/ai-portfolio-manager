"""P4-2: 10-Q and 8-K earnings ingestion into the same memory schema, cited."""

from evals.scenarios import EARNINGS_CONTEXT
from evals.scorers import score_citation_validity
from src.data_sources.sec_edgar import (
    CompanyFiling,
    SECEdgarClient,
    extract_10q_sections,
    extract_earnings_release_text,
    filing_index_url,
)
from src.memory.citations import _looks_like_memory_id, review_memory_citations
from src.memory.sec_filings import (
    earnings_release_to_memory_records,
    filing_sections_to_memory_records,
)

CIK = "0000320193"

SUBMISSIONS = {
    "https://data.sec.gov/submissions/CIK0000320193.json": {
        "filings": {
            "recent": {
                "form": ["8-K", "10-Q", "10-K"],
                "accessionNumber": [
                    "0000320193-25-000123",
                    "0000320193-25-000124",
                    "0000320193-25-000079",
                ],
                "filingDate": ["2026-05-01", "2026-05-02", "2025-10-31"],
                "reportDate": ["2026-03-28", "2026-03-28", "2025-09-27"],
                "primaryDocument": ["aapl-8k.htm", "aapl-10q.htm", "aapl-10k.htm"],
                "items": ["2.02,9.01", "", ""],
            }
        }
    },
}


class FakeSECClient(SECEdgarClient):
    def __init__(self, payloads, tmp_path):
        super().__init__(cache_dir=tmp_path, request_pause_seconds=0)
        self.payloads = payloads

    def _get_json(self, url):
        return self.payloads[url]

    def _get_text(self, url):
        return self.payloads[url]


def test_get_latest_10q_selects_10q_form(tmp_path):
    client = FakeSECClient(SUBMISSIONS, tmp_path)
    filing = client.get_latest_10q("AAPL", CIK)
    assert filing is not None
    assert filing.form == "10-Q"
    assert filing.accession_number == "0000320193-25-000124"


def test_get_latest_earnings_8k_requires_item_202(tmp_path):
    client = FakeSECClient(SUBMISSIONS, tmp_path)
    filing = client.get_latest_earnings_8k("AAPL", CIK)
    assert filing is not None
    assert filing.form == "8-K"
    assert "2.02" in filing.items


def test_get_latest_earnings_8k_skips_non_earnings_8k(tmp_path):
    payloads = {
        "https://data.sec.gov/submissions/CIK0000320193.json": {
            "filings": {"recent": {
                "form": ["8-K"],
                "accessionNumber": ["0000320193-25-000200"],
                "filingDate": ["2026-06-01"],
                "reportDate": ["2026-06-01"],
                "primaryDocument": ["aapl-8k.htm"],
                "items": ["5.02"],  # departure of directors — not earnings
            }}
        }
    }
    client = FakeSECClient(payloads, tmp_path)
    assert client.get_latest_earnings_8k("AAPL", CIK) is None


def _earnings_filing():
    return CompanyFiling(
        ticker="AAPL", cik=CIK, accession_number="0000320193-25-000123",
        form="8-K", filing_date="2026-05-01", report_date="2026-03-28",
        primary_document="aapl-8k.htm", items="2.02,9.01",
    )


def test_find_earnings_exhibit_locates_ex99(tmp_path):
    filing = _earnings_filing()
    payloads = {
        filing_index_url(filing): {
            "directory": {"item": [
                {"name": "aapl-8k.htm"},
                {"name": "aapl-ex991.htm"},
            ]}
        }
    }
    client = FakeSECClient(payloads, tmp_path)
    assert client.find_earnings_exhibit(filing) == "aapl-ex991.htm"


def test_extract_10q_sections_finds_mdna_and_market_risk():
    html = f"""
    <html><body>
      <p>Part I Financial Information</p>
      <h2>Item 2. Management's Discussion and Analysis {"of results " * 40}</h2>
      <h2>Item 3. Quantitative and Qualitative Disclosures About Market Risk {"exposure " * 40}</h2>
      <p>Part II Other Information</p>
      <h2>Item 1. Legal Proceedings.</h2>
    </body></html>
    """
    sections = extract_10q_sections(html)
    assert "item_2" in sections
    assert "item_3" in sections


def test_filing_sections_to_memory_records_10q_uses_10q_prefix():
    filing = CompanyFiling(
        ticker="AAPL", cik=CIK, accession_number="0000320193-25-000124",
        form="10-Q", filing_date="2026-05-02", report_date="2026-03-28",
        primary_document="aapl-10q.htm",
    )
    records = filing_sections_to_memory_records(
        filing=filing, sections={"item_2": "MD&A section", "item_3": "Market risk section"}
    )
    assert records[0].id == "10q:AAPL:000032019325000124:item_2:0000"
    assert records[0].source_type == "sec_10q"
    assert [r.memory_type for r in records] == ["thesis", "risk_lesson"]
    assert records[0].metadata["item_title"] == "Management Discussion and Analysis"


def test_earnings_release_records_are_earnings_events():
    filing = _earnings_filing()
    text = extract_earnings_release_text(
        "<html><body><p>" + "Record services revenue and upbeat guidance. " * 60 + "</p></body></html>"
    )
    records = earnings_release_to_memory_records(filing=filing, text=text)
    assert len(records) >= 1
    assert records[0].memory_type == "earnings_event"
    assert records[0].source_type == "earnings_8k"
    assert records[0].id == "earnings_event:AAPL:000032019325000123:0000"
    assert records[0].symbols == ["AAPL"]


def test_knowledge_source_ids_are_citable():
    assert _looks_like_memory_id("earnings_event:AAPL:000:0000")
    assert _looks_like_memory_id("10q:AAPL:000:item_2:0000")
    assert _looks_like_memory_id("10k:AAPL:000:item_1a:0000")
    assert not _looks_like_memory_id("random:AAPL")


def test_earnings_context_scenario_citation_validates():
    """A decision citing the scenario's earnings memory is a valid, no-warning citation."""
    earnings_id = EARNINGS_CONTEXT.memory[0]["id"]
    decision = {
        "outlook": "constructive",
        "summary": "Hold AAPL into strength.",
        "trades": [
            {"symbol": "AAPL", "action": "HOLD", "confidence": 0.7, "sources_used": [earnings_id]}
        ],
    }
    review = review_memory_citations(raw_decision=decision, memory_used=EARNINGS_CONTEXT.memory)
    assert not review.warnings
    assert review.citations[0].memory_id == earnings_id
    assert review.citations[0].source_type == "earnings_8k"
    # And the eval's deterministic scorer passes on it.
    assert score_citation_validity(decision, EARNINGS_CONTEXT).passed


def test_earnings_context_scenario_flags_unknown_citation():
    decision = {
        "trades": [
            {"symbol": "AAPL", "action": "BUY", "confidence": 0.7,
             "sources_used": ["earnings_event:AAPL:does-not-exist:0000"]}
        ],
    }
    assert not score_citation_validity(decision, EARNINGS_CONTEXT).passed
