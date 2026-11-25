import re
import subprocess
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from folio_desk import db
from folio_desk.config import load_settings
from folio_desk.signals import market

ROOT = Path(__file__).resolve().parent.parent


def test_env_overrides_and_public_hides_keys(tmp_path):
    p = tmp_path / "f.toml"
    p.write_text('[data]\npolygon_api_key = "secret"\n[watchlist]\nsymbols = ["AAA"]\n')
    s = load_settings(p, env={"FOLIO_WATCHLIST_SYMBOLS": "X,Y", "FOLIO_DATA_ALLOW_UNOFFICIAL": "true"})
    assert s.watchlist.symbols == ["X", "Y"] and s.data.allow_unofficial is True
    assert s.public()["data"]["polygon_api_key"] is True
    assert "secret" not in str(s.public())


@pytest.fixture
def client(mem_db):
    from folio_desk.api.app import app
    with TestClient(app) as c:
        yield c


def test_api_signals_flow(client, market_bars):
    assert client.get("/api/signals/latest").status_code == 404
    doc = market.compute(market.closes_from_bars(market_bars), watchlist=[], theme=[])
    db.put_doc("signals", doc["asOf"], doc)
    r = client.get("/api/signals/latest").json()
    assert r["asOf"] == doc["asOf"]
    r = client.post("/api/signals/manual", json={"items": {"B6": {"status": "green", "note": "beat and rallied"}}}).json()
    assert next(c for c in r["bottom"] if c["id"] == "B6")["status"] == "green"
    assert client.post("/api/signals/manual", json={"items": {"B6": {"status": "purple"}}}).status_code == 422


def test_api_funds_presets_portfolios(client):
    funds = client.get("/api/funds").json()
    assert any(f["ticker"] == "VTI" for f in funds)
    assert "Three-fund" in client.get("/api/presets").json()
    pid = client.post("/api/portfolios", json={"name": "Test", "rows": [{"t": "VTI", "a": "T", "w": 100}]}).json()["id"]
    assert [p["name"] for p in client.get("/api/portfolios").json()] == ["Test"]
    client.delete(f"/api/portfolios/{pid}")
    assert client.get("/api/portfolios").json() == []


def test_api_analyze_uses_price_layer(client, monkeypatch):
    idx = pd.bdate_range("2010-01-01", "2024-12-31")
    t = pd.Series(range(len(idx)), index=idx) / 252

    def fake(funds, tickers):
        return pd.DataFrame({k: 100 * (1.07 ** t) for k in tickers}), []
    monkeypatch.setattr("folio_desk.api.prices.extended", fake)
    r = client.post("/api/construction/analyze", json={"rows": [{"t": "VTI", "a": "T", "w": 60}, {"t": "BND", "a": "T", "w": 40}],
                                                        "accounts": {"T": 100000, "I": 0, "R": 0}}).json()
    mine = r["runs"][0]
    assert mine["name"] == "Your portfolio"
    assert mine["stats"]["cagr"] == pytest.approx(0.07, abs=0.003)
    assert any("BND in Taxable" in c["text"] for c in r["checks"])


def test_settings_endpoint_warns_without_sec_user_agent(client):
    r = client.get("/api/settings").json()
    assert any("SEC" in w for w in r["warnings"])


# ---------------------------------------------------------------- privacy guard

BANNED = [r"@gmail\.com", r"mohan", r"goyal", r"claude\.ai/artifact", r"trig_[0-9A-Za-z]{6,}", r"/Users/[a-z]+"]


def test_no_personal_identifiers_in_repo():
    files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                           capture_output=True, text=True).stdout.split()
    hits = []
    for f in files:
        p = ROOT / f
        if not p.is_file() or p.suffix in (".png", ".ico", ".lock") or f.endswith("test_api_and_config.py"):
            continue
        txt = p.read_text(errors="ignore")
        for pat in BANNED:
            if re.search(pat, txt, re.I):
                hits.append(f"{f}: {pat}")
    assert hits == []


def test_analyze_runs_share_one_start_date(client, monkeypatch):
    idx = pd.bdate_range("2005-01-03", "2024-12-31")
    t = pd.Series(range(len(idx)), index=idx) / 252

    def fake(funds, tickers):
        df = pd.DataFrame({k: 100 * (1.07 ** t) for k in tickers})
        df.loc[df.index < "2011-01-03", "VXUS"] = float("nan")  # VXUS history starts later
        return df, []
    monkeypatch.setattr("folio_desk.api.prices.extended", fake)
    r = client.post("/api/construction/analyze", json={"rows": [{"t": "VTI", "a": "T", "w": 100}],
                                                        "benchmarks": ["Three-fund"]}).json()
    starts = {run["name"]: run["backtest"]["dates"][0] for run in r["runs"]}
    assert len(set(starts.values())) == 1 and min(starts.values()) >= "2011-01-03"
