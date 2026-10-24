const MI = 2 ** 20;
const GI = 2 ** 30;

export const cores = (v: number) => `${v.toFixed(2)} cores`;
export const gib = (v: number) => `${(v / GI).toFixed(2)} GiB`;
export const cpu = (v: number | null | undefined) =>
  v == null ? "unset" : `${Math.round(v * 1000)}m`;
export const memory = (v: number | null | undefined) =>
  v == null ? "unset" : `${Math.round(v / MI)}Mi`;

export function when(at: number | null | undefined): string {
  if (at == null) return "never";
  return new Date(at * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

export const money = (v: number, currency: string) =>
  `${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}/month`;

/** One number to sort by: the waste's monthly cost when the Contract has prices, else
 * cores and GiB with a core weighing as much as 4 GiB. */
export const rank = (w: {
  waste: { cpu?: number; memory?: number };
  cost?: { waste: number } | null;
}) => (w.cost ? w.cost.waste : (w.waste.cpu ?? 0) + (w.waste.memory ?? 0) / GI / 4);
