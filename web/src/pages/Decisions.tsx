import { useState } from "react";
import { Link } from "react-router-dom";
import { useDoc, useJob } from "../lib/api";
import { pct, usd, usdK } from "../lib/format";
import { Card, Chip, Empty, Note, RunButton, Table, type Tone } from "../components/ui";
import { VERDICT_TONE } from "./Register";

interface RiskBrief { verdict: string; rules: { id: string; name: string; status: string; detail: string }[] }
interface PutIdea { expiry: string; strike: number; bid: number; annYield: number; dte: number; iv?: number; belowBuy: boolean; why: string; risk?: RiskBrief }
interface Row {
  ticker: string; action: string; label?: string; confidence: string; held: boolean; heldValue: number; price: number | null; size: number; shares: number;
  levels: { fv: number; buy: number; acc: number; trim: number } | null; reportAge: number | null; reasons: string[]; issues: string[]; risk?: RiskBrief; putIdea?: PutIdea | null;
}
interface Doc { asOf: string; regime: string | null; playbook: string | null; signalsAsOf: string | null; portfolioValue: number; rows: Row[]; note: string }

const ACTION_TONE: Record<string, Tone> = { BUY: "good", ADD: "good", HOLD: "muted", TRIM: "warn", SELL: "bad", AVOID: "muted", "NO VIEW": "info" };
const CONF_TONE: Record<string, Tone> = { High: "good", Medium: "warn", Low: "bad" };

const tradeLink = (r: Row) =>
  `/register?${new URLSearchParams({ ticker: r.ticker, side: r.action === "TRIM" || r.action === "SELL" ? "sell" : "buy", qty: String(r.shares || ""), price: r.price ? r.price.toFixed(2) : "", idea_source: "equity", thesis: r.reasons[0] ?? "" })}`;
const putLink = (r: Row, p: PutIdea) =>
  `/register?${new URLSearchParams({ ticker: r.ticker, asset: "option", side: "sell", qty: "1", price: String(p.bid), opt_kind: "put", strike: String(p.strike), expiry: p.expiry, iv: p.iv ? String(Math.round(p.iv * 100)) : "", strategy: "cash-secured put", idea_source: "equity" })}`;

export default function Decisions() {
  const q = useDoc<Doc>(["decisions"], "/api/decisions/latest");
  const job = useJob("/api/decisions/run", [["decisions"]]);
  const [open, setOpen] = useState<string | null>(null);
  const d = q.data;
  const run = <RunButton label="Refresh decisions" busy={job.busy} onClick={job.run} status={job.job?.status} />;
  if (q.isLoading) return <p className="text-muted">Loading…</p>;
  if (!d) return (
    <Card title="Decisions" actions={run}>
      <Empty>No decision run yet. It combines your equity reports, the market regime, your holdings and your risk limits into one call per name. Run the signals desk and a few equity reports first for the most useful result.</Empty>
      {job.job?.status === "error" && <p className="mt-2 text-sm text-bad">{job.job.message}</p>}
    </Card>
  );
  return (
    <div className="grid gap-5">
      <Card title="Decisions" sub={`as of ${d.asOf} · portfolio ${usdK(d.portfolioValue)}`} actions={run}>
        <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
          {d.regime ? <><Chip tone="info" meaning="market regime from the signals desk">{d.regime}</Chip><span>{d.playbook}</span><span className="text-xs text-muted">(signals {d.signalsAsOf})</span></>
            : <><Chip tone="warn" meaning="no market-signals run on file">regime unknown</Chip><span>Run the signals desk so sizing reflects the market.</span></>}
        </div>
        {!d.rows.length ? <Empty>Nothing to decide yet: add a watchlist, log holdings, or run an equity report.</Empty> : (
          <Table head={["Name", "Call", "Confidence", "Price vs levels", "Suggested", "Risk", "Put idea", ""]}>
            {d.rows.flatMap((r) => {
              const main = (
                <tr key={r.ticker} className="cursor-pointer" onClick={() => setOpen(open === r.ticker ? null : r.ticker)}>
                  <td><Link to={`/equity/${r.ticker}`} className="font-semibold text-info" onClick={(e) => e.stopPropagation()}>{r.ticker}</Link>{r.held && <span className="ml-1 text-xs text-muted">held {usdK(r.heldValue)}</span>}</td>
                  <td><Chip tone={ACTION_TONE[r.action] ?? "muted"} meaning="research call">{r.action}</Chip></td>
                  <td>{r.confidence === "n/a" ? <span className="text-xs text-muted">fund</span> : <Chip tone={CONF_TONE[r.confidence] ?? "muted"} meaning={r.issues.join("; ") || "no reliability issues"}>{r.confidence}</Chip>}</td>
                  <td className="text-xs">{r.levels && r.price ? <span className="num">{usd(r.price)} · BUY {usd(r.levels.buy, 0)} · ACC {usd(r.levels.acc, 0)} · TRIM {usd(r.levels.trim, 0)}</span> : "—"}</td>
                  <td className="num">{r.size ? `${usdK(r.size)}${r.shares ? ` · ${r.shares} sh` : ""}` : "—"}</td>
                  <td>{r.risk ? <Chip tone={VERDICT_TONE[r.risk.verdict]} meaning={r.risk.rules.map((x) => `${x.id}: ${x.detail}`).join(" | ") || "all rules pass"}>{r.risk.verdict}</Chip> : "—"}</td>
                  <td className="text-xs">{r.putIdea ? <>{r.putIdea.expiry} ${r.putIdea.strike} put · {pct(r.putIdea.annYield)}/yr {r.putIdea.risk && <Chip tone={VERDICT_TONE[r.putIdea.risk.verdict]} meaning={r.putIdea.risk.rules.map((x) => `${x.id}: ${x.detail}`).join(" | ") || "all rules pass"}>{r.putIdea.risk.verdict}</Chip>}</> : "—"}</td>
                  <td className="text-xs text-muted">{open === r.ticker ? "▲" : "▼"}</td>
                </tr>
              );
              if (open !== r.ticker) return [main];
              return [main, (
                <tr key={r.ticker + "-detail"}>
                  <td colSpan={8} className="bg-page">
                    <div className="grid gap-2 p-2 text-sm md:grid-cols-2">
                      <div><b>Why</b><ul className="ml-4 list-disc">{r.reasons.map((x) => <li key={x}>{x}</li>)}</ul></div>
                      <div><b>Reliability issues</b>{r.issues.length ? <ul className="ml-4 list-disc">{r.issues.map((x) => <li key={x}>{x}</li>)}</ul> : <p className="text-muted">None.</p>}
                        {r.risk && r.risk.rules.length > 0 && <><b>Risk check on the suggested trade</b><ul className="ml-4 list-disc">{r.risk.rules.map((x) => <li key={x.id}>{x.id} {x.status}: {x.detail}</li>)}</ul></>}
                        {r.putIdea && <p className="mt-1">{r.putIdea.why}</p>}
                      </div>
                    </div>
                    <div className="flex gap-3 p-2 text-sm">
                      {["BUY", "ADD", "TRIM", "SELL"].includes(r.action) && <Link className="text-info" to={tradeLink(r)}>Log this trade →</Link>}
                      {r.putIdea && <Link className="text-info" to={putLink(r, r.putIdea)}>Log the put →</Link>}
                      <Link className="text-info" to={`/equity/${r.ticker}`}>Equity report →</Link>
                    </div>
                  </td>
                </tr>
              )];
            })}
          </Table>
        )}
        <div className="mt-3 grid gap-1"><Note>{d.note} Click a row for the reasons. Rules: docs/decisions.md.</Note></div>
      </Card>
    </div>
  );
}
