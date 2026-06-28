from src.data_sources.sec_edgar import CompanyFiling, SECEdgarClient, extract_10k_sections
from src.memory.sec_filings import filing_sections_to_memory_records


class FakeSECClient(SECEdgarClient):
    def __init__(self, payloads, tmp_path):
        super().__init__(cache_dir=tmp_path, request_pause_seconds=0)
        self.payloads = payloads

    def _get_json(self, url):
        return self.payloads[url]

    def _get_text(self, url):
        return self.payloads[url]


def test_sec_client_loads_cached_ticker_mapping(tmp_path):
    cache_dir = tmp_path / "sec"
    cache_dir.mkdir()
    (cache_dir / "company_tickers.json").write_text(
        """
        {
          "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
        }
        """
    )

    client = SECEdgarClient(cache_dir=cache_dir, request_pause_seconds=0)

    assert client.load_company_tickers() == {"AAPL": "0000320193"}


def test_sec_client_finds_latest_10k_from_submissions(tmp_path):
    client = FakeSECClient(
        payloads={
            "https://data.sec.gov/submissions/CIK0000320193.json": {
                "filings": {
                    "recent": {
                        "form": ["8-K", "10-K"],
                        "accessionNumber": ["0000000000-00-000001", "0000320193-25-000079"],
                        "filingDate": ["2025-10-30", "2025-10-31"],
                        "reportDate": ["2025-10-30", "2025-09-27"],
                        "primaryDocument": ["aapl-8k.htm", "aapl-20250927.htm"],
                    }
                }
            }
        },
        tmp_path=tmp_path,
    )

    filing = client.get_latest_10k("AAPL", "0000320193")

    assert filing is not None
    assert filing.accession_number == "0000320193-25-000079"
    assert filing.primary_document == "aapl-20250927.htm"


def test_extract_10k_sections_from_html():
    long_business = "Business overview " * 30
    long_risks = "Risk factor disclosure " * 30
    long_mda = "Management discussion " * 30
    html = f"""
    <html><body>
      <h1>Item 1. {long_business}</h1>
      <h1>Item 1A. {long_risks}</h1>
      <h1>Item 7. {long_mda}</h1>
      <h1>Item 8. Financial statements.</h1>
    </body></html>
    """

    sections = extract_10k_sections(html)

    assert "item_1" in sections
    assert "item_1a" in sections
    assert "item_7" in sections
    assert "item_7a" not in sections
    assert "Business overview" in sections["item_1"]
    assert "Risk factor disclosure" in sections["item_1a"]


def test_filing_sections_to_memory_records():
    filing = CompanyFiling(
        ticker="AAPL",
        cik="0000320193",
        accession_number="0000320193-25-000079",
        form="10-K",
        filing_date="2025-10-31",
        report_date="2025-09-27",
        primary_document="aapl-20250927.htm",
    )

    records = filing_sections_to_memory_records(
        filing=filing,
        sections={
            "item_1": "Business section",
            "item_1a": "Risk section",
        },
    )

    assert [record.memory_type for record in records] == ["thesis", "risk_lesson"]
    assert records[0].id == "10k:AAPL:000032019325000079:item_1"
    assert records[0].symbols == ["AAPL"]
    assert records[0].source_type == "sec_10k"
    assert records[0].metadata["accession_number"] == "0000320193-25-000079"
    assert records[1].metadata["item_title"] == "Risk Factors"
