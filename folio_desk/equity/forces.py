"""Forces ledger: the 4-10 headwinds and tailwinds that matter for a stock, each tied to evidence, a lever
and a number to watch. This module validates the ledger and sizes each lever change in $/share by
re-running the valuation engine (bump one lever in the base case, recompute fair value, take the difference).
Nothing in the sized output may be hand-set.
"""
from __future__ import annotations

import copy

from . import engine

TYPES = {"demand", "pricing", "costs", "supply", "competition", "policy", "macro", "financing", "ai-disruption",
         "concentration", "execution", "sentiment"}
EVID = {"filed", "guided", "reported", "inferred"}
INBASE = {"base", "bull", "bear", "none"}
HORIZ = {"0-6m", "6-18m", "18m+"}
LEVERS = {"growth", "margin", "multiple", "shares", "coe", "none"}


def bump(m: dict, lv: dict) -> dict:
    m = copy.deepcopy(m)
    d, kind = lv.get("delta"), lv["lever"]
    if kind in ("growth", "margin"):
        names = [x["name"] for x in m["drivers"]]
        tgt = [x for x in m["drivers"] if x["name"] == lv.get("driver")] if lv.get("driver") else m["drivers"]
        if lv.get("driver") and not tgt:
            raise ValueError(f"driver '{lv.get('driver')}' not in {names}")
        for x in tgt:
            sc = x["sc"][1]
            if kind == "growth":
                if sc.get("sales"):
                    raise ValueError(f"driver '{x['name']}' follows an explicit sales path; size it with a margin or multiple change")
                sc["g"] += d
            else:
                sc["m1"] += d
                sc["m2"] += d
    elif kind == "multiple":
        m["mult"][1] += d
    elif kind == "shares":
        m["shares"]["g"][1] += d
    elif kind == "coe":
        m["coe"] += d
    return m


def size(report: dict) -> tuple[dict | None, list[str]]:
    """Return (forcesCalc, problems)."""
    P: list[str] = []
    F = report.get("forces")
    if not F:
        return None, ["report.forces missing (the headwinds/tailwinds ledger)"]
    items = F.get("items") or []
    if not 4 <= len(items) <= 10:
        P.append(f"forces.items has {len(items)} rows; list 4-10 (the forces that matter, not everything)")
    if not {"tailwind", "headwind"} <= {i.get("direction") for i in items}:
        P.append("forces need at least one tailwind and one headwind")
    trig = report.get("triggers") or {}
    m0 = report["model"]
    base = engine.signal(m0, report["price"])
    rows = []
    for k, it in enumerate(items):
        nm = (it.get("force") or f"row {k + 1}")[:50]
        for key, allowed in (("type", TYPES), ("evidence", EVID), ("inBase", INBASE), ("horizon", HORIZ)):
            if it.get(key) not in allowed:
                P.append(f"force '{nm}': {key} must be one of {sorted(allowed)}")
        if it.get("direction") not in ("tailwind", "headwind"):
            P.append(f"force '{nm}': direction must be tailwind or headwind")
        if not it.get("source"):
            P.append(f"force '{nm}': source needed (accession, release, or dated URL)")
        w = it.get("watch") or {}
        if not (w.get("metric") and w.get("where")):
            P.append(f"force '{nm}': watch.metric and watch.where needed")
        lv = it.get("lever") or {"lever": "none"}
        tref = it.get("trigger")
        if lv.get("lever") not in LEVERS:
            P.append(f"force '{nm}': lever.lever must be one of {sorted(LEVERS)}")
        if lv.get("lever") == "none" and not tref and it.get("type") != "sentiment":
            P.append(f"force '{nm}': link it to a lever (with a delta) or to a trigger; only sentiment forces may have neither")
        if it.get("type") == "sentiment" and lv.get("lever") not in ("none", "multiple"):
            P.append(f"force '{nm}': sentiment can only move the multiple, never earnings")
        if it.get("evidence") in ("reported", "inferred") and it.get("inBase") == "base" and not it.get("baseReason"):
            P.append(f"force '{nm}': {it.get('evidence')} evidence is in the base case; keep unverified forces out of base or give baseReason")
        if tref:
            side, _, ix = str(tref).partition(":")
            lst = trig.get(side, []) if side in ("up", "down") else None
            if lst is None or not ix.isdigit() or int(ix) >= len(lst):
                P.append(f"force '{nm}': trigger '{tref}' does not point at an existing triggers.{side} entry")
        usd = None
        if lv.get("lever") not in (None, "none") and lv.get("lever") in LEVERS:
            d = lv.get("delta")
            if not isinstance(d, (int, float)) or d == 0:
                P.append(f"force '{nm}': lever.delta must be a non-zero number")
            else:
                sgn = 1 if it.get("direction") == "tailwind" else -1
                if (lv["lever"] in ("growth", "margin", "multiple") and d * sgn < 0) or (lv["lever"] in ("shares", "coe") and d * sgn > 0):
                    P.append(f"force '{nm}': delta sign contradicts direction")
                if lv["lever"] in ("growth", "margin") and abs(d) > 0.25:
                    P.append(f"force '{nm}': delta {d} looks like a percent; use fractions (0.03 = 3 points)")
                try:
                    usd = engine.signal(bump(m0, lv), report["price"])["fv"] - base["fv"]
                except Exception as e:
                    P.append(f"force '{nm}': could not size the lever change: {e}")
        rows.append({"i": k, "force": it.get("force"), "direction": it.get("direction"), "inBase": it.get("inBase"),
                     "sentiment": it.get("type") == "sentiment", "usd": None if usd is None else round(usd, 2),
                     "pctFV": None if usd is None or not base["fv"] else round(usd / base["fv"], 4)})
    if P:
        return None, P
    sized = [r for r in rows if r["usd"] is not None and not r["sentiment"]]
    tw = [r for r in sized if r["direction"] == "tailwind"]
    hw = [r for r in sized if r["direction"] == "headwind"]
    unp = [r for r in sized if r["inBase"] != "base"]
    total = lambda rs: round(sum(r["usd"] for r in rs), 2)
    return {"fv": round(base["fv"], 2), "rows": rows, "tailwindUsd": total(tw), "headwindUsd": total(hw),
            "netUsd": total(tw + hw), "unpricedNetUsd": total(unp),
            "sentimentUsd": total([r for r in rows if r["usd"] is not None and r["sentiment"]]),
            "note": "Each $ is the change in fair value from that one lever change in the base case, holding everything else."}, []
