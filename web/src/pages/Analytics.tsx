import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, post } from "../lib/api";
import { pct, pctSigned, usd, usdK } from "../lib/format";
import { Button, Card, Chip, Empty, Kpi, KpiGrid, Note, Table } from "../components/ui";
import { VERDICT_TONE } from "./Register";

// ---------------------------------------------------------------- performance

interface Group { pnl: number; n: number; wins: number }
interface Perf { mode: string; from: string; to: string; value: number; twrTotal: number; twrAnnual: number | null; mwrAnnual: number | null; vol: number | null; maxDrawdown: number; dates: string[]; nav: number[]; benchmarks: Record<string, { total: number; series: number[] }>; attribution: { byIdeaSource: Record<string, Group>; byStrategy: Record<string, Group> }; notes: string[]; error?: string }

export function Performance() {
  const [bench, setBench] = useState("SPY,QQQ");
  const run = useMutation({ mutationFn: () => post<Perf>("/api/performance", { benchmarks: bench.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean) }) });
  const d = run.data;
  const chart = useMemo(() => !d || d.error ? [] : d.dates.map((x, i) => Object.fromEntries([["d", x], ["Portfolio", d.nav[i] * 100], ...Object.entries(d.benchmarks).map(([k, v]) => [k, v.series[i] * 100])])), [d]);
  const colors = ["var(--color-info)", "var(--color-warn)", "var(--color-good)", "var(--color-bad)"];
  const names = ["blue", "amber", "green", "red"];
  return (
    <div className="grid gap-5">
      <Card title="Portfolio performance" sub="from the trading register" actions={<>
        <input value={bench} onChange={(e) => setBench(e.target.value)} aria-label="Benchmarks" className="rounded border border-line bg-panel px-2 py-1 text-sm" />
        <Button primary onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? "Computing…" : "Compute"}</Button></>}>
        {run.error ? <p className="text-sm text-bad">{(run.error as Error).message}</p> : !d ? <Empty>Log trades (and deposits) in the register, then compute.</Empty> : d.error ? <Empty>{d.error}</Empty> : (
          <>
            <KpiGrid>
              <Kpi label="Value" value={usdK(d.value)} sub={`${d.from} to ${d.to}`} />
              <Kpi label="Time-weighted, total" value={pctSigned(d.twrTotal)} sub={d.twrAnnual != null ? `${pctSigned(d.twrAnnual)} a year` : "under a year"} />
              <Kpi label="Money-weighted (XIRR)" value={d.mwrAnnual != null ? pctSigned(d.mwrAnnual) : "—"} sub="a year, your timing included" />
              <Kpi label="Volatility" value={pct(d.vol)} />
              <Kpi label="Worst fall" value={pct(d.maxDrawdown)} />
              {Object.entries(d.benchmarks).map(([k, v]) => <Kpi key={k} label={`${k}, same period`} value={pctSigned(v.total)} />)}
            </KpiGrid>
            <div className="mt-3 h-72">
              <ResponsiveContainer>
                <LineChart data={chart}>
                  <CartesianGrid stroke="var(--color-line)" vertical={false} />
                  <XAxis dataKey="d" tick={{ fontSize: 11 }} minTickGap={40} /><YAxis tick={{ fontSize: 11 }} domain={["auto", "auto"]} /><Tooltip /><Legend />
                  {["Portfolio", ...Object.keys(d.benchmarks)].map((k, i) => <Line key={k} dataKey={k} name={`${k} (${names[i % 4]})`} stroke={colors[i % 4]} dot={false} isAnimationActive={false} strokeWidth={i ? 1.5 : 2.5} />)}
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-2 grid gap-1">{d.notes.map((n) => <Note key={n}>{n}</Note>)}</div>
          </>
        )}
      </Card>
      {d && !d.error && (
        <Card title="Attribution: realized P&L by idea source and strategy" sub="which desks' ideas made or lost money">
          {!Object.keys(d.attribution.byIdeaSource).length ? <Empty>No closed trades yet: attribution counts realized P&L once positions close.</Empty> : <Table head={["Group", "Closed", "Win rate", "P&L"]}>
            {[...Object.entries(d.attribution.byIdeaSource).map(([k, v]) => ["Source: " + k, v] as const), ...Object.entries(d.attribution.byStrategy).map(([k, v]) => ["Strategy: " + k, v] as const)].map(([k, v]) => (
              <tr key={k}><td>{k}</td><td className="num">{v.n}</td><td className="num">{v.n ? `${Math.round((100 * v.wins) / v.n)}%` : "—"}</td><td className="num">{usd(v.pnl, 0)}</td></tr>
            ))}
          </Table>}
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- optimization

interface OptRes { method: string; weights: Record<string, number>; riskShare: Record<string, number>; assetVol: Record<string, number>; vol: number; histReturn: number; window: { from: string; to: string }; converged: boolean; caveat: string; rebalance?: { rows: { ticker: string; current: number; target: number; drift: number; band: number; outside: boolean }[]; trades: { ticker: string; side: string; amount: number }[]; rule: string } }

export function Optimization() {
  const [tickers, setTickers] = useState("VTI, VXUS, BND, GLDM");
  const [method, setMethod] = useState("risk_parity");
  const [maxW, setMaxW] = useState(60);
  const [minW, setMinW] = useState(0);
  const [years, setYears] = useState(5);
  const [current, setCurrent] = useState("");
  const [total, setTotal] = useState(100000);
  const run = useMutation({
    mutationFn: () => post<OptRes>("/api/optimize", {
      tickers: tickers.split(/[,\s]+/).filter(Boolean), method, min_weight: minW / 100, max_weight: maxW / 100, lookback_years: years, total_value: total,
      current: current.trim() ? Object.fromEntries(current.split(",").map((x) => x.split(":").map((s) => s.trim())).filter((p) => p.length === 2).map(([k, v]) => [k.toUpperCase(), +v])) : null,
    }),
  });
  const r = run.data;
  const input = "w-full min-w-0 rounded border border-line bg-panel px-2 py-1";
  return (
    <div className="grid gap-5">
      <Card title="Portfolio optimization" sub="weights from past prices; risk parity and minimum variance need no return forecast">
        <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-3 lg:grid-cols-6">
          <label className="col-span-2 grid gap-1">Tickers<input value={tickers} onChange={(e) => setTickers(e.target.value)} className={input} /></label>
          <label className="grid gap-1">Method<select value={method} onChange={(e) => setMethod(e.target.value)} className={input}>
            <option value="risk_parity">Risk parity</option><option value="min_variance">Minimum variance</option><option value="max_sharpe">Max Sharpe (shrunk; what-if)</option></select></label>
          <label className="grid gap-1">Min weight %<input type="number" value={minW} onChange={(e) => setMinW(+e.target.value)} className={input} /></label>
          <label className="grid gap-1">Max weight %<input type="number" value={maxW} onChange={(e) => setMaxW(+e.target.value)} className={input} /></label>
          <label className="grid gap-1">Lookback, years<input type="number" value={years} onChange={(e) => setYears(+e.target.value)} className={input} /></label>
          <label className="col-span-2 grid gap-1">Current weights (optional, e.g. VTI:55, BND:45)<input value={current} onChange={(e) => setCurrent(e.target.value)} className={input} /></label>
          <label className="grid gap-1">Portfolio $<input type="number" value={total} onChange={(e) => setTotal(+e.target.value)} className={input} /></label>
        </div>
        <div className="mt-3"><Button primary onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? "Optimizing…" : "Optimize"}</Button></div>
        {run.error && <p className="mt-2 text-sm text-bad">{(run.error as Error).message}</p>}
      </Card>
      {r && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card title="Target weights" sub={`${r.window.from} to ${r.window.to}`}>
            <Table head={["Ticker", "Weight", "Share of risk", "Asset volatility"]}>
              {Object.entries(r.weights).map(([k, w]) => <tr key={k}><td className="font-semibold">{k}</td><td className="num">{pct(w)}</td><td className="num">{pct(r.riskShare[k])}</td><td className="num">{pct(r.assetVol[k])}</td></tr>)}
            </Table>
            <div className="mt-3"><KpiGrid><Kpi label="Expected volatility" value={pct(r.vol)} /><Kpi label="Past return of this mix" value={pct(r.histReturn)} sub="not a forecast" /></KpiGrid></div>
            {!r.converged && <p className="mt-2 text-sm"><Chip tone="warn" meaning="solver did not fully converge">check</Chip> The solver stopped early; treat the weights as approximate.</p>}
            <div className="mt-2"><Note>{r.caveat}</Note></div>
          </Card>
          {r.rebalance && (
            <Card title="Rebalancing" sub={r.rebalance.rule}>
              <Table head={["Ticker", "Current", "Target", "Drift", "Band", ""]}>
                {r.rebalance.rows.map((x) => <tr key={x.ticker}><td>{x.ticker}</td><td className="num">{pct(x.current)}</td><td className="num">{pct(x.target)}</td><td className="num">{pctSigned(x.drift)}</td><td className="num">±{pct(x.band)}</td>
                  <td>{x.outside ? <Chip tone="warn" meaning="outside its band: rebalance">rebalance</Chip> : <Chip tone="good" meaning="inside its band">ok</Chip>}</td></tr>)}
              </Table>
              {r.rebalance.trades.length > 0 && <ul className="mt-2 text-sm">{r.rebalance.trades.map((t) => <li key={t.ticker}>{t.side === "buy" ? "Buy" : "Sell"} {usdK(t.amount)} of {t.ticker}</li>)}</ul>}
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- risk

type Limits = Record<string, unknown> & { clusters: Record<string, string[]>; regimeMultiplier: Record<string, number>; putDeltaMax: Record<string, number> };
const NUMERIC: [string, string][] = [["maxPositionPct", "Max single name, % of portfolio"], ["maxClusterPct", "Max cluster, % of portfolio"], ["maxShortPutNotionalPct", "Max short-put assignment exposure, %"], ["minCashPct", "Cash floor, % of portfolio"]];
const BOOLS: [string, string][] = [["requireStrikeAtOrBelowAccumulate", "Short-put strike must be at or below the equity desk's ACCUMULATE level"], ["blockPutsSpanningEarningsAboveAccumulate", "Block puts across earnings unless the strike is at or below ACCUMULATE"], ["noAveragingDownInRiskOff", "No averaging down into names below their 200-day in Risk-off"], ["cashSecuredPuts", "Short puts must be fully cash-secured"]];
const REGIMES = ["Risk-on", "Caution", "Risk-off", "Washout"];

export function Risk() {
  const qc = useQueryClient();
  const lim = useQuery({ queryKey: ["limits"], queryFn: () => api<Limits>("/api/risk/limits") });
  const log = useQuery({ queryKey: ["checks"], queryFn: () => api<{ id: string; createdAt: string; verdict: string; fingerprint: string; proposal: Record<string, unknown> }[]>("/api/risk/checks") });
  const [draft, setDraft] = useState<Limits | null>(null);
  const [clusters, setClusters] = useState<string | null>(null);
  const L = draft ?? lim.data;
  const save = useMutation({
    mutationFn: () => api("/api/risk/limits", { method: "PUT", body: JSON.stringify({ ...L, clusters: parseClusters(clusters ?? fmtClusters(L!.clusters)) }) }),
    onSuccess: () => { setDraft(null); setClusters(null); qc.invalidateQueries({ queryKey: ["limits"] }); },
  });
  if (!L) return null;
  const set = (k: string, v: unknown) => setDraft({ ...L, [k]: v } as Limits);
  const input = "w-full min-w-0 rounded border border-line bg-panel px-2 py-1";
  return (
    <div className="grid gap-5">
      <Card title="Risk limits" sub="every trade is checked against these; the market regime scales them" actions={<Button primary onClick={() => save.mutate()} disabled={!draft && clusters === null}>Save limits</Button>}>
        <div className="grid gap-3 text-sm md:grid-cols-2">
          {NUMERIC.map(([k, label]) => <label key={k} className="grid gap-1">{label}<input type="number" value={L[k] as number} onChange={(e) => set(k, +e.target.value)} className={input} /></label>)}
        </div>
        <div className="mt-4 overflow-x-auto"><Table head={["Regime", "Size multiplier", "Max put delta"]}>
          {REGIMES.map((g) => <tr key={g}><td>{g}</td>
            <td><input type="number" step={0.05} value={L.regimeMultiplier[g]} onChange={(e) => set("regimeMultiplier", { ...L.regimeMultiplier, [g]: +e.target.value })} className={`${input} w-24`} /></td>
            <td><input type="number" step={0.05} value={L.putDeltaMax[g]} onChange={(e) => set("putDeltaMax", { ...L.putDeltaMax, [g]: +e.target.value })} className={`${input} w-24`} /></td></tr>)}
        </Table></div>
        <div className="mt-4 grid gap-2 text-sm">{BOOLS.map(([k, label]) => <label key={k} className="flex gap-2"><input type="checkbox" checked={!!L[k]} onChange={(e) => set(k, e.target.checked)} />{label}</label>)}</div>
        <label className="mt-4 grid gap-1 text-sm">Clusters of names that move together (one per line: Name: TICK, TICK)
          <textarea rows={4} value={clusters ?? fmtClusters(L.clusters)} onChange={(e) => setClusters(e.target.value)} className={`${input} num`} /></label>
        <div className="mt-2"><Note>The defaults are starting points, not advice. Set them to what you can live with in a bad month.</Note></div>
      </Card>
      <Card title="Check log" sub="every pre-trade check, with a fingerprint of exactly what was checked">
        {!log.data?.length ? <Empty>No checks yet. Run one from the trade form in the register.</Empty> : (
          <Table head={["When", "Verdict", "Proposal", "Fingerprint"]}>
            {log.data.map((c) => <tr key={c.id}><td className="text-xs">{c.createdAt.slice(0, 16).replace("T", " ")}</td><td><Chip tone={VERDICT_TONE[c.verdict]} meaning="risk verdict">{c.verdict}</Chip></td>
              <td className="text-xs">{String(c.proposal.side)} {String(c.proposal.qty)} {String(c.proposal.ticker)} {c.proposal.asset === "option" ? `${c.proposal.expiry} ${c.proposal.opt_kind} ${c.proposal.strike}` : `@ ${c.proposal.price}`}</td>
              <td className="num text-xs">{c.fingerprint}</td></tr>)}
          </Table>
        )}
      </Card>
    </div>
  );
}

const fmtClusters = (c: Record<string, string[]>) => Object.entries(c).map(([k, v]) => `${k}: ${v.join(", ")}`).join("\n");
const parseClusters = (s: string) => Object.fromEntries(s.split("\n").map((l) => l.split(":")).filter((p) => p.length === 2 && p[0].trim())
  .map(([k, v]) => [k.trim(), v.split(",").map((x) => x.trim().toUpperCase()).filter(Boolean)]));
