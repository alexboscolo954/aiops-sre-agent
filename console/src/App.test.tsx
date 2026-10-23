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
