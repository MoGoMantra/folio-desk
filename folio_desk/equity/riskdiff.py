"""Risk-factor change finder. Compares the Risk Factors section of the latest full risk-factor set (10-K, or a
10-Q that restates all of them) with the prior annual report, and pulls any 10-Q risk-factor update.
Unchanged boilerplate is dropped; NEW, REWRITTEN and REMOVED passages are returned. It finds text; it never
interprets it.
"""
from __future__ import annotations

import datetime as dt
import re

from ..data.edgar import EdgarClient, filings_list

FULL = 20000  # a section this long is a full risk-factor set, not a short update


def section(t: str, form: str) -> str:
    if form in ("20-F", "40-F"):
        pats = [r"(?is)\bD\.\s*Risk\s*Factors(.*?)(?:Item\s*4\.?\s*Information on the Company)"]
    elif form == "10-Q":
        pats = [r"(?is)Item\s*1A\.?\s*Risk\s*Factors(.*?)(?:Item\s*2\.?\s*Unregistered|Item\s*5\.?\s*Other|Item\s*6\.?\s*Exhibits)"]
    elif form in ("S-1", "F-1", "424B4"):
        pats = [r"(?is)\bRisk\s*Factors\s*\n(.*?)(?:\n\s*(?:Special Note Regarding|Cautionary Note Regarding|Use of Proceeds))"]
    else:
        pats = [r"(?is)Item\s*1A\.?\s*Risk\s*Factors(.*?)(?:Item\s*1B\.?\s*Unresolved|Item\s*1C\.?\s*Cybersecurity|Item\s*2\.?\s*Properties)"]
    best = ""
    for p in pats:
        for m in re.finditer(p, t):
            if len(m.group(1)) > len(best):
                best = m.group(1)
    return best.strip()


def paras(s: str) -> list[str]:
    out = []
    for p in re.split(r"\n+", s):
        p = re.sub(r"\s+", " ", p).strip()
        if len(p) >= 120 and not re.match(r"(?i)^(table of contents|\d+\s*$)", p):
            out.append(p)
    return out


def norm(p: str) -> str:
    p = re.sub(r"\b(19|20)\d{2}\b", "YYYY", p.lower())
    p = re.sub(r"\$?\d[\d,.]*\s*(%|million|billion)?", "N", p)
    return re.sub(r"[^a-z ]+", " ", p)


def shingles(p: str, k: int = 5) -> set[str]:
    w = norm(p).split()
    return {" ".join(w[i:i + k]) for i in range(max(1, len(w) - k + 1))}


def diff(new: list[str], old: list[str]) -> list[dict]:
    index: dict[str, list[int]] = {}
    for j, sh in enumerate(shingles(p) for p in old):
        for g in sh:
            index.setdefault(g, []).append(j)
    added = []
    for p in new:
        sh = shingles(p)
        hits: dict[int, int] = {}
        for g in sh:
            for j in index.get(g, ()):
                hits[j] = hits.get(j, 0) + 1
        best = max((h / max(len(sh), 1) for h in hits.values()), default=0.0)
        if best < 0.75:
            added.append({"text": p[:1500], "chars": len(p), "similarity": round(best, 2), "status": "new" if best < 0.35 else "rewritten"})
    return added


def riskdiff(ticker: str, ec: EdgarClient, cik: int | None = None) -> dict:
    warns: list[str] = []
    if not cik:
        cik, _ = ec.cik_for(ticker)
    if not cik:
        raise ValueError(f"{ticker} not found at SEC")
    fl = filings_list(ec.submissions(cik))
    annual = [f for f in fl if f["form"] in ("10-K", "20-F", "40-F")][:2]
    qs = [f for f in fl if f["form"] == "10-Q"][:1]
    ipo = [f for f in fl if f["form"] in ("424B4", "S-1", "F-1")][:1]
    cache: dict[str, str] = {}

    def sec_of(f):
        if f["acc"] not in cache:
            try:
                cache[f["acc"]] = section(ec.filing_text(cik, f["acc"], f["doc"]), f["form"])
            except Exception as e:
                warns.append(f"fetch {f['form']} {f['acc']}: {e}")
                cache[f["acc"]] = ""
        return cache[f["acc"]]

    res = {"ticker": ticker.upper(), "cik": cik, "asOf": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "compared": [], "added": [], "removed": [], "quarterly": None}
    cands = sorted(qs + annual, key=lambda f: f["date"], reverse=True)
    cur = next((f for f in cands if len(sec_of(f)) >= FULL), None)
    prior = None
    if cur:
        older = [f for f in annual if f["date"] < cur["date"]]
        prior = next((f for f in older if len(sec_of(f)) >= FULL), None) or \
            next((f for f in ipo if f["date"] < cur["date"] and len(sec_of(f)) >= FULL), None)
    if cur and prior:
        new, old = paras(sec_of(cur)), paras(sec_of(prior))
        res["compared"] = [{"form": f["form"], "date": f["date"], "acc": f["acc"], "chars": len(sec_of(f)), "role": r}
                           for f, r in ((cur, "current"), (prior, "prior"))]
        res["added"] = sorted(diff(new, old), key=lambda x: -x["chars"])[:25]
        res["removed"] = sorted(diff(old, new), key=lambda x: -x["chars"])[:10]
        res["counts"] = {"newParas": len(new), "oldParas": len(old), "added": len(res["added"]), "removed": len(res["removed"])}
    else:
        warns.append("could not find two full risk-factor sets to compare")
    q = qs[0] if qs else None
    if q and len(sec_of(q)) < FULL and (not cur or q["acc"] != cur["acc"]):
        s_ = sec_of(q)
        nochange = bool(re.search(r"(?i)no material changes", s_[:2000]))
        res["quarterly"] = {"form": "10-Q", "date": q["date"], "acc": q["acc"], "chars": len(s_),
                            "noMaterialChanges": nochange, "text": None if nochange else s_[:6000]}
    res["warnings"] = warns
    return res
