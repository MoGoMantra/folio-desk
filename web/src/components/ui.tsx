import type { ReactNode } from "react";
import { Line, LineChart, ResponsiveContainer, YAxis } from "recharts";

export type Tone = "good" | "warn" | "bad" | "info" | "muted";

/** Status colour, its colour name (shown on hover) and a default meaning. */
export const TONES: Record<Tone, { cls: string; name: string }> = {
  good: { cls: "bg-good-soft text-good", name: "Green" },
  warn: { cls: "bg-warn-soft text-warn", name: "Amber" },
  bad: { cls: "bg-bad-soft text-bad", name: "Red" },
  info: { cls: "bg-info-soft text-info", name: "Blue" },
  muted: { cls: "bg-line/50 text-muted", name: "Grey" },
};

export const toneOf = (status?: string): Tone =>
  status === "green" ? "good" : status === "amber" ? "warn" : status === "red" ? "bad" : status === "pending" ? "info" : "muted";

export function Chip({ tone = "muted", children, meaning }: { tone?: Tone; children: ReactNode; meaning?: string }) {
  const t = TONES[tone];
  return (
    <span
      title={`${t.name}${meaning ? ` — ${meaning}` : ""}`}
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap ${t.cls}`}
    >
      {children}
    </span>
  );
}

export function Card({ title, sub, children, actions }: { title?: ReactNode; sub?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-panel p-4 min-w-0">
      {(title || actions) && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {title && <h2 className="text-[15px] font-semibold">{title}</h2>}
          {sub && <span className="text-xs text-muted">{sub}</span>}
          <div className="ml-auto flex gap-2">{actions}</div>
        </div>
      )}
      {children}
    </section>
  );
}

export function Kpi({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="bg-panel px-3 py-2.5">
      <div className="num text-xl font-medium">{value}</div>
      <div className="text-[11px] text-muted">{label}</div>
      {sub && <div className="text-[11px] text-muted">{sub}</div>}
    </div>
  );
}

export function KpiGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-px overflow-hidden rounded-md border border-line bg-line">{children}</div>;
}

export function Button({ children, onClick, disabled, primary }: { children: ReactNode; onClick?: () => void; disabled?: boolean; primary?: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`rounded-md border px-3 py-1.5 text-[13px] font-semibold disabled:cursor-not-allowed disabled:opacity-50 ${
        primary ? "border-info bg-info text-white" : "border-line bg-panel hover:bg-line/40"
      }`}
    >
      {children}
    </button>
  );
}

export function RunButton({ label, busy, onClick, status }: { label: string; busy: boolean; onClick: () => void; status?: string }) {
  return (
    <span className="flex items-center gap-2">
      {status === "error" && <Chip tone="bad" meaning="run failed">Failed</Chip>}
      <Button primary onClick={onClick} disabled={busy}>
        {busy ? "Running…" : label}
      </Button>
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-line p-8 text-center text-muted">{children}</div>;
}

export function Spark({ data, tone = "info" }: { data: (number | null)[]; tone?: Tone }) {
  const pts = data.map((v, i) => ({ i, v }));
  const color = { good: "var(--color-good)", warn: "var(--color-warn)", bad: "var(--color-bad)", info: "var(--color-info)", muted: "var(--color-muted)" }[tone];
  return (
    <div className="h-8 w-28" aria-hidden>
      <ResponsiveContainer>
        <LineChart data={pts}>
          <YAxis hide domain={["dataMin", "dataMax"]} />
          <Line type="monotone" dataKey="v" stroke={color} dot={false} strokeWidth={1.5} isAnimationActive={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Table({ head, children }: { head: ReactNode[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr>
            {head.map((h, i) => (
              <th key={i} className="whitespace-nowrap border-b border-line px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="[&_td]:border-b [&_td]:border-line [&_td]:px-2 [&_td]:py-1.5">{children}</tbody>
      </table>
    </div>
  );
}

export function Note({ children }: { children: ReactNode }) {
  return <p className="max-w-[75ch] text-xs text-muted">{children}</p>;
}
