"""XBRL company facts -> discrete quarters.

Prefer true 3-month facts; otherwise de-cumulate year-to-date facts within each fiscal year
(Q = YTD_n - YTD_n-1; Q4 = FY - 9M). Fallback tags are merged, latest filing wins. Quarter ends within
7 days of each other are clustered (52/53-week fiscal calendars).
"""
from __future__ import annotations

import datetime as dt

FORMS = ("10-Q", "10-K", "20-F", "6-K", "40-F", "10-Q/A", "10-K/A")
REV_TAGS = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"]
DUR_TAGS = {
    "revenue": REV_TAGS,
    "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
    "grossProfit": ["GrossProfit"],
    "opIncome": ["OperatingIncomeLoss"],
    "netIncome": ["NetIncomeLoss"],
    "epsDiluted": ["EarningsPerShareDiluted"],
    "dilutedShares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsForCapitalImprovements", "PaymentsToAcquireProductiveAssets"],
    "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet",
           "DepreciationAmortizationAndOther", "DepreciationAndAmortizationExcludingNuclearFuel", "Depreciation"],
    "amortization": ["AmortizationOfIntangibleAssets"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
    "interestExpense": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
}
INST_TAGS = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "stInvest": ["ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "receivables": ["AccountsReceivableNetCurrent"],
    "inventory": ["InventoryNet"],
    "payables": ["AccountsPayableCurrent"],
    "goodwill": ["Goodwill"],
    "intangibles": ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"],
    "assets": ["Assets"],
    "debtCurrent": ["DebtCurrent", "LongTermDebtCurrent", "ShortTermBorrowings"],
    "debtLT": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "LongTermDebt"],
    "equity": ["StockholdersEquity"],
    "contractLiab": ["ContractWithCustomerLiability"],
}


def days(a: str, b: str) -> int:
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def facts_for(cf: dict, tag: str):
    for ns in ("us-gaap", "ifrs-full", "dei"):
        g = cf.get("facts", {}).get(ns, {})
        if tag in g:
            units = g[tag]["units"]
            return units.get("USD") or units.get("USD/shares") or units.get("shares") or next(iter(units.values()))
    return None


def quarterly(cf: dict, tags: list[str]) -> tuple[dict, list]:
    best, used = {}, []
    for tag in tags:
        u = facts_for(cf, tag)
        if not u:
            continue
        used.append(tag)
        q3, ytd = {}, {}
        for f in u:
            if not f.get("start") or f.get("form") not in FORMS:
                continue
            d = days(f["start"], f["end"])
            if 80 <= d <= 100 and (f["end"] not in q3 or f.get("filed", "") >= q3[f["end"]][1]):
                q3[f["end"]] = (f["val"], f.get("filed", ""))
            if d >= 80:
                key = (f["start"], f["end"])
                if key not in ytd or f.get("filed", "") >= ytd[key][1]:
                    ytd[key] = (f["val"], f.get("filed", ""))
        out = {e: v[0] for e, v in q3.items()}
        by_start: dict = {}
        for (s, e), (v, _) in ytd.items():
            by_start.setdefault(s, []).append((e, v))
        for arr in by_start.values():
            arr.sort()
            prev = None
            for e, v in arr:
                if prev is not None and e not in out and 80 <= days(prev[0], e) <= 100:
                    out[e] = v - prev[1]
                prev = (e, v)
        for e, v in out.items():
            best.setdefault(e, v)
    return best, used


def instant(cf: dict, tags: list[str]) -> tuple[dict, list]:
    best, used = {}, []
    for tag in tags:
        u = facts_for(cf, tag)
        if not u:
            continue
        used.append(tag)
        for f in u:
            if f.get("start") or f.get("form") not in FORMS:
                continue
            best.setdefault(f["end"], f["val"])
    return best, used


def snap_quarter_ends(series_list: list[dict], n: int = 12):
    ends = sorted({e for s in series_list for e in s})
    clusters: list[list[str]] = []
    for e in ends:
        if clusters and days(clusters[-1][-1], e) <= 7:
            clusters[-1].append(e)
        else:
            clusters.append([e])
    return [c[-1] for c in clusters][-n:], clusters[-n:]


def pick(series: dict, cluster: list[str]):
    for e in reversed(cluster):
        if e in series:
            return series[e]
    return None


def quarters_table(cf: dict, n: int = 12) -> tuple[list[dict], dict, list[str]]:
    """Returns (quarters oldest->newest, tags used per line, warnings)."""
    dur, used = {}, {}
    for k, tags in DUR_TAGS.items():
        dur[k], used[k] = quarterly(cf, tags)
    inst = {}
    for k, tags in INST_TAGS.items():
        inst[k], used[k] = instant(cf, tags)
    q_ends, clusters = snap_quarter_ends([dur["revenue"], dur["netIncome"]], n)
    rows = []
    for e, cl in zip(q_ends, clusters):
        row = {"end": e}
        for k in dur:
            row[k] = pick(dur[k], cl)
        for k in inst:
            row[k] = pick(inst[k], cl)
        rows.append(row)
    for row in rows:  # de-cumulated share counts are meaningless: back them out of NI / EPS when off by > 20%
        if row.get("dilutedShares") is not None and row.get("netIncome") and row.get("epsDiluted"):
            implied = row["netIncome"] / row["epsDiluted"]
            if implied and abs(row["dilutedShares"] - implied) / abs(implied) > 0.2:
                row["dilutedShares"] = round(implied)
    warns = []
    missing = [k for k in ("revenue", "netIncome", "ocf", "capex") if not any(q.get(k) is not None for q in rows[-4:])]
    if missing:
        warns.append(f"XBRL gaps in the last 4 quarters: {missing} (check the filing tables directly)")
    return rows, used, warns
