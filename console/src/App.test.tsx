import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { Point, Workloads } from "./api";
import App from "./App";
import { series } from "./series";

vi.mock("./Chart", () => ({ default: () => <div>chart</div> })); // jsdom has no canvas

const GI = 2 ** 30;
const container = {
  workload: "kind/lab/Deployment/api/app",
  cluster: "kind",
  namespace: "lab",
  kind: "Deployment",
  name: "api",
  container: "app",
  policy: "production",
  state: "ready" as const,
  pods: 3,
  cpu: { action: "lower", current: 1, target: 0.115, basis: 0.1 },
  memory: { action: "lower", current: GI, target: 96 * 2 ** 20, basis: 80 * 2 ** 20 },
  waste: { cpu: 2.655, memory: 2.7 * GI },
  risks: [{ kind: "oom_killed", text: '<img src=x onerror="alert(1)">' }],
};

function workload(name: string, cpu: number, memory: number, risks = container.risks) {
  return {
    workload: `kind/lab/Deployment/${name}`,
    cluster: "kind",
    namespace: "lab",
    kind: "Deployment",
    name,
    pods: 1,
    waste: { cpu, memory },
    risks: risks.map((r) => ({ ...r, container: "app" })),
    containers: [{ ...container, name, workload: `kind/lab/Deployment/${name}/app`, risks }],
  };
}

const DATA: Workloads = {
  contract: "demo-shop",
  clusters: { kind: { at: 1_700_000_000, error: null, since: null } },
  total: { cpu: 1.5, memory: 5 * GI },
  workloads: [workload("cpu-heavy", 1, 0, []), workload("memory-heavy", 0, 5 * GI)],
  learning: [{ ...container, name: "db", workload: "kind/lab/StatefulSet/db/app", state: "learning", history_h: 24, needs_h: 72 }],
  excluded: [],
};

function answer(routes: Record<string, [number, unknown]>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const path = url.split("?")[0];
      const [status, body] = routes[path] ?? [404, {}];
      return new Response(JSON.stringify(body), { status });
    }),
  );
}

beforeEach(() => history.replaceState(null, "", "/app/"));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("model and Hub text renders as text, never as markup", async () => {
  answer({
    "/api/v1/contracts": [200, [{ id: "demo-shop", name: "demo-shop" }]],
    "/api/v1/contracts/demo-shop/workloads": [200, DATA],
    "/api/v1/contracts/demo-shop/history": [200, { points: [] }],
  });
  const { container: page } = render(<App />);
  fireEvent.click(await screen.findByText("Deployment/memory-heavy"));
  expect(await screen.findByText(/onerror="alert\(1\)"/)).toBeTruthy();
  expect(page.querySelector("img")).toBeNull();
});

test("Workloads rank by waste, a core like 4 GiB", async () => {
  answer({
    "/api/v1/contracts": [200, [{ id: "demo-shop", name: "demo-shop" }]],
    "/api/v1/contracts/demo-shop/workloads": [200, DATA],
  });
  render(<App />);
  await screen.findByText("Deployment/memory-heavy");
  const names = screen.getAllByRole("button").map((b) => b.textContent);
  expect(names.slice(0, 2)).toEqual(["Deployment/memory-heavy", "Deployment/cpu-heavy"]);
  expect(screen.getByText(/Learning: kind\/lab\/StatefulSet\/db\/app \(24 h of 72 h\)/)).toBeTruthy();
});

test("with prices, Workloads rank by the monthly cost of their waste and show it", async () => {
  // cpu-heavy wastes 1 core, memory-heavy 5 GiB: by cost, CPU's price puts it first
  const priced: Workloads = {
    ...DATA,
    currency: "EUR",
    cost: { waste: 1234.5, requests: 5000 },
    workloads: [
      { ...workload("memory-heavy", 0, 5 * GI), cost: { waste: 15.33, requests: 40 } },
      { ...workload("cpu-heavy", 1, 0, []), cost: { waste: 1219.17, requests: 4960 } },
    ],
  };
  answer({
    "/api/v1/contracts": [200, [{ id: "demo-shop", name: "demo-shop" }]],
    "/api/v1/contracts/demo-shop/workloads": [200, priced],
  });
  render(<App />);
  await screen.findByText("Deployment/memory-heavy");
  const names = screen.getAllByRole("button").map((b) => b.textContent);
  expect(names.slice(0, 2)).toEqual(["Deployment/cpu-heavy", "Deployment/memory-heavy"]);
  expect(screen.getByText("1,234.50 EUR/month")).toBeTruthy();
  expect(screen.getByText("1,219.17 EUR/month")).toBeTruthy();
  expect(screen.getByText("4,960.00 EUR/month")).toBeTruthy();
  expect(screen.queryByText(/a core ranks like 4 GiB/)).toBeNull();
});

test("the Cost page lists namespaces by what their requests cost, each linking its Workloads", async () => {
  history.replaceState(null, "", "/app/?view=cost");
  answer({
    "/api/v1/contracts": [200, [{ id: "demo-shop", name: "demo-shop" }]],
    "/api/v1/contracts/demo-shop/cost": [
      200,
      {
        contract: "demo-shop",
        by: "namespace",
        currency: "USD",
        groups: [
          { group: "kind/lab", workloads: 9, requests: { cpu: 5, memory: 8 * GI }, waste: { cpu: 2, memory: GI }, cost: { requests: 148.5, waste: 74.65 } },
          { group: "kind/demo", workloads: 1, requests: { cpu: 0.1, memory: 0 }, waste: { cpu: 0, memory: 0 }, cost: { requests: 2.31, waste: 0 } },
        ],
        groupings: ["namespace"],
        warnings: [],
      },
    ],
  });
  render(<App />);
  const lab = await screen.findByRole("link", { name: "kind/lab" });
  expect(lab.getAttribute("href")).toBe("/app/?contract=demo-shop&cluster=kind&namespace=lab");
  expect(screen.getByText("74.65 USD/month")).toBeTruthy();
  expect(screen.getByText("150.81 USD/month")).toBeTruthy(); // the total of the requests
  const rows = screen.getAllByRole("link").map((a) => a.textContent).filter((t) => t?.startsWith("kind/"));
  expect(rows).toEqual(["kind/lab", "kind/demo"]);
});

test("the Cost page groups by team on request, with no Workloads links and the Hub's warnings as text", async () => {
  history.replaceState(null, "", "/app/?view=cost&by=team");
  answer({
    "/api/v1/contracts": [200, [{ id: "demo-shop", name: "demo-shop" }]],
    "/api/v1/contracts/demo-shop/cost": [
      200,
      {
        contract: "demo-shop",
        by: "team",
        currency: null,
        groups: [
          { group: "<b>payments</b>", workloads: 3, requests: { cpu: 2, memory: 4 * GI }, waste: { cpu: 1, memory: GI }, cost: null },
          { group: "(no team)", workloads: 1, requests: { cpu: 0.5, memory: 0 }, waste: { cpu: 0, memory: 0 }, cost: null },
        ],
        groupings: ["namespace", "team", "label:team"],
        warnings: ["kind: no pod has label team; kube-state-metrics needs --metric-labels-allowlist=pods=[team]"],
      },
    ],
  });
  const { container: page } = render(<App />);
  expect(await screen.findByText("demo-shop: Cost by team")).toBeTruthy();
  expect(screen.getByText("<b>payments</b>")).toBeTruthy();
  expect(page.querySelector("b")).toBeNull();
  expect(screen.getByText(/no pod has label team/)).toBeTruthy();
  expect(screen.queryByRole("link", { name: "(no team)" })).toBeNull();
  const calls = (fetch as unknown as { mock: { calls: string[][] } }).mock.calls.map((c) => c[0]);
  expect(calls).toContain("/api/v1/contracts/demo-shop/cost?by=team");
  const options = [...page.querySelectorAll("option")].map((o) => o.textContent);
  expect(options).toEqual(["namespace", "team", "label team"]);
});

test("another Contract's Cost page starts by namespace", async () => {
  history.replaceState(null, "", "/app/?view=cost&by=team");
  const body = { contract: "demo-shop", by: "team", currency: null, groups: [], groupings: ["namespace", "team"], warnings: [] };
  answer({
    "/api/v1/contracts": [200, [{ id: "demo-shop", name: "demo-shop" }, { id: "demo-bank", name: "demo-bank" }]],
    "/api/v1/contracts/demo-shop/cost": [200, body],
    "/api/v1/contracts/demo-bank/cost": [200, { ...body, contract: "demo-bank", by: "namespace", groupings: ["namespace"] }],
  });
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Contract"), { target: { value: "demo-bank" } });
  await screen.findByText("demo-bank: Cost by namespace");
  const calls = (fetch as unknown as { mock: { calls: string[][] } }).mock.calls.map((c) => c[0]);
  expect(calls).toContain("/api/v1/contracts/demo-bank/cost?by=namespace");
});

test("without the approver cookie it links the token page", async () => {
  answer({ "/api/v1/contracts": [401, { detail: { token_url: "/console/token" } }] });
  render(<App />);
  const link = await screen.findByRole("link", { name: "paste it" });
  expect(link.getAttribute("href")).toBe("/console/token");
});

test("a chart plots request, Sizing and basis in millicores or MiB", () => {
  const points: Point[] = [
    { at: 1, cpu: { action: "keep", current: 0.5, target: 0.5, basis: 0.25 } },
    { at: 2, memory: { action: "set", current: null, target: 2 ** 21, basis: 2 ** 20 } },
  ];
  expect(series(points, "cpu")).toEqual([[1, 2], [500, null], [500, null], [250, null]]);
  expect(series(points, "memory")).toEqual([[1, 2], [null, null], [null, 2], [null, 1]]);
});
