"""FastAPI application: JSON API under /api, the built React app at /."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import __version__, db
from ..config import get_settings
from ..construction import portfolio as pf
from ..equity import engine
from . import jobs, prices
from .phase2 import router as phase2_router

def _startup():
    if db._Session is None:
        db.init_db(get_settings().db_file)
    with db.session() as s:
        if not s.scalars(select(db.Fund).limit(1)).first():
            for f in pf.default_funds():
                s.add(db.Fund(**{k: f[k] for k in ("ticker", "name", "category", "index", "fee", "type", "proxy")}))
    jobs.start_scheduler()


@asynccontextmanager
async def lifespan(_app):
    _startup()
    yield


app = FastAPI(title="folio-desk", version=__version__, lifespan=lifespan,
              description="Research and portfolio desk for individual investors. Research output, not investment advice.")


app.include_router(phase2_router)


# ---------------------------------------------------------------- meta

@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__}


@app.get("/api/settings")
def settings():
    s = get_settings()
    out = s.public()
    out["warnings"] = []
    if not s.sec.user_agent:
        out["warnings"].append("SEC user agent not set: equity runs need [sec] user_agent in folio-desk.toml.")
    return out


@app.get("/api/jobs")
def list_jobs():
    return jobs.recent()


@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "no such job")
    return {k: v for k, v in j.items() if k != "trace"}


# ---------------------------------------------------------------- market signals

class ManualItems(BaseModel):
    items: dict[str, dict] = Field(..., description='{"B6": {"status": "green", "note": "..."}}')


@app.get("/api/signals/latest")
def signals_latest():
    d = db.latest_doc("signals")
    if not d:
        raise HTTPException(404, "no signal run yet: POST /api/signals/run")
    return d


@app.get("/api/signals/history")
def signals_history(limit: int = 60):
    return [{k: d.get(k) for k in ("id", "regime", "riskScore", "leadScore", "bottomGreens", "changes")} for d in db.list_docs("signals", limit)]


@app.post("/api/signals/run")
def signals_run():
    return jobs.submit("signals", jobs.job_signals, "manual")


@app.post("/api/signals/manual")
def signals_manual(body: ManualItems):
    d = db.latest_doc("signals")
    if not d:
        raise HTTPException(404, "no signal run yet")
    for c in d["bottom"]:
        if c["id"] in body.items and c["id"] in ("B6", "B7", "B9"):
            it = body.items[c["id"]]
            if it.get("status") not in ("green", "amber", "red", "pending"):
                raise HTTPException(422, "status must be green, amber, red or pending")
            c["status"], c["now"] = it["status"], it.get("note", "")
    d["bottomGreens"] = sum(c["status"] == "green" for c in d["bottom"])
    g = d["bottomGreens"]
    d["bottomLevel"] = "Bottom signals strong" if g >= 6 else "Bottom forming" if g >= 4 else "No bottom yet"
    db.put_doc("signals", d["asOf"], d)
    return d


# ---------------------------------------------------------------- decisions

@app.get("/api/decisions/latest")
def decisions_latest():
    d = db.latest_doc("decisions")
    if not d:
        raise HTTPException(404, "no decision run yet: POST /api/decisions/run")
    return d


@app.post("/api/decisions/run")
def decisions_run():
    return jobs.submit("decisions", jobs.job_decisions, "manual")


# ---------------------------------------------------------------- sectors

@app.get("/api/sectors/rotation/latest")
def rotation_latest():
    d = db.latest_doc("rotation")
    if not d:
        raise HTTPException(404, "no rotation run yet: POST /api/sectors/rotation/run")
    return d


@app.post("/api/sectors/rotation/run")
def rotation_run():
    return jobs.submit("rotation", jobs.job_rotation, "manual")


@app.get("/api/sectors/drawdowns/latest")
def drawdowns_latest():
    d = db.latest_doc("drawdowns")
    if not d:
        raise HTTPException(404, "no drawdown run yet: POST /api/sectors/drawdowns/run")
    return d


@app.post("/api/sectors/drawdowns/run")
def drawdowns_run():
    return jobs.submit("drawdowns", jobs.job_drawdowns, "manual")


# ---------------------------------------------------------------- equity

class EquityRun(BaseModel):
    peers: list[str] | None = None


class Recompute(BaseModel):
    model: dict
    price: float


@app.get("/api/equity")
def equity_index():
    return [{"ticker": d["id"], "company": d.get("company"), "asOf": d.get("asOf"), "price": d.get("price"),
             "label": (d.get("signal") or {}).get("label"), "fv": (d.get("signal") or {}).get("fv"), "mode": d.get("mode")}
            for d in db.list_docs("equity")]


@app.get("/api/equity/{ticker}")
def equity_get(ticker: str):
    d = db.get_doc("equity", ticker.upper())
    if not d:
        raise HTTPException(404, f"no report for {ticker.upper()}: POST /api/equity/{ticker.upper()}/run")
    return d


@app.post("/api/equity/{ticker}/run")
def equity_run(ticker: str, body: EquityRun):
    t = ticker.upper()
    locked = db.get_doc("peers", t)
    peers = body.peers if body.peers is not None else (locked or {}).get("peers")
    if body.peers is not None:
        db.put_doc("peers", t, {"peers": [p.upper() for p in body.peers]})
    return jobs.submit("equity", lambda: jobs.job_equity(t, peers), t)


class Review(BaseModel):
    model: dict
    overrides: list[dict] = Field(..., description='[{"lever": "Exit P/E", "why": "..."}], one per changed lever')
    forces: dict | None = None
    triggers: dict | None = None
    thesis: list[str] | None = None


@app.post("/api/equity/{ticker}/review")
def equity_review(ticker: str, body: Review):
    """Save a reviewed model. Every override needs a reason; the same guard rails apply as in auto mode."""
    t = ticker.upper()
    rep = db.get_doc("equity", t)
    if not rep:
        raise HTTPException(404, f"run {t} first")
    if not body.overrides or any(not str(o.get("why", "")).strip() for o in body.overrides):
        raise HTTPException(422, "each override needs a lever and a reason ('why')")
    m = body.model | {"overrides": body.overrides, "rules": rep["model"].get("rules", [])}
    collect_like = {"ownPE": rep.get("ownPE"), "peerSet": rep["model"].get("peers")}
    problems = engine.validate({"ticker": t, "asOf": rep["asOf"], "price": rep["price"], "model": m}, "auto", collect=collect_like)
    if problems:
        raise HTTPException(422, {"problems": problems})
    sig = engine.signal(m, rep["price"])
    new = rep | {"mode": "reviewed", "model": m, "signal": sig, "reviewedAt": jobs._now(),
                 "headline": f"{sig['label']}: fair value ${sig['fv']:.2f} vs ${rep['price']:.2f} (reviewed: {len(body.overrides)} override(s))."}
    if body.triggers is not None:
        new["triggers"] = body.triggers
    if body.thesis is not None:
        new["thesis"] = body.thesis
    if body.forces is not None:
        from ..equity import forces as forces_mod
        new["forces"] = body.forces
        calc, fprobs = forces_mod.size(new)
        if fprobs:
            raise HTTPException(422, {"problems": fprobs})
        new["forcesCalc"] = calc
    db.put_doc("equity", t, new)
    return {"signal": sig, "mode": "reviewed"}


@app.post("/api/equity/recompute")
def equity_recompute(body: Recompute):
    """Recompute the signal for an edited model; returns validation problems alongside."""
    problems = engine.validate({"ticker": "-", "asOf": "-", "price": body.price, "model": body.model}, "auto")
    if problems and any("needs" in p or "missing" in p for p in problems):
        return {"problems": problems}
    sig = engine.signal(body.model, body.price)
    return {"problems": problems, "signal": sig}


# ---------------------------------------------------------------- construction

class FundIn(BaseModel):
    ticker: str
    name: str = ""
    category: str = "US Total Market"
    index: str = ""
    fee: float = 0.0
    type: str = "ETF"
    proxy: str = ""


class PortfolioIn(BaseModel):
    name: str
    rows: list[dict]
    accounts: dict[str, float] = {"T": 100000, "I": 0, "R": 0}
    notes: str = ""


class Analyze(BaseModel):
    rows: list[dict]
    accounts: dict[str, float] = {"T": 100000, "I": 0, "R": 0}
    rebal: str = "A"
    contrib_monthly: float = 0.0
    start: str | None = None
    benchmarks: list[str] = ["100% US total market", "Three-fund"]


def _funds() -> dict[str, dict]:
    with db.session() as s:
        return {f.ticker: {"ticker": f.ticker, "name": f.name, "category": f.category, "index": f.index, "fee": f.fee,
                           "type": f.type, "proxy": f.proxy} for f in s.scalars(select(db.Fund)).all()}


@app.get("/api/funds")
def funds():
    return sorted(_funds().values(), key=lambda f: (f["category"], f["ticker"]))


@app.put("/api/funds/{ticker}")
def fund_put(ticker: str, f: FundIn):
    with db.session() as s:
        s.merge(db.Fund(**{**f.model_dump(), "ticker": ticker.upper()}))
    return {"ok": True}


@app.get("/api/presets")
def preset_list():
    return pf.presets()


@app.get("/api/portfolios")
def portfolios():
    with db.session() as s:
        return [{"id": p.id, "name": p.name, "rows": p.rows, "accounts": p.accounts, "notes": p.notes,
                 "updatedAt": p.updated_at.isoformat() if p.updated_at else None} for p in s.scalars(select(db.Portfolio)).all()]


@app.post("/api/portfolios")
def portfolio_save(p: PortfolioIn):
    with db.session() as s:
        ex = s.scalars(select(db.Portfolio).where(db.Portfolio.name == p.name)).first()
        if ex:
            ex.rows, ex.accounts, ex.notes = p.rows, p.accounts, p.notes
            return {"id": ex.id}
        pid = "p" + uuid.uuid4().hex[:10]
        s.add(db.Portfolio(id=pid, name=p.name, rows=p.rows, accounts=p.accounts, notes=p.notes))
        return {"id": pid}


@app.delete("/api/portfolios/{pid}")
def portfolio_delete(pid: str):
    with db.session() as s:
        p = s.get(db.Portfolio, pid)
        if p:
            s.delete(p)
    return {"ok": True}


@app.post("/api/construction/analyze")
def analyze(a: Analyze):
    F = _funds()
    w = pf.weights_by_ticker(a.rows)
    ps = pf.presets()
    bench = {b: pf.weights_by_ticker([{"t": t, "a": ac, "w": x} for t, ac, x in ps[b]]) for b in a.benchmarks if b in ps}
    tickers = sorted(set(w) | {t for b in bench.values() for t in b} | {"SPY"})
    px, notes = prices.extended(F, tickers)
    init = sum(a.accounts.values()) or 1.0
    used = [t for ww in [w, *bench.values()] for t in ww if t in px]
    firsts = [px[t].first_valid_index() for t in used if px[t].first_valid_index() is not None]
    start = max(firsts) if firsts else None  # every run starts on the same date so the lines are comparable
    if a.start and (start is None or pd.Timestamp(a.start) > start):
        start = pd.Timestamp(a.start)
    runs = []
    for name, ww in [("Your portfolio", w)] + list(bench.items()):
        bt = pf.backtest(ww, px, a.rebal, init, a.contrib_monthly, start.date().isoformat() if start is not None else None)
        if bt and "missing" not in bt:
            runs.append({"name": name, "backtest": {k: bt[k] for k in ("dates", "nav", "val")}, "stats": pf.stats(bt)})
        elif bt:
            runs.append({"name": name, "missing": bt["missing"]})
    mix: dict[str, float] = {}
    fee = 0.0
    tw = sum(w.values()) or 1
    for t, x in w.items():
        f = F.get(t, {})
        k = pf.CATEGORY_CLASS.get(f.get("category", ""), "us")
        mix[k] = mix.get(k, 0) + x / tw
        fee += x / tw * f.get("fee", 0)
    return {"runs": runs, "mix": mix, "blendedFee": fee, "stress": pf.stress(w, px),
            "checks": pf.placement_checks(a.rows, F, a.accounts), "notes": notes}


# ---------------------------------------------------------------- static React app

STATIC = Path(__file__).resolve().parent.parent / "static"
if STATIC.is_dir() and (STATIC / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = STATIC / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(STATIC / "index.html")
