#!/usr/bin/env python3
"""Ingest latest SEC 10-K sections for watchlist companies into memory."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_sources.sec_edgar import SECEdgarClient, extract_10k_sections
from src.memory.ingestion_service import MemoryIngestionService
from src.memory.sec_filings import filing_sections_to_memory_records
from src.research.market_context import WATCHLIST

SKIP_SYMBOLS = {"SPY", "QQQ", "^VIX"}


def main() -> int:
    args = parse_args()
    symbols = [symbol.upper() for symbol in (args.symbols or WATCHLIST)]
    symbols = [symbol for symbol in symbols if symbol not in SKIP_SYMBOLS]

    client = SECEdgarClient(request_pause_seconds=args.pause)
    cik_by_ticker = client.load_company_tickers(refresh=args.refresh_tickers)

    records = []
    skipped = []
    processed = []

    for symbol in symbols:
        cik = cik_by_ticker.get(symbol)
        if cik is None:
            skipped.append({"symbol": symbol, "reason": "missing CIK mapping"})
            continue

        filing = client.get_latest_10k(symbol, cik)
        if filing is None:
            skipped.append({"symbol": symbol, "reason": "no recent 10-K found"})
            continue

        html = client.fetch_filing_html(filing, refresh=args.refresh_filings)
        sections = extract_10k_sections(html)
        filing_records = filing_sections_to_memory_records(filing=filing, sections=sections)
        records.extend(filing_records)
        processed.append(
            {
                "symbol": symbol,
                "cik": cik,
                "accession_number": filing.accession_number,
                "filing_date": filing.filing_date,
                "sections": sorted(sections),
                "records": len(filing_records),
            }
        )

    result = MemoryIngestionService().ingest_records(records)
    print(
        json.dumps(
            {
                "ingestion": result.to_dict(),
                "processed": processed,
                "skipped": skipped,
            },
            indent=2,
        )
    )
    return 0 if result.status in {"ok", "skipped"} else 1


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "symbols",
        nargs="*",
        help="Optional ticker symbols. Defaults to the repository watchlist.",
    )
    parser.add_argument(
        "--refresh-tickers",
        action="store_true",
        help="Refresh cached SEC ticker-to-CIK mapping.",
    )
    parser.add_argument(
        "--refresh-filings",
        action="store_true",
        help="Refetch filings even if cached locally.",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0.15,
        help="Pause between SEC requests in seconds.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
