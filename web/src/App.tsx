import { useQuery } from "@tanstack/react-query";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./lib/api";
import { Card, Chip, Note } from "./components/ui";
import Signals from "./pages/Signals";
import { Drawdowns, Rotation } from "./pages/Sectors";
import { EquityIndex, EquityReport } from "./pages/Equity";
import Construction from "./pages/Construction";

const NAV: { to: string; label: string; soon?: boolean }[] = [
  { to: "/", label: "Market signals" },
  { to: "/sectors", label: "Sector rotation" },
  { to: "/drawdowns", label: "Drawdowns" },
  { to: "/equity", label: "Equity research" },
  { to: "/register", label: "Trading register", soon: true },
  { to: "/construction", label: "Portfolio construction" },
  { to: "/performance", label: "Performance", soon: true },
  { to: "/optimization", label: "Optimization", soon: true },
  { to: "/risk", label: "Risk management", soon: true },
  { to: "/settings", label: "Settings" },
];

function Settings() {
  const s = useQuery({ queryKey: ["settings"], queryFn: () => api<Record<string, Record<string, unknown>> & { warnings: string[] }>("/api/settings") });
  if (!s.data) return null;
  const { warnings, ...rest } = s.data;
  return (
    <Card title="Settings" sub="edit folio-desk.toml (or FOLIO_* environment variables) and restart">
      {warnings.map((w) => <p key={w} className="mb-2 text-sm"><Chip tone="warn" meaning="needs attention">check</Chip> {w}</p>)}
      <pre className="num overflow-x-auto rounded bg-page p-3 text-xs">{JSON.stringify(rest, null, 2)}</pre>
      <Note>API keys show as true/false only; they are never sent to the page.</Note>
    </Card>
  );
}

function Soon({ name }: { name: string }) {
  return <Card title={name}><p className="text-muted">Coming in the next phase.</p></Card>;
}

export default function App() {
  return (
    <div className="min-h-screen md:grid md:grid-cols-[220px_1fr]">
      <aside className="border-b border-line bg-panel p-4 md:min-h-screen md:border-b-0 md:border-r">
        <div className="mb-4 text-lg font-bold tracking-tight">folio-desk</div>
        <nav className="flex gap-1 overflow-x-auto md:flex-col">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"}
              className={({ isActive }) => `whitespace-nowrap rounded-md px-3 py-1.5 text-sm ${isActive ? "bg-info-soft font-semibold text-info" : "text-muted hover:bg-page"}`}>
              {n.label}{n.soon && <span className="ml-1 text-[10px] uppercase">soon</span>}
            </NavLink>
          ))}
        </nav>
        <p className="mt-6 hidden text-[11px] text-muted md:block">Research software, not investment advice.</p>
      </aside>
      <main className="mx-auto w-full max-w-7xl p-4 md:p-6">
        <Routes>
          <Route path="/" element={<Signals />} />
          <Route path="/sectors" element={<Rotation />} />
          <Route path="/drawdowns" element={<Drawdowns />} />
          <Route path="/equity" element={<EquityIndex />} />
          <Route path="/equity/:ticker" element={<EquityReport />} />
          <Route path="/construction" element={<Construction />} />
          <Route path="/settings" element={<Settings />} />
          {NAV.filter((n) => n.soon).map((n) => <Route key={n.to} path={n.to} element={<Soon name={n.label} />} />)}
        </Routes>
      </main>
    </div>
  );
}
