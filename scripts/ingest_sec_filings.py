#!/usr/bin/env python3
"""Ingest latest SEC filings (10-K, 10-Q, 8-K earnings) for watchlist companies."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import DATA_DIR, WATCHLIST
from src.data_sources.sec_edgar import (
    SECEdgarClient,
    extract_10k_sections,
    extract_10q_sections,
    extract_earnings_release_text,
)
from src.memory.ingestion_service import MemoryIngestionService
from src.memory.sec_filings import (
    earnings_release_to_memory_records,
    filing_sections_to_memory_records,
)

SKIP_SYMBOLS = {"SPY", "QQQ", "^VIX"}
DEFAULT_SUMMARY_PATH = DATA_DIR / "memory_sec_filings.json"
DEFAULT_FORMS = ["10-K", "10-Q", "8-K"]


def _ingest_periodic(client, symbol, cik, args, *, form_label, get_filing, extract):
    """Ingest a 10-K or 10-Q: fetch, extract sections, build chunked records."""
    filing = get_filing(symbol, cik)
    if filing is None:
        return [], {"symbol": symbol, "form": form_label, "reason": f"no recent {form_label}"}
    html = client.fetch_filing_html(filing, refresh=args.refresh_filings)
    sections = extract(html)
    records = filing_sections_to_memory_records(filing=filing, sections=sections)
    return records, {
        "symbol": symbol,
        "form": form_label,
        "accession_number": filing.accession_number,
        "filing_date": filing.filing_date,
        "sections": sorted(sections),
        "records": len(records),
    }


def _ingest_earnings(client, symbol, cik, args):
    """Ingest the latest 8-K earnings release (EX-99 exhibit)."""
    filing = client.get_latest_earnings_8k(symbol, cik)
    if filing is None:
        return [], {"symbol": symbol, "form": "8-K", "reason": "no earnings 8-K"}
    html = client.fetch_earnings_release_html(filing, refresh=args.refresh_filings)
    if not html:
        return [], {"symbol": symbol, "form": "8-K", "reason": "no EX-99 earnings exhibit"}
    records = earnings_release_to_memory_records(
        filing=filing, text=extract_earnings_release_text(html)
    )
    return records, {
        "symbol": symbol,
        "form": "8-K",
        "accession_number": filing.accession_number,
        "filing_date": filing.filing_date,
        "records": len(records),
    }


def main() -> int:
    args = parse_args()
    symbols = [symbol.upper() for symbol in (args.symbols or WATCHLIST)]
    symbols = [symbol for symbol in symbols if symbol not in SKIP_SYMBOLS]
    forms = [f.upper() for f in args.forms]

    client = SECEdgarClient(request_pause_seconds=args.pause)
    cik_by_ticker = client.load_company_tickers(refresh=args.refresh_tickers)

    ingestors = {
        "10-K": lambda s, c: _ingest_periodic(
            client, s, c, args, form_label="10-K",
            get_filing=client.get_latest_10k, extract=extract_10k_sections,
        ),
        "10-Q": lambda s, c: _ingest_periodic(
            client, s, c, args, form_label="10-Q",
            get_filing=client.get_latest_10q, extract=extract_10q_sections,
        ),
        "8-K": lambda s, c: _ingest_earnings(client, s, c, args),
    }

    records = []
    skipped = []
    processed = []

    for symbol in symbols:
        cik = cik_by_ticker.get(symbol)
        if cik is None:
            skipped.append({"symbol": symbol, "reason": "missing CIK mapping"})
            continue

        for form in forms:
            ingestor = ingestors.get(form)
            if ingestor is None:
                continue
            filing_records, entry = ingestor(symbol, cik)
            records.extend(filing_records)
            (skipped if "reason" in entry else processed).append(entry)

    result = MemoryIngestionService().ingest_records(records)
    payload = {
        "ingested_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "ingestion": result.to_dict(),
        "processed": processed,
        "skipped": skipped,
    }
    print(json.dumps(payload, indent=2))
    if args.summary_path:
        args.summary_path.parent.mkdir(parents=True, exist_ok=True)
        args.summary_path.write_text(json.dumps(payload, indent=2))
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
        "--forms",
        type=lambda v: [f.strip() for f in v.split(",") if f.strip()],
        default=DEFAULT_FORMS,
        help="Comma-separated forms to ingest (default: 10-K,10-Q,8-K).",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0.15,
        help="Pause between SEC requests in seconds.",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=DEFAULT_SUMMARY_PATH,
        help="Write the latest SEC filing ingestion summary for memory health exports.",
    )
    parser.add_argument(
        "--no-summary",
        action="store_const",
        const=None,
        dest="summary_path",
        help="Only print the SEC filing ingestion summary.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
