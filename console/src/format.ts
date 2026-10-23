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

/** One number to sort by: a core weighs as much as 4 GiB until Phase 10's prices. */
export const rank = (w: { waste: { cpu?: number; memory?: number } }) =>
  (w.waste.cpu ?? 0) + (w.waste.memory ?? 0) / GI / 4;
