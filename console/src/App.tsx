// Workloads per Contract (slice 9.5a): each Workload's waste and risks from the
// Hub's latest stored Sizings, and one container's requests vs Sizing over time.
// Cost (slice 10.2): what each namespace's, team's or label value's requests and waste cost.
// Everything from the API is rendered as text.
import { useEffect, useMemo, useState } from "react";
import * as api from "./api";
import type { Allocation, Container, Point, Workload, Workloads } from "./api";
import Chart from "./Chart";
import { cores, cpu, gib, memory, money, rank, when } from "./format";

function useParam(name: string): [string, (v: string) => void] {
  const [value, set] = useState(() => new URLSearchParams(location.search).get(name) ?? "");
  const update = (v: string) => {
    const q = new URLSearchParams(location.search);
    if (v) q.set(name, v);
    else q.delete(name);
    history.replaceState(null, "", `${location.pathname}?${q}`);
    set(v);
  };
  return [value, update];
}

export default function App() {
  const [contracts, setContracts] = useState<api.ContractSummary[]>([]);
  const [contract, setContract] = useParam("contract");
  const [view] = useParam("view");
  const [by, setBy] = useParam("by");
  const [data, setData] = useState<Workloads | null>(null);
  const [allocation, setAllocation] = useState<Allocation | null>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    api.contracts().then(setContracts, setError);
  }, []);
  const shown = contract || contracts[0]?.id || "";
  const costView = view === "cost";
  useEffect(() => {
    if (!shown) return;
    setData(null);
    setAllocation(null);
    if (costView) api.cost(shown, by || "namespace").then(setAllocation, setError);
    else api.workloads(shown).then(setData, setError);
  }, [shown, costView, by]);
  const here = shown ? `contract=${encodeURIComponent(shown)}` : "";

  return (
    <>
      <header>
        <a className="brand" href="/console">aiops</a>
        <nav>
          <a href="/console">Investigations</a>
          <a href="/console/teachings">Teachings</a>
          <a href="/console/health">Health</a>
          <a href={`/app/?${here}`} aria-current={costView ? undefined : "page"}>Workloads</a>
          <a href={`/app/?${here}&view=cost`} aria-current={costView ? "page" : undefined}>Cost</a>
          <a href="/console/token">Approver token</a>
        </nav>
      </header>
      <main>
        {error instanceof api.NeedsToken ? (
          <p className="notice">
            This browser hasn't got the approver token yet: <a href={error.tokenUrl}>paste it</a>,
            then come back.
          </p>
        ) : error ? (
          <p className="notice">The Hub didn't answer: {error.message}</p>
        ) : null}
        {contracts.length > 1 && (
          <label>
            Contract{" "}
            <select
              value={shown}
              onChange={(e) => {
                setBy(""); // another Contract may not have this grouping
                setContract(e.target.value);
              }}
            >
              {contracts.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </label>
        )}
        {data && !costView && <Page contract={shown} data={data} />}
        {allocation && costView && <CostPage data={allocation} setBy={setBy} />}
      </main>
    </>
  );
}

function Page({ contract, data }: { contract: string; data: Workloads }) {
  const [cluster, setCluster] = useParam("cluster");
  const [namespace, setNamespace] = useParam("namespace");
  const [picked, setPicked] = useParam("workload");
  const clusters = Object.keys(data.clusters).sort();
  const namespaces = [...new Set(data.workloads.map((w) => w.namespace))].sort();
  const rows = useMemo(
    () =>
      data.workloads
        .filter((w) => (!cluster || w.cluster === cluster) && (!namespace || w.namespace === namespace))
        .sort((a, b) => rank(b) - rank(a) || a.workload.localeCompare(b.workload)),
    [data, cluster, namespace],
  );
  const selected = data.workloads.find((w) => w.workload === picked);

  return (
    <>
      <h1>{data.contract}: Workloads</h1>
      <ul className="clusters">
        {clusters.map((name) => {
          const st = data.clusters[name];
          return (
            <li key={name} className={st.error ? "stale" : ""}>
              {name}: Sizings as of {when(st.at)}
              {st.error && `; stale since ${when(st.since)}: ${st.error}`}
            </li>
          );
        })}
      </ul>
      {clusters.length === 0 && <p>No Sizings stored yet: the Hub stores them hourly.</p>}
      {data.currency && data.cost ? (
        <p className="total">
          Waste: <strong>{money(data.cost.waste, data.currency)}</strong> ({cores(data.total.cpu ?? 0)},{" "}
          {gib(data.total.memory ?? 0)}) of {money(data.cost.requests, data.currency)} in requests{" "}
          <span className="hint">(requests above the Sizings; requests are what pods reserve, not the nodes)</span>
        </p>
      ) : (
        <p className="total">
          Waste: <strong>{cores(data.total.cpu ?? 0)}</strong>, <strong>{gib(data.total.memory ?? 0)}</strong>{" "}
          <span className="hint">(requests above the Sizings; a core ranks like 4 GiB)</span>
        </p>
      )}
      <div className="filters">
        <label>
          Cluster{" "}
          <select value={cluster} onChange={(e) => setCluster(e.target.value)}>
            <option value="">all</option>
            {clusters.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label>
          Namespace{" "}
          <select value={namespace} onChange={(e) => setNamespace(e.target.value)}>
            <option value="">all</option>
            {namespaces.map((n) => <option key={n}>{n}</option>)}
          </select>
        </label>
      </div>
      <table>
        <thead>
          <tr>
            <th>Workload</th>
            <th>Pods</th>
            <th>CPU waste</th>
            <th>Memory waste</th>
            {data.currency && <th>Waste cost</th>}
            {data.currency && <th>Requests cost</th>}
            <th>Risks</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((w) => (
            <tr
              key={w.workload}
              className={w.workload === picked ? "picked" : ""}
              onClick={() => setPicked(w.workload)}
            >
              <td>
                <button type="button" className="link">{w.kind}/{w.name}</button>
                <div className="hint">{w.cluster}/{w.namespace}</div>
              </td>
              <td>{w.pods}</td>
              <td>{cores(w.waste.cpu ?? 0)}</td>
              <td>{gib(w.waste.memory ?? 0)}</td>
              {data.currency && <td>{w.cost ? money(w.cost.waste, data.currency) : "-"}</td>}
              {data.currency && <td>{w.cost ? money(w.cost.requests, data.currency) : "-"}</td>}
              <td>
                {[...new Set(w.risks.map((r) => r.kind))].sort().map((k) => (
                  <span key={k} className="chip">{k}</span>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {selected && <Detail contract={contract} workload={selected} />}
      {data.learning.length > 0 && (
        <p>
          Learning:{" "}
          {data.learning
            .map((c) => `${c.workload} (${c.history_h ?? 0} h of ${c.needs_h ?? 0} h)`)
            .join(", ")}
        </p>
      )}
      {data.excluded.length > 0 && <p>Excluded: {data.excluded.map((c) => c.workload).join(", ")}</p>}
    </>
  );
}

function CostPage({ data, setBy }: { data: Allocation; setBy: (v: string) => void }) {
  const currency = data.currency;
  const total = data.groups.reduce((sum, g) => sum + (g.cost?.requests ?? 0), 0);
  const label = data.by.replace(/^label:/, "label ");
  return (
    <>
      <h1>{data.contract}: Cost by {label}</h1>
      <p className="hint">Requests in the Contract's namespaces, not the nodes; waste is the requests above the Sizings.</p>
      {data.groupings.length > 1 && (
        <label>
          Group by{" "}
          <select value={data.by} onChange={(e) => setBy(e.target.value)}>
            {data.groupings.map((g) => (
              <option key={g} value={g}>{g.replace(/^label:/, "label ")}</option>
            ))}
          </select>
        </label>
      )}
      {data.warnings.map((w) => (
        <p key={w} className="notice">{w}</p>
      ))}
      {currency && (
        <p className="total">
          Requests: <strong>{money(total, currency)}</strong>
        </p>
      )}
      {data.groups.length === 0 && <p>No Sizings stored yet: the Hub stores them hourly.</p>}
      <table>
        <thead>
          <tr>
            <th>{label[0].toUpperCase() + label.slice(1)}</th>
            <th>Workloads</th>
            <th>Requests</th>
            <th>Waste</th>
          </tr>
        </thead>
        <tbody>
          {data.groups.map((g) => {
            const [cluster, namespace] = g.group.split("/");
            const q = new URLSearchParams({ contract: data.contract, cluster, namespace });
            return (
              <tr key={g.group}>
                <td>{data.by === "namespace" ? <a href={`/app/?${q}`}>{g.group}</a> : g.group}</td>
                <td>{g.workloads}</td>
                <td>
                  {currency && g.cost
                    ? money(g.cost.requests, currency)
                    : `${cores(g.requests.cpu ?? 0)}, ${gib(g.requests.memory ?? 0)}`}
                </td>
                <td>
                  {currency && g.cost
                    ? money(g.cost.waste, currency)
                    : `${cores(g.waste.cpu ?? 0)}, ${gib(g.waste.memory ?? 0)}`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}

function Detail({ contract, workload }: { contract: string; workload: Workload }) {
  return (
    <section className="detail">
      <h2>{workload.kind}/{workload.name}</h2>
      {workload.containers.map((c) => (
        <ContainerDetail key={c.container} contract={contract} c={c} />
      ))}
    </section>
  );
}

function ContainerDetail({ contract, c }: { contract: string; c: Container }) {
  const [days, setDays] = useState<14 | 400>(14);
  const [points, setPoints] = useState<Point[] | null>(null);
  useEffect(() => {
    setPoints(null);
    api.history(contract, c, days).then((h) => setPoints(h.points), () => setPoints([]));
  }, [contract, c, days]);
  return (
    <div className="container">
      <h3>
        {c.container} <span className="hint">({c.policy})</span>
      </h3>
      <p>
        CPU {c.cpu?.action ?? "-"} {cpu(c.cpu?.current)} → {cpu(c.cpu?.target)}; memory{" "}
        {c.memory?.action ?? "-"} {memory(c.memory?.current)} → {memory(c.memory?.target)}
      </p>
      {c.risks.length > 0 && (
        <ul className="risks">
          {c.risks.map((r, i) => (
            <li key={i}>
              <span className="chip">{r.kind}</span> {r.text}
            </li>
          ))}
        </ul>
      )}
      <div className="range">
        {([14, 400] as const).map((d) => (
          <button key={d} type="button" aria-pressed={days === d} onClick={() => setDays(d)}>
            {d === 14 ? "14 days, hourly" : "400 days, daily"}
          </button>
        ))}
      </div>
      {points === null ? (
        <p className="hint">Loading…</p>
      ) : points.length === 0 ? (
        <p className="hint">No stored Sizings in this range.</p>
      ) : (
        <div className="charts">
          <Chart points={points} res="cpu" />
          <Chart points={points} res="memory" />
        </div>
      )}
    </div>
  );
}
