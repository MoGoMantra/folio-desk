"""SEC EDGAR client (primary source, free, official).

SEC fair-access rules require a User-Agent with your name and email, and at most 10 requests per second.
This client refuses to run without settings.sec.user_agent and stays under ~7 requests per second.
"""
from __future__ import annotations

import html
import re
import threading
import time

import httpx

from ..config import get_settings
from .base import DataError

SEC_MIN_GAP = 0.15
_lock = threading.Lock()
_last = [0.0]


class EdgarClient:
    def __init__(self, user_agent: str | None = None, transport: httpx.BaseTransport | None = None):
        ua = user_agent if user_agent is not None else get_settings().sec.user_agent
        if not ua or "@" not in ua:
            raise DataError(
                "SEC EDGAR needs your name and email as the User-Agent. Set [sec] user_agent in folio-desk.toml "
                "or the FOLIO_SEC_USER_AGENT environment variable, e.g. \"Jane Investor jane@example.com\"."
            )
        self.client = httpx.Client(headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, timeout=40,
                                   transport=transport, follow_redirects=True)

    def get(self, url: str, tries: int = 3) -> bytes:
        for k in range(tries):
            with _lock:
                wait = SEC_MIN_GAP - (time.time() - _last[0])
                if wait > 0:
                    time.sleep(wait)
                _last[0] = time.time()
            try:
                r = self.client.get(url)
                if r.status_code in (429, 500, 502, 503, 504) and k < tries - 1:
                    time.sleep(2 * (k + 1))
                    continue
                r.raise_for_status()
                return r.content
            except httpx.HTTPError:
                if k == tries - 1:
                    raise
                time.sleep(2 * (k + 1))
        raise DataError(f"EDGAR request failed: {url}")

    def json(self, url: str):
        import json
        return json.loads(self.get(url))

    # --- common lookups
    def cik_for(self, ticker: str) -> tuple[int | None, str | None]:
        m = self.json("https://www.sec.gov/files/company_tickers.json")
        t = ticker.upper().replace(".", "-")
        for v in m.values():
            if v["ticker"].upper() == t:
                return int(v["cik_str"]), v["title"]
        return None, None

    def submissions(self, cik: int) -> dict:
        return self.json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")

    def company_facts(self, cik: int) -> dict:
        return self.json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")

    def filing_url(self, cik: int, accession: str, doc: str) -> str:
        return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{doc}"

    def filing_text(self, cik: int, accession: str, doc: str) -> str:
        return html_text(self.get(self.filing_url(cik, accession, doc)))


def html_text(b: bytes) -> str:
    s = b.decode("utf-8", "ignore")
    s = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", s)
    s = re.sub(r"(?i)</t[dh]>", " | ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def filings_list(sub: dict) -> list[dict]:
    r = sub["filings"]["recent"]
    n = len(r["form"])
    return [dict(form=r["form"][i], date=r["filingDate"][i], acc=r["accessionNumber"][i], doc=r["primaryDocument"][i],
                 items=(r.get("items") or [""] * n)[i], report=(r.get("reportDate") or [""] * n)[i]) for i in range(n)]
