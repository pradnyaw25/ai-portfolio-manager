from src.data_sources.sec_edgar import CompanyFiling, SECTION_ITEMS
from src.memory.schemas import MemoryRecord

SECTION_MEMORY_TYPES = {
    "item_1": "thesis",
    "item_1a": "risk_lesson",
    "item_7": "thesis",
    "item_7a": "risk_lesson",
}


def filing_sections_to_memory_records(
    *,
    filing: CompanyFiling,
    sections: dict[str, str],
) -> list[MemoryRecord]:
    records = []
    for item_key, content in sections.items():
        memory_type = SECTION_MEMORY_TYPES.get(item_key)
        if memory_type is None:
            continue

        records.append(
            MemoryRecord(
                id=f"10k:{filing.ticker}:{filing.accession_no_dashes}:{item_key}",
                memory_type=memory_type,
                content=content,
                date=filing.filing_date,
                run_id=None,
                symbols=[filing.ticker],
                source_type="sec_10k",
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
                },
            )
        )
    return records
