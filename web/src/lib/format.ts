export const isNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);

export const pct = (x: number | null | undefined, d = 1) => (isNum(x) ? `${(x * 100).toFixed(d)}%` : "—");
export const pctSigned = (x: number | null | undefined, d = 1) =>
  isNum(x) ? `${x > 0 ? "+" : ""}${(x * 100).toFixed(d)}%` : "—";
/** For values already in percent units (e.g. 3.2 meaning 3.2%). */
export const pp = (x: number | null | undefined, d = 1) => (isNum(x) ? `${x > 0 ? "+" : ""}${x.toFixed(d)}%` : "—");
export const usd = (x: number | null | undefined, d = 2) =>
  isNum(x) ? `${x < 0 ? "−" : ""}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })}` : "—";
export const usdK = (x: number | null | undefined) => {
  if (!isNum(x)) return "—";
  const a = Math.abs(x);
  const s = x < 0 ? "−$" : "$";
  return a >= 1e6 ? `${s}${(a / 1e6).toFixed(2)}M` : a >= 1e3 ? `${s}${Math.round(a / 1e3)}k` : `${s}${a.toFixed(0)}`;
};
export const num = (x: number | null | undefined, d = 2) => (isNum(x) ? x.toFixed(d) : "—");
