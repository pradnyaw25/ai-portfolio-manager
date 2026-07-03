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
SUPPORTED_10Q_FORMS = {"10-Q", "10-Q/A"}
EARNINGS_8K_FORMS = {"8-K", "8-K/A"}
# 8-K Item 2.02 — Results of Operations and Financial Condition (the earnings release).
EARNINGS_ITEM = "2.02"

SECTION_ITEMS = {
    "item_1": "Business",
    "item_1a": "Risk Factors",
    "item_7": "Management Discussion and Analysis",
    "item_7a": "Market Risk",
    # 10-Q Part I items (MD&A and market risk).
    "item_2": "Management Discussion and Analysis",
    "item_3": "Market Risk",
}

# Item tokens extracted per form (order matters only for the regex alternation;
# section slicing takes the first occurrence, so Part I precedes Part II).
FORM_ITEM_TOKENS = {
    "10-K": ("1a", "1", "7a", "7"),
    "10-Q": ("2", "3"),
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
    items: str = ""

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

    def get_latest_filing(
        self,
        ticker: str,
        cik: str,
        forms: set[str],
        *,
        require_item: str | None = None,
    ) -> CompanyFiling | None:
        """Return the most recent filing whose form is in ``forms``.

        ``require_item`` filters 8-K-style filings to those reporting a specific
        item number (e.g. ``2.02`` for an earnings release).
        """
        submissions = self._get_json(f"{SEC_DATA_BASE}/submissions/CIK{cik}.json")
        filings = submissions.get("filings", {}).get("recent", {})
        form_list = filings.get("form", [])
        accession_numbers = filings.get("accessionNumber", [])
        filing_dates = filings.get("filingDate", [])
        report_dates = filings.get("reportDate", [])
        primary_documents = filings.get("primaryDocument", [])
        items_list = filings.get("items", [])

        for index, form in enumerate(form_list):
            if form not in forms:
                continue
            items = items_list[index] if index < len(items_list) else ""
            if require_item and require_item not in items:
                continue
            return CompanyFiling(
                ticker=ticker.upper(),
                cik=cik,
                accession_number=accession_numbers[index],
                form=form,
                filing_date=filing_dates[index],
                report_date=report_dates[index],
                primary_document=primary_documents[index],
                items=items,
            )
        return None

    def get_latest_10k(self, ticker: str, cik: str) -> CompanyFiling | None:
        return self.get_latest_filing(ticker, cik, SUPPORTED_FORM_TYPES)

    def get_latest_10q(self, ticker: str, cik: str) -> CompanyFiling | None:
        return self.get_latest_filing(ticker, cik, SUPPORTED_10Q_FORMS)

    def get_latest_earnings_8k(self, ticker: str, cik: str) -> CompanyFiling | None:
        return self.get_latest_filing(
            ticker, cik, EARNINGS_8K_FORMS, require_item=EARNINGS_ITEM
        )

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

    def find_earnings_exhibit(self, filing: CompanyFiling) -> str | None:
        """Return the EX-99.x exhibit document name for an 8-K, if present.

        The 8-K's primary document is the cover; the earnings release is a
        separate EX-99 exhibit listed in the accession index.
        """
        index = self._get_json(filing_index_url(filing))
        items = index.get("directory", {}).get("item", [])
        for entry in items:
            name = str(entry.get("name", ""))
            if re.search(r"(?i)ex-?99", name) and name.lower().endswith((".htm", ".html")):
                return name
        return None

    def fetch_earnings_release_html(
        self, filing: CompanyFiling, *, refresh: bool = False
    ) -> str | None:
        """Fetch the EX-99 earnings-release HTML for an 8-K (None if no exhibit)."""
        exhibit = self.find_earnings_exhibit(filing)
        if exhibit is None:
            return None

        path = filing.cache_dir / exhibit
        if path.exists() and not refresh:
            return path.read_text(errors="ignore")

        path.parent.mkdir(parents=True, exist_ok=True)
        url = (
            f"{SEC_ARCHIVES_BASE}/{int(filing.cik)}/"
            f"{filing.accession_no_dashes}/{exhibit}"
        )
        html = self._get_text(url)
        path.write_text(html)
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


def extract_filing_sections(html: str, *, item_tokens: tuple[str, ...]) -> dict[str, str]:
    """Extract item sections from a filing's HTML.

    ``item_tokens`` are the raw item numbers to slice on (e.g. ``("1a","1","7a","7")``
    for a 10-K). Sections are the text between consecutive item headers; the first
    occurrence of each item wins, so Part I precedes Part II in a 10-Q.
    """
    text = html_to_text(html)
    alternation = "|".join(sorted(item_tokens, key=len, reverse=True))
    markers = []
    for match in re.finditer(rf"\bitem\s+({alternation})\s*[\.\-:]", text, flags=re.IGNORECASE):
        key = f"item_{match.group(1).lower()}"
        if key in SECTION_ITEMS:
            markers.append((match.start(), key))

    sections: dict[str, str] = {}
    for index, (start, key) in enumerate(markers):
        if key in sections:
            continue
        end = markers[index + 1][0] if index + 1 < len(markers) else len(text)
        section_text = clean_section_text(text[start:end])
        if len(section_text) >= 200:
            sections[key] = section_text
    return sections


def extract_10k_sections(html: str) -> dict[str, str]:
    return extract_filing_sections(html, item_tokens=FORM_ITEM_TOKENS["10-K"])


def extract_10q_sections(html: str) -> dict[str, str]:
    return extract_filing_sections(html, item_tokens=FORM_ITEM_TOKENS["10-Q"])


def extract_earnings_release_text(html: str) -> str:
    return clean_section_text(html_to_text(html))


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
