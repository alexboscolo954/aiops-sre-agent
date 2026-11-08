// Investigations (slice 11.5a): a Contract's list, one Investigation in full, and the
// approver token page. Reports, Answers and tool output are model and client text: each
// field is rendered as text, line breaks kept, never as markup, and an Evidence link
// stays text too. Deciding, Report feedback and Jira arrive in 11.5b.
import { useEffect, useState } from "react";
import * as api from "./api";
import { when } from "./format";

export const page = (id: string) => `/app/?view=investigation&id=${encodeURIComponent(id)}`;

function state(t: { status: string; failed: boolean }): string {
  return t.failed ? "failed" : t.status.replace("_", " ");
}

export function InvestigationList({ contract }: { contract: string }) {
  const [rows, setRows] = useState<api.Brief[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setRows(null);
    setError("");
    api.investigations(contract).then(setRows, (e: Error) => setError(e.message));
  }, [contract]);
  if (error) return <p className="notice">The Hub didn't answer: {error}</p>;
  if (!rows) return null;
  return (
    <>
      <h1>{contract}: Investigations</h1>
      <p className="hint">Newest first. Passing Checks are left out.</p>
      {rows.length === 0 ? (
        <p>None yet.</p>
      ) : (
        <table className="investigations">
          <thead>
            <tr>
              <th>Started</th>
              <th>Kind</th>
              <th>Status</th>
              <th>Title</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.id}>
                <td className="hint">{when(t.started)}</td>
                <td>{t.kind}</td>
                <td>{state(t)}</td>
                <td>
                  <a href={page(t.id)}>{t.title}</a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function EvidenceList({ items }: { items: api.Evidence[] }) {
  return (
    <ul className="evidence">
      {items.map((e, n) => (
        <li key={n}>
          <code>{e.source}</code>: {e.finding}
          {e.link ? ` (${e.link})` : ""}
        </li>
      ))}
    </ul>
  );
}

function Report({ r, executed }: { r: api.TriageReport; executed: string[] }) {
  return (
    <section className="panel">
      <h2>Report</h2>
      <p className="text">
        <strong>{r.summary}</strong>
      </p>
      <p className="text">
        Root cause ({r.confidence} confidence, {r.category}): {r.probable_root_cause}
      </p>
      <p>
        Severity: {r.severity} · Affected: {r.affected.join(", ") || "-"}
      </p>
      <h3>Evidence</h3>
      <EvidenceList items={r.evidence} />
      <h3>Recommendations</h3>
      <ol>
        {r.recommended_actions.map((a, n) => (
          <li key={n} className="text">{a}</li>
        ))}
      </ol>
      {executed.length > 0 && (
        <>
          <h3>Executed actions</h3>
          <ul>
            {executed.map((a, n) => (
              <li key={n}>
                <code>{a}</code>
              </li>
            ))}
          </ul>
        </>
      )}
      {r.runbook && <p>Runbook: {r.runbook}</p>}
    </section>
  );
}

export function InvestigationPage({ id }: { id: string }) {
  const [t, setT] = useState<api.InvestigationPage | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = () =>
      api.investigation(id).then(
        (x) => {
          if (stopped) return;
          setT(x);
          if (x.status === "running") timer = setTimeout(load, 5000); // as the Jinja page reloads
        },
        (e: Error) => !stopped && setError(e.message),
      );
    setT(null);
    setError("");
    load();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [id]);
  if (error) return <p className="notice">The Hub didn't answer: {error}</p>;
  if (!t) return null;
  const masked = Object.entries(t.masked);
  return (
    <>
      <h1>{t.title}</h1>
      <p className="meta">
        {state(t)} · {t.contract} · {t.kind} · started {when(t.started)} · <code>{t.id}</code>
        <br />
        Tokens: {t.usage.input_tokens} in, {t.usage.output_tokens} out · cost:{" "}
        {t.usage.cost_usd == null ? "-" : `$${t.usage.cost_usd.toFixed(4)}`}
        {masked.length > 0 &&
          ` · masked for the LLM: ${masked.map(([kind, n]) => `${n} ${kind}${n === 1 ? "" : "s"}`).join(", ")}`}
      </p>
      {t.error && <p className="notice">Failed: {t.error}</p>}
      {t.status === "running" && <p className="hint">Working on it: this page updates every 5 seconds.</p>}
      {t.pending.length > 0 && (
        <section className="panel waiting">
          <h2>Waiting for a decision</h2>
          <p>Goes Stale at {when(t.deadline)}. Decide in Slack, or on the <a href={`/console/investigations/${encodeURIComponent(t.id)}`}>older page</a> until this one can.</p>
          {t.pending.map((p, n) => (
            <pre key={n}>{p}</pre>
          ))}
        </section>
      )}
      {t.check_result && (
        <section className="panel">
          <h2>Check</h2>
          <p className="text">
            <strong>{t.check_result.passed ? "Passed" : "Failed"}:</strong> {t.check_result.summary}
          </p>
          <h3>Evidence</h3>
          <EvidenceList items={t.check_result.evidence} />
        </section>
      )}
      {t.report && <Report r={t.report} executed={t.executed_actions} />}
      {t.answer && (
        <section className="panel">
          <h2>Answer</h2>
          <p className="text">{t.answer.answer}</p>
          <h3>Evidence</h3>
          <EvidenceList items={t.answer.evidence} />
        </section>
      )}
      {t.scenario && (
        <p>
          <a href={`/api/v1/investigations/${encodeURIComponent(t.id)}/scenario.yaml`} download>
            Save as Scenario
          </a>{" "}
          <span className="hint">a draft to edit and commit to the contracts repo.</span>
        </p>
      )}
      {(t.feedback.length > 0 || t.taught.length > 0) && (
        <section className="panel">
          <h2>Feedback</h2>
          {t.feedback.map((f, n) => (
            <p key={n}>
              {when(f.at)} · {f.by}: {f.correct ? "right" : "wrong"}
              {f.correction ? `: ${f.correction}` : ""}
            </p>
          ))}
          {t.taught.map((x) => (
            <p key={x.id}>
              Teaching #{x.id} ({x.status}): {x.text}
            </p>
          ))}
        </section>
      )}
      {t.related.length > 0 && (
        <>
          <h2>Related alert groups</h2>
          <p className="hint">They joined this Triage instead of starting their own.</p>
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Alert group</th>
                <th>Shares</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {t.related.map((r, n) => (
                <tr key={n}>
                  <td className="hint">{when(r.at)}</td>
                  <td>{r.title}</td>
                  <td>
                    {Object.entries(r.matched)
                      .map(([k, v]) => `${k}=${v}`)
                      .join(" ")}
                  </td>
                  <td>
                    {r.louder && <strong>higher severity </strong>}
                    {r.separate_id && <a href={page(r.separate_id)}>triaged separately</a>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <h2>Decisions</h2>
      {t.decisions.length === 0 ? (
        <p className="hint">None.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>When</th>
              <th>By</th>
              <th>Decision</th>
              <th>Actions</th>
              <th>Message</th>
            </tr>
          </thead>
          <tbody>
            {t.decisions.map((d, n) => (
              <tr key={n}>
                <td className="hint">{when(d.at)}</td>
                <td>{d.decided_by}</td>
                <td>{d.approve ? "approved" : "rejected"}</td>
                <td>{d.actions.join(", ")}</td>
                <td>{d.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h2>Tool calls</h2>
      {t.tool_calls.length === 0 ? (
        <p className="hint">None.</p>
      ) : (
        <ol className="calls">
          {t.tool_calls.map((c, n) => (
            <li key={n}>
              <code>{c.tool}</code>
              {c.is_error && " (failed)"}
              <details>
                <summary>
                  <code>{JSON.stringify(c.args)}</code>
                </summary>
                <pre>{c.result}</pre>
              </details>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}

/** The approver token, once per browser: it earns the cookie every API call needs. */
export function TokenPage() {
  const [token, setToken] = useState("");
  const [failed, setFailed] = useState("");
  return (
    <>
      <h1>Approver token</h1>
      <p>
        Your Tailscale identity says who you are. To see anything else here, and to approve, reject
        or ask, the console also needs <code>AIOPS_APPROVER_TOKEN</code>, once per browser: it stays as
        a cookie that proves the token without holding it.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          api.saveToken(token).then(
            () => location.assign("/app/"),
            (err: Error) => setFailed(err.message),
          );
        }}
      >
        <label>
          Approver token{" "}
          <input type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} />
        </label>{" "}
        <button type="submit">Save</button>
      </form>
      {failed && <p className="notice">Couldn't: {failed}</p>}
    </>
  );
}
