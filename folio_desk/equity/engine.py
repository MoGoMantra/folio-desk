"""Valuation engine: driver-based scenarios (bear / base / bull) -> economic EPS -> exit multiple -> present
value, plus a DCF cross-check, a margin of safety from downside dispersion, and BUY / ACCUMULATE / HOLD /
TRIM levels. The web page recomputes the same maths live when levers are edited (web/src/lib/engine.ts).

Units: $mm for sales, income, capex, net debt; mm shares; fractions for rates.
"""
from __future__ import annotations

import statistics as st


def run(m: dict, i: int) -> dict:
    Y, prev = [], None
    n = len(m["years"])
    for t in range(n):
        y = {"seg": []}
        sales = ni = 0.0
        for k, d in enumerate(m["drivers"]):
            sc = d["sc"][i]
            if t == 0:
                s, mg = d["base"], d["m0"]
            else:
                ov = sc.get("sales")
                if ov and len(ov) >= t and ov[t - 1] is not None:
                    s = ov[t - 1]
                else:
                    g = sc["g"] * (1 - sc.get("d", 0)) ** (t - 1)
                    s = prev["seg"][k] * (1 + g)
                mg = sc["m1"] if t == 1 else sc["m2"]
            y["seg"].append(s)
            sales += s
            ni += s * mg
        corp = m["corp"]["base"] if t == 0 else prev["corp"] * (1 + m["corp"]["g"][i])
        sh = m["shares"]["base"] if t == 0 else prev["sh"] * (1 + m["shares"]["g"][i])
        y.update(corp=corp, sh=sh, sales=sales)
        y["ni"] = ni - corp
        y["eps"] = y["ni"] / sh
        ph = m["haircut"].get("phase", 2)
        y["hc"] = m["haircut"]["perShare"][i] * min(1, t / ph) if ph else m["haircut"]["perShare"][i]
        y["econ"] = y["eps"] - y["hc"]
        dc = m["dcf"]
        capex = dc["capex0"] if t == 0 else dc["capex"][i][min(t - 1, len(dc["capex"][i]) - 1)]
        prior = dc["salesPrior"] if t == 0 else prev["sales"]
        y["fcf"] = y["econ"] * sh + dc["da"][i] * sales - capex - dc["wc"][i] * (sales - prior)
        Y.append(y)
        prev = y
    v = m["valueYear"]
    disc = 1 / (1 + m["coe"]) ** m["yrs"]
    pv = Y[v]["econ"] * m["mult"][i] * disc
    w, tg = m["dcf"]["wacc"][i], m["dcf"]["tg"][i]
    pvf = sum(y["fcf"] / (1 + w) ** (j + 0.5) for j, y in enumerate(Y))
    tv = Y[-1]["fcf"] * (1 + tg) / (w - tg)
    pvtv = tv / (1 + w) ** (len(Y) - 0.5)
    dcf = (pvf + pvtv - m["dcf"]["netDebt"]) / m["shares"]["base"]
    tot = pvf + pvtv
    return {"Y": Y, "pv": pv, "dcf": dcf, "tvShare": pvtv / tot if tot else float("nan"), "disc": disc}


def signal(m: dict, price: float) -> dict:
    R = [run(m, i) for i in range(3)]
    w = m["wt"]
    ws = sum(w)
    pvs = [r["pv"] for r in R]
    fv = sum(p * x for p, x in zip(pvs, w)) / ws
    cv = st.stdev(pvs) / st.mean(pvs) if st.mean(pvs) else float("nan")
    down = max(0.0, (pvs[1] - pvs[0]) / pvs[1]) if pvs[1] > 0 else 1.0
    mos = min(0.40, max(0.15, down * 0.5))
    buy, acc, trim = fv * (1 - mos), fv * (1 - mos / 2), fv * (1 + mos / 2)
    lab = "BUY" if price < buy else "ACCUMULATE" if price < acc else "TRIM" if price > trim else "HOLD"
    dcf = sum(r["dcf"] * x for r, x in zip(R, w)) / ws
    flags = []
    if fv > 0 and dcf > 0 and max(fv, dcf) / min(fv, dcf) > 2:
        flags.append(f"Scenario value ${fv:.0f} and DCF ${dcf:.0f} differ by more than 2x: the exit multiple carries the value.")
    elif dcf <= 0 < fv:
        flags.append("DCF is negative: free cash flow does not support the scenario value.")
    if R[1]["tvShare"] > 0.70:
        flags.append(f"Terminal value is {R[1]['tvShare']:.0%} of the DCF: treat it as a weak cross-check.")
    if fv <= 0:
        flags.append("Fair value is not positive: the model does not support a valuation (losses through the value year).")
    return dict(fv=fv, cv=cv, down=down, mos=mos, buy=buy, acc=acc, trim=trim, label=lab, dcf=dcf, pvs=pvs,
                baseEcon=R[1]["Y"][m["valueYear"]]["econ"], tvShare=R[1]["tvShare"], flags=flags,
                eps=[[round(y["econ"], 3) for y in r["Y"]] for r in R])


def validate(R: dict, mode: str = "auto", collect: dict | None = None, locked_peers: list[str] | None = None) -> list[str]:
    """Return a list of problems (empty = valid). mode 'auto' checks the model; 'full' also checks the sections a
    reviewed report must carry (business, news, street, steelman, triggers)."""
    P: list[str] = []
    need = lambda c, msg: c or P.append(msg)
    for k in ["ticker", "asOf", "price", "model"]:
        need(k in R, f"missing top-level key: {k}")
    if mode == "full":
        for k in ["headline", "thesis", "business", "news", "steelman", "triggers", "sources"]:
            need(k in R, f"full report missing: {k}")
    m = R.get("model", {})
    yrs = m.get("years", [])
    need(len(yrs) >= 3, "model.years needs at least 3 years")
    need(isinstance(m.get("valueYear"), int) and 0 < m.get("valueYear", 0) < len(yrs), "model.valueYear must index a projected year")
    need(len(m.get("drivers", [])) >= 1, "model.drivers is empty")
    for d in m.get("drivers", []):
        need(len(d.get("sc", [])) == 3, f"driver {d.get('name')}: sc needs 3 scenarios (bear, base, bull)")
        for s_ in d.get("sc", []):
            for k in ("g", "m1", "m2"):
                need(isinstance(s_.get(k), (int, float)), f"driver {d.get('name')}: scenario missing {k}")
            need(abs(s_.get("m2", 0)) < 1 and abs(s_.get("g", 0)) < 3, f"driver {d.get('name')}: margins/growth must be fractions (0.24, not 24)")
    for a, b in [("corp", "g"), ("shares", "g"), ("haircut", "perShare")]:
        need(len(m.get(a, {}).get(b, [])) == 3, f"model.{a}.{b} needs 3 values")
    for k in ["mult", "wt"]:
        need(len(m.get(k, [])) == 3, f"model.{k} needs 3 values")
    need(sum(m.get("wt", [0])) > 0, "weights sum to zero")
    dc = m.get("dcf", {})
    for k in ["da", "wc", "wacc", "tg"]:
        need(len(dc.get(k, [])) == 3, f"model.dcf.{k} needs 3 values")
    need(len(dc.get("capex", [])) == 3 and all(len(c) >= len(yrs) - 1 for c in dc.get("capex", [[]])),
         "model.dcf.capex needs 3 lists, one value per projected year")
    if P:
        return P
    for i in range(3):
        need(dc["wacc"][i] > dc["tg"][i], "wacc must exceed terminal growth")
    mu = m["mult"]
    need(mu[2] <= mu[1] * 1.3 + 0.5, f"bull exit P/E {mu[2]} exceeds base x 1.3 ({mu[1] * 1.3:.1f})")
    need(mu[0] <= mu[1], "bear exit P/E must not exceed base")
    beta = m.get("beta")
    need(isinstance(beta, (int, float)), "model.beta missing (used for the cost-of-equity cap)")
    cap = 0.11 if (beta or 0) < 2 else 0.15
    need(0.09 <= m["coe"] <= cap + 1e-9, f"cost of equity {m['coe']} outside 9%-{cap:.0%} (beta {beta})")
    for d in m["drivers"]:
        b, bl, br = d["sc"][1], d["sc"][2], d["sc"][0]
        if b.get("sales"):
            continue
        if b["g"] > 0.10:
            need(b.get("d", 0) >= 0.15 - 1e-9, f"driver {d['name']}: base growth {b['g']:.0%} needs base decay >= 0.15")
        need(bl.get("d", 0) <= b.get("d", 0) + 1e-9, f"driver {d['name']}: bull decay must not exceed base decay")
        need(br.get("d", 0) >= b.get("d", 0) - 1e-9, f"driver {d['name']}: bear decay must not be below base decay")
    v = m["valueYear"]
    if v + 1 < len(yrs):
        rb = run(m, 1)
        g_after = rb["Y"][v + 1]["eps"] / rb["Y"][v]["eps"] - 1 if rb["Y"][v]["eps"] > 0 else 0
        cap_pe = max(12.0, 100 * g_after)
        need(mu[1] <= cap_pe + 0.5, f"base exit P/E {mu[1]}x exceeds the growth cap {cap_pe:.1f}x (PEG 1.0 on {g_after:.0%} EPS growth after the value year)")
    if collect:
        o = collect.get("ownPE") or {}
        if o.get("usable"):
            need(mu[1] <= o["medianPE"] + 0.5, f"base exit P/E {mu[1]}x is above the stock's own median trailing P/E {o['medianPE']}x")
        if collect.get("peerSet"):
            need(sorted(m.get("peers") or []) == sorted(collect["peerSet"]), "model.peers differ from the peers the collector used")
    if locked_peers is not None:
        changed = sorted(locked_peers) != sorted(m.get("peers") or [])
        has_ovr = any("peer" in str(x.get("lever", "")).lower() for x in m.get("overrides", []))
        need(not changed or has_ovr, "peer set changed from the locked set without a 'Peer set' override explaining why")
    return P
