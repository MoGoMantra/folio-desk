import { useState } from "react";
import { useDoc, useJob } from "../lib/api";
import { num, pp } from "../lib/format";
import { Card, Chip, Empty, Note, RunButton, Spark, Table, type Tone } from "../components/ui";

interface Sector {
  key: string; label: string; etf: string; members: number; rank: number; rankChg: number; stage: string;
  rsEW: { w1: number; w4: number; w12: number }; rsCW: { w4: number }; vs50: number; breadth: number; breadthChg: number;
  lead: Record<string, boolean>; notes: string[]; hist: { rank: number[]; breadth: number[] };
}
interface ListRow { sym: string; name: string; industry: string; rsSector: number; ret20: number; rsSPY: number; from52: number; ext50: number; dvolM: number }
interface RotationDoc {
  asOf: string; status: string; universe: { members: number; source?: string }; sectors: Sector[]; lists: Record<string, ListRow[]>;
  backtest: { from: string; baseUpPct: number; baseDownPct: number; flags: Record<string, { n: number; hitPct: number | null; edgePts: number | null; dir: string }>; lists: { n: number; beatSectorPct: number | null; meanVsSector: number | null }; caveat: string };
}
interface DDRow { sym: string; name: string; sector: string; price: number; dd: number; peakDate: string; d1: number; r5: number; w1: number; w1Date: string; closes: number[]; flag: string }
interface DDDoc { asOf: string; stats: Record<string, number>; rows: DDRow[]; research: string[]; universeSource?: string }

const STAGE_TONE: Record<string, Tone> = { Confirmed: "good", Losing: "bad", Early: "info", Watch: "info", "Stale watch": "muted", Neutral: "muted" };

export function Rotation() {
  const q = useDoc<RotationDoc>(["rotation"], "/api/sectors/rotation/latest");
  const job = useJob("/api/sectors/rotation/run", [["rotation"]]);
  const d = q.data;
  const run = <RunButton label="Run rotation" busy={job.busy} onClick={job.run} status={job.job?.status} />;
  if (q.isLoading) return <p className="text-muted">Loading…</p>;
  if (!d) return <Card title="Sector rotation" actions={run}><Empty>No rotation run yet. A run downloads two years of prices for the universe and takes a few minutes.</Empty></Card>;
  const sectors = [...d.sectors].sort((a, b) => a.rank - b.rank);
  return (
    <div className="grid gap-5">
      <Card title="Sector rotation" sub={`as of ${d.asOf} · ${d.universe.members} stocks · ${d.universe.source ?? ""}`} actions={run}>
        <div className="mb-3"><Chip tone="warn" meaning="the flags have not shown a forecasting edge yet">UNVALIDATED</Chip></div>
        <Table head={["Rank", "Sector", "Stage", "4-wk RS (equal wt)", "12-wk RS", "ETF 4-wk vs SPY", "vs 50-day", "Breadth", "20-day breadth chg", "Leading flags", "Rank, 60 sessions"]}>
          {sectors.map((s) => (
            <tr key={s.key}>
              <td className="num">{s.rank} <span className="text-xs text-muted">({s.rankChg > 0 ? "+" : ""}{s.rankChg})</span></td>
              <td><b>{s.label}</b> <span className="text-xs text-muted">{s.etf}</span>{s.notes.map((n) => <div key={n} className="text-xs text-muted">{n}</div>)}</td>
              <td><Chip tone={STAGE_TONE[s.stage] ?? "muted"} meaning="rotation stage">{s.stage}</Chip></td>
              <td className="num">{pp(s.rsEW.w4)}</td>
              <td className="num">{pp(s.rsEW.w12)}</td>
              <td className="num">{pp(s.rsCW.w4)}</td>
              <td className="num">{pp(s.vs50)}</td>
              <td className="num">{num(s.breadth, 0)}%</td>
              <td className="num">{pp(s.breadthChg, 0)}</td>
              <td className="text-xs">{Object.entries(s.lead).filter(([, v]) => v).map(([k]) => k).join(" ") || "—"}</td>
              <td><Spark data={s.hist.rank.map((r) => -r)} /></td>
            </tr>
          ))}
        </Table>
      </Card>
      {Object.entries(d.lists).map(([key, rows]) => (
        <Card key={key} title={`Candidates in ${d.sectors.find((s) => s.key === key)?.label}`} sub="top 10 by 20-session return vs the sector; candidates only">
          <Table head={["Ticker", "Name", "Industry", "vs sector 20d", "20d return", "vs SPY", "From 52-wk high", "Above 50-day", "$M/day"]}>
            {rows.map((r) => (
              <tr key={r.sym}>
                <td className="font-semibold">{r.sym}</td><td>{r.name}</td><td className="text-xs text-muted">{r.industry}</td>
                <td className="num">{pp(r.rsSector)}</td><td className="num">{pp(r.ret20)}</td><td className="num">{pp(r.rsSPY)}</td>
                <td className="num">{pp(r.from52)}</td><td className="num">{pp(r.ext50)}</td><td className="num">{num(r.dvolM, 0)}</td>
              </tr>
            ))}
          </Table>
        </Card>
      ))}
      <Card title="Evidence so far" sub={`re-scored every run over history from ${d.backtest.from}; forward 20 sessions`}>
        <Table head={["Flag", "Episodes", "Hit rate", "Edge vs base rate"]}>
          {Object.entries(d.backtest.flags).map(([k, v]) => (
            <tr key={k}>
              <td>{k}</td><td className="num">{v.n}</td><td className="num">{v.hitPct == null ? "—" : `${v.hitPct}%`}</td>
              <td className="num">{v.edgePts == null ? "—" : `${v.edgePts > 0 ? "+" : ""}${v.edgePts} pts`}</td>
            </tr>
          ))}
        </Table>
        <div className="mt-2 grid gap-1">
          <Note>Base rates: sector beat the universe {d.backtest.baseUpPct}% / lagged {d.backtest.baseDownPct}% of the time. Candidate lists beat their sector {d.backtest.lists.beatSectorPct ?? "—"}% of the time ({d.backtest.lists.n} picks).</Note>
          <Note>{d.backtest.caveat}</Note>
        </div>
      </Card>
    </div>
  );
}

export function Drawdowns() {
  const q = useDoc<DDDoc>(["drawdowns"], "/api/sectors/drawdowns/latest");
  const job = useJob("/api/sectors/drawdowns/run", [["drawdowns"]]);
  const [min, setMin] = useState(15);
  const [hideCA, setHideCA] = useState(true);
  const d = q.data;
  const run = <RunButton label="Run drawdown screen" busy={job.busy} onClick={job.run} status={job.job?.status} />;
  if (q.isLoading) return <p className="text-muted">Loading…</p>;
  if (!d) return <Card title="Multi-week drawdowns" actions={run}><Empty>No drawdown run yet.</Empty></Card>;
  const rows = d.rows.filter((r) => r.dd <= -min && (!hideCA || !r.flag.includes("ca?")));
  return (
    <Card title="Multi-week drawdowns" sub={`as of ${d.asOf} · close vs highest close of the last 16 sessions`} actions={run}>
      <div className="mb-3 flex flex-wrap items-center gap-4 text-sm">
        <label>At least <input type="number" min={10} step={1} value={min} onChange={(e) => setMin(Math.max(10, +e.target.value))} className="w-16 rounded border border-line bg-panel px-1" />% down</label>
        <label><input type="checkbox" checked={hideCA} onChange={(e) => setHideCA(e.target.checked)} /> Hide likely splits / spin-offs</label>
        <span className="text-muted">{rows.length} names · ≤−10%: {d.stats.dd10} · ≤−20%: {d.stats.dd20} of {d.stats.universe}</span>
      </div>
      <Table head={["Ticker", "Name", "Sector", "Drawdown", "Peak", "1 day", "5 days", "Worst day", "16 sessions", "Flag"]}>
        {rows.slice(0, 300).map((r) => (
          <tr key={r.sym}>
            <td className="font-semibold">{r.sym}</td><td>{r.name}</td><td className="text-xs text-muted">{r.sector}</td>
            <td className="num">{pp(r.dd)}</td><td className="text-xs">{r.peakDate}</td><td className="num">{pp(r.d1)}</td>
            <td className="num">{pp(r.r5)}</td><td className="num">{pp(r.w1)} <span className="text-xs text-muted">{r.w1Date}</span></td>
            <td><Spark data={r.closes} tone="bad" /></td>
            <td>{r.flag && <Chip tone="warn" meaning="ca? = likely corporate action; new = recent listing">{r.flag}</Chip>}</td>
          </tr>
        ))}
      </Table>
      <div className="mt-2"><Note>A drawdown is a question, not a signal: find what caused it in the filings and news before treating it as an opportunity.</Note></div>
    </Card>
  );
}
