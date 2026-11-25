import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Bar, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, post, useDoc, useJob } from "../lib/api";
import { num, pct, usd } from "../lib/format";
import { Button, Card, Chip, Empty, Kpi, KpiGrid, Note, RunButton, Table, type Tone } from "../components/ui";

interface Scenario { g: number; d: number; m1: number; m2: number }
interface Model { years: string[]; valueYear: number; drivers: { name: string; base: number; m0: number; sc: Scenario[] }[]; mult: number[]; coe: number; beta: number; rules: { lever: string; rule: string; value: string }[]; calibration: { label: string; model: number; ref: string }[]; overrides: { lever: string; why: string }[]; [k: string]: unknown }
interface Sig { fv: number; buy: number; acc: number; trim: number; label: string; dcf: number; mos: number; tvShare: number; pvs: number[]; flags: string[] }
interface Report {
  ticker: string; company: string; asOf: string; price: number; priceDate: string; mode: string; headline: string; model: Model; signal: Sig;
  options: { candidates: { expiry: string; dte: number; strike: number; bid: number; annYield: number; belowBuy: boolean; otmPct: number }[]; verdict: string };
  history: { quarters: string[]; revenue: (number | null)[]; netMargin: (number | null)[] };
  warnings: string[]; problems: string[]; insiders?: { openMarketBuys: number; openMarketSells: number; buyValue: number; sellValue: number };
}
interface IndexRow { ticker: string; company: string; asOf: string; price: number; label: string; fv: number }

export const LABEL_TONE: Record<string, Tone> = { BUY: "good", ACCUMULATE: "info", HOLD: "muted", TRIM: "warn" };

export function EquityIndex() {
  const idx = useQuery({ queryKey: ["equity-index"], queryFn: () => api<IndexRow[]>("/api/equity") });
  const [t, setT] = useState("");
  const nav = useNavigate();
  return (
    <div className="grid gap-5">
      <Card title="Equity research" sub="primary-source fair value, priced levels and a put overlay">
        <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (t.trim()) nav(`/equity/${t.trim().toUpperCase()}`); }}>
          <input value={t} onChange={(e) => setT(e.target.value)} placeholder="Ticker, e.g. MSFT" aria-label="Ticker" className="rounded-md border border-line bg-panel px-2 py-1.5" />
          <Button primary>Open</Button>
        </form>
      </Card>
      <Card title="Reports on file">
        {!idx.data?.length ? <Empty>No reports yet. Open a ticker and run it.</Empty> : (
          <Table head={["Ticker", "Company", "Signal", "Fair value", "Price", "As of"]}>
            {idx.data.map((r) => (
              <tr key={r.ticker}>
                <td><Link className="font-semibold text-info" to={`/equity/${r.ticker}`}>{r.ticker}</Link></td>
                <td>{r.company}</td>
                <td><Chip tone={LABEL_TONE[r.label] ?? "muted"} meaning="model signal">{r.label}</Chip></td>
                <td className="num">{usd(r.fv)}</td><td className="num">{usd(r.price)}</td><td className="text-xs">{r.asOf?.slice(0, 10)}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}

export function EquityReport() {
  const { ticker = "" } = useParams();
  const q = useDoc<Report>(["equity", ticker], `/api/equity/${ticker}`);
  const [peers, setPeers] = useState("");
  const job = useJob(`/api/equity/${ticker}/run`, [["equity", ticker], ["equity-index"]],
    () => ({ peers: peers.trim() ? peers.split(",").map((p) => p.trim().toUpperCase()).filter(Boolean) : null }));
  const r = q.data;
  const runCard = (
    <Card title={`${ticker}: run`} sub="EDGAR filings, prices, consensus and option chain; 1-3 minutes">
      <div className="flex flex-wrap items-center gap-2">
        <input value={peers} onChange={(e) => setPeers(e.target.value)} placeholder="Peers, comma-separated (locked once set)" aria-label="Peers"
          className="min-w-72 flex-1 rounded-md border border-line bg-panel px-2 py-1.5" />
        <RunButton label={r ? "Re-run" : "Run"} busy={job.busy} onClick={job.run} status={job.job?.status} />
      </div>
      {job.job?.status === "error" && <p className="mt-2 text-sm text-bad">{job.job.message}</p>}
      <div className="mt-2"><Note>Peers set the exit multiple. Pick 8-12 from the 10-K's competition section; the same set is reused on every run unless you change it here.</Note></div>
    </Card>
  );
  if (q.isLoading) return <p className="text-muted">Loading…</p>;
  if (!r) return <div className="grid gap-5">{runCard}</div>;
  return (
    <div className="grid gap-5">
      <ReportView r={r} />
      {runCard}
    </div>
  );
}

function ReportView({ r }: { r: Report }) {
  const [model, setModel] = useState<Model>(r.model);
  useEffect(() => setModel(r.model), [r]);
  const recompute = useMutation({ mutationFn: (m: Model) => post<{ signal?: Sig; problems: string[] }>("/api/equity/recompute", { model: m, price: r.price }) });
  const sig = recompute.data?.signal ?? r.signal;
  const edited = model !== r.model;
  const base = model.drivers[0].sc[1];
  const setBase = (k: keyof Scenario, v: number) => {
    const m = structuredClone(model);
    m.drivers[0].sc[1][k] = v;
    setModel(m);
    recompute.mutate(m);
  };
  const setMult = (v: number) => {
    const m = structuredClone(model);
    m.mult[1] = v;
    setModel(m);
    recompute.mutate(m);
  };
  const hist = useMemo(() => r.history.quarters.map((qq, i) => ({ q: qq.slice(0, 7), rev: (r.history.revenue[i] ?? 0) / 1e6, margin: (r.history.netMargin[i] ?? 0) * 100 })), [r]);
  return (
    <>
      <Card title={`${r.ticker} · ${r.company}`} sub={`price ${usd(r.price)} on ${r.priceDate} · ${r.mode === "auto" ? "automatic levers" : "reviewed"}`}>
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <Chip tone={LABEL_TONE[sig.label] ?? "muted"} meaning="model signal">{sig.label}</Chip>
          <span className="text-sm">{r.headline}</span>
          {edited && <Chip tone="info" meaning="levers edited on this page, not saved">edited</Chip>}
        </div>
        <KpiGrid>
          <Kpi label="Fair value (weighted)" value={usd(sig.fv)} sub={`bear ${usd(sig.pvs[0], 0)} · base ${usd(sig.pvs[1], 0)} · bull ${usd(sig.pvs[2], 0)}`} />
          <Kpi label="BUY below" value={usd(sig.buy)} />
          <Kpi label="ACCUMULATE below" value={usd(sig.acc)} />
          <Kpi label="TRIM above" value={usd(sig.trim)} />
          <Kpi label="Margin of safety" value={pct(sig.mos, 0)} />
          <Kpi label="DCF cross-check" value={usd(sig.dcf)} sub={`terminal value ${pct(sig.tvShare, 0)}`} />
        </KpiGrid>
        {sig.flags.length > 0 && <ul className="mt-3 grid gap-1">{sig.flags.map((f) => <li key={f}><Chip tone="warn" meaning="model reliability">check</Chip> <span className="text-sm">{f}</span></li>)}</ul>}
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Base-case levers" sub="edit to see the signal move; changes are not saved">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <Lever label="Revenue growth, first year" value={base.g} onChange={(v) => setBase("g", v)} />
            <Lever label="Growth decay per year" value={base.d} onChange={(v) => setBase("d", v)} />
            <Lever label="Net margin, year 1" value={base.m1} onChange={(v) => setBase("m1", v)} />
            <Lever label="Net margin, year 2+" value={base.m2} onChange={(v) => setBase("m2", v)} />
            <label className="grid gap-1">Exit P/E (base)
              <input type="number" step={0.5} value={model.mult[1]} onChange={(e) => setMult(+e.target.value)} className="num rounded border border-line bg-panel px-2 py-1" />
            </label>
            <div className="text-xs text-muted">Cost of equity {pct(model.coe, 1)} (beta {num(model.beta)})</div>
          </div>
          {recompute.data?.problems?.length ? <ul className="mt-2 text-xs text-bad">{recompute.data.problems.map((p) => <li key={p}>{p}</li>)}</ul> : null}
          {edited && <div className="mt-2"><Button onClick={() => { setModel(r.model); recompute.reset(); }}>Reset levers</Button></div>}
        </Card>
        <Card title="Revenue and net margin" sub="last 12 quarters, from XBRL">
          <div className="h-56">
            <ResponsiveContainer>
              <ComposedChart data={hist}>
                <XAxis dataKey="q" tick={{ fontSize: 11 }} />
                <YAxis yAxisId="l" tick={{ fontSize: 11 }} />
                <YAxis yAxisId="r" orientation="right" tick={{ fontSize: 11 }} unit="%" />
                <Tooltip />
                <Bar yAxisId="l" dataKey="rev" name="Revenue $mm (blue)" fill="var(--color-info)" />
                <Line yAxisId="r" dataKey="margin" name="Net margin % (amber)" stroke="var(--color-warn)" dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <Card title="How each lever was set">
        <Table head={["Lever", "Rule", "Value"]}>
          {r.model.rules.map((x) => <tr key={x.lever}><td className="font-semibold">{x.lever}</td><td className="text-xs">{x.rule}</td><td className="num text-xs">{x.value}</td></tr>)}
        </Table>
        {r.model.calibration.length > 0 && (
          <div className="mt-3"><Table head={["Calibration", "Model", "Reference"]}>
            {r.model.calibration.map((c) => <tr key={c.label}><td>{c.label}</td><td className="num">{num(c.model)}</td><td className="text-xs">{c.ref}</td></tr>)}
          </Table></div>
        )}
      </Card>

      <Card title="Options overlay: cash-secured puts" sub="strikes at or below ACCUMULATE, 30-130 days">
        <p className="mb-2 text-sm">{r.options.verdict}</p>
        {r.options.candidates.length > 0 && (
          <Table head={["Expiry", "Days", "Strike", "Bid", "Annualised", "Below spot", "Below BUY?"]}>
            {r.options.candidates.map((o) => (
              <tr key={o.expiry + o.strike}>
                <td>{o.expiry}</td><td className="num">{o.dte}</td><td className="num">{usd(o.strike)}</td><td className="num">{usd(o.bid)}</td>
                <td className="num">{pct(o.annYield)}</td><td className="num">{pct(o.otmPct)}</td>
                <td>{o.belowBuy ? <Chip tone="good" meaning="assignment would be at or below the BUY level">yes</Chip> : "no"}</td>
              </tr>
            ))}
          </Table>
        )}
        <div className="mt-2"><Note>Selling a put obliges you to buy 100 shares per contract at the strike. Size it against your cash and the risk limits.</Note></div>
      </Card>

      {(r.warnings.length > 0 || r.problems.length > 0) && (
        <Card title="Data notes">
          <ul className="grid gap-1 text-sm">
            {r.problems.map((p) => <li key={p}><Chip tone="bad" meaning="validation problem">problem</Chip> {p}</li>)}
            {r.warnings.map((w) => <li key={w}><Chip tone="warn" meaning="data warning">note</Chip> {w}</li>)}
          </ul>
        </Card>
      )}
      <Note>Research output from automatic rules, not investment advice. Read the filings before acting.</Note>
    </>
  );
}

function Lever({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <label className="grid gap-1">{label}
      <span className="flex items-center gap-1">
        <input type="number" step={0.5} value={+(value * 100).toFixed(2)} onChange={(e) => onChange(+e.target.value / 100)} className="num w-24 rounded border border-line bg-panel px-2 py-1" />%
      </span>
    </label>
  );
}
