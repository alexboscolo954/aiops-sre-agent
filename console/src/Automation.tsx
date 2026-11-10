// Automation (slice 12.6b): what each Actuator of a Contract last did with each container,
// whether the Contract automates it, and the Operator's Revert. Reasons are the Actuator's
// text: shown as text.
import { useEffect, useState } from "react";
import * as api from "./api";
import { cpu, memory, when } from "./format";

function automation(h: api.Held): string {
  if (!h.automated) return "off";
  if (h.stopped) return "stopped by a Revert, until you approve one of its Sizings";
  if (h.resumes != null) return `ended by 3 rollbacks, resumes ${when(h.resumes)}`;
  return "on";
}

export function AutomationPage({ contract }: { contract: string }) {
  const [data, setData] = useState<api.AutomationPage | null>(null);
  const [error, setError] = useState("");
  const [failed, setFailed] = useState("");
  useEffect(() => {
    setData(null);
    setError("");
    api.automation(contract).then(setData, (e: Error) => setError(e.message));
  }, [contract]);
  if (error) return <p className="notice">The Hub didn't answer: {error}</p>;
  if (!data) return null;
  const undo = (cluster: string, h: api.Held) => {
    setFailed("");
    api
      .revert(contract, { cluster, namespace: h.namespace, kind: h.kind, name: h.name, container: h.container })
      .then(setData, (e: Error) => setFailed(e.message));
  };
  return (
    <>
      <h1>{contract}: Automation</h1>
      <p className="hint">
        What the Actuator in each cluster last did with each container (90 days). Revert puts a
        container's pods back to their template's requests, and stops its Automation until you
        approve one of its Sizings.
      </p>
      {data.kill_switch && <p className="notice">The Kill switch is on: a Revert is refused.</p>}
      {failed && <p className="notice">Couldn't: {failed}</p>}
      {data.clusters.length === 0 && <p className="hint">No cluster of this Contract runs an Actuator.</p>}
      {data.clusters.map((cl) => (
        <section key={cl.cluster}>
          <h2>{cl.cluster}</h2>
          {cl.containers.length === 0 ? (
            <p className="hint">Nothing reported yet.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Container</th>
                  <th>Automation</th>
                  <th>Last</th>
                  <th>Requests</th>
                  <th>Why</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {cl.containers.map((h) => {
                  const where = `${h.namespace}/${h.kind}/${h.name}/${h.container}`;
                  return (
                    <tr key={where}>
                      <td>{where}</td>
                      <td>{automation(h)}</td>
                      <td>
                        {h.outcome}, {h.pods} pods, {when(h.at)}
                      </td>
                      <td>
                        {h.cpu != null && `cpu ${cpu(h.cpu)} `}
                        {h.memory != null && `memory ${memory(h.memory)}`}
                      </td>
                      <td className="text">{h.reason}</td>
                      <td>
                        {h.reverting ? (
                          <span className="hint">reverting</span>
                        ) : (
                          (h.outcome === "applied" || h.outcome === "failed") && (
                            <button aria-label={`Revert ${where}`} onClick={() => undo(cl.cluster, h)}>
                              Revert
                            </button>
                          )
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
      ))}
    </>
  );
}
