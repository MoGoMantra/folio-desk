import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, post } from "../lib/api";
import { num, usd, usdK } from "../lib/format";
import { Button, Card, Chip, Empty, Kpi, KpiGrid, Note, Table, type Tone } from "../components/ui";

interface Position { account: string; key: string; ticker: string; asset: string; qty: number; avgPrice: number | null; mark: number | null; value: number | null; unrealized: number | null; optKind: string; strike: number | null; expiry: string; strategy: string; assignmentNotional?: number }
interface Group { pnl: number; n: number; wins: number }
interface PosResp { positions: Position[]; portfolioValue: number; shortPutNotional: number; uncheckedTrades: number; reviewsDue: { id: string; ticker: string; review: string; thesis: string }[]; summary: { realizedTotal: number; fees: number; cash: Record<string, number>; byStrategy: Record<string, Group>; byIdeaSource: Record<string, Group>; warnings: string[] }; note: string }
interface Trade { id: string; date: string; account: string; ticker: string; asset: string; side: string; qty: number; price: number; opt_kind: string; strike: number | null; expiry: string; strategy: string; idea_source: string; event: string; check_id: string; thesis: string }
interface CheckResult { id: string; verdict: "PASS" | "WARN" | "BLOCK"; rules: { id: string; name: string; status: string; detail: string }[] }

export const VERDICT_TONE: Record<string, Tone> = { PASS: "good", WARN: "warn", BLOCK: "bad", SKIP: "muted" };
const STRATEGIES = ["long stock", "cash-secured put", "covered call", "PMCC long call", "PMCC short call", "long call", "long put", "other"];
const SOURCES = ["equity", "signals", "rotation", "drawdowns", "other"];
const today = () => new Date().toISOString().slice(0, 10);
const blank = { date: today(), account: "T", ticker: "", asset: "stock", side: "buy", qty: "", price: "", fees: "0", opt_kind: "put", strike: "", expiry: "", iv: "", earnings_date: "", strategy: "long stock", idea_source: "equity", thesis: "", invalidation: "", review_date: "" };

export default function Register() {
  const qc = useQueryClient();
  const pos = useQuery({ queryKey: ["positions"], queryFn: () => api<PosResp>("/api/register/positions") });
  const trades = useQuery({ queryKey: ["trades"], queryFn: () => api<Trade[]>("/api/register/trades") });
  const flows = useQuery({ queryKey: ["cashflows"], queryFn: () => api<{ id: string; date: string; account: string; amount: number; note: string }[]>("/api/register/cashflows") });
  const refresh = () => ["positions", "trades", "cashflows"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const [f, setF] = useState(blank);
  const [chk, setChk] = useState<CheckResult | null>(null);
  const [confirmBlock, setConfirmBlock] = useState(false);
  const [cf, setCf] = useState({ date: today(), account: "T", amount: "", note: "" });
  const set = (k: keyof typeof blank, v: string) => { setF({ ...f, [k]: v }); setChk(null); setConfirmBlock(false); };
  const isOpt = f.asset === "option";
  const body = () => ({ ...f, qty: +f.qty, price: +f.price, fees: +f.fees || 0, strike: isOpt ? +f.strike : null, expiry: isOpt ? f.expiry : "",
    opt_kind: isOpt ? f.opt_kind : "", iv: f.iv ? +f.iv / 100 : null, earnings_date: f.earnings_date || null });
  const check = useMutation({ mutationFn: () => post<CheckResult>("/api/risk/check", body()), onSuccess: setChk });
  const save = useMutation({ mutationFn: () => post("/api/register/trades", { ...body(), check_id: chk?.id ?? "" }), onSuccess: () => { setF({ ...blank, date: f.date }); setChk(null); refresh(); } });
  const act = useMutation({ mutationFn: (b: object) => post("/api/register/options/action", b), onSuccess: refresh });
  const del = useMutation({ mutationFn: (id: string) => api(`/api/register/trades/${id}`, { method: "DELETE" }), onSuccess: refresh });
  const addCf = useMutation({ mutationFn: () => post("/api/register/cashflows", { ...cf, amount: +cf.amount }), onSuccess: () => { setCf({ ...cf, amount: "", note: "" }); refresh(); } });
  const p = pos.data;
  const input = "w-full min-w-0 rounded border border-line bg-panel px-2 py-1";

  return (
    <div className="grid gap-5">
      <Card title="Trading register" sub="every position change is one row; options marked at intrinsic value">
        {p && (
          <KpiGrid>
            <Kpi label="Portfolio value" value={usdK(p.portfolioValue)} />
            {Object.entries(p.summary.cash).map(([a, c]) => <Kpi key={a} label={`Cash · ${a}`} value={usdK(c)} />)}
            <Kpi label="Realized P&L" value={usdK(p.summary.realizedTotal)} sub={`fees ${usd(p.summary.fees)}`} />
            <Kpi label="Short-put assignment exposure" value={usdK(p.shortPutNotional)} />
            <Kpi label="Trades without a risk check" value={p.uncheckedTrades} />
          </KpiGrid>
        )}
        {p?.reviewsDue.length ? (
          <ul className="mt-3 grid gap-1 text-sm">
            {p.reviewsDue.map((r) => <li key={r.id}><Chip tone="warn" meaning="thesis review date has passed">review due</Chip> <b>{r.ticker}</b> ({r.review}): {r.thesis || "no thesis written"}</li>)}
          </ul>
        ) : null}
        {p?.summary.warnings.map((w) => <p key={w} className="mt-2 text-sm"><Chip tone="warn" meaning="ledger warning">check</Chip> {w}</p>)}
      </Card>

      <Card title="Log a trade" sub="run the risk check first; the check is attached to the trade">
        <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4 lg:grid-cols-6">
          <label className="grid gap-1">Date<input type="date" value={f.date} onChange={(e) => set("date", e.target.value)} className={input} /></label>
          <label className="grid gap-1">Account<select value={f.account} onChange={(e) => set("account", e.target.value)} className={input}><option value="T">Taxable</option><option value="I">Trad IRA</option><option value="R">Roth</option></select></label>
          <label className="grid gap-1">Ticker<input value={f.ticker} onChange={(e) => set("ticker", e.target.value.toUpperCase())} className={input} /></label>
          <label className="grid gap-1">Type<select value={f.asset} onChange={(e) => set("asset", e.target.value)} className={input}><option value="stock">Stock / ETF</option><option value="option">Option</option></select></label>
          <label className="grid gap-1">Side<select value={f.side} onChange={(e) => set("side", e.target.value)} className={input}><option value="buy">Buy</option><option value="sell">Sell</option></select></label>
          <label className="grid gap-1">{isOpt ? "Contracts" : "Shares"}<input type="number" value={f.qty} onChange={(e) => set("qty", e.target.value)} className={input} /></label>
          <label className="grid gap-1">{isOpt ? "Premium / share" : "Price"}<input type="number" step="0.01" value={f.price} onChange={(e) => set("price", e.target.value)} className={input} /></label>
          <label className="grid gap-1">Fees<input type="number" step="0.01" value={f.fees} onChange={(e) => set("fees", e.target.value)} className={input} /></label>
          {isOpt && <>
            <label className="grid gap-1">Put / call<select value={f.opt_kind} onChange={(e) => set("opt_kind", e.target.value)} className={input}><option value="put">Put</option><option value="call">Call</option></select></label>
            <label className="grid gap-1">Strike<input type="number" step="0.5" value={f.strike} onChange={(e) => set("strike", e.target.value)} className={input} /></label>
            <label className="grid gap-1">Expiry<input type="date" value={f.expiry} onChange={(e) => set("expiry", e.target.value)} className={input} /></label>
            <label className="grid gap-1">IV % (for delta)<input type="number" value={f.iv} onChange={(e) => set("iv", e.target.value)} className={input} /></label>
            <label className="grid gap-1">Next earnings<input type="date" value={f.earnings_date} onChange={(e) => set("earnings_date", e.target.value)} className={input} /></label>
          </>}
          <label className="grid gap-1">Strategy<select value={f.strategy} onChange={(e) => set("strategy", e.target.value)} className={input}>{STRATEGIES.map((s) => <option key={s}>{s}</option>)}</select></label>
          <label className="grid gap-1">Idea source<select value={f.idea_source} onChange={(e) => set("idea_source", e.target.value)} className={input}>{SOURCES.map((s) => <option key={s}>{s}</option>)}</select></label>
          <label className="grid gap-1">Review on<input type="date" value={f.review_date} onChange={(e) => set("review_date", e.target.value)} className={input} /></label>
          <label className="col-span-2 grid gap-1 md:col-span-2">Thesis<input value={f.thesis} onChange={(e) => set("thesis", e.target.value)} className={input} /></label>
          <label className="col-span-2 grid gap-1 md:col-span-2">Invalidation trigger<input value={f.invalidation} onChange={(e) => set("invalidation", e.target.value)} className={input} /></label>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button onClick={() => check.mutate()} disabled={!f.ticker || !f.qty || check.isPending}>{check.isPending ? "Checking…" : "Run risk check"}</Button>
          <Button primary onClick={() => { if (chk?.verdict === "BLOCK" && !confirmBlock) { setConfirmBlock(true); return; } save.mutate(); setConfirmBlock(false); }}
            disabled={!f.ticker || !f.qty || !f.price || save.isPending}>
            {chk?.verdict === "BLOCK" ? (confirmBlock ? "Click again to log a BLOCKED trade" : "Log anyway (BLOCKED)") : `Log trade${chk ? ` (${chk.verdict})` : " (unchecked)"}`}
          </Button>
          {(check.error || save.error) && <span className="text-sm text-bad">{((check.error || save.error) as Error).message}</span>}
        </div>
        {chk && <CheckView c={chk} />}
        <div className="mt-2"><Note>folio-desk never places orders. Log the trade after you place it with your broker.</Note></div>
      </Card>

      <Card title="Open positions" sub={p?.note}>
        {!p?.positions.length ? <Empty>No open positions.</Empty> : (
          <Table head={["Account", "Position", "Qty", "Avg price", "Mark", "Value", "Unrealized", "Strategy", ""]}>
            {p.positions.map((x) => (
              <tr key={x.account + x.key}>
                <td>{x.account}</td><td className="font-semibold">{x.key}</td><td className="num">{num(x.qty, 2)}</td>
                <td className="num">{usd(x.avgPrice)}</td><td className="num">{usd(x.mark)}</td><td className="num">{usdK(x.value)}</td>
                <td className="num">{usdK(x.unrealized)}</td><td className="text-xs">{x.strategy}{x.assignmentNotional ? ` · obliges ${usdK(x.assignmentNotional)}` : ""}</td>
                <td className="whitespace-nowrap">{x.asset === "option" && <OptionActions x={x} onAct={(b) => act.mutate(b)} />}</td>
              </tr>
            ))}
          </Table>
        )}
        {act.error && <p className="mt-2 text-sm text-bad">{(act.error as Error).message}</p>}
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Realized P&L by strategy and idea source">
          {p && <Table head={["Group", "Closed", "Win rate", "P&L"]}>
            {[...Object.entries(p.summary.byStrategy).map(([k, v]) => ["Strategy: " + k, v] as const), ...Object.entries(p.summary.byIdeaSource).map(([k, v]) => ["Source: " + k, v] as const)].map(([k, v]) => (
              <tr key={k}><td>{k}</td><td className="num">{v.n}</td><td className="num">{v.n ? `${Math.round((100 * v.wins) / v.n)}%` : "—"}</td><td className="num">{usd(v.pnl, 0)}</td></tr>
            ))}
          </Table>}
        </Card>
        <Card title="Deposits and withdrawals" sub="needed for account-level returns">
          <div className="mb-2 flex flex-wrap gap-2 text-sm">
            <input type="date" value={cf.date} onChange={(e) => setCf({ ...cf, date: e.target.value })} className={input} aria-label="Date" />
            <select value={cf.account} onChange={(e) => setCf({ ...cf, account: e.target.value })} className={input} aria-label="Account"><option value="T">Taxable</option><option value="I">Trad IRA</option><option value="R">Roth</option></select>
            <input type="number" placeholder="+ deposit / − withdrawal" value={cf.amount} onChange={(e) => setCf({ ...cf, amount: e.target.value })} className={input} aria-label="Amount" />
            <Button onClick={() => addCf.mutate()} disabled={!cf.amount}>Add</Button>
          </div>
          <Table head={["Date", "Account", "Amount"]}>
            {(flows.data ?? []).map((c) => <tr key={c.id}><td>{c.date}</td><td>{c.account}</td><td className="num">{usd(c.amount, 0)}</td></tr>)}
          </Table>
        </Card>
      </div>

      <Card title="All register rows" actions={<a className="text-sm text-info" href="/api/register/export.csv">Export CSV</a>}>
        <Table head={["Date", "Acct", "Instrument", "Side", "Qty", "Price", "Event", "Source", "Risk check", ""]}>
          {(trades.data ?? []).map((t) => (
            <tr key={t.id}>
              <td>{t.date}</td><td>{t.account}</td><td>{t.asset === "option" ? `${t.ticker} ${t.expiry} ${t.opt_kind === "put" ? "P" : "C"} ${t.strike}` : t.ticker}</td>
              <td>{t.side}</td><td className="num">{num(t.qty, 2)}</td><td className="num">{usd(t.price)}</td><td className="text-xs">{t.event}</td><td className="text-xs">{t.idea_source}</td>
              <td>{t.event !== "trade" ? "" : t.check_id ? <Chip tone="good" meaning="a risk check was run before logging">checked</Chip> : <Chip tone="warn" meaning="logged without a risk check">unchecked</Chip>}</td>
              <td><button className="text-xs text-bad" onClick={() => del.mutate(t.id)}>Delete</button></td>
            </tr>
          ))}
        </Table>
      </Card>
    </div>
  );
}

export function CheckView({ c }: { c: CheckResult }) {
  return (
    <div className="mt-3 rounded-md border border-line p-3">
      <div className="mb-2 flex items-center gap-2"><Chip tone={VERDICT_TONE[c.verdict]} meaning="overall risk verdict">{c.verdict}</Chip><span className="text-xs text-muted">check {c.id}</span></div>
      <ul className="grid gap-1 text-sm">
        {c.rules.map((r) => <li key={r.id} className="flex gap-2"><Chip tone={VERDICT_TONE[r.status]} meaning={r.name}>{r.id}</Chip><span><b>{r.name}.</b> {r.detail}</span></li>)}
      </ul>
    </div>
  );
}

function OptionActions({ x, onAct }: { x: Position; onAct: (b: object) => void }) {
  const [roll, setRoll] = useState(false);
  const [r, setR] = useState({ close_price: "", new_expiry: "", new_strike: "", open_price: "" });
  const base = { account: x.account, key: x.key, date: today() };
  if (roll)
    return (
      <span className="flex flex-wrap items-center gap-1 text-xs">
        <input placeholder="close @" className="w-16 rounded border border-line bg-panel px-1" value={r.close_price} onChange={(e) => setR({ ...r, close_price: e.target.value })} />
        <input type="date" className="rounded border border-line bg-panel px-1" value={r.new_expiry} onChange={(e) => setR({ ...r, new_expiry: e.target.value })} />
        <input placeholder="strike" className="w-14 rounded border border-line bg-panel px-1" value={r.new_strike} onChange={(e) => setR({ ...r, new_strike: e.target.value })} />
        <input placeholder="open @" className="w-16 rounded border border-line bg-panel px-1" value={r.open_price} onChange={(e) => setR({ ...r, open_price: e.target.value })} />
        <button className="text-info" onClick={() => { onAct({ ...base, action: "roll", close_price: +r.close_price, new_expiry: r.new_expiry, new_strike: +r.new_strike, open_price: +r.open_price }); setRoll(false); }}>Save</button>
        <button className="text-muted" onClick={() => setRoll(false)}>Cancel</button>
      </span>
    );
  return (
    <span className="flex gap-2 text-xs">
      <button className="text-info" onClick={() => onAct({ ...base, action: "expire" })}>Expired</button>
      <button className="text-info" onClick={() => onAct({ ...base, action: "assign" })}>{x.qty < 0 ? "Assigned" : "Exercised"}</button>
      <button className="text-info" onClick={() => setRoll(true)}>Roll</button>
    </span>
  );
}
