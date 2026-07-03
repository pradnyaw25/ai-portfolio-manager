from src.config import sector_for
from src.data_sources.sec_edgar import CompanyFiling, SECTION_ITEMS
from src.memory.chunking import chunk_text
from src.memory.schemas import MemoryRecord

# Section item -> memory type, per form. 10-K business/MD&A read as theses; risk
# and market-risk items read as risk lessons.
SECTION_MEMORY_TYPES = {
    "item_1": "thesis",
    "item_1a": "risk_lesson",
    "item_7": "thesis",
    "item_7a": "risk_lesson",
}
SECTION_MEMORY_TYPES_10Q = {
    "item_2": "thesis",
    "item_3": "risk_lesson",
}

# form -> (id prefix, source_type, section->memory-type map). The id prefix keeps
# citations legible (10k:… / 10q:…) and matches MEMORY_ID_PREFIXES.
FORM_RECORD_CONFIG = {
    "10-K": ("10k", "sec_10k", SECTION_MEMORY_TYPES),
    "10-K/A": ("10k", "sec_10k", SECTION_MEMORY_TYPES),
    "10-Q": ("10q", "sec_10q", SECTION_MEMORY_TYPES_10Q),
    "10-Q/A": ("10q", "sec_10q", SECTION_MEMORY_TYPES_10Q),
}


def filing_sections_to_memory_records(
    *,
    filing: CompanyFiling,
    sections: dict[str, str],
) -> list[MemoryRecord]:
    """Chunk each extracted filing section into per-chunk memory records.

    Form-aware: a 10-K yields ``10k:…`` records, a 10-Q yields ``10q:…`` records,
    both through the same chunking + sector-tagging pipeline.
    """
    id_prefix, source_type, section_types = FORM_RECORD_CONFIG.get(
        filing.form, ("10k", "sec_10k", SECTION_MEMORY_TYPES)
    )
    sector = sector_for(filing.ticker)
    records: list[MemoryRecord] = []
    for item_key, content in sections.items():
        memory_type = section_types.get(item_key)
        if memory_type is None:
            continue

        base_id = f"{id_prefix}:{filing.ticker}:{filing.accession_no_dashes}:{item_key}"
        for chunk in chunk_text(content, label=base_id):
            records.append(
                MemoryRecord(
                    id=f"{base_id}:{chunk.index:04d}",
                    memory_type=memory_type,
                    content=chunk.text,
                    date=filing.filing_date,
                    run_id=None,
                    symbols=[filing.ticker],
                    sectors=[sector],
                    source_type=source_type,
                    source_id=filing.filing_url,
                    metadata={
                        "ticker": filing.ticker,
                        "cik": filing.cik,
                        "accession_number": filing.accession_number,
                        "form": filing.form,
                        "filing_date": filing.filing_date,
                        "report_date": filing.report_date,
                        "primary_document": filing.primary_document,
                        "item": item_key,
                        "item_title": SECTION_ITEMS.get(item_key),
                        "sector": sector,
                        "chunk_index": chunk.index,
                        "total_chunks": chunk.total,
                    },
                )
            )
    return records


def earnings_release_to_memory_records(
    *,
    filing: CompanyFiling,
    text: str,
) -> list[MemoryRecord]:
    """Chunk an 8-K earnings-release exhibit into ``earnings_event`` records."""
    sector = sector_for(filing.ticker)
    base_id = f"earnings_event:{filing.ticker}:{filing.accession_no_dashes}"
    records: list[MemoryRecord] = []
    for chunk in chunk_text(text, label=base_id):
        records.append(
            MemoryRecord(
                id=f"{base_id}:{chunk.index:04d}",
                memory_type="earnings_event",
                content=chunk.text,
                date=filing.filing_date,
                run_id=None,
                symbols=[filing.ticker],
                sectors=[sector],
                source_type="earnings_8k",
                source_id=filing.filing_url,
                metadata={
                    "ticker": filing.ticker,
                    "cik": filing.cik,
                    "accession_number": filing.accession_number,
                    "form": filing.form,
                    "filing_date": filing.filing_date,
                    "report_date": filing.report_date,
                    "primary_document": filing.primary_document,
                    "item": "earnings_release",
                    "item_title": "Earnings Release",
                    "sector": sector,
                    "chunk_index": chunk.index,
                    "total_chunks": chunk.total,
                },
            )
        )
    return records
