import json
import re
import time
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import requests

from src.config import DATA_DIR, SEC_USER_AGENT

SEC_DATA_BASE = "https://data.sec.gov"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_CACHE_DIR = DATA_DIR / "sec_filings"

SUPPORTED_FORM_TYPES = {"10-K", "10-K/A"}
SECTION_ITEMS = {
    "item_1": "Business",
    "item_1a": "Risk Factors",
    "item_7": "Management Discussion and Analysis",
    "item_7a": "Market Risk",
}


@dataclass(frozen=True)
class CompanyFiling:
    ticker: str
    cik: str
    accession_number: str
    form: str
    filing_date: str
    report_date: str
    primary_document: str

    @property
    def accession_no_dashes(self) -> str:
        return self.accession_number.replace("-", "")

    @property
    def cache_dir(self) -> Path:
        return SEC_CACHE_DIR / self.ticker / self.accession_no_dashes

    @property
    def filing_url(self) -> str:
        return (
            f"{SEC_ARCHIVES_BASE}/{int(self.cik)}/"
            f"{self.accession_no_dashes}/{self.primary_document}"
        )


class SECEdgarClient:
    def __init__(
        self,
        *,
        cache_dir: Path = SEC_CACHE_DIR,
        user_agent: str = SEC_USER_AGENT,
        request_pause_seconds: float = 0.15,
    ):
        self.cache_dir = cache_dir
        self.user_agent = user_agent
        self.request_pause_seconds = request_pause_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
            }
        )

    def load_company_tickers(self, *, refresh: bool = False) -> dict[str, str]:
        path = self.cache_dir / "company_tickers.json"
        if path.exists() and not refresh:
            payload = json.loads(path.read_text())
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = self._get_json(COMPANY_TICKERS_URL)
            path.write_text(json.dumps(payload, indent=2))

        mapping = {}
        for item in payload.values():
            ticker = str(item.get("ticker", "")).upper()
            cik = str(item.get("cik_str", "")).zfill(10)
            if ticker and cik:
                mapping[ticker] = cik
        return mapping

    def get_latest_10k(self, ticker: str, cik: str) -> CompanyFiling | None:
        submissions = self._get_json(f"{SEC_DATA_BASE}/submissions/CIK{cik}.json")
        filings = submissions.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        accession_numbers = filings.get("accessionNumber", [])
        filing_dates = filings.get("filingDate", [])
        report_dates = filings.get("reportDate", [])
        primary_documents = filings.get("primaryDocument", [])

        for index, form in enumerate(forms):
            if form not in SUPPORTED_FORM_TYPES:
                continue
            return CompanyFiling(
                ticker=ticker.upper(),
                cik=cik,
                accession_number=accession_numbers[index],
                form=form,
                filing_date=filing_dates[index],
                report_date=report_dates[index],
                primary_document=primary_documents[index],
            )
        return None

    def fetch_filing_html(self, filing: CompanyFiling, *, refresh: bool = False) -> str:
        path = filing.cache_dir / filing.primary_document
        if path.exists() and not refresh:
            return path.read_text(errors="ignore")

        path.parent.mkdir(parents=True, exist_ok=True)
        html = self._get_text(filing.filing_url)
        path.write_text(html)
        (filing.cache_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "ticker": filing.ticker,
                    "cik": filing.cik,
                    "accession_number": filing.accession_number,
                    "form": filing.form,
                    "filing_date": filing.filing_date,
                    "report_date": filing.report_date,
                    "primary_document": filing.primary_document,
                    "filing_url": filing.filing_url,
                },
                indent=2,
            )
        )
        return html

    def _get_json(self, url: str) -> dict:
        time.sleep(self.request_pause_seconds)
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response.json()

    def _get_text(self, url: str) -> str:
        time.sleep(self.request_pause_seconds)
        response = self.session.get(url, timeout=60)
        response.raise_for_status()
        return response.text


def extract_10k_sections(html: str) -> dict[str, str]:
    text = html_to_text(html)
    markers = []
    for match in re.finditer(r"\bitem\s+(1a|1|7a|7)\s*[\.\-:]", text, flags=re.IGNORECASE):
        item = match.group(1).lower()
        key = f"item_{item}"
        if key in SECTION_ITEMS:
            markers.append((match.start(), key))

    sections = {}
    for index, (start, key) in enumerate(markers):
        if key in sections:
            continue
        end = markers[index + 1][0] if index + 1 < len(markers) else len(text)
        section_text = clean_section_text(text[start:end])
        if len(section_text) >= 200:
            sections[key] = section_text
    return sections


def html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<script.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?</style>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>|</div>|</tr>|</table>|</h[1-6]>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = text.replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", text)


# Sections are chunked downstream, so this cap only bounds how much of a very
# long section (e.g. Item 1A risk factors) we retain before splitting — it is no
# longer the size of a single stored vector.
SECTION_MAX_CHARS = 40000


def clean_section_text(text: str, *, max_chars: int = SECTION_MAX_CHARS) -> str:
    lines = [line.strip() for line in text.splitlines()]
    compact = "\n".join(line for line in lines if line)
    compact = re.sub(r"\n{3,}", "\n\n", compact)
    return compact[:max_chars].strip()


def filing_index_url(filing: CompanyFiling) -> str:
    return urljoin(
        f"{SEC_ARCHIVES_BASE}/{int(filing.cik)}/{filing.accession_no_dashes}/",
        "index.json",
    )
