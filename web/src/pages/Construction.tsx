import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, post } from "../lib/api";
import { num, pct, pctSigned, usdK } from "../lib/format";
import { Button, Card, Chip, Empty, Kpi, KpiGrid, Note, Table, type Tone } from "../components/ui";

interface Fund { ticker: string; name: string; category: string; index: string; fee: number }
interface Row { t: string; a: "T" | "I" | "R"; w: number }
interface Stats { cagr: number; vol: number; sharpe: number | null; mdd: number; recoveryMonths: number | null; worst12: number; best12: number; endValue: number; contributed: number; years: Record<string, number> }
interface Run { name: string; backtest?: { dates: string[]; nav: number[] }; stats?: Stats; missing?: string[] }
interface Analysis { runs: Run[]; mix: Record<string, number>; blendedFee: number; stress: { window: string; from: string; to: string; portfolio: number | null; spy: number | null }[]; checks: { level: string; text: string }[]; notes: string[] }
interface Saved { id: string; name: string; rows: Row[]; accounts: Record<string, number> }

const ACCT = { T: "Taxable", I: "Trad IRA", R: "Roth" } as const;
const LEVEL: Record<string, Tone> = { good: "good", warn: "warn", bad: "bad", info: "info" };
const COLORS = ["var(--color-info)", "var(--color-warn)", "var(--color-good)", "var(--color-bad)"];
const COLOR_NAMES = ["blue", "amber", "green", "red"];
const MIX_NAMES: Record<string, string> = { us: "US stocks", intl: "International stocks", stack: "Stacked 90/60", sat: "Satellite", bond: "Bonds", tips: "TIPS", gold: "Gold", real: "Real assets", cash: "Cash" };

export default function Construction() {
  const qc = useQueryClient();
  const funds = useQuery({ queryKey: ["funds"], queryFn: () => api<Fund[]>("/api/funds") });
  const presets = useQuery({ queryKey: ["presets"], queryFn: () => api<Record<string, [string, Row["a"], number][]>>("/api/presets") });
  const saved = useQuery({ queryKey: ["portfolios"], queryFn: () => api<Saved[]>("/api/portfolios") });
  const [rows, setRows] = useState<Row[]>([]);
  const [accounts, setAccounts] = useState({ T: 100000, I: 0, R: 0 });
  const [rebal, setRebal] = useState("A");
  const [contrib, setContrib] = useState(0);
  const [name, setName] = useState("");
  const [add, setAdd] = useState("");
  const analyze = useMutation({ mutationFn: () => post<Analysis>("/api/construction/analyze", { rows, accounts, rebal, contrib_monthly: contrib }) });
  const save = useMutation({ mutationFn: () => post("/api/portfolios", { name, rows, accounts }), onSuccess: () => qc.invalidateQueries({ queryKey: ["portfolios"] }) });
  const total = rows.reduce((s, r) => s + (+r.w || 0), 0);
  const fundMap = useMemo(() => Object.fromEntries((funds.data ?? []).map((f) => [f.ticker, f])), [funds.data]);
  const a = analyze.data;
  const chart = useMemo(() => {
    if (!a) return [];
    const runs = a.runs.filter((r) => r.backtest);
    const dates = runs[0]?.backtest?.dates ?? [];
    return dates.map((d, i) => Object.fromEntries([["d", d.slice(0, 7)], ...runs.map((r) => [r.name, +(r.backtest!.nav[i] * 100).toFixed(2)])]));
  }, [a]);

  const loadPreset = (k: string) => {
    const p = presets.data?.[k];
    if (p) { setRows(p.map(([t, ac, w]) => ({ t, a: ac, w }))); setName(k); }
  };

  return (
    <div className="grid gap-5">
      <Card title="Portfolio construction" sub="build a mix across accounts, backtest it, check tax placement">
        <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
          <select aria-label="Start from a preset" onChange={(e) => { loadPreset(e.target.value); e.target.value = ""; }} className="rounded border border-line bg-panel px-2 py-1">
            <option value="">Start from a preset…</option>
            {Object.keys(presets.data ?? {}).map((k) => <option key={k}>{k}</option>)}
          </select>
          <select aria-label="Load a saved portfolio" onChange={(e) => { const p = saved.data?.find((x) => x.id === e.target.value); if (p) { setRows(p.rows); setAccounts({ T: 0, I: 0, R: 0, ...p.accounts }); setName(p.name); } e.target.value = ""; }} className="rounded border border-line bg-panel px-2 py-1">
            <option value="">Load saved…</option>
            {(saved.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          {(["T", "I", "R"] as const).map((k) => (
            <label key={k}>{ACCT[k]} $<input type="number" step={10000} value={accounts[k]} onChange={(e) => setAccounts({ ...accounts, [k]: Math.max(0, +e.target.value) })} className="num ml-1 w-28 rounded border border-line bg-panel px-1" /></label>
          ))}
        </div>
        {rows.length === 0 ? <Empty>Pick a preset or add funds below.</Empty> : (
          <Table head={["Fund", "Account", "Weight %", "Amount", ""]}>
            {rows.map((r, i) => (
              <tr key={i}>
                <td><b>{r.t}</b> <span className="text-xs text-muted">{fundMap[r.t]?.name ?? "not in fund list"}</span></td>
                <td><select aria-label={`Account for ${r.t}`} value={r.a} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, a: e.target.value as Row["a"] } : x))} className="rounded border border-line bg-panel">
                  {(["T", "I", "R"] as const).map((k) => <option key={k} value={k}>{ACCT[k]}</option>)}</select></td>
                <td><input type="number" step={0.5} value={r.w} aria-label={`Weight for ${r.t}`} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, w: +e.target.value } : x))} className="num w-20 rounded border border-line bg-panel px-1" /></td>
                <td className="num">{usdK(((+r.w || 0) / 100) * (accounts.T + accounts.I + accounts.R))}</td>
                <td><button className="text-xs text-bad" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</button></td>
              </tr>
            ))}
          </Table>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <span className="num">Total {total.toFixed(1)}%</span>
          {Math.abs(total - 100) < 0.05 ? <Chip tone="good" meaning="weights add to 100%">100%</Chip> : <Chip tone="warn" meaning="weights do not add to 100%">{total > 100 ? "over" : "under"}</Chip>}
          <select aria-label="Add a fund" value={add} onChange={(e) => setAdd(e.target.value)} className="rounded border border-line bg-panel px-1 py-1">
            <option value="">Add a fund…</option>
            {(funds.data ?? []).map((f) => <option key={f.ticker} value={f.ticker}>{f.ticker} · {f.category} · {f.fee}%</option>)}
          </select>
          <Button onClick={() => { if (add) { setRows([...rows, { t: add, a: "T", w: 0 }]); setAdd(""); } }}>Add</Button>
          <label>Rebalance <select value={rebal} onChange={(e) => setRebal(e.target.value)} className="rounded border border-line bg-panel">
            <option value="M">Monthly</option><option value="Q">Quarterly</option><option value="A">Annually</option><option value="N">Never</option></select></label>
          <label>Monthly contribution $<input type="number" step={100} value={contrib} onChange={(e) => setContrib(Math.max(0, +e.target.value))} className="num ml-1 w-24 rounded border border-line bg-panel px-1" /></label>
          <Button primary disabled={!rows.length || analyze.isPending} onClick={() => analyze.mutate()}>{analyze.isPending ? "Analysing…" : "Analyse"}</Button>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Portfolio name" aria-label="Portfolio name" className="rounded border border-line bg-panel px-2 py-1" />
          <Button disabled={!name || !rows.length} onClick={() => save.mutate()}>Save</Button>
        </div>
        {analyze.error && <p className="mt-2 text-sm text-bad">{(analyze.error as Error).message}</p>}
      </Card>

      {a && (
        <>
          <Card title="Growth of 100" sub="time-weighted, adjusted for dividends and fund fees; taxes not modelled">
            <div className="h-72">
              <ResponsiveContainer>
                <LineChart data={chart}>
                  <CartesianGrid stroke="var(--color-line)" vertical={false} />
                  <XAxis dataKey="d" tick={{ fontSize: 11 }} minTickGap={40} />
                  <YAxis tick={{ fontSize: 11 }} scale="log" domain={["auto", "auto"]} />
                  <Tooltip />
                  <Legend />
                  {a.runs.filter((r) => r.backtest).map((r, i) => (
                    <Line key={r.name} dataKey={r.name} name={`${r.name} (${COLOR_NAMES[i % 4]})`} stroke={COLORS[i % 4]} dot={false} strokeWidth={i ? 1.5 : 2.5} isAnimationActive={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
            {a.notes.length > 0 && <Note>Stand-in history: {a.notes.join("; ")}.</Note>}
          </Card>
          <div className="grid gap-5 lg:grid-cols-2">
            <Card title="Risk and return">
              <Table head={["", ...a.runs.map((r) => r.name)]}>
                {([["Return per year", (s: Stats) => pct(s.cagr)], ["Volatility", (s: Stats) => pct(s.vol)], ["Sharpe (rf = 0)", (s: Stats) => num(s.sharpe)],
                  ["Worst fall", (s: Stats) => pct(s.mdd)], ["Months to recover", (s: Stats) => s.recoveryMonths ?? "not yet"],
                  ["Worst 12 months", (s: Stats) => pct(s.worst12)], ["Ending value", (s: Stats) => usdK(s.endValue)]] as [string, (s: Stats) => React.ReactNode][]).map(([l, f]) => (
                  <tr key={l}><td>{l}</td>{a.runs.map((r) => <td key={r.name} className="num">{r.stats ? f(r.stats) : `missing ${r.missing?.join(", ")}`}</td>)}</tr>
                ))}
              </Table>
              <div className="mt-3"><KpiGrid>
                <Kpi label="Blended fee" value={pct(a.blendedFee / 100, 3)} />
                {Object.entries(a.mix).map(([k, v]) => <Kpi key={k} label={MIX_NAMES[k] ?? k} value={pct(v, 0)} />)}
              </KpiGrid></div>
            </Card>
            <Card title="Account placement checks">
              <ul className="grid gap-2">
                {a.checks.map((c, i) => <li key={i} className="flex gap-2 text-sm"><Chip tone={LEVEL[c.level] ?? "muted"} meaning="placement check">{c.level === "good" ? "OK" : c.level === "bad" ? "Fix" : c.level === "warn" ? "Review" : "Note"}</Chip><span>{c.text}</span></li>)}
              </ul>
            </Card>
          </div>
          <Card title="Past shocks replayed on this mix" sub="buy-and-hold from the start of each window">
            <Table head={["Window", "Dates", "Your mix", "S&P 500"]}>
              {a.stress.map((s) => <tr key={s.window}><td>{s.window}</td><td className="text-xs">{s.from} to {s.to}</td><td className="num">{s.portfolio == null ? "no data" : pctSigned(s.portfolio)}</td><td className="num">{pctSigned(s.spy)}</td></tr>)}
            </Table>
          </Card>
        </>
      )}
    </div>
  );
}
