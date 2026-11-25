import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post, useDoc, useJob } from "../lib/api";
import { num, pp } from "../lib/format";
import { Card, Chip, Empty, Kpi, KpiGrid, Note, RunButton, Spark, Table, toneOf, type Tone } from "../components/ui";

interface Signal { id: string; layer: string; name: string; value: number | null; unit: string; status: string; rule: string; kind: string; hist?: (number | null)[] }
interface Check { id: string; name: string; status: string; now: string; rule: string }
interface WatchRow { sym: string; px: number; d1: number; d20: number; vs50: number; vs200: number; dd: number }
export interface SignalsDoc {
  asOf: string; regime: string; playbook: string; riskScore: number; leadScore: number; riskLevel: string;
  bottomGreens: number; bottomTotal: number; bottomLevel: string; signals: Signal[]; bottom: Check[];
  watchlist: WatchRow[]; changes: { id: string; name: string; from: string; to: string }[]; caveat: string; missing?: string[];
}

const REGIME_TONE: Record<string, Tone> = { "Risk-on": "good", Caution: "warn", "Risk-off": "bad", Washout: "info" };
const LAYERS = ["Breadth", "Leadership", "Credit", "Volatility", "Macro", "Risk appetite"];
const MANUAL = new Set(["B6", "B7", "B9"]);

export default function Signals() {
  const q = useDoc<SignalsDoc>(["signals"], "/api/signals/latest");
  const job = useJob("/api/signals/run", [["signals"]]);
  const qc = useQueryClient();
  const setManual = useMutation({
    mutationFn: (v: { id: string; status: string }) => post("/api/signals/manual", { items: { [v.id]: { status: v.status, note: "set on the Signals page" } } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["signals"] }),
  });
  const d = q.data;
  const run = <RunButton label="Run signals now" busy={job.busy} onClick={job.run} status={job.job?.status} />;

  if (q.isLoading) return <p className="text-muted">Loading…</p>;
  if (!d)
    return (
      <Card title="Market signals" actions={run}>
        <Empty>No signal run yet. Run it now (takes about a minute), or turn on the daily schedule in folio-desk.toml.</Empty>
        {job.job?.status === "error" && <p className="mt-2 text-sm text-bad">{job.job.message}</p>}
      </Card>
    );

  return (
    <div className="grid gap-5">
      <Card title="Market regime" sub={`as of close ${d.asOf}`} actions={run}>
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <Chip tone={REGIME_TONE[d.regime] ?? "muted"} meaning="market regime">{d.regime}</Chip>
          <span className="text-sm">{d.playbook}</span>
        </div>
        <KpiGrid>
          <Kpi label="Top-risk score (0-100)" value={num(d.riskScore, 1)} sub={d.riskLevel} />
          <Kpi label="Lead-signal score" value={num(d.leadScore, 1)} />
          <Kpi label="Bottom checklist" value={`${d.bottomGreens}/${d.bottomTotal}`} sub={d.bottomLevel} />
          <Kpi label="State changes vs last run" value={d.changes.length} />
        </KpiGrid>
        {d.changes.length > 0 && (
          <ul className="mt-3 grid gap-1 text-sm">
            {d.changes.map((c) => (
              <li key={c.id}>
                <b>{c.name}</b>: {c.from ?? "—"} → {c.to}
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3"><Note>{d.caveat} Leads warn; confirms describe. No single signal calls a top or a bottom.</Note></div>
      </Card>

      <Card title="Signals by layer">
        <Table head={["", "Signal", "Value", "Last 120 sessions", "Kind"]}>
          {LAYERS.flatMap((layer) => {
            const rows = d.signals.filter((s) => s.layer === layer);
            if (!rows.length) return [];
            return [
              <tr key={layer}>
                <td colSpan={5} className="bg-page text-[11px] font-semibold uppercase tracking-wide text-muted">{layer}</td>
              </tr>,
              ...rows.map((s) => (
                <tr key={s.id}>
                  <td><Chip tone={toneOf(s.status)} meaning={s.rule}>{s.id}</Chip></td>
                  <td title={s.rule}>{s.name}</td>
                  <td className="num">{num(s.value, 2)}{s.unit === "%" ? "%" : ` ${s.unit}`}</td>
                  <td>{s.hist ? <Spark data={s.hist} tone={toneOf(s.status)} /> : null}</td>
                  <td className="text-xs text-muted">{s.kind}</td>
                </tr>
              )),
            ];
          })}
        </Table>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Bottom checklist" sub="4-5 green: first tranche; 6+: next tranche">
          <Table head={["", "Item", "Now"]}>
            {d.bottom.map((c) => (
              <tr key={c.id}>
                <td><Chip tone={toneOf(c.status)} meaning={c.rule}>{c.id}</Chip></td>
                <td>{c.name}</td>
                <td className="text-xs">
                  {MANUAL.has(c.id) ? (
                    <select
                      aria-label={`Set ${c.id}`}
                      value={c.status}
                      onChange={(e) => setManual.mutate({ id: c.id, status: e.target.value })}
                      className="rounded border border-line bg-panel px-1 py-0.5"
                    >
                      {["pending", "green", "amber", "red"].map((s) => <option key={s}>{s}</option>)}
                    </select>
                  ) : (
                    <span className="num">{c.now}</span>
                  )}
                </td>
              </tr>
            ))}
          </Table>
          <div className="mt-2"><Note>B6, B7 and B9 need judgment from the news; set them here. They carry forward between runs.</Note></div>
        </Card>
        <Card title="Watchlist trend" sub="edit [watchlist] in folio-desk.toml">
          <Table head={["Ticker", "Last", "1 day", "20 days", "vs 50-day", "vs 200-day", "From 52-wk high"]}>
            {d.watchlist.map((w) => (
              <tr key={w.sym}>
                <td className="font-semibold">{w.sym}</td>
                <td className="num">{num(w.px)}</td>
                <td className="num">{pp(w.d1)}</td>
                <td className="num">{pp(w.d20)}</td>
                <td className="num">{pp(w.vs50)}</td>
                <td className="num">{pp(w.vs200)}</td>
                <td className="num">{pp(w.dd)}</td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>
    </div>
  );
}
