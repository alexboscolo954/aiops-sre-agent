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
  prices: [],
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
        total: { requests: { cpu: 5.1, memory: 8 * GI }, waste: { cpu: 2, memory: GI }, cost: { requests: 150.81, waste: 74.65 } },
        realized: {
          currency: "USD",
          rate: { cpu: 2.655, memory: 0 },
          accrued: { cpu: 26.55, memory: 0 },
          week: { cpu: 2.655, memory: 0 },
          cost: { rate: 77.53, accrued: 1.06, week: 77.53 },
          drops: [{ workload: "kind/lab/Deployment/api/app", resource: "cpu", at: 0, before: 1, after: 0.115, sizing: 0.115, pods: 3, saved: 2.655, cost: { rate: 77.53, accrued: 1.06 } }],
        },
      },
    ],
  });
  render(<App />);
  const lab = await screen.findByRole("link", { name: "kind/lab" });
  expect(lab.getAttribute("href")).toBe("/app/?contract=demo-shop&cluster=kind&namespace=lab");
  expect(screen.getAllByText("74.65 USD/month")).toHaveLength(2); // kind/lab's and the total Savings
  expect(screen.getByText("150.81 USD/month")).toBeTruthy(); // the total of the requests
  expect(screen.queryByText("Δ requests")).toBeNull(); // nothing compared
  expect(screen.getByText("77.53 USD/month")).toBeTruthy(); // realized
  expect(screen.getByText(/1\.06 USD so far, 77\.53 USD\/month from this week's/)).toBeTruthy();
  expect(screen.getByText(/1 request lowered to its Sizing/)).toBeTruthy();
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
        total: { requests: { cpu: 2.5, memory: 4 * GI }, waste: { cpu: 1, memory: GI }, cost: null },
        realized: { currency: null, rate: { cpu: 0, memory: 0 }, accrued: { cpu: 0, memory: 0 }, week: { cpu: 0, memory: 0 }, cost: null, drops: [] },
      },
    ],
  });
  const { container: page } = render(<App />);
  expect(await screen.findByText("demo-shop: Cost by team")).toBeTruthy();
  expect(screen.getByText("<b>payments</b>")).toBeTruthy();
  expect(page.querySelector("b")).toBeNull();
  expect(screen.getByText(/no pod has label team/)).toBeTruthy();
  expect(screen.getByText(/Savings realized: none yet/)).toBeTruthy();
  expect(screen.queryByRole("link", { name: "(no team)" })).toBeNull();
  const calls = (fetch as unknown as { mock: { calls: string[][] } }).mock.calls.map((c) => c[0]);
  expect(calls).toContain("/api/v1/contracts/demo-shop/cost?by=team");
  const options = [...screen.getByLabelText("Group by").querySelectorAll("option")].map((o) => o.textContent);
  expect(options).toEqual(["namespace", "team", "label team"]);
});

test("the Cost page says where each cluster's price comes from, as text", async () => {
  history.replaceState(null, "", "/app/?view=cost");
  const zero = { cpu: 0, memory: 0 };
  const total = { requests: zero, waste: zero, cost: null };
  const realized = { currency: null, rate: zero, accrued: zero, week: zero, cost: null, drops: [] };
  answer({
    "/api/v1/contracts": [200, [{ id: "demo-shop", name: "demo-shop" }]],
    "/api/v1/contracts/demo-shop/cost": [
      200,
      {
        contract: "demo-shop", by: "namespace", currency: null, groups: [], groupings: ["namespace"], warnings: [], total, realized,
        prices: [
          { cluster: "eu", source: "list", note: "list price of 3 x aws <i>m5.large</i> in us-east-1" },
          { cluster: "kind", source: "none", note: "no list price: 1 of 1 nodes lack an instance type" },
        ],
      },
    ],
  });
  const { container: page } = render(<App />);
  expect(await screen.findByText(/list price of 3 x aws/)).toBeTruthy();
  expect(page.querySelector("i")).toBeNull();
  expect(screen.getByText(/eu: list price/).className).toBe("hint");
  expect(screen.getByText(/kind: no list price/).className).toBe("notice");
});

test("another Contract's Cost page starts by namespace", async () => {
  history.replaceState(null, "", "/app/?view=cost&by=team");
  const zero = { cpu: 0, memory: 0 };
  const total = { requests: zero, waste: zero, cost: null };
  const realized = { currency: null, rate: zero, accrued: zero, week: zero, cost: null, drops: [] };
  const body = { contract: "demo-shop", by: "team", currency: null, groups: [], groupings: ["namespace", "team"], warnings: [], total, realized };
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

test("comparing shows each group's change, a group gone since and what was left out", async () => {
  history.replaceState(null, "", "/app/?view=cost");
  const zero = { cpu: 0, memory: 0 };
  const change = (requests: number, waste: number) => ({ requests: zero, waste: zero, cost: { requests, waste } });
  answer({
    "/api/v1/contracts": [200, [{ id: "demo-shop", name: "demo-shop" }]],
    "/api/v1/contracts/demo-shop/cost": [
      200,
      {
        contract: "demo-shop",
        by: "namespace",
        currency: "USD",
        groups: [
          { group: "kind/lab", workloads: 9, requests: zero, waste: zero, cost: { requests: 147.29, waste: 74.65 }, change: change(-36.5, -18.25) },
          { group: "kind/old", workloads: 0, requests: zero, waste: zero, cost: { requests: 0, waste: 0 }, change: change(-9.12, 0) },
        ],
        groupings: ["namespace"],
        warnings: [],
        total: { requests: zero, waste: zero, cost: { requests: 147.29, waste: 74.65 } },
        realized: { currency: "USD", rate: zero, accrued: zero, week: zero, cost: { rate: 0, accrued: 0, week: 0 }, drops: [] },
        compare: {
          since: 86400,
          clusters: { kind: { at: 86400, oldest: 0 }, eu: { at: null, oldest: 172800 } },
          change: change(-45.62, -18.25),
          left_out: ["kind/lab/StatefulSet/db/db"],
        },
      },
    ],
  });
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Compare with"), { target: { value: "7" } });
  expect(await screen.findByText("-36.50 USD/month")).toBeTruthy();
  expect(screen.getByText("-9.12 USD/month")).toBeTruthy(); // kind/old, gone since
  expect(screen.getAllByText("+0.00 USD/month")).toHaveLength(1);
  expect(screen.getByText(/\(-45\.62 USD\/month, -18\.25 USD\/month\)/)).toBeTruthy();
  expect(screen.getByText("kind: compared with its run of 1970-01-02 00:00 UTC")).toBeTruthy();
  expect(screen.getByText(/eu: no run that old, oldest 1970-01-03 00:00 UTC/)).toBeTruthy();
  expect(screen.getByText(/kind\/lab\/StatefulSet\/db\/db/)).toBeTruthy();
  const calls = (fetch as unknown as { mock: { calls: string[][] } }).mock.calls.map((c) => c[0]);
  expect(calls).toContain("/api/v1/contracts/demo-shop/cost?by=namespace&compare=7");
  expect(location.search).toContain("compare=7");
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
