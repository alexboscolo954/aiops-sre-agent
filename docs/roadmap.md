# Roadmap

The goal is one Hub that lets the Operator run SRE for several Contracts at once. It answers alerts, answers questions and runs checks, and it never lets one Contract's data reach another. HolmesGPT, OpenSRE and IncidentFox inspire the features. We take their ideas, not their code.

Terms are defined in [`CONTEXT.md`](../CONTEXT.md). The decisions behind the shape are in [ADR 0002](adr/0002-hub-and-relay.md) (Hub and Relay) and [ADR 0003](adr/0003-contract-data-in-private-git.md) (Contract data in a private repo).

## Where we start

| Today | Needed |
|---|---|
| `Settings` is global: one kube context, one namespace list, one Runbooks dir, one Slack webhook, one pair of tokens | Everything except Hub settings is set per Contract |
| `triages` and `recent` live in memory. Dedup is keyed by `groupKey` alone | Postgres, keyed by Contract. Two Contracts can send the same `groupKey` |
| `InMemorySaver` checkpointer. A restart loses pending approvals | Postgres checkpointer. Pending approvals survive a restart |
| `read_only(tool)` trusted the server's `readOnlyHint` | Done in 0.2: the Hub's own list decides read or write, and a server can only make a tool stricter |
| `replay_server` builds tools from our in-process servers | Replay also builds them from saved schema snapshots of vendor servers |
| Alerts only, Slack webhook only, API for approvals | Triage, Question and Check, with Slack and a web console |

## How every slice ships

A slice is one commit-sized change, about one working session (1 to 3 hours).

1. **Glossary first.** New terms go in `CONTEXT.md` before code. Add an ADR only when the decision is hard to reverse, would surprise a reader, and came from a real trade-off.
2. **Tests for every branch of new logic.** Mutation-check each new test: remove the logic, and the test must fail.
3. **An isolation test** for anything that stores, reads or sends Contract data. It uses the two demo Contracts and proves Contract A's data never reaches Contract B, whether in prompts, tools, storage or notifications.
4. **Rerun the real eval suite** when anything the model sees changes: the prompt, tool names, descriptions or schemas, or the Report schema. Commit the results under `evals/results/`. No Scenario may regress.
5. **Keep lint and the full suite green.** Update the README and config table.
6. **Write a one-line commit subject.** CI must be green before moving on.

**Where checks run.**
- **CI**, in the public repo: lint, unit and isolation tests, the kind demo integration and the deploy smoke test. These run on the two synthetic demo Contracts only.
- **Locally:** the real-LLM evals (they need the API key), and Contract Scenarios from the private contracts repo.

## Decisions

| Topic | Decision |
|---|---|
| Who works | One Operator. The Operator receives every Report and makes every Approval decision |
| Reaching a Contract | **Direct** (the Hub holds the credentials) or **Relay** (dials out from the client network) |
| Hub | A cloud VM you own: docker compose with the Hub and Postgres |
| Operator interfaces | Your own Slack workspace, one channel per Contract, with approve buttons. Also a web console |
| Client delivery | Optional per Contract. A Client report goes when the Operator clicks Send, never with approval controls |
| Data policy | Set per Contract. Default: no restrictions |
| Integrations | Hybrid: vendor MCP servers where they're good, our own where they're missing |
| Contract config | YAML per Contract in one private repo, with SOPS secrets and an age key per Contract |
| Console | View and act. It shows config read-only and is reachable only over Tailscale |
| Investigations | Triage, then Question, then Check |
| Knowledge | Similar incidents and Teachings stay in their own Contract. Teachings need review. Shared knowledge is written by the Operator |

## Defaults you can veto

| Choice | Default | Why |
|---|---|---|
| Persistence | Postgres 17, `langgraph-checkpoint-postgres`, psycopg 3, numbered `.sql` migrations | One database for state, checkpoints and knowledge |
| Secrets | `sops -d` at load. The Hub holds age keys for Direct Contracts only | No new library. A Relay Contract's credentials never reach the Hub |
| Many clusters | One kubernetes server per Contract, with a `cluster` argument limited to that Contract's clusters | A Contract can have dozens of clusters, and one server per cluster would multiply the tool count |
| Slack | Web API over httpx; Socket Mode over `websockets` (1.2), not slack-bolt | No public Slack endpoint, and no framework for one socket and a few calls |
| Console stack | FastAPI + Jinja + HTMX, with no JS build | One language, one process |
| Console login | Tailscale identity headers from `tailscale serve`, with the console on `127.0.0.1`, plus an Operator allowlist | No passwords to manage. `serve` strips a client's copy of the header, but anything else that can reach the port (local processes, other containers on the compose network) could send it |
| Jira | An issue is created only when the Operator clicks | Never write to a client's tracker unasked |
| Budget | Monthly per Contract. Warn at 80%. At 100%, refuse new Investigations but still notify | An alert is never silently dropped |
| Model | One Hub default, overridable per Contract | |
| Similar incidents | Postgres full-text search first. Add pgvector only if evals show misses | No embedding calls until they pay off |

## Phases

There are about 36 slices. Neither current Contract needs a Relay, so Phase 3 stays where it is. **It moves to right after Phase 0 if a new Contract can be reached only through a Relay.**

### Phase 0: Foundation: many Contracts, durable state (5 slices)

**0.1 Contract config.** Done.
- A pydantic schema and a loader for a contracts directory (`src/aiops_agent/contracts.py`), with `aiops contracts validate <dir>`.
- A Contract file holds:
  - its id and name;
  - its clusters: name, namespaces, and a context with an optional kubeconfig file or secret, or `in_cluster`;
  - its integrations, as a list of entries. `kubernetes` (`enable_actions`, `max_replicas`), `prometheus` (`url`, `token_secret`) and `runbooks` are builtin entries, so Phase 4 needs no migration.
- These fields mirror today's `Settings`. Unknown keys fail, so each later field arrives in the slice that gives it behaviour, and existing files stay valid:
  - tool allowlist in YAML: 4.1, when vendor tools need it. Builtins keep their list in code;
  - notification targets: 1.1 (the client channel: 1.3);
  - Data policy: 6.4 (1.3 needed none: the Operator reviews each Client report);
  - model and budget: 2.4;
  - health probe: 2.5;
  - reach: 3.2;
  - vendor source: 4.1.
- Secrets sit in `secrets.sops.yaml` and are decrypted with the `sops` binary. The checker:
  - refuses plaintext files;
  - names a bad key without ever printing its value;
  - fails when two Contracts share an age recipient. It reads recipients from sops metadata, so it needs no key.
- Two synthetic demo Contracts live in `demo/contracts/`, each with its own test-only age key. The `two_contracts` fixture loads them for every later isolation test.

**0.2 Contract-scoped tools.** Done, except one open item: a Scenario where the Contract has two clusters and the alert's `cluster` label must pick one.
- Each Contract gets its own MCP server set. The kubernetes server takes a `cluster` argument limited to the Contract's clusters, with a namespace allowlist per cluster. Runbooks come from the Contract's directory plus Shared knowledge.
- **Part 1, done: the allowlist decides read or write.** Each builtin server declares its list in code (`ACCESS`), and `open_agent` requires it. A tool not on the list is hidden, and a server's annotation can only make a tool stricter. This closed a gap: before, a server that wrongly marked a write tool as read-only skipped approval. A server that leaves the marker out was already safe, because those tools are gated.
- *Done when:*
  - the isolation tests pass: A's agent sees only A's tools, naming B's cluster errors, and Runbook search never returns B's Runbooks;
  - a tool annotated read-only but allowlisted as `write` is gated;
  - a tool annotated as a write but allowlisted as `read` is still gated;
  - a tool not on the list is invisible.
- **Part 2, done.** `build_mcp(contract, settings)` builds one Contract's tools. Isolation tests live in `tests/test_isolation.py`. The kind demo has the `bank` namespace, and a kind-backed test shows demo-bank can't read demo-shop's namespace. Until 0.3, the API, `aiops triage` and `aiops mcp` turn the `AIOPS_*` variables into one Contract named `default`.

**0.3 Contract-scoped intake.** Done.
- `POST /contracts/{id}/alertmanager` with a webhook token per Contract. Dedup is keyed by (Contract, `groupKey`). This replaces `/alertmanager` and the global token.
- The token is stored as its SHA-256 in `contract.yaml` (`aiops contracts new-token`), so the in-cluster deploy needs no sops yet: the image gains sops in 0.5. The `AIOPS_*` cluster settings are gone; `serve`, `triage` and `mcp` refuse to start if one is still set.
- Known limit: `AIOPS_MAX_CONCURRENT_TRIAGES` is shared, so one Contract's alert storm can hold every slot. Revisit with per-Contract queues when it bites.
- *Done when:*
  - A's token can't post to B;
  - the same `groupKey` in A and B starts two Triages;
  - A's group resolving doesn't make B's Proposed actions Stale.

**0.4 Postgres state.** Done.
- Tables: Investigations (with a kind column), Proposed and Executed actions, the dedup seen-set, and the audit log. Use the LangGraph Postgres checkpointer.
- Store every tool call's args and the raw result (before the cap, after redaction) so slice 2.6 can turn it into a Scenario.
- Stale deadlines are stored in the database, and timers are re-armed at startup instead of sleeping in memory.
- Rename `Triage` in code to `Investigation` with a kind. Done (part a): the API is now `/investigations`, and each record has `kind: triage`.
- *Done when:*
  - a pending approval survives a Hub restart and can still be approved;
  - a deadline that passes while the Hub is down is made Stale at startup;
  - storage tests run against Postgres in CI.

**0.5 Hub deployment.** Done.
- `deploy/hub`: docker compose with the Hub, Postgres, Caddy and a backup job. Caddy serves TLS and passes only `POST /contracts/<id>/alertmanager` (bodies up to 1 MB); everything else is a 404 there.
- The API listens on `127.0.0.1` only, with `tailscale serve` in front. Never bind it to the Tailscale interface: any tailnet device could then connect directly and forge the identity header.
- The contracts repo reaches the VM through a read-only deploy key. `update-contracts.sh` validates every Contract in the image before restarting, and rolls the clone back if one is invalid.
- The image ships pinned `sops`, checksum-verified for amd64 and arm64.
- `make hub-smoke` in CI. CI has no model key, so instead of a Report it proves: the stack is healthy, both Contracts decrypt in the image, only the alert route is public, an alert is stored and fails the way it should without a cluster, a backup restores, and a bad update is refused.
- Not covered by CI: `tailscale serve`, real certificates, the deploy-key clone, the arm64 image.

### Phase 1: Slack (4 slices)

**1.1 Slack threads.** Done.
- Each Contract has its own channel. Each Investigation is one thread that shows its status, then the Report. This replaces `slack_webhook_url`.
- Posting needs only the Web API (`chat.postMessage`, `chat.update`) with a bot token, so 1.1 uses httpx and no Slack library. Socket Mode, which receives events, moves to 1.2 with the buttons; decide there between keeping this poster and slack-bolt's client.
- *Done when:* a fake Slack client shows A's Investigations never post to B's channel.

**1.2 Approve and reject buttons.** Done.
- The buttons use the same decision path as the API (`settle`: claim, record, resume). A reject reason is entered in a modal, and the pause is claimed only on submit, so a cancelled modal decides nothing. Only the Operator's Slack user id (`AIOPS_SLACK_OPERATOR_ID`) is accepted, and only in the Investigation's own channel.
- The buttons sit on the thread's parent, not on a reply: the parent is re-rendered on every status change, so they disappear on any decision or Stale with no extra state. Each button carries its pause's deadline, so a click from an earlier pause can't decide a later one.
- Socket Mode is a small loop over `websockets` (ack each envelope, reconnect on `disconnect`); the httpx poster stays, and slack-bolt was not needed.
- *Done when:*
  - a click from anyone but the Operator is refused;
  - a second click is refused;
  - going Stale updates the message.

**1.3 Optional client delivery.** Done.
- Per Contract, `slack.client_channel` (a Slack Connect channel). A finished Report gets a **Send to client** button in the Operator's thread, and the Client report goes once, as plain text with no controls. It holds the summary, root cause, severity, affected and Recommendations. Evidence, Executed actions, the Runbook and ids never go.
- Deviations: sent on the Operator's click, not automatically, so AI output is read before a client sees it. No Data policy field: the click is the review, and masking stays in 6.4.
- A crash between claiming the send and posting it leaves it marked sent but unsent (a `ponytail:` note in `api.py`).
- *Done when:* delivery is off by default, and the client message never contains buttons.

**1.4 Questions.** Done.
- **Part a, done:** the agent answers a Question with an Answer (read tools only; write tools are hidden, not gated), a follow-up is a new message on the same thread, and the eval runner takes Question Scenarios. Two pass, with budgets set from the runs (see the README's Evals).
- **Part b, done:** an @mention in a Contract's operator channel starts a Question, and the Answer goes in the thread. A mention in the thread continues the same Investigation. Decided: only messages that @mention the bot (it never reads other channel traffic), Questions only read, and a Question always ends with an Answer.
- One Investigation per Slack thread (a unique index), so a redelivered mention can't start two. A follow-up claims a finished Question only with a newer mention, so two never run at once. Mentions from anyone but the Operator, in a client channel, or in a Triage thread are refused privately. A Question's thread root is the Operator's message, so the Hub only replies there.
- Widen Scenario and Expectation in the glossary and in the eval runner. A Scenario can start from a Question, and its Expectation checks the Answer's keywords and Evidence instead of a Category.
- *Done when:*
  - two Question Scenarios pass;
  - a Question in A's channel can't reach B's clusters.

### Phase 2: Web console, Tailscale only (6 slices)

**2.1 Skeleton and login.** Done.
- Login trusts the identity headers that `tailscale serve` sets. That is safe only because the console listens on `127.0.0.1` (slice 0.5).
- `/console` lists the Contracts for a login in `AIOPS_CONSOLE_OPERATORS`; anything else gets a 403, and with no operators set the console isn't mounted (404), so the in-cluster deploy stays closed. Jinja autoescapes everything, and pages send a CSP and `frame-ancestors 'none'`. `hub-smoke` proves `/console` is a 404 through Caddy even with a forged header, and renders on `127.0.0.1` from the image.
- Not covered by CI: a real `tailscale serve`.
- *Done when:* a request without the Operator's Tailscale identity is refused.

**2.2 Investigations.** Done.
- `/console` lists Investigations, filtered by Contract; each one's page shows the Report or Answer, the decisions and every tool call (args, and the redacted raw result).
- Approve and reject are plain forms (no HTMX needed), through the same decision path as the API and Slack. Each form names its pause (the deadline), like the buttons.
- **Acting needs more than the identity header.** `serve` only strips a *client's* copy of the header; anything else that reaches the Hub's port (local processes, the other containers on the compose network) could send it, and neither a network split nor tailscaled's `whois` stops that behind Docker's published port. So the header alone opens nothing but the token page (since 2.3: a forged header could read client data from tool results), and every page and every POST also needs the approver token (pasted once per browser, kept as an HMAC of it in a Secure, HttpOnly, SameSite=Strict cookie) and must be same-origin (`Sec-Fetch-Site`, or `Origin` against `Host`), which also stops CSRF.

**2.3 Ask a Question** from a form. Done.
- A form on `/console` (Contract and question) and **Follow up** on a Question's page, through the same Question path as Slack (`start_question`, `follow_up`). Same rules as acting: identity, the token cookie, same origin. The page reloads itself while the Question runs (a meta refresh, no script). A console Question has no Slack thread.

**2.4 Cost.** Done.
- **Part a, done:** every model call's tokens are recorded as it happens (a `wrap_model_call` middleware, so a resume never counts earlier Runs and a failed Run still counts), priced per call from `AIOPS_MODEL_PRICES` in USD, including Haiku's long-context tier. The console shows tokens and cost per Investigation and spend per Contract this month. Contracts gain `model:` (through the Hub's gateway) and `monthly_budget_usd:`; a budget needs its model priced at startup.
- **Part b, done:** budgets apply only where a new Run starts (alerts, Questions, follow-ups), never on a resume. At 100% the alert is still recorded (so repeats stay duplicates) and fails with the spend and budget, with no model call; Slack still hears of it. The 80% and 100% notices post once per Contract per month (`budget_notices`). Runs starting together can overshoot (a `ponytail:` note).
- *Done when:* at 100% budget, a new alert still notifies the Operator, and its Failed investigation names the budget as the reason.

**2.5 Health.** Done.
- Shows Relay connections, integration health probes, and the last successful Investigation per Contract. Also shows the effective config read-only, with secrets masked.
- `/console/health` runs one cheap read per integration through the Contract's own tools (`agent.probes`) on each load, with a 10 s limit each. Errors are redacted; check results are never shown. Config shows secret names and whether each decrypted, never values; Hub settings come out of pydantic with every `SecretStr` masked.
- Deviations: no `health probe` field in `contract.yaml` (the builtin probes are enough until a vendor integration needs its own, in 4.1), and Relay connections wait for Phase 3.

**2.6 Save as Scenario.** Done.
- Each Investigation stores its input at intake (migration 0008). The download (`/console/investigations/<id>/scenario.yaml`, identity plus token) builds the Scenario from the recorded tool calls, leaving out Runbook tools (replay reads the files). A saved Scenario names its `clusters` and `integrations`, and the replay builds exactly those with placeholder config, so it offers the tools production did; older Scenarios build byte-identical tools (fingerprinted). `--runbooks` repeats for shared plus the Contract's own.
- Turns a finished Investigation into a Scenario YAML for the Operator to download: the alert or Question, the recorded tool results, and a draft Expectation to edit. The Operator commits it to the contracts repo. The Hub never gets push access to a repo holding every Contract's secrets. The eval runner takes `--scenarios <contracts-repo>/<contract>/scenarios`.
- *Done when:* a saved Scenario replays to the same tool calls.

### Phase 3: Relay (4 slices)

**3.1 Reversed MCP connection.**
- The Relay dials the Hub over WSS and runs the MCP server over that socket. The Hub runs a `ClientSession` on its end. Both SDK sides take raw streams, so this is an adapter, not a new protocol. Each Relay token is bound to one Contract.
- *Done when:*
  - it works over in-memory streams and over a real websocket;
  - A's Relay token can't serve B.

**3.2 Relay process.**
- `aiops relay` ships in the same image, with manifests for the client cluster. Credentials come from a Secret in the client cluster. The Hub hides any tool the Relay offers that isn't on the Contract's allowlist.

**3.3 Hub side.**
- A registry of connected Relays, reconnect with backoff, and a timeout per call.
- *Done when:* killing the Relay mid-Run ends in a Failed investigation ("Relay offline") within the timeout, not a hang.

**3.4 Alert forwarding.**
- The Relay accepts the in-cluster Alertmanager webhook and forwards it over the same connection.
- *Done when:* on a kind cluster with no inbound route from the Hub, a full Triage through the Relay passes the demo eval.

### Phase 4: Integration framework and first integrations (4 slices)

**4.1 Vendor sources.** Done.
- Vendor servers run as pinned stdio subprocesses or remote HTTP servers, behind the same allowlist enforcement as slice 0.2.
- *Done when:* the slice 0.2 allowlist tests also pass against a vendor subprocess.
- A Contract integration `{name, vendor, env, env_secrets, tools, probe}`: `vendor` names an entry in the Hub's registry (`servers/vendors.py`), so the command never comes from the contracts repo (the ADR 0002 reasoning for kubeconfig exec plugins); each binary ships in the image, pinned. `tools` is the Hub's read/write list for it (the YAML allowlist pencilled in for 4.1). The 0.2 allowlist tests run against an in-process server and a real vendor subprocess.
- The subprocess gets MCP's safe default environment plus its own `env` and secrets, never the Hub's (tested with the demo Contracts). A Contract may set only the variables its vendor's registry entry lists (`LD_PRELOAD`, `PATH`, `NODE_OPTIONS` and the like would run code), and registry commands are absolute paths. One process per tool call, none outliving a Run; a handshake timeout drops a vendor that never answers, and the Run goes on. Health: a `probe` tool (must be listed `read`), or by default the vendor starts and offers every listed tool.
- Deviations: stdio only. Remote HTTP waits for 4.4, where the Jira choice (Atlassian's remote MCP or a builtin) decides whether it's needed. Unannotated vendor tools stay gated (Grafana annotates its reads). Replaying a Scenario with a vendor refuses until 4.2's snapshots.

**4.2 Schema snapshots.** Done.
- `aiops integrations snapshot <name>` saves a pinned vendor server's tool schemas into this repo. They hold schemas only, no data. Replay builds tools from the snapshot.
- *Done when:* a test diffs the snapshot against the real pinned server, so a vendor renaming a tool fails a test instead of silently breaking an eval.
- As built: `src/aiops_agent/servers/snapshots/<vendor>.json` keeps each tool's name, title, description, input and output schemas and annotations (what the model and the approval gate see), sorted, so a diff reads well. The vendor starts with no Contract and no variables at all: a vendor that writes its config into a description has none to write into a file this public repo commits. `--check` prints the diff and fails. A saved Scenario lists a vendor as `{name, vendor, tools}` (never its env, secrets or probe), and replay offers its tools from the snapshot without starting it.
- Deviations: the registry is still empty, so the diff test runs against the fixture vendor (`tests/fixtures/snapshots/fixture.json`, checked against the live fixture on every CI run); for a real vendor the check is `aiops integrations snapshot <name> --check`, run where its pinned binary is (4.3). A vendor saved by name only, in a draft from before 4.2, still refuses to replay. A Scenario from a Contract with no clusters now replays with none, instead of a made-up `kind` one.

**4.3 Grafana stack** through `mcp-grafana`.
- Registry entry plus `snapshots/grafana.json`; hub-smoke runs `aiops integrations snapshot grafana --check` inside the image, where the pinned binary is, so a renamed Grafana tool fails CI.
- Check first: a snapshot is taken with no variables, so mcp-grafana must list its tools without `GRAFANA_URL`, and its toolset choice must live in the registry's command args, not in env; otherwise the snapshot won't match what a Contract's Run offers.
- Covers Prometheus/Mimir and Loki (stats and patterns before raw logs, an IncidentFox idea), plus Tempo traces, Pyroscope and dashboard deep links in Reports. Grafana Alerting becomes a second alert source, normalized into an Alert group.
- The kind demo gains a Grafana LGTM stack.
- *Done when:* two new recorded Scenarios pass, one with the root cause in log patterns and one in traces.

**4.4 Jira.**
- A "Create Jira issue" button in Slack and the console puts the Report into the Contract's project. Searching past issues becomes an Evidence source.
- *Decide at slice time:* Atlassian's remote MCP (OAuth) or a small builtin server (API token).

### Phase 5: Clouds, read-only (3 slices)

**5.1 Azure, 5.2 AWS, 5.3 GCP**, each through its official MCP server.
- Each integration gets a documented read-only role (Reader, ReadOnlyAccess, Viewer), an allowlist, a schema snapshot, and one Scenario recorded from a sandbox account. Examples: a node pool at max, database storage full, a quota hit.
- Recording needs a sandbox account per cloud, which costs a little money.

### Phase 6: Investigation quality (4 slices)

**6.1 What changed.**
- One timeline of rollouts, Helm releases, ArgoCD/Flux syncs and cloud activity logs before the alert.
- *Done when:* Scenarios pass where the cause is a change to a different resource.

**6.2 Large output.**
- Select fields and filter JSON at the server. Oversized results go to storage behind a `read_more` tool instead of being cut (a HolmesGPT idea).

**6.3 Alert correlation within a Contract.**
- A new Alert group that overlaps an open Investigation in time and topology joins it instead of starting a Triage. This needs a new glossary term, decided in a grilling round at slice time.

**6.4 Masking.**
- Identifiers are replaced with stable placeholders before the LLM call and restored in the Report (an OpenSRE idea). Built when the first Contract's Data policy requires it.

### Phase 7: Knowledge (4 slices)

**7.1 Similar incidents.**
- Full-text search over the same Contract's past Reports.
- *Done when:*
  - a Scenario passes where a past Report holds the decisive hint;
  - the isolation test passes.

**7.2 Shared knowledge.**
- `shared/` in the contracts repo, mounted read-only for every Contract.
- *Done when:* tests show the agent has no write path to it.

**7.3 Teachings.**
- The agent proposes Teachings after an Investigation, or from the Operator's thumbs up/down and correction. Each is checked against existing Teachings for duplicates and contradictions, then goes to a review queue in Slack and the console.
- *Done when:*
  - an unapproved Teaching never reaches a prompt;
  - A's Teachings never reach B.

**7.4 Embeddings** (pgvector), only if 7.1's evals show misses.

### Phase 8: Checks (2 slices)

**8.1 Scheduled Checks.**
- Per Contract, a cron schedule and a check prompt in YAML. A passing Check is recorded quietly. A failing one produces a Report and notifies the Operator. The schedule lives in Postgres, so a restart never fires a Check twice.

**8.2 Deploy verification.**
- A rollout or ArgoCD sync starts a Check of the new revision after a set delay.

## Deferred

| Item | Why not now | Trigger to revisit |
|---|---|---|
| Full agent inside a client network | A Relay keeps credentials there already | A Contract forbids tool output leaving its network |
| Specialist sub-agents (IncidentFox) | Allowlists and good tools come first | Evals fail on cross-domain Scenarios |
| Anomaly detection (Prophet) | Needs history and tuning. Alerts already cover it | Repeated misses that no alert catches |
| Hierarchical retrieval (RAPTOR) | Full-text search over a small corpus is enough | Runbooks outgrow search plus embeddings |
| Teams, Google Chat | No Contract uses them | A Contract asks |
| Multi-user RBAC, SSO | One Operator | A second person joins |
| Sandbox and credential proxy (IncidentFox, BSL) | A Relay keeps credentials out of the Hub | A Direct Contract's threat model demands it |
| Actions that run without approval | Not without months of evidence | Never by default |
| Fix PRs on GitHub/GitLab (HolmesGPT) | Needs code access per Contract | After Jira, when a Contract grants repo access |
| Other integrations (Datadog, Splunk, PagerDuty, Opsgenie, ServiceNow, ...) | Added through the Phase 4 framework, each with a Scenario | A Contract uses it |

## Next

Phase 4 first (the Operator's choice: no Contract needs a Relay yet). Next: slice 4.3, the Grafana stack.
