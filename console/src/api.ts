// The Hub's JSON API (/api/v1), same origin, with the approver cookie the browser
// already holds. Types come from the API's OpenAPI: `make console-types`.
import type { components } from "./api-types";

export type Schemas = components["schemas"];
export type Workloads = Schemas["Workloads"];
export type Workload = Schemas["Workload"];
export type Container = Schemas["Container"];
export type Point = Schemas["Point"];
export type ContractSummary = Schemas["ContractSummary"];
export type Allocation = Schemas["Allocation"];
export type Group = Schemas["Group"];
export type Change = Schemas["Change"];
export type Bills = Schemas["Bills"];
export type KillSwitch = Schemas["KillSwitch"];
export type Agenda = Schemas["Agenda"];
export type AgendaItem = Schemas["Item"];
export type Brief = Schemas["Brief"];
export type InvestigationPage = Schemas["InvestigationPage"];
export type TriageReport = Schemas["TriageReport"];
export type Evidence = Schemas["Evidence"];

/** The API answered 401: this browser hasn't pasted the approver token. */
export class NeedsToken extends Error {
  constructor(public tokenUrl: string) {
    super("paste the approver token first");
  }
}

async function get<T>(path: string, method: "GET" | "POST" | "DELETE" = "GET"): Promise<T> {
  const r = await fetch(`/api/v1${path}`, { method, credentials: "same-origin" });
  if (r.status === 401) {
    const body = await r.json().catch(() => ({}));
    throw new NeedsToken(body?.detail?.token_url ?? "/console/token");
  }
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return (await r.json()) as T;
}

export const contracts = () => get<ContractSummary[]>("/contracts");

export const workloads = (contract: string) =>
  get<Workloads>(`/contracts/${encodeURIComponent(contract)}/workloads`);

export function cost(contract: string, by: string, compare: string) {
  const q = new URLSearchParams({ by });
  if (compare) q.set("compare", compare);
  return get<Allocation>(`/contracts/${encodeURIComponent(contract)}/cost?${q}`);
}

export const billing = (contract: string) =>
  get<Bills>(`/contracts/${encodeURIComponent(contract)}/billing`);

export const agenda = (contract: string) =>
  get<Agenda>(`/contracts/${encodeURIComponent(contract)}/agenda`);

export const investigations = (contract: string) =>
  get<Brief[]>(`/contracts/${encodeURIComponent(contract)}/investigations`);

export const investigation = (id: string) =>
  get<InvestigationPage>(`/investigations/${encodeURIComponent(id)}`);

/** Earns this browser the cookie: the token page's only call without it. */
export async function saveToken(token: string): Promise<void> {
  const r = await fetch("/api/v1/token", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  if (r.status === 403) throw new Error("that is not the approver token");
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
}

export function history(contract: string, c: Container, days: 14 | 400) {
  const q = new URLSearchParams({
    cluster: c.cluster,
    namespace: c.namespace,
    kind: c.kind,
    name: c.name,
    container: c.container,
    days: String(days),
  });
  return get<Schemas["History"]>(`/contracts/${encodeURIComponent(contract)}/history?${q}`);
}

const switchPath = (contract: string) => `/contracts/${encodeURIComponent(contract)}/kill-switch`;
export const killSwitch = (contract: string) => get<KillSwitch>(switchPath(contract));
export const turnOnKillSwitch = (contract: string) => get<KillSwitch>(switchPath(contract), "POST");
/** The only way a Kill switch goes off. */
export const turnOffKillSwitch = (contract: string) =>
  get<KillSwitch>(switchPath(contract), "DELETE");
